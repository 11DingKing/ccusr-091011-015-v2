"""
保管区容量与相容性规则引擎

入库、转移、预约三类操作共用同一判断口径：
- 规则版本：按生效时间取发生时有效版本，历史版本不可变；
- 临时超限：仅生效中的批准可临时追加额度，到期/撤销自动失效；
- 容量占用：所有增减都通过数据库条件更新完成，
  并发占用不会超卖，容量释放不会出现负数。
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.core.exceptions import BusinessException
from .models import (
    CapacityOverride,
    StockPlacement,
    StorageZone,
    ZoneCapacity,
    ZoneReservation,
    ZoneRuleVersion,
    ZoneValidationLog,
)

logger = logging.getLogger('apps')


class ZoneRuleEngine:
    """保管区规则引擎（入库/转移/预约统一校验入口）"""

    # ---------------- 规则版本 ----------------

    @staticmethod
    def get_active_version(zone, at=None):
        """获取指定时刻生效的规则版本（默认当前）"""
        at = at or timezone.now()
        version = (
            zone.rule_versions.filter(effective_from__lte=at)
            .order_by('-version')
            .first()
        )
        if version is None:
            # 所有版本均未生效时，回退到最早版本，保证口径可解释
            version = zone.rule_versions.order_by('version').first()
        return version

    @staticmethod
    def get_active_overrides(zone, at=None):
        """获取指定时刻生效中的临时超限批准"""
        at = at or timezone.now()
        return list(
            zone.overrides.filter(is_revoked=False, expires_at__gt=at)
        )

    @classmethod
    def get_effective_limits(cls, zone, at=None):
        """
        计算有效容量上限 = 规则版本上限 + 生效中的临时超限额度

        返回 (rule_version, max_weight, max_items, overrides)
        """
        version = cls.get_active_version(zone, at)
        if version is None:
            return None, None, None, []
        overrides = cls.get_active_overrides(zone, at)
        extra_weight = sum((o.extra_weight for o in overrides), Decimal('0'))
        extra_items = sum((o.extra_items for o in overrides), Decimal('0'))
        return (
            version,
            version.max_weight + extra_weight,
            version.max_items + extra_items,
            overrides,
        )

    # ---------------- 占用口径 ----------------

    @staticmethod
    def get_present_category_ids(zone, exclude_reservation=None):
        """
        区内当前存在的品类集合（实物存放 + 生效中的预约）

        相容性判断以该集合为准，预约与实物同一口径。
        """
        category_ids = set(
            StockPlacement.objects.filter(zone=zone, quantity__gt=0)
            .values_list('goods__variety__category_id', flat=True)
        )
        reservations = zone.reservations.filter(
            status='active', expires_at__gt=timezone.now()
        )
        if exclude_reservation is not None:
            reservations = reservations.exclude(pk=exclude_reservation.pk)
        category_ids.update(
            reservations.values_list('goods__variety__category_id', flat=True)
        )
        return category_ids

    @classmethod
    def expire_due_reservations(cls, zone):
        """把已到期的预约置为过期并释放其预约占用（容量自动释放）"""
        due = zone.reservations.filter(status='active', expires_at__lte=timezone.now())
        for reservation in due:
            released = cls._adjust_capacity(
                zone, reservation.quantity, reservation.weight,
                field_pair=('reserved_items', 'reserved_weight'), sign=-1,
            )
            if released:
                reservation.status = 'expired'
                reservation.save(update_fields=['status', 'updated_at'])
                logger.info(f"Reservation {reservation.id} expired and capacity released")

    # ---------------- 统一校验入口 ----------------

    @classmethod
    def validate_placement(cls, zone, goods, quantity, operation, actor,
                           exclude_reservation=None):
        """
        入库/转移/预约统一校验

        返回 (ok, reasons, rule_version)；无论通过与否都写校验记录，
        记录绑定发生时的规则版本与上限快照，供历史解释。
        """
        category = goods.variety.category
        weight = (quantity * goods.unit_weight).quantize(Decimal('0.01'))
        reasons = []

        cls.expire_due_reservations(zone)

        if not zone.is_active:
            reasons.append('保管区已停用')

        version, max_weight, max_items, overrides = cls.get_effective_limits(zone)
        if version is None:
            reasons.append('保管区未配置容量规则')
        else:
            # 类别准入
            allowed_ids = set(version.allowed_categories.values_list('id', flat=True))
            if allowed_ids and category.id not in allowed_ids:
                reasons.append(f'品类"{category.name}"不在该保管区准入范围内')

            # 相容性：申请品类与区内已存在品类不得构成不相容对
            present_ids = cls.get_present_category_ids(
                zone, exclude_reservation=exclude_reservation
            )
            present_ids.discard(category.id)
            if present_ids:
                conflicts = version.incompatibilities.filter(
                    Q(category_a_id=category.id, category_b_id__in=present_ids)
                    | Q(category_b_id=category.id, category_a_id__in=present_ids)
                ).select_related('category_a', 'category_b')
                for conflict in conflicts:
                    other = (
                        conflict.category_b.name
                        if conflict.category_a_id == category.id
                        else conflict.category_a.name
                    )
                    reasons.append(f'品类"{category.name}"与区内"{other}"不相容，不得同区存放')

            # 容量：实物占用 + 预约占用 + 本次申请 ≤ 有效上限
            capacity, _ = ZoneCapacity.objects.get_or_create(zone=zone)
            if exclude_reservation is not None:
                reserved_items = capacity.reserved_items - exclude_reservation.quantity
                reserved_weight = capacity.reserved_weight - exclude_reservation.weight
            else:
                reserved_items = capacity.reserved_items
                reserved_weight = capacity.reserved_weight
            if capacity.current_weight + reserved_weight + weight > max_weight:
                reasons.append(
                    f'超出重量上限：申请后将达 '
                    f'{capacity.current_weight + reserved_weight + weight}kg，'
                    f'上限 {max_weight}kg'
                )
            if capacity.current_items + reserved_items + quantity > max_items:
                reasons.append(
                    f'超出件数上限：申请后将达 '
                    f'{capacity.current_items + reserved_items + quantity} 件，'
                    f'上限 {max_items} 件'
                )

        log = ZoneValidationLog.objects.create(
            zone=zone,
            rule_version=version,
            operation=operation,
            result='passed' if not reasons else 'rejected',
            goods=goods,
            category=category,
            quantity=quantity,
            weight=weight,
            limit_weight_snapshot=max_weight,
            limit_items_snapshot=max_items,
            override=overrides[0] if overrides else None,
            reasons='; '.join(reasons),
            actor=actor,
        )
        logger.info(
            f"Zone validation {log.id}: zone={zone.code} op={operation} "
            f"result={log.result} version={version.version if version else None}"
        )
        return not reasons, reasons, version

    # ---------------- 原子容量变动 ----------------

    @staticmethod
    def _adjust_capacity(zone, items, weight, field_pair, sign, limits=None):
        """
        对容量计数器做一次原子条件更新

        sign=+1（占用）时要求占用后不超过 limits（防超卖）；
        sign=-1（释放）时要求释放后不低于零（防负数）。
        返回是否更新成功。
        """
        items_field, weight_field = field_pair
        filters = {'zone': zone}
        if sign > 0:
            if limits is not None:
                max_items, max_weight = limits
                filters[f'{items_field}__lte'] = max_items - items
                filters[f'{weight_field}__lte'] = max_weight - weight
            updates = {
                items_field: F(items_field) + items,
                weight_field: F(weight_field) + weight,
            }
        else:
            filters[f'{items_field}__gte'] = items
            filters[f'{weight_field}__gte'] = weight
            updates = {
                items_field: F(items_field) - items,
                weight_field: F(weight_field) - weight,
            }
        return ZoneCapacity.objects.filter(**filters).update(**updates) == 1

    @classmethod
    def occupy(cls, zone, quantity, weight, reserved=False):
        """
        占用容量（实物或预约），并发安全

        以当前有效上限作为条件更新的约束，即使校验与占用之间
        出现并发申请，也不会超卖。
        """
        _, max_weight, max_items, _ = cls.get_effective_limits(zone)
        if max_weight is None:
            raise BusinessException('保管区未配置容量规则')
        field_pair = (
            ('reserved_items', 'reserved_weight') if reserved
            else ('current_items', 'current_weight')
        )
        ZoneCapacity.objects.get_or_create(zone=zone)
        ok = cls._adjust_capacity(
            zone, quantity, weight, field_pair, sign=+1,
            limits=(max_items, max_weight),
        )
        if not ok:
            raise BusinessException('保管区容量不足，请重新校验后提交')

    @classmethod
    def release(cls, zone, quantity, weight, reserved=False):
        """释放容量（实物或预约），并发安全，不会出现负数"""
        field_pair = (
            ('reserved_items', 'reserved_weight') if reserved
            else ('current_items', 'current_weight')
        )
        ok = cls._adjust_capacity(zone, quantity, weight, field_pair, sign=-1)
        if not ok:
            raise BusinessException('容量释放失败：释放量超过当前占用量')

    @classmethod
    def fulfill_reservation(cls, reservation):
        """预约履约：预约占用转为实物占用（一次原子更新）"""
        zone = reservation.zone
        _, max_weight, max_items, _ = cls.get_effective_limits(zone)
        if max_weight is None:
            raise BusinessException('保管区未配置容量规则')
        updated = ZoneCapacity.objects.filter(
            zone=zone,
            reserved_items__gte=reservation.quantity,
            reserved_weight__gte=reservation.weight,
            current_items__lte=max_items - reservation.quantity,
            current_weight__lte=max_weight - reservation.weight,
        ).update(
            reserved_items=F('reserved_items') - reservation.quantity,
            reserved_weight=F('reserved_weight') - reservation.weight,
            current_items=F('current_items') + reservation.quantity,
            current_weight=F('current_weight') + reservation.weight,
        )
        if updated != 1:
            raise BusinessException('预约履约失败：容量状态已变化，请重新校验')

    # ---------------- 存放明细 ----------------

    @staticmethod
    def add_placement(goods, zone, quantity):
        """累加存放明细"""
        placement, _ = StockPlacement.objects.get_or_create(
            goods=goods, zone=zone, defaults={'quantity': Decimal('0')}
        )
        StockPlacement.objects.filter(pk=placement.pk).update(
            quantity=F('quantity') + quantity
        )

    @staticmethod
    def remove_placement(goods, zone, quantity):
        """扣减存放明细，不足时失败（不会出现负数）"""
        updated = StockPlacement.objects.filter(
            goods=goods, zone=zone, quantity__gte=quantity
        ).update(quantity=F('quantity') - quantity)
        if updated != 1:
            raise BusinessException('该保管区内存放数量不足')

    # ---------------- 复合操作 ----------------

    @classmethod
    def stock_in(cls, *, zone, goods, quantity, operator, batch_no='',
                 supplier='', remark='', reservation=None):
        """
        入库：统一校验 → 占用容量 → 存放明细 → 库存数量 → 入库记录

        校验（含留痕）在事务外执行，拒绝的判定不会因回滚丢失；
        容量变动在事务内以条件更新兜底，并发下也不会超卖。
        携带预约时按预约履约口径处理（预约占用转为实物占用）。
        """
        from .models import StockIn

        if reservation is not None and (
            reservation.status != 'active'
            or reservation.expires_at <= timezone.now()
        ):
            raise BusinessException('预约已失效，无法按预约入库')

        ok, reasons, version = cls.validate_placement(
            zone, goods, quantity, 'stock_in', operator,
            exclude_reservation=reservation,
        )
        if not ok:
            raise BusinessException('；'.join(reasons))

        weight = (quantity * goods.unit_weight).quantize(Decimal('0.01'))
        with transaction.atomic():
            if reservation is not None:
                reservation.refresh_from_db()
                if reservation.status != 'active':
                    raise BusinessException('预约已失效，无法按预约入库')
                cls.fulfill_reservation(reservation)
                reservation.status = 'fulfilled'
                reservation.save(update_fields=['status', 'updated_at'])
            else:
                cls.occupy(zone, quantity, weight)

            cls.add_placement(goods, zone, quantity)
            type(goods).objects.filter(pk=goods.pk).update(
                quantity=F('quantity') + quantity
            )
            stock_in = StockIn.objects.create(
                goods=goods, operator=operator, quantity=quantity,
                batch_no=batch_no, supplier=supplier, remark=remark,
                zone=zone, rule_version=version,
            )
        logger.info(
            f"Stock in: goods={goods.code} zone={zone.code} "
            f"qty={quantity} by {operator.username}"
        )
        return stock_in

    @classmethod
    def transfer(cls, *, goods, from_zone, to_zone, quantity, operator):
        """
        转移：源区释放与目标区占用在同一事务内完成，
        目标区校验与入库/预约同一口径。
        """
        from .models import ZoneTransfer

        if from_zone == to_zone:
            raise BusinessException('转出与转入保管区不能相同')

        ok, reasons, version = cls.validate_placement(
            to_zone, goods, quantity, 'transfer', operator,
        )
        if not ok:
            raise BusinessException('；'.join(reasons))

        weight = (quantity * goods.unit_weight).quantize(Decimal('0.01'))
        with transaction.atomic():
            # 任一步失败整体回滚，源区不会出现"扣了没补"的中间态
            cls.remove_placement(goods, from_zone, quantity)
            cls.release(from_zone, quantity, weight)
            cls.occupy(to_zone, quantity, weight)
            cls.add_placement(goods, to_zone, quantity)

            transfer = ZoneTransfer.objects.create(
                goods=goods, from_zone=from_zone, to_zone=to_zone,
                quantity=quantity, weight=weight,
                rule_version=version, operator=operator,
            )
        logger.info(
            f"Transfer: goods={goods.code} {from_zone.code}->{to_zone.code} "
            f"qty={quantity} by {operator.username}"
        )
        return transfer

    @classmethod
    def reserve(cls, *, zone, goods, quantity, expires_at, operator):
        """预约：统一校验 → 占用预约额度 → 生成预约记录"""
        if expires_at <= timezone.now():
            raise BusinessException('预约失效时间必须晚于当前时间')

        ok, reasons, version = cls.validate_placement(
            zone, goods, quantity, 'reservation', operator,
        )
        if not ok:
            raise BusinessException('；'.join(reasons))

        weight = (quantity * goods.unit_weight).quantize(Decimal('0.01'))
        with transaction.atomic():
            cls.occupy(zone, quantity, weight, reserved=True)
            reservation = ZoneReservation.objects.create(
                zone=zone, goods=goods, rule_version=version,
                quantity=quantity, weight=weight,
                expires_at=expires_at, created_by=operator,
            )
        logger.info(
            f"Reservation: goods={goods.code} zone={zone.code} "
            f"qty={quantity} by {operator.username}"
        )
        return reservation

    @classmethod
    @transaction.atomic
    def cancel_reservation(cls, reservation, operator):
        """取消预约：释放预约占用"""
        if reservation.status != 'active':
            raise BusinessException('仅生效中的预约可以取消')
        cls.release(
            reservation.zone, reservation.quantity, reservation.weight,
            reserved=True,
        )
        reservation.status = 'cancelled'
        reservation.save(update_fields=['status', 'updated_at'])
        logger.info(f"Reservation {reservation.id} cancelled by {operator.username}")

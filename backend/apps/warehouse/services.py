"""
保管区容量与相容性校验服务

入库、转移、预约共用同一套校验口径（validate_placement）；
占用台账通过条件更新原子变更，保证容量释放不为负、并发占用不超卖。
"""
import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum, Value, DecimalField
from django.utils import timezone

from apps.core.exceptions import BusinessException
from .models import (
    CategoryIncompatibility,
    CompatibilityRuleVersion,
    Goods,
    GoodsZoneStock,
    OverLimitApproval,
    StockIn,
    StorageZone,
    ZoneCategoryOccupancy,
    ZoneOccupancy,
    ZoneReservation,
    ZoneRuleVersion,
    ZoneTransfer,
)

logger = logging.getLogger('apps')

DECIMAL_14 = DecimalField(max_digits=14, decimal_places=2)


class PlacementValidationError(BusinessException):
    """摆放校验失败（区域状态、类别准入、相容性或容量）"""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__('；'.join(self.violations), code=400)


class OccupancyConflictError(BusinessException):
    """占用台账变更冲突（并发占用导致容量不足，或释放量超过当前占用）"""

    def __init__(self, message='容量不足或存在并发冲突，请重试'):
        super().__init__(message, code=409)


# ==================== 规则版本查询 ====================


def get_zone_rule_at(zone, at_time):
    """获取保管区在指定时间生效的容量规则版本"""
    return (
        ZoneRuleVersion.objects.filter(zone=zone, effective_from__lte=at_time)
        .order_by('-effective_from', '-version')
        .first()
    )


def get_compat_rule_at(at_time):
    """获取指定时间生效的相容性规则版本"""
    return (
        CompatibilityRuleVersion.objects.filter(effective_from__lte=at_time)
        .order_by('-effective_from', '-version')
        .first()
    )


def get_active_override_totals(zone, at_time):
    """指定时间有效的临时超限额度合计（未撤销且未过期）"""
    totals = OverLimitApproval.objects.filter(
        zone=zone, is_revoked=False, expires_at__gt=at_time
    ).aggregate(
        extra_weight=Sum('extra_weight'),
        extra_items=Sum('extra_items'),
    )
    return (
        totals['extra_weight'] or Decimal('0'),
        totals['extra_items'] or Decimal('0'),
    )


def get_effective_limits(zone, rule_version, at_time):
    """有效上限 = 规则上限 + 有效临时超限额度"""
    extra_weight, extra_items = get_active_override_totals(zone, at_time)
    return (
        rule_version.max_weight + extra_weight,
        rule_version.max_items + extra_items,
    )


# ==================== 统一校验口径 ====================


def validate_placement(zone, category, quantity, unit_weight, at_time=None):
    """
    校验一批物资能否放入指定保管区（入库、转移、预约共用）。

    返回校验上下文（含规则版本快照与有效上限）；
    校验失败抛出 PlacementValidationError，violations 为全部违规项。
    """
    at_time = at_time or timezone.now()
    weight = (quantity * unit_weight).quantize(Decimal('0.01'))
    violations = []

    if not zone.is_active:
        violations.append(f'保管区"{zone.name}"已停用')

    rule_version = get_zone_rule_at(zone, at_time)
    if rule_version is None:
        violations.append(f'保管区"{zone.name}"尚未配置生效的容量规则')
        raise PlacementValidationError(violations)

    # 类别准入：规则配置了允许清单时，仅清单内品类可存放
    allowed_ids = set(rule_version.allowances.values_list('category_id', flat=True))
    if allowed_ids and category.id not in allowed_ids:
        violations.append(f'品类"{category.name}"不在保管区"{zone.name}"允许存放的类别内')

    # 相容性：与区域内已存放（含预约）的品类不得互斥
    compat_version = get_compat_rule_at(at_time)
    if compat_version is not None:
        incompatible_ids = set()
        pairs = CategoryIncompatibility.objects.filter(
            rule_version=compat_version
        ).values_list('category_a_id', 'category_b_id')
        for a_id, b_id in pairs:
            if a_id == category.id:
                incompatible_ids.add(b_id)
            elif b_id == category.id:
                incompatible_ids.add(a_id)
        if incompatible_ids:
            present = (
                ZoneCategoryOccupancy.objects.filter(zone=zone)
                .filter(Q(used_items__gt=0) | Q(reserved_items__gt=0))
                .exclude(category=category)
                .values_list('category_id', 'category__name')
            )
            for present_id, present_name in present:
                if present_id in incompatible_ids:
                    violations.append(
                        f'品类"{category.name}"与区域内已存放的"{present_name}"不相容'
                    )

    # 容量：已用 + 预约 + 本次 不得超过有效上限
    occupancy = ZoneOccupancy.objects.filter(zone=zone).first()
    used_weight = occupancy.used_weight if occupancy else Decimal('0')
    used_items = occupancy.used_items if occupancy else Decimal('0')
    reserved_weight = occupancy.reserved_weight if occupancy else Decimal('0')
    reserved_items = occupancy.reserved_items if occupancy else Decimal('0')

    max_weight, max_items = get_effective_limits(zone, rule_version, at_time)
    projected_weight = used_weight + reserved_weight + weight
    projected_items = used_items + reserved_items + quantity
    if projected_weight > max_weight:
        violations.append(
            f'重量超限：已用{used_weight}kg + 预约{reserved_weight}kg + 本次{weight}kg'
            f' 超过上限{max_weight}kg'
        )
    if projected_items > max_items:
        violations.append(
            f'件数超限：已用{used_items}件 + 预约{reserved_items}件 + 本次{quantity}件'
            f' 超过上限{max_items}件'
        )

    if violations:
        raise PlacementValidationError(violations)

    return {
        'rule_version': rule_version,
        'compat_version': compat_version,
        'weight': weight,
        'items': quantity,
        'max_weight': max_weight,
        'max_items': max_items,
    }


# ==================== 占用台账原子变更 ====================


def _lock_zone_occupancy(zone):
    """
    锁定并返回区域占用台账。

    SQLite 不支持行级锁：事务内首个语句即执行写操作，
    借助库级写锁将同一区域的并发变更串行化。
    """
    now = timezone.now()
    updated = ZoneOccupancy.objects.filter(zone=zone).update(updated_at=now)
    if not updated:
        try:
            ZoneOccupancy.objects.create(zone=zone)
        except IntegrityError:
            # 并发创建，重新锁定已有行
            ZoneOccupancy.objects.filter(zone=zone).update(updated_at=now)
    return ZoneOccupancy.objects.get(zone=zone)


def _ensure_category_occupancy(zone, category):
    try:
        return ZoneCategoryOccupancy.objects.get(zone=zone, category=category)
    except ZoneCategoryOccupancy.DoesNotExist:
        try:
            return ZoneCategoryOccupancy.objects.create(zone=zone, category=category)
        except IntegrityError:
            return ZoneCategoryOccupancy.objects.get(zone=zone, category=category)


def occupy(zone, category, weight, items, kind, max_weight, max_items):
    """
    原子占用容量。kind 为 'used'（实际占用）或 'reserved'（预约占用）。

    通过单条条件 UPDATE 保证：已用 + 预约 + 本次 <= 有效上限，
    并发下不会出现超卖。
    """
    _ensure_category_occupancy(zone, category)
    capacity_guard = {
        'used_weight__lte': Value(max_weight, output_field=DECIMAL_14)
        - F('reserved_weight')
        - Value(weight, output_field=DECIMAL_14),
        'used_items__lte': Value(max_items, output_field=DECIMAL_14)
        - F('reserved_items')
        - Value(items, output_field=DECIMAL_14),
    }
    if kind == 'used':
        changes = {
            'used_weight': F('used_weight') + weight,
            'used_items': F('used_items') + items,
        }
    else:
        changes = {
            'reserved_weight': F('reserved_weight') + weight,
            'reserved_items': F('reserved_items') + items,
        }
    updated = (
        ZoneOccupancy.objects.filter(zone=zone)
        .filter(**capacity_guard)
        .update(**changes, updated_at=timezone.now())
    )
    if not updated:
        raise OccupancyConflictError('容量不足，可能已被并发占用，请重试')

    if kind == 'used':
        ZoneCategoryOccupancy.objects.filter(zone=zone, category=category).update(
            used_weight=F('used_weight') + weight,
            used_items=F('used_items') + items,
        )
    else:
        ZoneCategoryOccupancy.objects.filter(zone=zone, category=category).update(
            reserved_weight=F('reserved_weight') + weight,
            reserved_items=F('reserved_items') + items,
        )


def release(zone, category, weight, items, kind):
    """
    原子释放容量。释放量超过当前占用时拒绝，保证不出现负数。
    """
    field_weight = 'used_weight' if kind == 'used' else 'reserved_weight'
    field_items = 'used_items' if kind == 'used' else 'reserved_items'
    guard = {
        f'{field_weight}__gte': weight,
        f'{field_items}__gte': items,
    }
    updated = ZoneOccupancy.objects.filter(zone=zone).filter(**guard).update(
        **{
            field_weight: F(field_weight) - weight,
            field_items: F(field_items) - items,
        },
        updated_at=timezone.now(),
    )
    if not updated:
        raise OccupancyConflictError('释放数量超过当前占用，已中止')

    updated = ZoneCategoryOccupancy.objects.filter(zone=zone, category=category).filter(**guard).update(
        **{
            field_weight: F(field_weight) - weight,
            field_items: F(field_items) - items,
        }
    )
    if not updated:
        raise OccupancyConflictError('释放数量超过当前品类占用，已中止')


def _move_reserved_to_used(zone, category, weight, items):
    """预约核销：reserved 桶转入 used 桶，总量不变，不重新校验容量。"""
    guard = {'reserved_weight__gte': weight, 'reserved_items__gte': items}
    updated = ZoneOccupancy.objects.filter(zone=zone).filter(**guard).update(
        reserved_weight=F('reserved_weight') - weight,
        reserved_items=F('reserved_items') - items,
        used_weight=F('used_weight') + weight,
        used_items=F('used_items') + items,
        updated_at=timezone.now(),
    )
    if not updated:
        raise OccupancyConflictError('预约占用数据异常，核销失败')
    updated = ZoneCategoryOccupancy.objects.filter(zone=zone, category=category).filter(**guard).update(
        reserved_weight=F('reserved_weight') - weight,
        reserved_items=F('reserved_items') - items,
        used_weight=F('used_weight') + weight,
        used_items=F('used_items') + items,
    )
    if not updated:
        raise OccupancyConflictError('预约品类占用数据异常，核销失败')


def _add_goods_zone_stock(goods, zone, quantity):
    updated = GoodsZoneStock.objects.filter(goods=goods, zone=zone).update(
        quantity=F('quantity') + quantity
    )
    if not updated:
        try:
            GoodsZoneStock.objects.create(goods=goods, zone=zone, quantity=quantity)
        except IntegrityError:
            GoodsZoneStock.objects.filter(goods=goods, zone=zone).update(
                quantity=F('quantity') + quantity
            )


def release_expired_reservations(zone=None, now=None):
    """释放已过期预约占用的容量，返回释放条数。"""
    now = now or timezone.now()
    queryset = ZoneReservation.objects.filter(status='active', expires_at__lte=now)
    if zone is not None:
        queryset = queryset.filter(zone=zone)
    released = 0
    for reservation in queryset.select_related('goods__variety__category'):
        category = reservation.goods.variety.category
        release(
            reservation.zone, category,
            reservation.weight, reservation.quantity, 'reserved',
        )
        reservation.status = 'expired'
        reservation.save(update_fields=['status', 'updated_at'])
        released += 1
        logger.info(f"Reservation {reservation.id} expired, capacity released")
    return released


# ==================== 业务操作 ====================


@transaction.atomic
def stock_in_to_zone(*, goods, zone, quantity, operator, batch_no='', supplier='', remark=''):
    """入库：统一校验后占用容量并登记。"""
    now = timezone.now()
    _lock_zone_occupancy(zone)
    release_expired_reservations(zone=zone, now=now)

    category = goods.variety.category
    context = validate_placement(zone, category, quantity, goods.unit_weight, at_time=now)
    occupy(zone, category, context['weight'], quantity, 'used',
           context['max_weight'], context['max_items'])

    _add_goods_zone_stock(goods, zone, quantity)
    Goods.objects.filter(pk=goods.pk).update(
        quantity=F('quantity') + quantity, updated_at=now
    )
    record = StockIn.objects.create(
        goods=goods, zone=zone, operator=operator,
        quantity=quantity, weight=context['weight'],
        batch_no=batch_no, supplier=supplier, remark=remark,
        rule_version=context['rule_version'],
        compat_version=context['compat_version'],
    )
    logger.info(
        f"User {operator.username} stocked in {quantity} of {goods.name} "
        f"to zone {zone.name} (rule v{context['rule_version'].version})"
    )
    return record


@transaction.atomic
def transfer_goods(*, goods, from_zone, to_zone, quantity, operator, remark=''):
    """转移：释放转出区域容量，按同一口径校验并占用转入区域。"""
    if from_zone.id == to_zone.id:
        raise BusinessException('转出与转入区域不能相同')

    now = timezone.now()
    # 按区域ID顺序加锁，避免交叉转移死锁
    for zone in sorted({from_zone, to_zone}, key=lambda z: z.id):
        _lock_zone_occupancy(zone)
        release_expired_reservations(zone=zone, now=now)

    # 先扣减转出方货物存量（条件更新，存量不足即失败）
    reduced = GoodsZoneStock.objects.filter(
        goods=goods, zone=from_zone, quantity__gte=quantity
    ).update(quantity=F('quantity') - quantity)
    if not reduced:
        raise BusinessException(f'货物在区域"{from_zone.name}"的存量不足')

    category = goods.variety.category
    weight = (quantity * goods.unit_weight).quantize(Decimal('0.01'))
    context = validate_placement(to_zone, category, quantity, goods.unit_weight, at_time=now)

    release(from_zone, category, weight, quantity, 'used')
    occupy(to_zone, category, weight, quantity, 'used',
           context['max_weight'], context['max_items'])
    _add_goods_zone_stock(goods, to_zone, quantity)

    record = ZoneTransfer.objects.create(
        goods=goods, from_zone=from_zone, to_zone=to_zone, operator=operator,
        quantity=quantity, weight=weight, remark=remark,
        rule_version=context['rule_version'],
        compat_version=context['compat_version'],
    )
    logger.info(
        f"User {operator.username} transferred {quantity} of {goods.name} "
        f"from {from_zone.name} to {to_zone.name}"
    )
    return record


@transaction.atomic
def create_reservation(*, goods, zone, quantity, expires_at, operator, remark=''):
    """预约：按同一口径校验后占用预约容量。"""
    now = timezone.now()
    if expires_at <= now:
        raise BusinessException('预约失效时间必须晚于当前时间')

    _lock_zone_occupancy(zone)
    release_expired_reservations(zone=zone, now=now)

    category = goods.variety.category
    context = validate_placement(zone, category, quantity, goods.unit_weight, at_time=now)
    occupy(zone, category, context['weight'], quantity, 'reserved',
           context['max_weight'], context['max_items'])

    reservation = ZoneReservation.objects.create(
        zone=zone, goods=goods, created_by=operator,
        quantity=quantity, unit_weight=goods.unit_weight, weight=context['weight'],
        expires_at=expires_at, remark=remark,
        rule_version=context['rule_version'],
        compat_version=context['compat_version'],
    )
    logger.info(
        f"User {operator.username} reserved {quantity} of {goods.name} "
        f"in zone {zone.name} until {expires_at}"
    )
    return reservation


@transaction.atomic
def cancel_reservation(*, reservation, operator):
    """取消预约并释放容量。"""
    _lock_zone_occupancy(reservation.zone)
    # 加锁后重读，避免并发下基于过期状态操作
    reservation = ZoneReservation.objects.get(pk=reservation.pk)
    if reservation.status != 'active':
        raise BusinessException('仅进行中的预约可以取消')
    category = reservation.goods.variety.category
    release(reservation.zone, category, reservation.weight, reservation.quantity, 'reserved')
    reservation.status = 'cancelled'
    reservation.save(update_fields=['status', 'updated_at'])
    logger.info(f"User {operator.username} cancelled reservation {reservation.id}")
    return reservation


@transaction.atomic
def fulfill_reservation(*, reservation, operator, remark=''):
    """
    核销预约：预约容量转为实际占用并生成入库记录。

    容量在预约时已按当时口径锁定，核销不再重复校验，
    仅做桶间转移，总量不变。
    """
    now = timezone.now()
    _lock_zone_occupancy(reservation.zone)
    # 加锁后重读，避免并发下基于过期状态操作
    reservation = ZoneReservation.objects.get(pk=reservation.pk)
    if reservation.status != 'active':
        raise BusinessException('仅进行中的预约可以核销')
    if reservation.expires_at <= now:
        release_expired_reservations(zone=reservation.zone, now=now)
        raise BusinessException('预约已失效，容量已释放')

    goods = reservation.goods
    zone = reservation.zone
    category = goods.variety.category
    _move_reserved_to_used(zone, category, reservation.weight, reservation.quantity)

    _add_goods_zone_stock(goods, zone, reservation.quantity)
    Goods.objects.filter(pk=goods.pk).update(
        quantity=F('quantity') + reservation.quantity, updated_at=now
    )
    record = StockIn.objects.create(
        goods=goods, zone=zone, reservation=reservation, operator=operator,
        quantity=reservation.quantity, weight=reservation.weight,
        remark=remark or f'预约#{reservation.id}核销入库',
        rule_version=reservation.rule_version,
        compat_version=reservation.compat_version,
    )
    reservation.status = 'fulfilled'
    reservation.save(update_fields=['status', 'updated_at'])
    logger.info(f"User {operator.username} fulfilled reservation {reservation.id}")
    return record

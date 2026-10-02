"""
保管区容量与相容性规则测试

覆盖：区域与规则版本、类别准入、相容性、容量上限、统一校验口径、
临时超限审批与失效、并发占用不超卖、容量释放不为负、历史按发生时规则解释。
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.core.exceptions import BusinessException
from .models import (
    CapacityOverride,
    Category,
    Goods,
    StockIn,
    StockPlacement,
    StorageZone,
    Unit,
    Variety,
    ZoneCapacity,
    ZoneReservation,
    ZoneRuleVersion,
    ZoneTransfer,
    ZoneValidationLog,
)
from .services import ZoneRuleEngine


class ZoneFixture(TestCase):
    """基础数据：两个品类（互不相容）、两种货物、两个保管区"""

    def setUp(self):
        self.admin = User.objects.create_user("zone-admin", "testpass123", role="admin")
        self.operator = User.objects.create_user("zone-operator", "testpass123", role="user")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.admin)}")

        self.unit = Unit.objects.create(name="件", created_by=self.admin)
        self.category_a = Category.objects.create(name="易燃品", unit=self.unit, created_by=self.admin)
        self.category_b = Category.objects.create(name="氧化剂", unit=self.unit, created_by=self.admin)
        self.variety_a = Variety.objects.create(name="酒精", category=self.category_a, created_by=self.admin)
        self.variety_b = Variety.objects.create(name="双氧水", category=self.category_b, created_by=self.admin)
        self.goods_a = Goods.objects.create(
            variety=self.variety_a, name="医用酒精", code="ALC-001",
            quantity=Decimal("0"), unit_weight=Decimal("2.00"),
        )
        self.goods_b = Goods.objects.create(
            variety=self.variety_b, name="双氧水试剂", code="H2O2-001",
            quantity=Decimal("0"), unit_weight=Decimal("5.00"),
        )

        self.zone = StorageZone.objects.create(name="一号保管区", code="Z1", created_by=self.admin)
        self.zone_b = StorageZone.objects.create(name="二号保管区", code="Z2", created_by=self.admin)
        for z in (self.zone, self.zone_b):
            ZoneCapacity.objects.create(zone=z)

        # 一号区规则 v1：100kg / 50 件，两品类不相容
        self.rule_v1 = ZoneRuleVersion.objects.create(
            zone=self.zone, version=1,
            max_weight=Decimal("100"), max_items=Decimal("50"),
            created_by=self.admin,
        )
        self.rule_v1.incompatibilities.create(
            category_a=self.category_a, category_b=self.category_b
        )
        # 二号区规则 v1：1000kg / 500 件，无不相容限制
        ZoneRuleVersion.objects.create(
            zone=self.zone_b, version=1,
            max_weight=Decimal("1000"), max_items=Decimal("500"),
            created_by=self.admin,
        )

    def stock_in(self, goods, zone, quantity, user=None, **kwargs):
        return ZoneRuleEngine.stock_in(
            zone=zone, goods=goods, quantity=Decimal(str(quantity)),
            operator=user or self.admin, **kwargs
        )

    def capacity(self, zone):
        return ZoneCapacity.objects.get(zone=zone)


class ZoneRuleVersionTest(ZoneFixture):
    def test_active_version_follows_effective_from(self):
        """规则版本按生效时间选取，历史版本保留"""
        future = timezone.now() + timedelta(days=1)
        ZoneRuleVersion.objects.create(
            zone=self.zone, version=2,
            max_weight=Decimal("200"), max_items=Decimal("80"),
            effective_from=future, created_by=self.admin,
        )
        # 未来版本尚未生效，当前仍为 v1
        self.assertEqual(ZoneRuleEngine.get_active_version(self.zone).version, 1)
        # 到达生效时间后切换为 v2
        self.assertEqual(
            ZoneRuleEngine.get_active_version(self.zone, at=future).version, 2
        )
        # 历史版本仍在
        self.assertEqual(self.zone.rule_versions.count(), 2)

    def test_rule_create_requires_admin(self):
        """规则版本调整仅管理员可操作"""
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {generate_token(self.operator)}"
        )
        response = self.client.post(
            f"/api/zones/{self.zone.id}/rules/",
            {"max_weight": "100", "max_items": "50"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_rule_create_via_api_keeps_versions(self):
        """通过接口调整规则生成新版本，旧版本不变"""
        response = self.client.post(
            f"/api/zones/{self.zone.id}/rules/",
            {
                "max_weight": "300",
                "max_items": "60",
                "allowed_category_ids": [self.category_a.id],
                "incompatible_pairs": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["version"], 2)
        self.rule_v1.refresh_from_db()
        self.assertEqual(self.rule_v1.max_weight, Decimal("100"))


class ZoneCapacityLimitTest(ZoneFixture):
    def test_weight_limit_rejected(self):
        """超过重量上限的入库被拒绝"""
        with self.assertRaises(BusinessException) as ctx:
            self.stock_in(self.goods_a, self.zone, 60)  # 60 × 2kg = 120kg > 100kg
        self.assertIn("重量上限", str(ctx.exception))

    def test_items_limit_rejected(self):
        """超过件数上限的入库被拒绝"""
        self.goods_a.unit_weight = Decimal("0.10")
        self.goods_a.save()
        with self.assertRaises(BusinessException) as ctx:
            self.stock_in(self.goods_a, self.zone, 51)
        self.assertIn("件数上限", str(ctx.exception))

    def test_boundary_exactly_at_limit_passes(self):
        """恰好达到上限可以通过"""
        self.stock_in(self.goods_a, self.zone, 50)  # 100kg / 50件，正好顶格
        cap = self.capacity(self.zone)
        self.assertEqual(cap.current_weight, Decimal("100.00"))
        self.assertEqual(cap.current_items, Decimal("50.00"))

    def test_allowed_categories_enforced(self):
        """配置准入品类后，未准入品类被拒绝"""
        self.rule_v1.allowed_categories.add(self.category_a)
        with self.assertRaises(BusinessException) as ctx:
            self.stock_in(self.goods_b, self.zone, 1)
        self.assertIn("准入", str(ctx.exception))

    def test_zone_without_rule_rejected(self):
        """未配置规则的保管区不能入库"""
        zone_c = StorageZone.objects.create(name="三号保管区", code="Z3", created_by=self.admin)
        ZoneCapacity.objects.create(zone=zone_c)
        with self.assertRaises(BusinessException) as ctx:
            self.stock_in(self.goods_a, zone_c, 1)
        self.assertIn("未配置容量规则", str(ctx.exception))


class ZoneCompatibilityTest(ZoneFixture):
    def test_incompatible_categories_rejected(self):
        """不相容品类不得同区存放"""
        self.stock_in(self.goods_a, self.zone, 10)
        with self.assertRaises(BusinessException) as ctx:
            self.stock_in(self.goods_b, self.zone, 1)
        self.assertIn("不相容", str(ctx.exception))

    def test_incompatible_allowed_in_different_zones(self):
        """不相容品类分属不同保管区可以存放"""
        self.stock_in(self.goods_a, self.zone, 10)
        self.stock_in(self.goods_b, self.zone_b, 10)
        self.assertEqual(self.capacity(self.zone_b).current_items, Decimal("10.00"))

    def test_reservation_counts_toward_compatibility(self):
        """预约与实物同一口径：有效预约的品类同样触发相容性拦截"""
        ZoneRuleEngine.reserve(
            zone=self.zone, goods=self.goods_a, quantity=Decimal("5"),
            expires_at=timezone.now() + timedelta(hours=2), operator=self.admin,
        )
        with self.assertRaises(BusinessException) as ctx:
            self.stock_in(self.goods_b, self.zone, 1)
        self.assertIn("不相容", str(ctx.exception))

    def test_history_interpreted_by_version_at_occurrence(self):
        """规则调整后新校验按新版本，历史记录仍按发生时版本解释"""
        self.stock_in(self.goods_a, self.zone, 10)
        # v1 口径下：B 与 A 不相容，被拒绝
        with self.assertRaises(BusinessException):
            self.stock_in(self.goods_b, self.zone, 1)
        rejected_log = ZoneValidationLog.objects.filter(result="rejected").latest("id")
        self.assertEqual(rejected_log.rule_version.version, 1)

        # 调整规则：v2 移除不相容限制
        v2 = ZoneRuleVersion.objects.create(
            zone=self.zone, version=2,
            max_weight=Decimal("100"), max_items=Decimal("50"),
            created_by=self.admin,
        )
        self.stock_in(self.goods_b, self.zone, 1)
        passed_log = ZoneValidationLog.objects.filter(result="passed").latest("id")
        self.assertEqual(passed_log.rule_version.version, 2)

        # 历史拒绝记录仍指向 v1，不随规则调整改变
        rejected_log.refresh_from_db()
        self.assertEqual(rejected_log.rule_version.version, 1)
        self.assertEqual(rejected_log.result, "rejected")


class UnifiedValidationTest(ZoneFixture):
    """入库、转移、预约同一判断口径"""

    def test_same_limit_applies_to_all_operations(self):
        """同一超限量在三种操作下都被拒绝，且校验记录区分操作类型"""
        # 先占用到接近上限：40 件 × 2kg = 80kg，余量 10 件 / 20kg
        self.stock_in(self.goods_a, self.zone, 40)

        # 入库 20 件（40kg）超限
        with self.assertRaises(BusinessException):
            self.stock_in(self.goods_a, self.zone, 20)
        # 预约 20 件超限
        with self.assertRaises(BusinessException):
            ZoneRuleEngine.reserve(
                zone=self.zone, goods=self.goods_a, quantity=Decimal("20"),
                expires_at=timezone.now() + timedelta(hours=1), operator=self.admin,
            )
        # 转移 20 件超限（先把货物放到二号区）
        self.stock_in(self.goods_a, self.zone_b, 30)
        with self.assertRaises(BusinessException):
            ZoneRuleEngine.transfer(
                goods=self.goods_a, from_zone=self.zone_b, to_zone=self.zone,
                quantity=Decimal("20"), operator=self.admin,
            )

        logs = ZoneValidationLog.objects.filter(zone=self.zone, result="rejected")
        self.assertEqual(
            set(logs.values_list("operation", flat=True)),
            {"stock_in", "transfer", "reservation"},
        )

    def test_reservation_counts_toward_capacity(self):
        """预约占用与实物占用合并计算容量"""
        ZoneRuleEngine.reserve(
            zone=self.zone, goods=self.goods_a, quantity=Decimal("30"),
            expires_at=timezone.now() + timedelta(hours=1), operator=self.admin,
        )
        # 已预约 30 件（60kg），再入库 25 件（50kg）合计 110kg 超限
        with self.assertRaises(BusinessException) as ctx:
            self.stock_in(self.goods_a, self.zone, 25)
        self.assertIn("重量上限", str(ctx.exception))
        # 入库 20 件（40kg）合计 100kg 通过
        self.stock_in(self.goods_a, self.zone, 20)


class CapacityOverrideTest(ZoneFixture):
    def test_override_requires_admin(self):
        """临时超限只能由有权限的人批准"""
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {generate_token(self.operator)}"
        )
        response = self.client.post(
            f"/api/zones/{self.zone.id}/overrides/",
            {
                "extra_weight": "50", "extra_items": "10",
                "reason": "临时周转",
                "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_override_requires_expiry(self):
        """临时超限必须设置失效时间"""
        response = self.client.post(
            f"/api/zones/{self.zone.id}/overrides/",
            {"extra_weight": "50", "reason": "临时周转"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("失效时间", response.json()["message"])

    def test_override_allows_temporary_excess(self):
        """生效中的临时超限追加额度，超限入库成功"""
        self.stock_in(self.goods_a, self.zone, 50)  # 顶格 100kg/50件
        CapacityOverride.objects.create(
            zone=self.zone, extra_weight=Decimal("20"), extra_items=Decimal("10"),
            reason="临时周转", approved_by=self.admin,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.stock_in(self.goods_a, self.zone, 5)  # 追加额度内
        self.assertEqual(self.capacity(self.zone).current_items, Decimal("55.00"))

    def test_expired_override_no_longer_effective(self):
        """超限批准到期后自动失效"""
        CapacityOverride.objects.create(
            zone=self.zone, extra_weight=Decimal("20"), extra_items=Decimal("10"),
            reason="临时周转", approved_by=self.admin,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.stock_in(self.goods_a, self.zone, 50)
        with self.assertRaises(BusinessException):
            self.stock_in(self.goods_a, self.zone, 1)

    def test_revoked_override_no_longer_effective(self):
        """超限批准被撤销后立即失效"""
        override = CapacityOverride.objects.create(
            zone=self.zone, extra_weight=Decimal("20"), extra_items=Decimal("10"),
            reason="临时周转", approved_by=self.admin,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        response = self.client.post(f"/api/overrides/{override.id}/revoke/")
        self.assertEqual(response.status_code, 200)
        self.stock_in(self.goods_a, self.zone, 50)
        with self.assertRaises(BusinessException):
            self.stock_in(self.goods_a, self.zone, 1)


class ConcurrencySafetyTest(ZoneFixture):
    """并发占用不超卖、容量释放不为负"""

    def test_double_occupy_after_double_validate_no_oversell(self):
        """两个请求同时通过校验后，条件更新只放行其一（模拟并发）"""
        # 余量 10 件：两个 8 件的申请都通过校验
        self.stock_in(self.goods_a, self.zone, 40)
        ok1, _, _ = ZoneRuleEngine.validate_placement(
            self.zone, self.goods_a, Decimal("8"), "stock_in", self.admin
        )
        ok2, _, _ = ZoneRuleEngine.validate_placement(
            self.zone, self.goods_a, Decimal("8"), "stock_in", self.admin
        )
        self.assertTrue(ok1 and ok2)

        # 第一次占用成功，第二次被数据库条件更新拦截
        ZoneRuleEngine.occupy(self.zone, Decimal("8"), Decimal("16"))
        with self.assertRaises(BusinessException):
            ZoneRuleEngine.occupy(self.zone, Decimal("8"), Decimal("16"))

        cap = self.capacity(self.zone)
        self.assertEqual(cap.current_items, Decimal("48.00"))
        self.assertLessEqual(cap.current_weight, Decimal("100.00"))

    def test_release_never_goes_negative(self):
        """释放量超过占用量时失败且计数不为负"""
        self.stock_in(self.goods_a, self.zone, 10)
        with self.assertRaises(BusinessException):
            ZoneRuleEngine.release(self.zone, Decimal("11"), Decimal("22"))
        cap = self.capacity(self.zone)
        self.assertEqual(cap.current_items, Decimal("10.00"))
        self.assertGreaterEqual(cap.current_weight, Decimal("0"))

    def test_reservation_release_never_negative(self):
        """重复取消预约不会重复释放"""
        reservation = ZoneRuleEngine.reserve(
            zone=self.zone, goods=self.goods_a, quantity=Decimal("5"),
            expires_at=timezone.now() + timedelta(hours=1), operator=self.admin,
        )
        ZoneRuleEngine.cancel_reservation(reservation, self.admin)
        with self.assertRaises(BusinessException):
            ZoneRuleEngine.cancel_reservation(reservation, self.admin)
        self.assertEqual(self.capacity(self.zone).reserved_items, Decimal("0.00"))


class TransferTest(ZoneFixture):
    def test_partial_transfer_moves_capacity(self):
        """部分转移同步移动存放明细与容量计数"""
        self.stock_in(self.goods_a, self.zone, 20)  # 40kg
        ZoneRuleEngine.transfer(
            goods=self.goods_a, from_zone=self.zone, to_zone=self.zone_b,
            quantity=Decimal("8"), operator=self.admin,
        )
        cap_a, cap_b = self.capacity(self.zone), self.capacity(self.zone_b)
        self.assertEqual(cap_a.current_items, Decimal("12.00"))
        self.assertEqual(cap_b.current_items, Decimal("8.00"))
        self.assertEqual(
            StockPlacement.objects.get(goods=self.goods_a, zone=self.zone_b).quantity,
            Decimal("8.00"),
        )
        self.assertEqual(ZoneTransfer.objects.count(), 1)

    def test_transfer_respects_target_compatibility(self):
        """转移校验目标区相容性"""
        self.stock_in(self.goods_a, self.zone, 10)
        self.stock_in(self.goods_b, self.zone_b, 10)
        with self.assertRaises(BusinessException) as ctx:
            ZoneRuleEngine.transfer(
                goods=self.goods_b, from_zone=self.zone_b, to_zone=self.zone,
                quantity=Decimal("1"), operator=self.admin,
            )
        self.assertIn("不相容", str(ctx.exception))

    def test_transfer_insufficient_source_rejected(self):
        """源区存放不足时转移失败"""
        self.stock_in(self.goods_a, self.zone, 5)
        with self.assertRaises(BusinessException) as ctx:
            ZoneRuleEngine.transfer(
                goods=self.goods_a, from_zone=self.zone, to_zone=self.zone_b,
                quantity=Decimal("6"), operator=self.admin,
            )
        self.assertIn("不足", str(ctx.exception))
        # 源区计数未被扣减
        self.assertEqual(self.capacity(self.zone).current_items, Decimal("5.00"))


class ReservationTest(ZoneFixture):
    def test_fulfill_reservation_via_stock_in(self):
        """按预约入库：预约占用转为实物占用并生成入库记录"""
        reservation = ZoneRuleEngine.reserve(
            zone=self.zone, goods=self.goods_a, quantity=Decimal("10"),
            expires_at=timezone.now() + timedelta(hours=2), operator=self.admin,
        )
        stock_in = ZoneRuleEngine.stock_in(
            zone=self.zone, goods=self.goods_a, quantity=Decimal("10"),
            operator=self.admin, reservation=reservation,
        )
        cap = self.capacity(self.zone)
        self.assertEqual(cap.reserved_items, Decimal("0.00"))
        self.assertEqual(cap.current_items, Decimal("10.00"))
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, "fulfilled")
        self.assertEqual(stock_in.rule_version.version, 1)
        self.assertEqual(stock_in.zone, self.zone)

    def test_expired_reservation_releases_capacity(self):
        """预约到期自动释放占用额度"""
        ZoneRuleEngine.reserve(
            zone=self.zone, goods=self.goods_a, quantity=Decimal("40"),
            expires_at=timezone.now() + timedelta(minutes=5), operator=self.admin,
        )
        # 到期前：余量不足，入库 20 件被拒
        with self.assertRaises(BusinessException):
            self.stock_in(self.goods_a, self.zone, 20)

        # 让预约过期
        ZoneReservation.objects.all().update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        # 下一次校验触发过期释放，入库成功
        self.stock_in(self.goods_a, self.zone, 20)
        self.assertEqual(self.capacity(self.zone).reserved_items, Decimal("0.00"))
        self.assertEqual(
            ZoneReservation.objects.get().status, "expired"
        )

    def test_reservation_requires_future_expiry(self):
        """预约失效时间必须晚于当前时间"""
        with self.assertRaises(BusinessException):
            ZoneRuleEngine.reserve(
                zone=self.zone, goods=self.goods_a, quantity=Decimal("1"),
                expires_at=timezone.now() - timedelta(minutes=1), operator=self.admin,
            )

    def test_stock_in_with_expired_reservation_rejected(self):
        """按已过期预约入库被拒绝，且不误记"通过"的校验留痕"""
        reservation = ZoneRuleEngine.reserve(
            zone=self.zone, goods=self.goods_a, quantity=Decimal("5"),
            expires_at=timezone.now() + timedelta(minutes=5), operator=self.admin,
        )
        ZoneReservation.objects.filter(pk=reservation.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        reservation.refresh_from_db()
        with self.assertRaises(BusinessException) as ctx:
            ZoneRuleEngine.stock_in(
                zone=self.zone, goods=self.goods_a, quantity=Decimal("5"),
                operator=self.admin, reservation=reservation,
            )
        self.assertIn("预约已失效", str(ctx.exception))
        self.assertFalse(
            ZoneValidationLog.objects.filter(operation="stock_in").exists()
        )


class ZoneAPITest(ZoneFixture):
    """接口层验收"""

    def test_zone_crud_and_occupancy(self):
        created = self.client.post(
            "/api/zones/", {"name": "三号保管区", "code": "Z3"}, format="json"
        )
        self.assertEqual(created.status_code, 200)
        zone_id = created.json()["data"]["id"]

        occupancy = self.client.get(f"/api/zones/{zone_id}/occupancy/")
        self.assertEqual(occupancy.status_code, 200)
        self.assertIsNone(occupancy.json()["data"]["rule_version"])

    def test_stock_in_api_validates_zone(self):
        """入库接口走统一校验：超限返回 400 且留校验记录"""
        response = self.client.post(
            "/api/stock-in/",
            {"goods": self.goods_a.id, "zone": self.zone.id, "quantity": "60"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("重量上限", response.json()["message"])
        log = ZoneValidationLog.objects.latest("id")
        self.assertEqual(log.operation, "stock_in")
        self.assertEqual(log.result, "rejected")
        self.assertEqual(log.limit_weight_snapshot, Decimal("100.00"))

    def test_stock_in_api_success_updates_everything(self):
        """入库成功：库存、存放明细、容量计数、入库记录一致"""
        response = self.client.post(
            "/api/stock-in/",
            {
                "goods": self.goods_a.id, "zone": self.zone.id,
                "quantity": "10", "batch_no": "B20261002",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.goods_a.refresh_from_db()
        self.assertEqual(self.goods_a.quantity, Decimal("10.00"))
        self.assertEqual(self.capacity(self.zone).current_items, Decimal("10.00"))
        self.assertEqual(
            StockPlacement.objects.get(goods=self.goods_a, zone=self.zone).quantity,
            Decimal("10.00"),
        )
        stock_in = StockIn.objects.latest("id")
        self.assertEqual(stock_in.zone, self.zone)
        self.assertEqual(stock_in.rule_version.version, 1)

    def test_reservation_api_and_cancel(self):
        """预约接口与取消接口"""
        expires = (timezone.now() + timedelta(hours=1)).isoformat()
        created = self.client.post(
            "/api/reservations/",
            {
                "goods": self.goods_a.id, "zone": self.zone.id,
                "quantity": "5", "expires_at": expires,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 200)
        reservation_id = created.json()["data"]["id"]
        self.assertEqual(self.capacity(self.zone).reserved_items, Decimal("5.00"))

        cancelled = self.client.post(f"/api/reservations/{reservation_id}/cancel/")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(self.capacity(self.zone).reserved_items, Decimal("0.00"))

    def test_transfer_api(self):
        """转移接口"""
        self.stock_in(self.goods_a, self.zone, 10)
        response = self.client.post(
            "/api/transfers/",
            {
                "goods": self.goods_a.id,
                "from_zone": self.zone.id, "to_zone": self.zone_b.id,
                "quantity": "4",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.capacity(self.zone_b).current_items, Decimal("4.00"))

    def test_validation_log_api(self):
        """校验记录接口返回发生时规则版本与上限快照"""
        self.stock_in(self.goods_a, self.zone, 10)
        response = self.client.get(f"/api/zones/{self.zone.id}/validations/")
        self.assertEqual(response.status_code, 200)
        item = response.json()["data"]["list"][0]
        self.assertEqual(item["rule_version_number"], 1)
        self.assertEqual(item["limit_weight_snapshot"], "100.00")
        self.assertEqual(item["result"], "passed")

    def test_zone_delete_guard(self):
        """有物资或记录的保管区不能删除"""
        self.stock_in(self.goods_a, self.zone, 1)
        response = self.client.delete(f"/api/zones/{self.zone.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(StorageZone.objects.filter(pk=self.zone.id).exists())

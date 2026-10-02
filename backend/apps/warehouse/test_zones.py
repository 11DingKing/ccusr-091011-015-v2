"""
保管区容量、相容性与统一校验测试
"""
import threading
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.core.exceptions import BusinessException
from . import services
from .models import (
    Category, Goods, GoodsZoneStock, OverLimitApproval, StockIn, StorageZone,
    Unit, Variety, ZoneCategoryOccupancy, ZoneOccupancy, ZoneReservation,
    ZoneRuleVersion,
)


class ZoneFixture(TestCase):
    """保管区测试基础数据"""

    def setUp(self):
        self.admin = User.objects.create_user("zone-admin", "testpass123", role="admin")
        self.operator = User.objects.create_user("zone-operator", "testpass123", role="user")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.admin)}")
        self.operator_client = APIClient()
        self.operator_client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.operator)}")

        self.unit = Unit.objects.create(name="件", created_by=self.admin)
        self.cat_chem = Category.objects.create(name="化学品", unit=self.unit, created_by=self.admin)
        self.cat_food = Category.objects.create(name="食品", unit=self.unit, created_by=self.admin)
        self.cat_doc = Category.objects.create(name="文档", unit=self.unit, created_by=self.admin)
        self.variety_chem = Variety.objects.create(name="试剂", category=self.cat_chem, created_by=self.admin)
        self.variety_food = Variety.objects.create(name="口粮", category=self.cat_food, created_by=self.admin)
        self.variety_doc = Variety.objects.create(name="卷宗", category=self.cat_doc, created_by=self.admin)
        self.goods_chem = Goods.objects.create(
            variety=self.variety_chem, name="酸碱试剂", code="CHEM-001",
            quantity=Decimal("0"), unit_weight=Decimal("2"),
        )
        self.goods_food = Goods.objects.create(
            variety=self.variety_food, name="应急口粮", code="FOOD-001",
            quantity=Decimal("0"), unit_weight=Decimal("1"),
        )
        self.goods_doc = Goods.objects.create(
            variety=self.variety_doc, name="封存卷宗", code="DOC-001",
            quantity=Decimal("0"), unit_weight=Decimal("0.5"),
        )

    def create_zone(self, name="A区", max_weight="100", max_items="10", allowed=None):
        """创建保管区并发布首版规则"""
        zone = StorageZone.objects.create(name=name, created_by=self.admin)
        payload = {"max_weight": max_weight, "max_items": max_items}
        if allowed is not None:
            payload["allowed_category_ids"] = allowed
        response = self.client.post(f"/api/zones/{zone.id}/rules/", payload, format="json")
        assert response.status_code == 200, response.json()
        return zone


class ZoneRuleApiTest(ZoneFixture):
    def test_create_zone_and_publish_rule_versions(self):
        created = self.client.post("/api/zones/", {"name": "冷链区", "description": "低温"}, format="json")
        self.assertEqual(created.status_code, 200)
        zone_id = created.json()["data"]["id"]

        v1 = self.client.post(
            f"/api/zones/{zone_id}/rules/",
            {"max_weight": "100", "max_items": "10", "allowed_category_ids": [self.cat_chem.id]},
            format="json",
        )
        self.assertEqual(v1.status_code, 200)
        self.assertEqual(v1.json()["data"]["version"], 1)
        self.assertEqual(v1.json()["data"]["allowed_category_ids"], [self.cat_chem.id])

        v2 = self.client.post(
            f"/api/zones/{zone_id}/rules/", {"max_weight": "80", "max_items": "8"}, format="json"
        )
        self.assertEqual(v2.status_code, 200)
        self.assertEqual(v2.json()["data"]["version"], 2)

        history = self.client.get(f"/api/zones/{zone_id}/rules/")
        versions = [item["version"] for item in history.json()["data"]]
        self.assertEqual(versions, [2, 1], "旧版本规则必须保留")

    def test_rule_validation_rejects_invalid_payload(self):
        zone = StorageZone.objects.create(name="B区", created_by=self.admin)
        bad = self.client.post(
            f"/api/zones/{zone.id}/rules/", {"max_weight": "0", "max_items": "10"}, format="json"
        )
        self.assertEqual(bad.status_code, 400)
        missing_category = self.client.post(
            f"/api/zones/{zone.id}/rules/",
            {"max_weight": "10", "max_items": "10", "allowed_category_ids": [99999]},
            format="json",
        )
        self.assertEqual(missing_category.status_code, 400)

    def test_future_effective_rule_not_yet_active(self):
        zone = StorageZone.objects.create(name="C区", created_by=self.admin)
        future = (timezone.now() + timedelta(days=1)).isoformat()
        self.client.post(
            f"/api/zones/{zone.id}/rules/",
            {"max_weight": "100", "max_items": "10", "effective_from": future},
            format="json",
        )
        # 规则尚未生效，入库被拒绝
        response = self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("尚未配置生效的容量规则", response.json()["message"])

    def test_delete_zone_with_rules_refused(self):
        zone = self.create_zone(name="D区")
        response = self.client.delete(f"/api/zones/{zone.id}/")
        self.assertEqual(response.status_code, 400)
        empty_zone = StorageZone.objects.create(name="E区", created_by=self.admin)
        response = self.client.delete(f"/api/zones/{empty_zone.id}/")
        self.assertEqual(response.status_code, 200)


class StockInValidationTest(ZoneFixture):
    """入库与预检共用统一判断口径"""

    def test_stock_in_occupies_capacity(self):
        zone = self.create_zone()
        response = self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "3"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()["data"]
        self.assertEqual(data["weight"], "6.00")
        self.assertEqual(data["rule_version_detail"]["version"], 1)

        occupancy = ZoneOccupancy.objects.get(zone=zone)
        self.assertEqual(occupancy.used_items, Decimal("3"))
        self.assertEqual(occupancy.used_weight, Decimal("6"))
        self.goods_chem.refresh_from_db()
        self.assertEqual(self.goods_chem.quantity, Decimal("3"))
        stock = GoodsZoneStock.objects.get(goods=self.goods_chem, zone=zone)
        self.assertEqual(stock.quantity, Decimal("3"))

    def test_stock_in_rejects_over_weight_and_items(self):
        zone = self.create_zone(max_weight="100", max_items="10")
        over_items = self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "11"}, format="json"
        )
        self.assertEqual(over_items.status_code, 400)
        self.assertIn("件数超限", over_items.json()["message"])

        over_weight = self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "10"}, format="json"
        )
        # 10件 * 2kg = 20kg，未超100kg；先入库5件再入6件超件数
        self.assertEqual(over_weight.status_code, 200)
        zone2 = self.create_zone(name="F区", max_weight="5", max_items="100")
        too_heavy = self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone2.id, "quantity": "3"}, format="json"
        )
        self.assertEqual(too_heavy.status_code, 400)
        self.assertIn("重量超限", too_heavy.json()["message"])

    def test_stock_in_rejects_disallowed_category(self):
        zone = self.create_zone(allowed=[self.cat_doc.id])
        response = self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不在保管区", response.json()["message"])

        ok = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(ok.status_code, 200)

    def test_stock_in_rejects_incompatible_category(self):
        self.client.post(
            "/api/compatibility-rules/",
            {"pairs": [{"category_a": self.cat_chem.id, "category_b": self.cat_food.id}]},
            format="json",
        )
        zone = self.create_zone()
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        response = self.client.post(
            "/api/stock-in/", {"goods": self.goods_food.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不相容", response.json()["message"])

        # 另一保管区无化学品，食品可以入库
        other_zone = self.create_zone(name="G区")
        ok = self.client.post(
            "/api/stock-in/", {"goods": self.goods_food.id, "zone": other_zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(ok.status_code, 200)

    def test_validate_preview_shares_same_rules(self):
        self.client.post(
            "/api/compatibility-rules/",
            {"pairs": [{"category_a": self.cat_chem.id, "category_b": self.cat_food.id}]},
            format="json",
        )
        zone = self.create_zone(max_items="5")
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        ok = self.client.post(
            f"/api/zones/{zone.id}/validate/",
            {"goods": self.goods_doc.id, "quantity": "1"},
            format="json",
        )
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["data"]["valid"])

        incompatible = self.client.post(
            f"/api/zones/{zone.id}/validate/",
            {"goods": self.goods_food.id, "quantity": "1"},
            format="json",
        )
        self.assertEqual(incompatible.status_code, 400)
        self.assertIn("不相容", incompatible.json()["message"])

        over_capacity = self.client.post(
            f"/api/zones/{zone.id}/validate/",
            {"goods": self.goods_doc.id, "quantity": "5"},
            format="json",
        )
        self.assertEqual(over_capacity.status_code, 400)
        self.assertIn("件数超限", over_capacity.json()["message"])

    def test_stock_in_requires_zone_and_goods(self):
        zone = self.create_zone()
        missing_zone = self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(missing_zone.status_code, 400)
        bad_goods = self.client.post(
            "/api/stock-in/", {"goods": 99999, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(bad_goods.status_code, 400)


class OverLimitApprovalTest(ZoneFixture):
    def test_only_admin_can_approve(self):
        zone = self.create_zone()
        payload = {
            "zone": zone.id, "extra_items": "5", "reason": "临时周转",
            "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        }
        denied = self.operator_client.post("/api/overrides/", payload, format="json")
        self.assertEqual(denied.status_code, 403)
        allowed = self.client.post("/api/overrides/", payload, format="json")
        self.assertEqual(allowed.status_code, 200)

    def test_approval_requires_future_expiry_and_positive_amount(self):
        zone = self.create_zone()
        no_expiry = self.client.post(
            "/api/overrides/", {"zone": zone.id, "extra_items": "5", "reason": "x"}, format="json"
        )
        self.assertEqual(no_expiry.status_code, 400)
        past_expiry = self.client.post(
            "/api/overrides/",
            {
                "zone": zone.id, "extra_items": "5", "reason": "x",
                "expires_at": (timezone.now() - timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(past_expiry.status_code, 400)
        zero_amount = self.client.post(
            "/api/overrides/",
            {
                "zone": zone.id, "reason": "x",
                "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(zero_amount.status_code, 400)

    def test_override_extends_capacity_until_expiry_or_revoke(self):
        zone = self.create_zone(max_items="10")
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "10"}, format="json"
        )
        overflow = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(overflow.status_code, 400)

        # 管理员批准临时超限 5 件
        approval = self.client.post(
            "/api/overrides/",
            {
                "zone": zone.id, "extra_items": "5", "reason": "月末集中入库",
                "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(approval.status_code, 200)
        approval_id = approval.json()["data"]["id"]

        ok = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "5"}, format="json"
        )
        self.assertEqual(ok.status_code, 200)

        # 撤销后立即恢复原有上限
        revoked = self.client.post(f"/api/overrides/{approval_id}/revoke/")
        self.assertEqual(revoked.status_code, 200)
        again = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(again.status_code, 400)

    def test_expired_override_not_counted(self):
        zone = self.create_zone(max_items="10")
        OverLimitApproval.objects.create(
            zone=zone, approved_by=self.admin, extra_items=Decimal("5"),
            reason="已过期", expires_at=timezone.now() - timedelta(minutes=1),
        )
        response = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "11"}, format="json"
        )
        self.assertEqual(response.status_code, 400)


class TransferTest(ZoneFixture):
    def test_transfer_moves_occupancy_between_zones(self):
        source = self.create_zone(name="源区")
        target = self.create_zone(name="目标区")
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": source.id, "quantity": "4"}, format="json"
        )

        response = self.client.post(
            "/api/transfers/",
            {"goods": self.goods_chem.id, "from_zone": source.id, "to_zone": target.id, "quantity": "3"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["data"]["weight"], "6.00")

        source_occ = ZoneOccupancy.objects.get(zone=source)
        target_occ = ZoneOccupancy.objects.get(zone=target)
        self.assertEqual(source_occ.used_items, Decimal("1"))
        self.assertEqual(target_occ.used_items, Decimal("3"))
        self.assertEqual(target_occ.used_weight, Decimal("6"))
        self.assertEqual(
            GoodsZoneStock.objects.get(goods=self.goods_chem, zone=source).quantity, Decimal("1")
        )
        self.assertEqual(
            GoodsZoneStock.objects.get(goods=self.goods_chem, zone=target).quantity, Decimal("3")
        )

    def test_transfer_validates_target_with_same_rules(self):
        self.client.post(
            "/api/compatibility-rules/",
            {"pairs": [{"category_a": self.cat_chem.id, "category_b": self.cat_food.id}]},
            format="json",
        )
        source = self.create_zone(name="源区2")
        target = self.create_zone(name="目标区2", max_items="2")
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": source.id, "quantity": "5"}, format="json"
        )
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_food.id, "zone": target.id, "quantity": "1"}, format="json"
        )

        # 目标区已有不相容品类
        incompatible = self.client.post(
            "/api/transfers/",
            {"goods": self.goods_chem.id, "from_zone": source.id, "to_zone": target.id, "quantity": "1"},
            format="json",
        )
        self.assertEqual(incompatible.status_code, 400)
        self.assertIn("不相容", incompatible.json()["message"])

        # 目标区容量不足（已用1件 + 本次2件 > 2件上限）
        self.client.post(
            "/api/compatibility-rules/", {"pairs": []}, format="json"
        )
        over = self.client.post(
            "/api/transfers/",
            {"goods": self.goods_chem.id, "from_zone": source.id, "to_zone": target.id, "quantity": "2"},
            format="json",
        )
        self.assertEqual(over.status_code, 400)
        self.assertIn("件数超限", over.json()["message"])

        # 校验失败不得影响源区占用
        self.assertEqual(ZoneOccupancy.objects.get(zone=source).used_items, Decimal("5"))

    def test_transfer_rejects_insufficient_stock_and_same_zone(self):
        source = self.create_zone(name="源区3")
        target = self.create_zone(name="目标区3")
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": source.id, "quantity": "2"}, format="json"
        )
        insufficient = self.client.post(
            "/api/transfers/",
            {"goods": self.goods_chem.id, "from_zone": source.id, "to_zone": target.id, "quantity": "5"},
            format="json",
        )
        self.assertEqual(insufficient.status_code, 400)
        self.assertIn("存量不足", insufficient.json()["message"])

        same_zone = self.client.post(
            "/api/transfers/",
            {"goods": self.goods_chem.id, "from_zone": source.id, "to_zone": source.id, "quantity": "1"},
            format="json",
        )
        self.assertEqual(same_zone.status_code, 400)


class ReservationTest(ZoneFixture):
    def _reserve(self, goods, zone, quantity, hours=1):
        return self.client.post(
            "/api/reservations/",
            {
                "goods": goods.id, "zone": zone.id, "quantity": str(quantity),
                "expires_at": (timezone.now() + timedelta(hours=hours)).isoformat(),
            },
            format="json",
        )

    def test_reservation_blocks_stock_in_under_same_rules(self):
        zone = self.create_zone(max_items="10")
        reserved = self._reserve(self.goods_chem, zone, 8)
        self.assertEqual(reserved.status_code, 200, reserved.json())
        self.assertEqual(reserved.json()["data"]["status"], "active")

        occupancy = ZoneOccupancy.objects.get(zone=zone)
        self.assertEqual(occupancy.reserved_items, Decimal("8"))
        self.assertEqual(occupancy.reserved_weight, Decimal("16"))

        # 预约占用计入同一口径：剩余仅2件
        rejected = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "3"}, format="json"
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("件数超限", rejected.json()["message"])
        ok = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "2"}, format="json"
        )
        self.assertEqual(ok.status_code, 200)

    def test_reservation_requires_future_expiry(self):
        zone = self.create_zone()
        response = self.client.post(
            "/api/reservations/",
            {
                "goods": self.goods_chem.id, "zone": zone.id, "quantity": "1",
                "expires_at": (timezone.now() - timedelta(minutes=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_releases_reserved_capacity(self):
        zone = self.create_zone(max_items="10")
        reservation_id = self._reserve(self.goods_chem, zone, 8).json()["data"]["id"]
        cancelled = self.client.post(f"/api/reservations/{reservation_id}/cancel/")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["data"]["status"], "cancelled")

        occupancy = ZoneOccupancy.objects.get(zone=zone)
        self.assertEqual(occupancy.reserved_items, Decimal("0"))
        self.assertEqual(occupancy.reserved_weight, Decimal("0"))

        # 已取消的预约不能再次取消或核销
        again = self.client.post(f"/api/reservations/{reservation_id}/cancel/")
        self.assertEqual(again.status_code, 400)
        fulfill = self.client.post(f"/api/reservations/{reservation_id}/fulfill/")
        self.assertEqual(fulfill.status_code, 400)

    def test_fulfill_converts_reservation_to_stock_in(self):
        zone = self.create_zone(max_items="10")
        reservation_id = self._reserve(self.goods_chem, zone, 6).json()["data"]["id"]
        fulfilled = self.client.post(f"/api/reservations/{reservation_id}/fulfill/")
        self.assertEqual(fulfilled.status_code, 200, fulfilled.json())

        record = StockIn.objects.get(reservation_id=reservation_id)
        self.assertEqual(record.quantity, Decimal("6"))
        self.assertEqual(record.zone_id, zone.id)
        self.assertIsNotNone(record.rule_version_id)

        occupancy = ZoneOccupancy.objects.get(zone=zone)
        self.assertEqual(occupancy.reserved_items, Decimal("0"))
        self.assertEqual(occupancy.used_items, Decimal("6"))
        self.goods_chem.refresh_from_db()
        self.assertEqual(self.goods_chem.quantity, Decimal("6"))
        self.assertEqual(
            ZoneReservation.objects.get(pk=reservation_id).status, "fulfilled"
        )

    def test_expired_reservation_released_on_next_operation(self):
        zone = self.create_zone(max_items="10")
        reservation_id = self._reserve(self.goods_chem, zone, 8).json()["data"]["id"]
        # 直接改写失效时间模拟过期
        ZoneReservation.objects.filter(pk=reservation_id).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        # 下一次入库操作触发过期释放，容量恢复后可入库
        response = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "10"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(ZoneReservation.objects.get(pk=reservation_id).status, "expired")
        occupancy = ZoneOccupancy.objects.get(zone=zone)
        self.assertEqual(occupancy.reserved_items, Decimal("0"))
        self.assertEqual(occupancy.used_items, Decimal("10"))

        # 过期预约不能核销
        fulfill = self.client.post(f"/api/reservations/{reservation_id}/fulfill/")
        self.assertEqual(fulfill.status_code, 400)

    def test_management_command_releases_expired(self):
        zone = self.create_zone(max_items="10")
        reservation_id = self._reserve(self.goods_chem, zone, 8).json()["data"]["id"]
        ZoneReservation.objects.filter(pk=reservation_id).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        from django.core.management import call_command
        call_command("release_expired_reservations")
        self.assertEqual(ZoneReservation.objects.get(pk=reservation_id).status, "expired")
        self.assertEqual(ZoneOccupancy.objects.get(zone=zone).reserved_items, Decimal("0"))


class OccupancyIntegrityTest(ZoneFixture):
    def test_release_beyond_occupancy_rejected(self):
        zone = self.create_zone()
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "2"}, format="json"
        )
        with self.assertRaises(BusinessException):
            services.release(zone, self.cat_chem, Decimal("100"), Decimal("5"), "used")
        occupancy = ZoneOccupancy.objects.get(zone=zone)
        self.assertEqual(occupancy.used_items, Decimal("2"), "释放失败不得改变现有占用")

    def test_database_constraints_prevent_negative_occupancy(self):
        zone = self.create_zone()
        self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "2"}, format="json"
        )
        occupancy = ZoneOccupancy.objects.get(zone=zone)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ZoneOccupancy.objects.filter(pk=occupancy.pk).update(used_items=Decimal("-1"))
        category_row = ZoneCategoryOccupancy.objects.get(zone=zone, category=self.cat_chem)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ZoneCategoryOccupancy.objects.filter(pk=category_row.pk).update(
                    reserved_weight=Decimal("-0.01")
                )


class RuleVersionHistoryTest(ZoneFixture):
    def test_records_keep_rule_snapshot_and_history_interpretation(self):
        zone = StorageZone.objects.create(name="历史区", created_by=self.admin)
        yesterday = timezone.now() - timedelta(days=1)
        v1 = ZoneRuleVersion.objects.create(
            zone=zone, version=1, max_weight=Decimal("1000"), max_items=Decimal("100"),
            effective_from=yesterday, created_by=self.admin,
        )
        first = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "50"}, format="json"
        )
        self.assertEqual(first.status_code, 200)
        record = StockIn.objects.get(pk=first.json()["data"]["id"])
        self.assertEqual(record.rule_version_id, v1.id, "入库记录必须保存发生时规则版本")

        # 发布更严格的 v2 后，同样的入库按新口径被拒绝
        self.client.post(
            f"/api/zones/{zone.id}/rules/", {"max_weight": "1000", "max_items": "60"}, format="json"
        )
        rejected = self.client.post(
            "/api/stock-in/", {"goods": self.goods_doc.id, "zone": zone.id, "quantity": "20"}, format="json"
        )
        self.assertEqual(rejected.status_code, 400)

        # 但按发生时（v1 生效期间）口径解释，50+20 并未超 100 件上限
        context = services.validate_placement(
            zone, self.cat_doc, Decimal("20"), self.goods_doc.unit_weight,
            at_time=timezone.now() - timedelta(hours=1),
        )
        self.assertEqual(context["rule_version"].version, 1)

        # 历史记录序列化携带规则快照
        listing = self.client.get("/api/stock-in/")
        first_record = listing.json()["data"]["list"][0]
        self.assertEqual(first_record["rule_version_detail"]["version"], 1)
        self.assertEqual(first_record["rule_version_detail"]["max_items"], "100.00")

    def test_compat_rule_history_interpretation(self):
        zone = self.create_zone(name="相容历史区")
        v1_response = self.client.post("/api/compatibility-rules/", {"pairs": []}, format="json")
        v1_id = v1_response.json()["data"]["id"]
        first = self.client.post(
            "/api/stock-in/", {"goods": self.goods_chem.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(first.status_code, 200)
        record = StockIn.objects.get(pk=first.json()["data"]["id"])
        self.assertEqual(record.compat_version_id, v1_id)

        # 新版本将化学品与食品列为不相容
        self.client.post(
            "/api/compatibility-rules/",
            {"pairs": [{"category_a": self.cat_chem.id, "category_b": self.cat_food.id}]},
            format="json",
        )
        rejected = self.client.post(
            "/api/stock-in/", {"goods": self.goods_food.id, "zone": zone.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("不相容", rejected.json()["message"])

        # 按 v1 生效时口径，食品当时可以放入
        from .models import CompatibilityRuleVersion
        v1 = CompatibilityRuleVersion.objects.get(pk=v1_id)
        context = services.validate_placement(
            zone, self.cat_food, Decimal("1"), self.goods_food.unit_weight,
            at_time=v1.effective_from,
        )
        self.assertEqual(context["compat_version"].id, v1_id)


class ConcurrentOccupancyTest(TransactionTestCase):
    """并发占用：不得超卖、不得出现负数"""

    def setUp(self):
        self.admin = User.objects.create_user("conc-admin", "testpass123", role="admin")
        self.unit = Unit.objects.create(name="件", created_by=self.admin)
        self.category = Category.objects.create(name="器材", unit=self.unit, created_by=self.admin)
        self.variety = Variety.objects.create(name="终端", category=self.category, created_by=self.admin)
        self.goods = Goods.objects.create(
            variety=self.variety, name="并发货物", code="CONC-001",
            quantity=Decimal("0"), unit_weight=Decimal("1"),
        )
        self.zone = StorageZone.objects.create(name="并发区", created_by=self.admin)
        ZoneRuleVersion.objects.create(
            zone=self.zone, version=1, max_weight=Decimal("1000"), max_items=Decimal("10"),
            created_by=self.admin,
        )

    def test_concurrent_stock_in_no_oversell(self):
        thread_count = 8
        quantity_per_thread = Decimal("2")  # 8 * 2 = 16 > 10 上限，至多成功 5 笔
        barrier = threading.Barrier(thread_count)
        results = {"success": 0, "conflict": 0}
        lock = threading.Lock()

        def worker():
            try:
                barrier.wait(timeout=10)
                services.stock_in_to_zone(
                    goods=self.goods, zone=self.zone, quantity=quantity_per_thread,
                    operator=self.admin,
                )
                with lock:
                    results["success"] += 1
            except BusinessException:
                with lock:
                    results["conflict"] += 1
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(results["success"], 5, "容量上限10件，每笔2件，应恰好成功5笔")
        self.assertEqual(results["conflict"], 3)

        occupancy = ZoneOccupancy.objects.get(zone=self.zone)
        self.assertEqual(occupancy.used_items, Decimal("10"))
        self.assertGreaterEqual(occupancy.used_items, 0)
        self.assertEqual(occupancy.reserved_items, Decimal("0"))
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("10"))
        self.assertEqual(
            GoodsZoneStock.objects.get(goods=self.goods, zone=self.zone).quantity, Decimal("10")
        )

    def test_concurrent_reserve_and_release_no_negative(self):
        # 先占满容量，再并发取消预约与入库，最终占用不得为负
        reservations = []
        for _ in range(5):
            reservations.append(
                services.create_reservation(
                    goods=self.goods, zone=self.zone, quantity=Decimal("2"),
                    expires_at=timezone.now() + timedelta(hours=1), operator=self.admin,
                )
            )
        barrier = threading.Barrier(5)
        errors = []

        def cancel_worker(reservation):
            try:
                barrier.wait(timeout=10)
                services.cancel_reservation(reservation=reservation, operator=self.admin)
            except BusinessException as exc:
                errors.append(str(exc))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=cancel_worker, args=(r,)) for r in reservations]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, [])
        occupancy = ZoneOccupancy.objects.get(zone=self.zone)
        self.assertEqual(occupancy.reserved_items, Decimal("0"))
        self.assertEqual(occupancy.reserved_weight, Decimal("0"))

"""
仓库管理URL配置
"""
from django.urls import path
from .views import (
    UnitListView, UnitDetailView, UnitBatchDeleteView, UnitAllView,
    CategoryListView, CategoryDetailView, CategoryBatchDeleteView, CategoryAllView,
    VarietyListView, VarietyDetailView, VarietyBatchDeleteView,
    VarietyTemplateView, VarietyImportView,
    DashboardView, GoodsListView, StockInListView, StockOutListView,
    WarningListView, ApprovalListView,
    ZoneListView, ZoneDetailView, ZoneAllView,
    ZoneRuleListView, ZoneOccupancyView, ZoneValidateView,
    CompatibilityRuleListView, CompatibilityRuleCurrentView,
    TransferListView,
    ReservationListView, ReservationCancelView, ReservationFulfillView,
    OverLimitApprovalListView, OverLimitApprovalRevokeView,
)

urlpatterns = [
    # 仪表盘
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # 单位管理
    path('units/', UnitListView.as_view(), name='unit-list'),
    path('units/all/', UnitAllView.as_view(), name='unit-all'),
    path('units/batch-delete/', UnitBatchDeleteView.as_view(), name='unit-batch-delete'),
    path('units/<int:pk>/', UnitDetailView.as_view(), name='unit-detail'),

    # 品类管理
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/all/', CategoryAllView.as_view(), name='category-all'),
    path('categories/batch-delete/', CategoryBatchDeleteView.as_view(), name='category-batch-delete'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category-detail'),

    # 品种管理
    path('varieties/', VarietyListView.as_view(), name='variety-list'),
    path('varieties/batch-delete/', VarietyBatchDeleteView.as_view(), name='variety-batch-delete'),
    path('varieties/template/', VarietyTemplateView.as_view(), name='variety-template'),
    path('varieties/import/', VarietyImportView.as_view(), name='variety-import'),
    path('varieties/<int:pk>/', VarietyDetailView.as_view(), name='variety-detail'),

    # 保管区管理
    path('zones/', ZoneListView.as_view(), name='zone-list'),
    path('zones/all/', ZoneAllView.as_view(), name='zone-all'),
    path('zones/<int:pk>/', ZoneDetailView.as_view(), name='zone-detail'),
    path('zones/<int:pk>/rules/', ZoneRuleListView.as_view(), name='zone-rules'),
    path('zones/<int:pk>/occupancy/', ZoneOccupancyView.as_view(), name='zone-occupancy'),
    path('zones/<int:pk>/validate/', ZoneValidateView.as_view(), name='zone-validate'),

    # 相容性规则
    path('compatibility-rules/', CompatibilityRuleListView.as_view(), name='compat-rule-list'),
    path('compatibility-rules/current/', CompatibilityRuleCurrentView.as_view(), name='compat-rule-current'),

    # 货物管理
    path('goods/', GoodsListView.as_view(), name='goods-list'),

    # 入库管理
    path('stock-in/', StockInListView.as_view(), name='stock-in-list'),

    # 转移管理
    path('transfers/', TransferListView.as_view(), name='transfer-list'),

    # 容量预约
    path('reservations/', ReservationListView.as_view(), name='reservation-list'),
    path('reservations/<int:pk>/cancel/', ReservationCancelView.as_view(), name='reservation-cancel'),
    path('reservations/<int:pk>/fulfill/', ReservationFulfillView.as_view(), name='reservation-fulfill'),

    # 临时超限批准
    path('overrides/', OverLimitApprovalListView.as_view(), name='override-list'),
    path('overrides/<int:pk>/revoke/', OverLimitApprovalRevokeView.as_view(), name='override-revoke'),

    # 出库管理
    path('stock-out/', StockOutListView.as_view(), name='stock-out-list'),

    # 预警管理
    path('warnings/', WarningListView.as_view(), name='warning-list'),

    # 审批管理
    path('approvals/', ApprovalListView.as_view(), name='approval-list'),
]

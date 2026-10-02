"""
仓库管理序列化器
"""
from django.utils import timezone
from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    StorageZone, ZoneRuleVersion, ZoneRuleIncompatibility, ZoneCapacity,
    CapacityOverride, StockPlacement, ZoneReservation, ZoneTransfer,
    ZoneValidationLog,
)


class UnitSerializer(serializers.ModelSerializer):
    """单位序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Unit
        fields = [
            'id', 'name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitCreateSerializer(serializers.Serializer):
    """单位创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=5, required=True, error_messages={
        'required': '请输入单位名称',
        'blank': '单位名称不能为空',
        'min_length': '单位名称至少1个字',
        'max_length': '单位名称最多5个字',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Unit.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('单位名称已存在')
        else:
            if Unit.objects.filter(name=value).exists():
                raise serializers.ValidationError('单位名称已存在')
        return value


class CategorySerializer(serializers.ModelSerializer):
    """品类序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'unit', 'unit_name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryCreateSerializer(serializers.Serializer):
    """品类创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=10, required=True, error_messages={
        'required': '请输入品类名称',
        'blank': '品类名称不能为空',
        'min_length': '品类名称至少1个字',
        'max_length': '品类名称最多10个字',
    })
    unit = serializers.IntegerField(required=True, error_messages={
        'required': '请选择单位',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Category.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('品类名称已存在')
        else:
            if Category.objects.filter(name=value).exists():
                raise serializers.ValidationError('品类名称已存在')
        return value
    
    def validate_unit(self, value):
        if not Unit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('单位不存在')
        return value


class VarietySerializer(serializers.ModelSerializer):
    """品种序列化器"""
    is_in_stock = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Variety
        fields = [
            'id', 'name', 'category', 'category_name', 'unit_name',
            'is_in_stock', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class VarietyCreateSerializer(serializers.Serializer):
    """品种创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入品种名称',
        'blank': '品种名称不能为空',
        'min_length': '品种名称至少1个字',
        'max_length': '品种名称最多20个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品类',
    })
    
    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value
    
    def validate(self, data):
        instance = self.context.get('instance')
        name = data['name']
        category_id = data['category']
        
        if instance:
            if Variety.objects.filter(name=name, category_id=category_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        else:
            if Variety.objects.filter(name=name, category_id=category_id).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        return data


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)

    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'warning_threshold', 'unit_weight', 'location',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    zone_name = serializers.CharField(source='zone.name', read_only=True)

    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'batch_no', 'supplier', 'zone', 'zone_name',
            'rule_version', 'stock_in_time', 'remark'
        ]


class StockOutSerializer(serializers.ModelSerializer):
    """出库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockOut
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'receiver', 'receiver_dept', 'quantity', 'status', 'status_display',
            'stock_out_time', 'remark', 'created_at'
        ]


class WarningSerializer(serializers.ModelSerializer):
    """预警记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Warning
        fields = [
            'id', 'goods', 'goods_name', 'type', 'type_display',
            'message', 'is_read', 'created_at'
        ]


class ApprovalSerializer(serializers.ModelSerializer):
    """审批记录序列化器"""
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'stock_out', 'approver', 'approver_name',
            'status', 'status_display', 'remark', 'created_at', 'updated_at'
        ]


# ==================== 保管区与容量规则 ====================


class StorageZoneSerializer(serializers.ModelSerializer):
    """保管区序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    current_version = serializers.SerializerMethodField()

    class Meta:
        model = StorageZone
        fields = [
            'id', 'name', 'code', 'description', 'is_active',
            'current_version', 'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_current_version(self, obj):
        from .services import ZoneRuleEngine
        version = ZoneRuleEngine.get_active_version(obj)
        return version.version if version else None


class StorageZoneCreateSerializer(serializers.Serializer):
    """保管区创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请输入区域名称',
        'blank': '区域名称不能为空',
        'max_length': '区域名称最多50个字',
    })
    code = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入区域编码',
        'blank': '区域编码不能为空',
        'max_length': '区域编码最多20个字',
    })
    description = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_name(self, value):
        instance = self.context.get('instance')
        qs = StorageZone.objects.filter(name=value)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError('区域名称已存在')
        return value

    def validate_code(self, value):
        instance = self.context.get('instance')
        qs = StorageZone.objects.filter(code=value)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError('区域编码已存在')
        return value


class ZoneRuleIncompatibilitySerializer(serializers.ModelSerializer):
    """品类相容性规则序列化器"""
    category_a_name = serializers.CharField(source='category_a.name', read_only=True)
    category_b_name = serializers.CharField(source='category_b.name', read_only=True)

    class Meta:
        model = ZoneRuleIncompatibility
        fields = ['id', 'category_a', 'category_a_name', 'category_b', 'category_b_name']


class ZoneRuleVersionSerializer(serializers.ModelSerializer):
    """区域规则版本序列化器"""
    incompatibilities = ZoneRuleIncompatibilitySerializer(many=True, read_only=True)
    allowed_category_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_categories', many=True, read_only=True
    )
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = ZoneRuleVersion
        fields = [
            'id', 'zone', 'version', 'max_weight', 'max_items',
            'allowed_category_ids', 'incompatibilities',
            'effective_from', 'created_by', 'created_by_name', 'created_at'
        ]


class ZoneRuleVersionCreateSerializer(serializers.Serializer):
    """
    规则版本创建序列化器

    规则调整只新增版本，历史版本不可变。
    """
    max_weight = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=True,
        error_messages={'required': '请输入重量上限'}
    )
    max_items = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=True,
        error_messages={'required': '请输入件数上限'}
    )
    allowed_category_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    incompatible_pairs = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2),
        required=False, default=list
    )
    effective_from = serializers.DateTimeField(required=False)

    def validate_allowed_category_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError('准入品类存在重复')
        existing = set(Category.objects.filter(pk__in=value).values_list('id', flat=True))
        missing = [str(v) for v in value if v not in existing]
        if missing:
            raise serializers.ValidationError(f'品类不存在：{", ".join(missing)}')
        return value

    def validate_incompatible_pairs(self, value):
        category_ids = {cid for pair in value for cid in pair}
        existing = set(Category.objects.filter(pk__in=category_ids).values_list('id', flat=True))
        seen = set()
        for pair in value:
            a, b = pair
            if a == b:
                raise serializers.ValidationError('不相容品类不能是同一品类')
            if a not in existing or b not in existing:
                raise serializers.ValidationError('不相容规则中存在不存在的品类')
            key = (min(a, b), max(a, b))
            if key in seen:
                raise serializers.ValidationError('不相容规则存在重复')
            seen.add(key)
        return value


class ZoneCapacitySerializer(serializers.ModelSerializer):
    """保管区容量序列化器"""

    class Meta:
        model = ZoneCapacity
        fields = [
            'current_weight', 'current_items',
            'reserved_weight', 'reserved_items', 'updated_at'
        ]


class CapacityOverrideSerializer(serializers.ModelSerializer):
    """临时超限批准序列化器"""
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    is_effective = serializers.BooleanField(read_only=True)
    zone_code = serializers.CharField(source='zone.code', read_only=True)

    class Meta:
        model = CapacityOverride
        fields = [
            'id', 'zone', 'zone_code', 'extra_weight', 'extra_items',
            'reason', 'approved_by', 'approved_by_name',
            'expires_at', 'is_revoked', 'is_effective', 'created_at'
        ]


class CapacityOverrideCreateSerializer(serializers.Serializer):
    """临时超限批准创建序列化器（必须设置失效时间）"""
    extra_weight = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, default=0
    )
    extra_items = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, default=0
    )
    reason = serializers.CharField(min_length=1, max_length=200, required=True, error_messages={
        'required': '请填写批准事由',
        'blank': '批准事由不能为空',
    })
    expires_at = serializers.DateTimeField(required=True, error_messages={
        'required': '临时超限必须设置失效时间',
    })

    def validate_expires_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError('失效时间必须晚于当前时间')
        return value

    def validate(self, data):
        if data['extra_weight'] <= 0 and data['extra_items'] <= 0:
            raise serializers.ValidationError('临时额度必须至少有一项大于零')
        return data


class StockPlacementSerializer(serializers.ModelSerializer):
    """存放明细序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    zone_code = serializers.CharField(source='zone.code', read_only=True)

    class Meta:
        model = StockPlacement
        fields = ['id', 'goods', 'goods_name', 'zone', 'zone_code', 'quantity', 'updated_at']


class ZoneReservationSerializer(serializers.ModelSerializer):
    """容量预约序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    zone_code = serializers.CharField(source='zone.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = ZoneReservation
        fields = [
            'id', 'zone', 'zone_code', 'goods', 'goods_name',
            'rule_version', 'quantity', 'weight', 'status', 'status_display',
            'expires_at', 'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]


class ZoneTransferSerializer(serializers.ModelSerializer):
    """区域转移记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    from_zone_code = serializers.CharField(source='from_zone.code', read_only=True)
    to_zone_code = serializers.CharField(source='to_zone.code', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = ZoneTransfer
        fields = [
            'id', 'goods', 'goods_name', 'from_zone', 'from_zone_code',
            'to_zone', 'to_zone_code', 'rule_version', 'quantity', 'weight',
            'operator', 'operator_name', 'created_at'
        ]


class ZoneValidationLogSerializer(serializers.ModelSerializer):
    """容量校验记录序列化器（历史记录按发生时规则版本解释）"""
    zone_code = serializers.CharField(source='zone.code', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    operation_display = serializers.CharField(source='get_operation_display', read_only=True)
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    actor_name = serializers.CharField(source='actor.username', read_only=True)
    rule_version_number = serializers.IntegerField(source='rule_version.version', read_only=True)

    class Meta:
        model = ZoneValidationLog
        fields = [
            'id', 'zone', 'zone_code', 'rule_version', 'rule_version_number',
            'operation', 'operation_display', 'result', 'result_display',
            'goods', 'goods_name', 'category', 'category_name',
            'quantity', 'weight', 'limit_weight_snapshot', 'limit_items_snapshot',
            'override', 'reasons', 'actor', 'actor_name', 'created_at'
        ]

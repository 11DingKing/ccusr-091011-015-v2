"""
仓库管理序列化器
"""
from django.utils import timezone
from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    StorageZone, ZoneRuleVersion, CompatibilityRuleVersion,
    ZoneOccupancy, GoodsZoneStock, ZoneReservation, ZoneTransfer,
    OverLimitApproval,
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


class GoodsZoneStockSerializer(serializers.ModelSerializer):
    """货物分区存量序列化器"""
    zone_name = serializers.CharField(source='zone.name', read_only=True)

    class Meta:
        model = GoodsZoneStock
        fields = ['zone', 'zone_name', 'quantity']


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)
    zone_stocks = GoodsZoneStockSerializer(many=True, read_only=True)

    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'warning_threshold', 'unit_weight', 'location',
            'zone_stocks',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class GoodsCreateSerializer(serializers.Serializer):
    """货物创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=200, required=True, error_messages={
        'required': '请输入货物名称',
        'blank': '货物名称不能为空',
    })
    code = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请输入货物编码',
        'blank': '货物编码不能为空',
    })
    variety = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品种',
    })
    specification = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    unit_weight = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0, min_value=0,
        error_messages={'min_value': '单件重量不能为负'},
    )
    warning_threshold = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=10, min_value=0,
    )
    location = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_code(self, value):
        if Goods.objects.filter(code=value).exists():
            raise serializers.ValidationError('货物编码已存在')
        return value

    def validate_variety(self, value):
        if not Variety.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品种不存在')
        return value


class ZoneRuleVersionBriefSerializer(serializers.ModelSerializer):
    """容量规则版本简要序列化器（用于历史记录快照解释）"""

    class Meta:
        model = ZoneRuleVersion
        fields = ['id', 'version', 'max_weight', 'max_items', 'effective_from']


class CompatRuleVersionBriefSerializer(serializers.ModelSerializer):
    """相容性规则版本简要序列化器"""

    class Meta:
        model = CompatibilityRuleVersion
        fields = ['id', 'version', 'effective_from']


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    zone_name = serializers.CharField(source='zone.name', read_only=True)
    rule_version_detail = ZoneRuleVersionBriefSerializer(source='rule_version', read_only=True)
    compat_version_detail = CompatRuleVersionBriefSerializer(source='compat_version', read_only=True)

    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'zone', 'zone_name', 'reservation',
            'quantity', 'weight', 'batch_no', 'supplier',
            'rule_version', 'rule_version_detail',
            'compat_version', 'compat_version_detail',
            'stock_in_time', 'remark'
        ]


class StockInCreateSerializer(serializers.Serializer):
    """入库创建序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    zone = serializers.IntegerField(required=True, error_messages={'required': '请选择保管区'})
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True, min_value=0.01,
        error_messages={'required': '请输入入库数量', 'min_value': '入库数量必须大于0'},
    )
    batch_no = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    supplier = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError('货物不存在或已停用')
        return value

    def validate_zone(self, value):
        if not StorageZone.objects.filter(pk=value).exists():
            raise serializers.ValidationError('保管区不存在')
        return value


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


class ZoneOccupancySerializer(serializers.ModelSerializer):
    """区域占用台账序列化器"""

    class Meta:
        model = ZoneOccupancy
        fields = ['used_weight', 'used_items', 'reserved_weight', 'reserved_items', 'updated_at']


class ZoneRuleVersionSerializer(serializers.ModelSerializer):
    """容量规则版本序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    allowed_category_ids = serializers.SerializerMethodField()

    class Meta:
        model = ZoneRuleVersion
        fields = [
            'id', 'zone', 'version', 'max_weight', 'max_items',
            'allowed_category_ids', 'effective_from',
            'created_by', 'created_by_name', 'created_at',
        ]

    def get_allowed_category_ids(self, obj):
        return list(obj.allowances.values_list('category_id', flat=True))


class ZoneRulePublishSerializer(serializers.Serializer):
    """容量规则发布序列化器（只增不改，每次发布生成新版本）"""
    max_weight = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=True, min_value=0.01,
        error_messages={'required': '请输入重量上限', 'min_value': '重量上限必须大于0'},
    )
    max_items = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True, min_value=0.01,
        error_messages={'required': '请输入件数上限', 'min_value': '件数上限必须大于0'},
    )
    allowed_category_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
        help_text='允许存放的品类ID列表，空列表表示不限制',
    )
    effective_from = serializers.DateTimeField(required=False)

    def validate_allowed_category_ids(self, value):
        ids = list(dict.fromkeys(value))
        existing = set(Category.objects.filter(pk__in=ids).values_list('id', flat=True))
        missing = [i for i in ids if i not in existing]
        if missing:
            raise serializers.ValidationError(f'品类不存在: {missing}')
        return ids


class StorageZoneSerializer(serializers.ModelSerializer):
    """保管区序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    occupancy = ZoneOccupancySerializer(read_only=True)
    current_rule = serializers.SerializerMethodField()

    class Meta:
        model = StorageZone
        fields = [
            'id', 'name', 'description', 'is_active',
            'occupancy', 'current_rule',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_current_rule(self, obj):
        from .services import get_zone_rule_at
        rule = get_zone_rule_at(obj, timezone.now())
        return ZoneRuleVersionSerializer(rule).data if rule else None


class StorageZoneCreateSerializer(serializers.Serializer):
    """保管区创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入区域名称',
        'blank': '区域名称不能为空',
        'max_length': '区域名称最多20个字',
    })
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')

    def validate_name(self, value):
        instance = self.context.get('instance')
        queryset = StorageZone.objects.filter(name=value)
        if instance:
            queryset = queryset.exclude(pk=instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('区域名称已存在')
        return value


class IncompatibilityPairSerializer(serializers.Serializer):
    """不相容品类对"""
    category_a = serializers.IntegerField()
    category_b = serializers.IntegerField()


class CompatibilityRuleVersionSerializer(serializers.ModelSerializer):
    """相容性规则版本序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    pairs = serializers.SerializerMethodField()

    class Meta:
        model = CompatibilityRuleVersion
        fields = ['id', 'version', 'pairs', 'effective_from', 'created_by', 'created_by_name', 'created_at']

    def get_pairs(self, obj):
        return [
            {
                'category_a': pair.category_a_id,
                'category_a_name': pair.category_a.name,
                'category_b': pair.category_b_id,
                'category_b_name': pair.category_b.name,
            }
            for pair in obj.incompatibilities.select_related('category_a', 'category_b')
        ]


class CompatibilityRulePublishSerializer(serializers.Serializer):
    """相容性规则发布序列化器"""
    pairs = IncompatibilityPairSerializer(many=True, required=False, default=list)
    effective_from = serializers.DateTimeField(required=False)

    def validate_pairs(self, value):
        normalized = set()
        category_ids = set()
        for pair in value:
            a, b = pair['category_a'], pair['category_b']
            if a == b:
                raise serializers.ValidationError('品类不能与自身不相容')
            normalized.add((min(a, b), max(a, b)))
            category_ids.update([a, b])
        existing = set(Category.objects.filter(pk__in=category_ids).values_list('id', flat=True))
        missing = category_ids - existing
        if missing:
            raise serializers.ValidationError(f'品类不存在: {sorted(missing)}')
        return sorted(normalized)


class ZoneTransferSerializer(serializers.ModelSerializer):
    """转移记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    from_zone_name = serializers.CharField(source='from_zone.name', read_only=True)
    to_zone_name = serializers.CharField(source='to_zone.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    rule_version_detail = ZoneRuleVersionBriefSerializer(source='rule_version', read_only=True)
    compat_version_detail = CompatRuleVersionBriefSerializer(source='compat_version', read_only=True)

    class Meta:
        model = ZoneTransfer
        fields = [
            'id', 'goods', 'goods_name', 'from_zone', 'from_zone_name',
            'to_zone', 'to_zone_name', 'operator', 'operator_name',
            'quantity', 'weight',
            'rule_version', 'rule_version_detail',
            'compat_version', 'compat_version_detail',
            'remark', 'created_at',
        ]


class ZoneTransferCreateSerializer(serializers.Serializer):
    """转移创建序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    from_zone = serializers.IntegerField(required=True, error_messages={'required': '请选择转出区域'})
    to_zone = serializers.IntegerField(required=True, error_messages={'required': '请选择转入区域'})
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True, min_value=0.01,
        error_messages={'required': '请输入转移数量', 'min_value': '转移数量必须大于0'},
    )
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError('货物不存在或已停用')
        return value

    def validate_from_zone(self, value):
        if not StorageZone.objects.filter(pk=value).exists():
            raise serializers.ValidationError('转出区域不存在')
        return value

    def validate_to_zone(self, value):
        if not StorageZone.objects.filter(pk=value).exists():
            raise serializers.ValidationError('转入区域不存在')
        return value


class ZoneReservationSerializer(serializers.ModelSerializer):
    """容量预约序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    zone_name = serializers.CharField(source='zone.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    rule_version_detail = ZoneRuleVersionBriefSerializer(source='rule_version', read_only=True)
    compat_version_detail = CompatRuleVersionBriefSerializer(source='compat_version', read_only=True)

    class Meta:
        model = ZoneReservation
        fields = [
            'id', 'zone', 'zone_name', 'goods', 'goods_name',
            'created_by', 'created_by_name',
            'quantity', 'unit_weight', 'weight',
            'status', 'status_display', 'expires_at',
            'rule_version', 'rule_version_detail',
            'compat_version', 'compat_version_detail',
            'remark', 'created_at', 'updated_at',
        ]


class ZoneReservationCreateSerializer(serializers.Serializer):
    """容量预约创建序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    zone = serializers.IntegerField(required=True, error_messages={'required': '请选择保管区'})
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True, min_value=0.01,
        error_messages={'required': '请输入预约数量', 'min_value': '预约数量必须大于0'},
    )
    expires_at = serializers.DateTimeField(required=True, error_messages={
        'required': '请设置预约失效时间',
        'invalid': '失效时间格式不正确',
    })
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError('货物不存在或已停用')
        return value

    def validate_zone(self, value):
        if not StorageZone.objects.filter(pk=value).exists():
            raise serializers.ValidationError('保管区不存在')
        return value


class OverLimitApprovalSerializer(serializers.ModelSerializer):
    """临时超限批准序列化器"""
    zone_name = serializers.CharField(source='zone.name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    revoked_by_name = serializers.CharField(source='revoked_by.username', read_only=True)
    is_in_effect = serializers.SerializerMethodField()

    class Meta:
        model = OverLimitApproval
        fields = [
            'id', 'zone', 'zone_name', 'approved_by', 'approved_by_name',
            'extra_weight', 'extra_items', 'reason', 'expires_at',
            'is_revoked', 'revoked_by', 'revoked_by_name', 'revoked_at',
            'is_in_effect', 'created_at',
        ]

    def get_is_in_effect(self, obj):
        return obj.is_in_effect()


class OverLimitApprovalCreateSerializer(serializers.Serializer):
    """临时超限批准创建序列化器"""
    zone = serializers.IntegerField(required=True, error_messages={'required': '请选择保管区'})
    extra_weight = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, default=0, min_value=0,
        error_messages={'min_value': '临时重量额度不能为负'},
    )
    extra_items = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0, min_value=0,
        error_messages={'min_value': '临时件数额度不能为负'},
    )
    reason = serializers.CharField(min_length=1, required=True, error_messages={
        'required': '请填写批准事由',
        'blank': '批准事由不能为空',
    })
    expires_at = serializers.DateTimeField(required=True, error_messages={
        'required': '请设置超限失效时间',
        'invalid': '失效时间格式不正确',
    })

    def validate_zone(self, value):
        if not StorageZone.objects.filter(pk=value).exists():
            raise serializers.ValidationError('保管区不存在')
        return value

    def validate(self, data):
        if data['extra_weight'] <= 0 and data['extra_items'] <= 0:
            raise serializers.ValidationError('临时重量额度与件数额度至少一项大于0')
        if data['expires_at'] <= timezone.now():
            raise serializers.ValidationError('超限失效时间必须晚于当前时间')
        return data

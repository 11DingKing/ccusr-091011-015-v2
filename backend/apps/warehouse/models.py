"""
库房管理模型
"""
from django.db import models
from django.utils import timezone
from apps.authentication.models import User


class Unit(models.Model):
    """单位模型"""
    name = models.CharField('单位名称', max_length=5, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_units', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_unit'
        verbose_name = '单位'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品类"""
        return self.categories.exists()


class Category(models.Model):
    """品类模型"""
    name = models.CharField('品类名称', max_length=10, unique=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT,
        related_name='categories', verbose_name='单位'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_categories', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_category'
        verbose_name = '品类'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品种"""
        return self.varieties.exists()


class Variety(models.Model):
    """品种模型"""
    name = models.CharField('品种名称', max_length=20)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='varieties', verbose_name='所属品类'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_varieties', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_variety'
        verbose_name = '品种'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        unique_together = ['category', 'name']
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    @property
    def is_in_stock(self):
        """是否已入库"""
        return self.goods.exists()
    
    @property
    def unit_name(self):
        """获取单位名称"""
        return self.category.unit.name if self.category and self.category.unit else ''


class Goods(models.Model):
    """货物模型"""
    variety = models.ForeignKey(
        Variety, on_delete=models.CASCADE,
        related_name='goods', verbose_name='所属品种'
    )
    name = models.CharField('货物名称', max_length=200)
    code = models.CharField('货物编码', max_length=50, unique=True)
    specification = models.CharField('规格型号', max_length=200, blank=True)
    quantity = models.DecimalField('库存数量', max_digits=12, decimal_places=2, default=0)
    warning_threshold = models.DecimalField('预警阈值', max_digits=12, decimal_places=2, default=10)
    unit_weight = models.DecimalField('单件重量(kg)', max_digits=12, decimal_places=2, default=0)
    location = models.CharField('存放位置', max_length=100, blank=True)
    remark = models.TextField('备注', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_goods'
        verbose_name = '货物'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_warning(self):
        """是否预警"""
        return self.quantity <= self.warning_threshold


class StockIn(models.Model):
    """入库记录模型"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_ins', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_in_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('入库数量', max_digits=12, decimal_places=2)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    supplier = models.CharField('供应商', max_length=200, blank=True)
    zone = models.ForeignKey(
        'StorageZone', on_delete=models.PROTECT, null=True, blank=True,
        related_name='stock_ins', verbose_name='入库保管区'
    )
    rule_version = models.ForeignKey(
        'ZoneRuleVersion', on_delete=models.PROTECT, null=True, blank=True,
        related_name='stock_ins', verbose_name='校验所用规则版本'
    )
    stock_in_time = models.DateTimeField('入库时间', auto_now_add=True)
    remark = models.TextField('备注', blank=True)
    
    class Meta:
        db_table = 'wh_stock_in'
        verbose_name = '入库记录'
        verbose_name_plural = verbose_name
        ordering = ['-stock_in_time']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class StockOut(models.Model):
    """出库记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_outs', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_out_operations', verbose_name='操作人'
    )
    receiver = models.CharField('领用人', max_length=100)
    receiver_dept = models.CharField('领用部门', max_length=100, blank=True)
    quantity = models.DecimalField('出库数量', max_digits=12, decimal_places=2)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    stock_out_time = models.DateTimeField('出库时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_stock_out'
        verbose_name = '出库记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class Warning(models.Model):
    """预警记录模型"""
    TYPE_CHOICES = [
        ('low_stock', '库存不足'),
        ('expiring', '即将过期'),
        ('expired', '已过期'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='warnings', verbose_name='货物'
    )
    type = models.CharField('预警类型', max_length=20, choices=TYPE_CHOICES)
    message = models.TextField('预警信息')
    is_read = models.BooleanField('是否已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_warning'
        verbose_name = '预警记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.get_type_display()}"


class Approval(models.Model):
    """审批记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    
    stock_out = models.ForeignKey(
        StockOut, on_delete=models.CASCADE,
        related_name='approvals', verbose_name='出库记录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approvals', verbose_name='审批人'
    )
    status = models.CharField('审批状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    remark = models.TextField('审批意见', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_approval'
        verbose_name = '审批记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.stock_out} - {self.get_status_display()}"


# ==================== 保管区与容量规则 ====================


class StorageZone(models.Model):
    """保管区模型"""
    name = models.CharField('区域名称', max_length=50, unique=True)
    code = models.CharField('区域编码', max_length=20, unique=True)
    description = models.CharField('区域说明', max_length=200, blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_zones', verbose_name='创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_storage_zone'
        verbose_name = '保管区'
        verbose_name_plural = verbose_name
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class ZoneRuleVersion(models.Model):
    """
    保管区规则版本模型

    每次规则调整（容量上限、准入类别、相容性）都生成新版本，
    历史版本不可变，历史记录按发生时的版本解释。
    """
    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='rule_versions', verbose_name='保管区'
    )
    version = models.PositiveIntegerField('版本号')
    max_weight = models.DecimalField('重量上限(kg)', max_digits=12, decimal_places=2)
    max_items = models.DecimalField('件数上限', max_digits=12, decimal_places=2)
    allowed_categories = models.ManyToManyField(
        Category, blank=True,
        related_name='zone_rule_versions', verbose_name='准入品类（空为不限制）'
    )
    effective_from = models.DateTimeField('生效时间', default=timezone.now)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_zone_rules', verbose_name='创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_zone_rule_version'
        verbose_name = '区域规则版本'
        verbose_name_plural = verbose_name
        ordering = ['zone', '-version']
        unique_together = ['zone', 'version']

    def __str__(self):
        return f"{self.zone.code} v{self.version}"


class ZoneRuleIncompatibility(models.Model):
    """品类相容性规则（挂在规则版本下，同一保管区内两品类不得共存）"""
    rule_version = models.ForeignKey(
        ZoneRuleVersion, on_delete=models.CASCADE,
        related_name='incompatibilities', verbose_name='规则版本'
    )
    category_a = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='incompatibility_as_a', verbose_name='品类甲'
    )
    category_b = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='incompatibility_as_b', verbose_name='品类乙'
    )

    class Meta:
        db_table = 'wh_zone_rule_incompatibility'
        verbose_name = '品类相容性规则'
        verbose_name_plural = verbose_name
        unique_together = ['rule_version', 'category_a', 'category_b']

    def __str__(self):
        return f"{self.category_a.name} ✕ {self.category_b.name}"


class ZoneCapacity(models.Model):
    """
    保管区容量计数器

    所有占用/释放都通过 ZoneRuleEngine 中的条件更新完成，
    数据库层面保证不出现负数与超卖。
    """
    zone = models.OneToOneField(
        StorageZone, on_delete=models.CASCADE,
        related_name='capacity', verbose_name='保管区'
    )
    current_weight = models.DecimalField('当前重量(kg)', max_digits=12, decimal_places=2, default=0)
    current_items = models.DecimalField('当前件数', max_digits=12, decimal_places=2, default=0)
    reserved_weight = models.DecimalField('预约占用重量(kg)', max_digits=12, decimal_places=2, default=0)
    reserved_items = models.DecimalField('预约占用件数', max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_zone_capacity'
        verbose_name = '保管区容量'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.zone.code} 容量"


class CapacityOverride(models.Model):
    """
    临时超限批准

    仅管理员可批准，必须设置失效时间；生效期间为对应保管区
    临时追加容量额度，到期或撤销后自动失效。
    """
    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='overrides', verbose_name='保管区'
    )
    extra_weight = models.DecimalField('临时重量额度(kg)', max_digits=12, decimal_places=2, default=0)
    extra_items = models.DecimalField('临时件数额度', max_digits=12, decimal_places=2, default=0)
    reason = models.CharField('批准事由', max_length=200)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approved_overrides', verbose_name='批准人'
    )
    expires_at = models.DateTimeField('失效时间')
    is_revoked = models.BooleanField('是否已撤销', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_capacity_override'
        verbose_name = '临时超限批准'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.zone.code} 临时超限（至 {self.expires_at:%Y-%m-%d %H:%M}）"

    @property
    def is_effective(self):
        """当前是否生效"""
        return (not self.is_revoked) and self.expires_at > timezone.now()


class StockPlacement(models.Model):
    """货物存放明细（货物在哪个保管区、存放多少）"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='placements', verbose_name='货物'
    )
    zone = models.ForeignKey(
        StorageZone, on_delete=models.PROTECT,
        related_name='placements', verbose_name='保管区'
    )
    quantity = models.DecimalField('存放数量', max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_stock_placement'
        verbose_name = '存放明细'
        verbose_name_plural = verbose_name
        unique_together = ['goods', 'zone']

    def __str__(self):
        return f"{self.goods.name} @ {self.zone.code} × {self.quantity}"


class ZoneReservation(models.Model):
    """容量预约模型"""
    STATUS_CHOICES = [
        ('active', '生效中'),
        ('fulfilled', '已履约'),
        ('cancelled', '已取消'),
        ('expired', '已过期'),
    ]

    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='reservations', verbose_name='保管区'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='zone_reservations', verbose_name='货物'
    )
    rule_version = models.ForeignKey(
        ZoneRuleVersion, on_delete=models.PROTECT, null=True,
        related_name='reservations', verbose_name='校验所用规则版本'
    )
    quantity = models.DecimalField('预约数量', max_digits=12, decimal_places=2)
    weight = models.DecimalField('预约重量(kg)', max_digits=12, decimal_places=2)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='active')
    expires_at = models.DateTimeField('预约失效时间')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='zone_reservations', verbose_name='预约人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_zone_reservation'
        verbose_name = '容量预约'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.goods.name} → {self.zone.code} × {self.quantity}"


class ZoneTransfer(models.Model):
    """区域转移记录模型"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='zone_transfers', verbose_name='货物'
    )
    from_zone = models.ForeignKey(
        StorageZone, on_delete=models.PROTECT,
        related_name='transfers_out', verbose_name='转出保管区'
    )
    to_zone = models.ForeignKey(
        StorageZone, on_delete=models.PROTECT,
        related_name='transfers_in', verbose_name='转入保管区'
    )
    rule_version = models.ForeignKey(
        ZoneRuleVersion, on_delete=models.PROTECT, null=True,
        related_name='transfers', verbose_name='目标区校验所用规则版本'
    )
    quantity = models.DecimalField('转移数量', max_digits=12, decimal_places=2)
    weight = models.DecimalField('转移重量(kg)', max_digits=12, decimal_places=2)
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='zone_transfers', verbose_name='操作人'
    )
    created_at = models.DateTimeField('转移时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_zone_transfer'
        verbose_name = '区域转移记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.goods.name} {self.from_zone.code}→{self.to_zone.code} × {self.quantity}"


class ZoneValidationLog(models.Model):
    """
    容量校验记录

    入库、转移、预约共用同一校验口径，每次判定都留痕，
    并绑定发生时的规则版本与上限快照，历史记录按发生时规则解释。
    """
    OPERATION_CHOICES = [
        ('stock_in', '入库'),
        ('transfer', '转移'),
        ('reservation', '预约'),
    ]
    RESULT_CHOICES = [
        ('passed', '通过'),
        ('rejected', '拒绝'),
    ]

    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='validation_logs', verbose_name='保管区'
    )
    rule_version = models.ForeignKey(
        ZoneRuleVersion, on_delete=models.SET_NULL, null=True,
        related_name='validation_logs', verbose_name='发生时规则版本'
    )
    operation = models.CharField('操作类型', max_length=20, choices=OPERATION_CHOICES)
    result = models.CharField('校验结果', max_length=20, choices=RESULT_CHOICES)
    goods = models.ForeignKey(
        Goods, on_delete=models.SET_NULL, null=True,
        related_name='validation_logs', verbose_name='货物'
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True,
        related_name='validation_logs', verbose_name='品类'
    )
    quantity = models.DecimalField('申请数量', max_digits=12, decimal_places=2)
    weight = models.DecimalField('申请重量(kg)', max_digits=12, decimal_places=2)
    limit_weight_snapshot = models.DecimalField(
        '当时重量上限(kg)', max_digits=12, decimal_places=2, null=True
    )
    limit_items_snapshot = models.DecimalField(
        '当时件数上限', max_digits=12, decimal_places=2, null=True
    )
    override = models.ForeignKey(
        CapacityOverride, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='validation_logs', verbose_name='依赖的临时超限批准'
    )
    reasons = models.TextField('拒绝原因', blank=True)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='zone_validation_logs', verbose_name='操作人'
    )
    created_at = models.DateTimeField('校验时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_zone_validation_log'
        verbose_name = '容量校验记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.zone.code} {self.get_operation_display()} {self.get_result_display()}"

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
    zone = models.ForeignKey(
        'StorageZone', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_ins', verbose_name='保管区'
    )
    reservation = models.ForeignKey(
        'ZoneReservation', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_ins', verbose_name='来源预约'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_in_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('入库数量', max_digits=12, decimal_places=2)
    weight = models.DecimalField('入库重量(kg)', max_digits=14, decimal_places=2, default=0)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    supplier = models.CharField('供应商', max_length=200, blank=True)
    # 校验时使用的规则快照，历史记录按发生时规则解释
    rule_version = models.ForeignKey(
        'ZoneRuleVersion', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_ins', verbose_name='容量规则版本'
    )
    compat_version = models.ForeignKey(
        'CompatibilityRuleVersion', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_ins', verbose_name='相容性规则版本'
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
    name = models.CharField('区域名称', max_length=20, unique=True)
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
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class ZoneRuleVersion(models.Model):
    """
    保管区容量规则版本

    规则一旦发布不可修改，调整只能发布新版本；
    校验时按生效时间选取版本，历史记录仍按发生时版本解释。
    """
    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='rule_versions', verbose_name='保管区'
    )
    version = models.PositiveIntegerField('版本号')
    max_weight = models.DecimalField('重量上限(kg)', max_digits=14, decimal_places=2)
    max_items = models.DecimalField('件数上限', max_digits=12, decimal_places=2)
    effective_from = models.DateTimeField('生效时间', default=timezone.now)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_zone_rules', verbose_name='发布人'
    )
    created_at = models.DateTimeField('发布时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_zone_rule_version'
        verbose_name = '容量规则版本'
        verbose_name_plural = verbose_name
        ordering = ['-version']
        unique_together = ['zone', 'version']

    def __str__(self):
        return f"{self.zone.name} - v{self.version}"


class ZoneCategoryAllowance(models.Model):
    """规则版本允许存放的品类（空集合表示不限制）"""
    rule_version = models.ForeignKey(
        ZoneRuleVersion, on_delete=models.CASCADE,
        related_name='allowances', verbose_name='规则版本'
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='zone_allowances', verbose_name='品类'
    )

    class Meta:
        db_table = 'wh_zone_category_allowance'
        verbose_name = '区域品类准入'
        verbose_name_plural = verbose_name
        unique_together = ['rule_version', 'category']

    def __str__(self):
        return f"{self.rule_version} - {self.category.name}"


class CompatibilityRuleVersion(models.Model):
    """
    品类相容性规则版本（全局）

    与容量规则一样只增不改，历史记录按发生时版本解释。
    """
    version = models.PositiveIntegerField('版本号', unique=True)
    effective_from = models.DateTimeField('生效时间', default=timezone.now)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_compat_rules', verbose_name='发布人'
    )
    created_at = models.DateTimeField('发布时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_compat_rule_version'
        verbose_name = '相容性规则版本'
        verbose_name_plural = verbose_name
        ordering = ['-version']

    def __str__(self):
        return f"相容性规则 v{self.version}"


class CategoryIncompatibility(models.Model):
    """不相容品类对（category_a_id < category_b_id 归一化存储）"""
    rule_version = models.ForeignKey(
        CompatibilityRuleVersion, on_delete=models.CASCADE,
        related_name='incompatibilities', verbose_name='规则版本'
    )
    category_a = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='incompatibilities_a', verbose_name='品类A'
    )
    category_b = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='incompatibilities_b', verbose_name='品类B'
    )

    class Meta:
        db_table = 'wh_category_incompatibility'
        verbose_name = '品类不相容'
        verbose_name_plural = verbose_name
        unique_together = ['rule_version', 'category_a', 'category_b']
        constraints = [
            models.CheckConstraint(
                check=models.Q(category_a__lt=models.F('category_b')),
                name='wh_incompat_a_lt_b',
            ),
        ]

    def __str__(self):
        return f"{self.category_a.name} ✕ {self.category_b.name}"


class ZoneOccupancy(models.Model):
    """
    保管区占用台账（每区一行）

    所有变更通过条件更新完成，配合非负约束，
    保证并发占用不超卖、容量释放不为负。
    """
    zone = models.OneToOneField(
        StorageZone, on_delete=models.CASCADE,
        related_name='occupancy', verbose_name='保管区'
    )
    used_weight = models.DecimalField('已用重量(kg)', max_digits=14, decimal_places=2, default=0)
    used_items = models.DecimalField('已用件数', max_digits=12, decimal_places=2, default=0)
    reserved_weight = models.DecimalField('预约重量(kg)', max_digits=14, decimal_places=2, default=0)
    reserved_items = models.DecimalField('预约件数', max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_zone_occupancy'
        verbose_name = '区域占用台账'
        verbose_name_plural = verbose_name
        constraints = [
            models.CheckConstraint(check=models.Q(used_weight__gte=0), name='wh_occ_used_weight_nonneg'),
            models.CheckConstraint(check=models.Q(used_items__gte=0), name='wh_occ_used_items_nonneg'),
            models.CheckConstraint(check=models.Q(reserved_weight__gte=0), name='wh_occ_reserved_weight_nonneg'),
            models.CheckConstraint(check=models.Q(reserved_items__gte=0), name='wh_occ_reserved_items_nonneg'),
        ]

    def __str__(self):
        return f"{self.zone.name} 占用"


class ZoneCategoryOccupancy(models.Model):
    """保管区分品类占用（用于相容性判断）"""
    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='category_occupancies', verbose_name='保管区'
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='zone_occupancies', verbose_name='品类'
    )
    used_weight = models.DecimalField('已用重量(kg)', max_digits=14, decimal_places=2, default=0)
    used_items = models.DecimalField('已用件数', max_digits=12, decimal_places=2, default=0)
    reserved_weight = models.DecimalField('预约重量(kg)', max_digits=14, decimal_places=2, default=0)
    reserved_items = models.DecimalField('预约件数', max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = 'wh_zone_category_occupancy'
        verbose_name = '区域品类占用'
        verbose_name_plural = verbose_name
        unique_together = ['zone', 'category']
        constraints = [
            models.CheckConstraint(check=models.Q(used_weight__gte=0), name='wh_catocc_used_weight_nonneg'),
            models.CheckConstraint(check=models.Q(used_items__gte=0), name='wh_catocc_used_items_nonneg'),
            models.CheckConstraint(check=models.Q(reserved_weight__gte=0), name='wh_catocc_reserved_weight_nonneg'),
            models.CheckConstraint(check=models.Q(reserved_items__gte=0), name='wh_catocc_reserved_items_nonneg'),
        ]

    def __str__(self):
        return f"{self.zone.name} - {self.category.name}"


class GoodsZoneStock(models.Model):
    """货物在各保管区的存量"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='zone_stocks', verbose_name='货物'
    )
    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='goods_stocks', verbose_name='保管区'
    )
    quantity = models.DecimalField('存量', max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = 'wh_goods_zone_stock'
        verbose_name = '货物分区存量'
        verbose_name_plural = verbose_name
        unique_together = ['goods', 'zone']
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gte=0), name='wh_gzs_quantity_nonneg'),
        ]

    def __str__(self):
        return f"{self.goods.name} @ {self.zone.name}"


class OverLimitApproval(models.Model):
    """
    临时超限批准

    仅管理员可批准，必须设置失效时间；
    生效期间区域上限 = 规则上限 + 各有效批准的增量之和。
    """
    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='over_limit_approvals', verbose_name='保管区'
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='over_limit_approvals', verbose_name='批准人'
    )
    extra_weight = models.DecimalField('临时重量额度(kg)', max_digits=14, decimal_places=2, default=0)
    extra_items = models.DecimalField('临时件数额度', max_digits=12, decimal_places=2, default=0)
    reason = models.TextField('批准事由')
    expires_at = models.DateTimeField('失效时间')
    is_revoked = models.BooleanField('是否已撤销', default=False)
    revoked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='revoked_over_limits', verbose_name='撤销人'
    )
    revoked_at = models.DateTimeField('撤销时间', null=True, blank=True)
    created_at = models.DateTimeField('批准时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_over_limit_approval'
        verbose_name = '临时超限批准'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.zone.name} 临时超限(+{self.extra_weight}kg/+{self.extra_items}件)"

    def is_in_effect(self, at_time=None):
        """是否在生效中"""
        at_time = at_time or timezone.now()
        return not self.is_revoked and self.expires_at > at_time


class ZoneReservation(models.Model):
    """保管区容量预约"""
    STATUS_CHOICES = [
        ('active', '进行中'),
        ('fulfilled', '已核销'),
        ('cancelled', '已取消'),
        ('expired', '已过期'),
    ]

    zone = models.ForeignKey(
        StorageZone, on_delete=models.CASCADE,
        related_name='reservations', verbose_name='保管区'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='reservations', verbose_name='货物'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='zone_reservations', verbose_name='预约人'
    )
    quantity = models.DecimalField('预约件数', max_digits=12, decimal_places=2)
    unit_weight = models.DecimalField('预约时单件重量(kg)', max_digits=12, decimal_places=2, default=0)
    weight = models.DecimalField('预约重量(kg)', max_digits=14, decimal_places=2, default=0)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='active')
    expires_at = models.DateTimeField('失效时间')
    # 校验时使用的规则快照
    rule_version = models.ForeignKey(
        ZoneRuleVersion, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reservations', verbose_name='容量规则版本'
    )
    compat_version = models.ForeignKey(
        CompatibilityRuleVersion, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reservations', verbose_name='相容性规则版本'
    )
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_zone_reservation'
        verbose_name = '容量预约'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.goods.name} @ {self.zone.name} - {self.get_status_display()}"


class ZoneTransfer(models.Model):
    """货物保管区转移记录"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='transfers', verbose_name='货物'
    )
    from_zone = models.ForeignKey(
        StorageZone, on_delete=models.SET_NULL, null=True,
        related_name='transfers_out', verbose_name='转出区域'
    )
    to_zone = models.ForeignKey(
        StorageZone, on_delete=models.SET_NULL, null=True,
        related_name='transfers_in', verbose_name='转入区域'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='zone_transfers', verbose_name='操作人'
    )
    quantity = models.DecimalField('转移件数', max_digits=12, decimal_places=2)
    weight = models.DecimalField('转移重量(kg)', max_digits=14, decimal_places=2, default=0)
    # 转入校验时使用的规则快照
    rule_version = models.ForeignKey(
        ZoneRuleVersion, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transfers', verbose_name='容量规则版本'
    )
    compat_version = models.ForeignKey(
        CompatibilityRuleVersion, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transfers', verbose_name='相容性规则版本'
    )
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('转移时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_zone_transfer'
        verbose_name = '区域转移记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.goods.name}: {self.from_zone} → {self.to_zone}"

"""
仓库管理视图
"""
import logging
import io
from decimal import Decimal, InvalidOperation
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from apps.core.response import success_response, error_response
from apps.core.exceptions import PermissionException
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    StorageZone, ZoneRuleVersion, ZoneCategoryAllowance,
    CompatibilityRuleVersion, CategoryIncompatibility,
    ZoneOccupancy, ZoneCategoryOccupancy,
    ZoneReservation, ZoneTransfer, OverLimitApproval,
)
from .serializers import (
    UnitSerializer, UnitCreateSerializer,
    CategorySerializer, CategoryCreateSerializer,
    VarietySerializer, VarietyCreateSerializer,
    GoodsSerializer, GoodsCreateSerializer,
    StockInSerializer, StockInCreateSerializer, StockOutSerializer,
    WarningSerializer, ApprovalSerializer,
    StorageZoneSerializer, StorageZoneCreateSerializer,
    ZoneRuleVersionSerializer, ZoneRulePublishSerializer,
    CompatibilityRuleVersionSerializer, CompatibilityRulePublishSerializer,
    ZoneTransferSerializer, ZoneTransferCreateSerializer,
    ZoneReservationSerializer, ZoneReservationCreateSerializer,
    OverLimitApprovalSerializer, OverLimitApprovalCreateSerializer,
)
from . import services

logger = logging.getLogger('apps')


def _paginate(request, queryset):
    """简单分页"""
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 10))
    start = (page - 1) * page_size
    end = start + page_size
    return queryset.count(), queryset[start:end], page, page_size


def _first_error(errors):
    first_error = list(errors.values())[0]
    if isinstance(first_error, list):
        first_error = first_error[0]
    return str(first_error)


def _require_admin(request):
    """临时超限等敏感操作仅管理员可执行"""
    if not request.user.is_admin:
        raise PermissionException('仅管理员可执行该操作')


# ==================== 单位管理 ====================

class UnitListView(APIView):
    """单位列表视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = Unit.objects.all().order_by('-created_at')
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        units = queryset[start:end]
        
        serializer = UnitSerializer(units, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    def post(self, request):
        """创建单位"""
        serializer = UnitCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        unit = Unit.objects.create(
            name=serializer.validated_data['name'],
            created_by=request.user
        )
        
        logger.info(f"User {request.user.username} created unit {unit.name}")
        
        return success_response(data=UnitSerializer(unit).data, message='创建成功')


class UnitDetailView(APIView):
    """单位详情视图"""
    permission_classes = [IsAuthenticated]
    
    def put(self, request, pk):
        """更新单位"""
        try:
            unit = Unit.objects.get(pk=pk)
        except Unit.DoesNotExist:
            return error_response(message='单位不存在', code=404)
        
        serializer = UnitCreateSerializer(data=request.data, context={'instance': unit})
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        unit.name = serializer.validated_data['name']
        unit.save()
        
        logger.info(f"User {request.user.username} updated unit {unit.name}")
        
        return success_response(data=UnitSerializer(unit).data, message='更新成功')
    
    def delete(self, request, pk):
        """删除单位"""
        try:
            unit = Unit.objects.get(pk=pk)
        except Unit.DoesNotExist:
            return error_response(message='单位不存在', code=404)
        
        if unit.is_linked:
            return error_response(message='该单位已被关联，无法删除')
        
        name = unit.name
        unit.delete()
        
        logger.info(f"User {request.user.username} deleted unit {name}")
        
        return success_response(message='删除成功')


class UnitBatchDeleteView(APIView):
    """单位批量删除视图"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return error_response(message='请选择要删除的单位')
        
        # 只删除未关联的单位
        units = Unit.objects.filter(pk__in=ids)
        deleted_count = 0
        for unit in units:
            if not unit.is_linked:
                unit.delete()
                deleted_count += 1
        
        logger.info(f"User {request.user.username} batch deleted {deleted_count} units")
        
        return success_response(message=f'成功删除 {deleted_count} 个单位')


class UnitAllView(APIView):
    """获取所有单位（用于下拉选择）"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        units = Unit.objects.filter(is_active=True).order_by('name')
        serializer = UnitSerializer(units, many=True)
        return success_response(data=serializer.data)


# ==================== 品类管理 ====================

class CategoryListView(APIView):
    """品类列表视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = Category.objects.all().order_by('-created_at')
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        categories = queryset[start:end]
        
        serializer = CategorySerializer(categories, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    def post(self, request):
        """创建品类"""
        serializer = CategoryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        unit = Unit.objects.get(pk=serializer.validated_data['unit'])
        category = Category.objects.create(
            name=serializer.validated_data['name'],
            unit=unit,
            created_by=request.user
        )
        
        logger.info(f"User {request.user.username} created category {category.name}")
        
        return success_response(data=CategorySerializer(category).data, message='创建成功')


class CategoryDetailView(APIView):
    """品类详情视图"""
    permission_classes = [IsAuthenticated]
    
    def put(self, request, pk):
        """更新品类"""
        try:
            category = Category.objects.get(pk=pk)
        except Category.DoesNotExist:
            return error_response(message='品类不存在', code=404)
        
        serializer = CategoryCreateSerializer(data=request.data, context={'instance': category})
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        category.name = serializer.validated_data['name']
        category.unit = Unit.objects.get(pk=serializer.validated_data['unit'])
        category.save()
        
        logger.info(f"User {request.user.username} updated category {category.name}")
        
        return success_response(data=CategorySerializer(category).data, message='更新成功')
    
    def delete(self, request, pk):
        """删除品类"""
        try:
            category = Category.objects.get(pk=pk)
        except Category.DoesNotExist:
            return error_response(message='品类不存在', code=404)
        
        if category.is_linked:
            return error_response(message='该品类已被关联，无法删除')
        
        name = category.name
        category.delete()
        
        logger.info(f"User {request.user.username} deleted category {name}")
        
        return success_response(message='删除成功')


class CategoryBatchDeleteView(APIView):
    """品类批量删除视图"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return error_response(message='请选择要删除的品类')
        
        categories = Category.objects.filter(pk__in=ids)
        deleted_count = 0
        for category in categories:
            if not category.is_linked:
                category.delete()
                deleted_count += 1
        
        logger.info(f"User {request.user.username} batch deleted {deleted_count} categories")
        
        return success_response(message=f'成功删除 {deleted_count} 个品类')


class CategoryAllView(APIView):
    """获取所有品类（用于下拉选择）"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        categories = Category.objects.filter(is_active=True).order_by('name')
        serializer = CategorySerializer(categories, many=True)
        return success_response(data=serializer.data)


# ==================== 品种管理 ====================

class VarietyListView(APIView):
    """品种列表视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = Variety.objects.all().order_by('-created_at')
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        varieties = queryset[start:end]
        
        serializer = VarietySerializer(varieties, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    def post(self, request):
        """创建品种"""
        serializer = VarietyCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0]
            if isinstance(first_error, list):
                first_error = first_error[0]
            return error_response(message=str(first_error))
        
        category = Category.objects.get(pk=serializer.validated_data['category'])
        variety = Variety.objects.create(
            name=serializer.validated_data['name'],
            category=category,
            created_by=request.user
        )
        
        logger.info(f"User {request.user.username} created variety {variety.name}")
        
        return success_response(data=VarietySerializer(variety).data, message='创建成功')


class VarietyDetailView(APIView):
    """品种详情视图"""
    permission_classes = [IsAuthenticated]
    
    def put(self, request, pk):
        """更新品种"""
        try:
            variety = Variety.objects.get(pk=pk)
        except Variety.DoesNotExist:
            return error_response(message='品种不存在', code=404)
        
        serializer = VarietyCreateSerializer(data=request.data, context={'instance': variety})
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0]
            if isinstance(first_error, list):
                first_error = first_error[0]
            return error_response(message=str(first_error))
        
        variety.name = serializer.validated_data['name']
        variety.category = Category.objects.get(pk=serializer.validated_data['category'])
        variety.save()
        
        logger.info(f"User {request.user.username} updated variety {variety.name}")
        
        return success_response(data=VarietySerializer(variety).data, message='更新成功')
    
    def delete(self, request, pk):
        """删除品种"""
        try:
            variety = Variety.objects.get(pk=pk)
        except Variety.DoesNotExist:
            return error_response(message='品种不存在', code=404)
        
        if variety.is_in_stock:
            return error_response(message='该品种已入库，无法删除')
        
        name = variety.name
        variety.delete()
        
        logger.info(f"User {request.user.username} deleted variety {name}")
        
        return success_response(message='删除成功')


class VarietyBatchDeleteView(APIView):
    """品种批量删除视图"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return error_response(message='请选择要删除的品种')
        
        varieties = Variety.objects.filter(pk__in=ids)
        deleted_count = 0
        for variety in varieties:
            if not variety.is_in_stock:
                variety.delete()
                deleted_count += 1
        
        logger.info(f"User {request.user.username} batch deleted {deleted_count} varieties")
        
        return success_response(message=f'成功删除 {deleted_count} 个品种')


class VarietyTemplateView(APIView):
    """品种导入模板下载"""
    permission_classes = []  # 允许匿名访问，通过token参数验证
    
    def get(self, request):
        # 从URL参数获取token进行验证
        from apps.authentication.backends import decode_token
        from apps.authentication.models import User
        
        token = request.query_params.get('token')
        if not token:
            return error_response(message='缺少认证信息', code=401)
        
        payload = decode_token(token)
        if not payload:
            return error_response(message='认证信息无效或已过期', code=401)
        
        try:
            user = User.objects.get(pk=payload['user_id'])
        except User.DoesNotExist:
            return error_response(message='用户不存在', code=401)
        
        wb = Workbook()
        
        # 第一个表格 - 导入模板
        ws1 = wb.active
        ws1.title = '品种导入'
        
        # 设置表头样式
        header_font = Font(bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='4F46E5', end_color='4F46E5', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center')
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        headers = ['品种', '品类', '单位']
        for col, header in enumerate(headers, 1):
            cell = ws1.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # 设置列宽
        ws1.column_dimensions['A'].width = 25
        ws1.column_dimensions['B'].width = 20
        ws1.column_dimensions['C'].width = 15
        
        # 第二个表格 - 品类参考
        ws2 = wb.create_sheet(title='品类参考')
        
        headers2 = ['品类', '单位']
        for col, header in enumerate(headers2, 1):
            cell = ws2.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # 填充品类数据
        categories = Category.objects.filter(is_active=True).select_related('unit')
        for row, category in enumerate(categories, 2):
            ws2.cell(row=row, column=1, value=category.name).border = thin_border
            ws2.cell(row=row, column=2, value=category.unit.name).border = thin_border
        
        ws2.column_dimensions['A'].width = 20
        ws2.column_dimensions['B'].width = 15
        
        # 返回Excel文件
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename=variety_import_template.xlsx'
        
        return response


class VarietyImportView(APIView):
    """品种导入视图"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        if 'file' not in request.FILES:
            return error_response(message='请上传文件')
        
        file = request.FILES['file']
        
        try:
            wb = load_workbook(file)
            ws = wb.active
        except Exception as e:
            return error_response(message='文件格式错误，请上传Excel文件')
        
        # 获取所有品类及其单位
        categories = {c.name: c for c in Category.objects.filter(is_active=True).select_related('unit')}
        
        can_import = []
        cannot_import = []
        
        for row in range(2, ws.max_row + 1):
            variety_name = ws.cell(row=row, column=1).value
            category_name = ws.cell(row=row, column=2).value
            unit_name = ws.cell(row=row, column=3).value
            
            if not variety_name:
                continue
            
            variety_name = str(variety_name).strip()
            category_name = str(category_name).strip() if category_name else ''
            unit_name = str(unit_name).strip() if unit_name else ''
            
            # 验证
            error_msg = None
            
            if not variety_name:
                error_msg = '品种名称不能为空'
            elif len(variety_name) > 20:
                error_msg = '品种名称最多20个字'
            elif not category_name:
                error_msg = '品类不能为空'
            elif category_name not in categories:
                error_msg = f'品类"{category_name}"不存在'
            elif not unit_name:
                error_msg = '单位不能为空'
            elif categories.get(category_name) and categories[category_name].unit.name != unit_name:
                error_msg = f'单位与品类不匹配，应为"{categories[category_name].unit.name}"'
            elif Variety.objects.filter(name=variety_name, category__name=category_name).exists():
                error_msg = '该品种已存在'
            
            if error_msg:
                cannot_import.append({
                    'row': row,
                    'variety': variety_name,
                    'category': category_name,
                    'unit': unit_name,
                    'reason': error_msg
                })
            else:
                can_import.append({
                    'row': row,
                    'variety': variety_name,
                    'category': category_name,
                    'unit': unit_name
                })
        
        # 如果是预览请求
        if request.data.get('preview') == 'true':
            return success_response(data={
                'can_import': can_import,
                'cannot_import': cannot_import,
                'can_import_count': len(can_import),
                'cannot_import_count': len(cannot_import)
            })
        
        # 执行导入
        imported_count = 0
        for item in can_import:
            category = categories[item['category']]
            Variety.objects.create(
                name=item['variety'],
                category=category,
                created_by=request.user
            )
            imported_count += 1
        
        logger.info(f"User {request.user.username} imported {imported_count} varieties")
        
        return success_response(
            data={
                'imported_count': imported_count,
                'failed_count': len(cannot_import),
                'failed_items': cannot_import
            },
            message=f'成功导入 {imported_count} 个品种'
        )


# ==================== 其他视图占位 ====================

class DashboardView(APIView):
    """仪表盘视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        return success_response(data={
            'message': '仪表盘功能开发中...'
        })


class GoodsListView(APIView):
    """货物列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Goods.objects.select_related(
            'variety__category__unit'
        ).prefetch_related('zone_stocks__zone').order_by('-created_at')

        keyword = request.query_params.get('keyword')
        if keyword:
            queryset = queryset.filter(name__icontains=keyword) | queryset.filter(code__icontains=keyword)

        total, goods_list, page, page_size = _paginate(request, queryset)
        serializer = GoodsSerializer(goods_list, many=True)
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })

    def post(self, request):
        """创建货物"""
        serializer = GoodsCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        goods = Goods.objects.create(
            name=data['name'],
            code=data['code'],
            variety=Variety.objects.get(pk=data['variety']),
            specification=data['specification'],
            unit_weight=data['unit_weight'],
            warning_threshold=data['warning_threshold'],
            location=data['location'],
            remark=data['remark'],
        )
        logger.info(f"User {request.user.username} created goods {goods.name}")
        return success_response(data=GoodsSerializer(goods).data, message='创建成功')


class StockInListView(APIView):
    """入库记录列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = StockIn.objects.select_related(
            'goods', 'zone', 'operator', 'rule_version', 'compat_version'
        ).order_by('-stock_in_time')

        goods_id = request.query_params.get('goods_id')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        zone_id = request.query_params.get('zone_id')
        if zone_id:
            queryset = queryset.filter(zone_id=zone_id)

        total, records, page, page_size = _paginate(request, queryset)
        serializer = StockInSerializer(records, many=True)
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })

    def post(self, request):
        """入库：按统一口径校验容量、类别准入与相容性"""
        serializer = StockInCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        record = services.stock_in_to_zone(
            goods=Goods.objects.get(pk=data['goods']),
            zone=StorageZone.objects.get(pk=data['zone']),
            quantity=data['quantity'],
            operator=request.user,
            batch_no=data['batch_no'],
            supplier=data['supplier'],
            remark=data['remark'],
        )
        return success_response(data=StockInSerializer(record).data, message='入库成功')


class StockOutListView(APIView):
    """出库记录列表视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        return success_response(data={
            'list': [],
            'total': 0,
            'page': 1,
            'page_size': 10
        })


class WarningListView(APIView):
    """预警记录列表视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        return success_response(data={
            'list': [],
            'total': 0,
            'page': 1,
            'page_size': 10
        })


class ApprovalListView(APIView):
    """审批记录列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return success_response(data={
            'list': [],
            'total': 0,
            'page': 1,
            'page_size': 10
        })


# ==================== 保管区管理 ====================


class ZoneListView(APIView):
    """保管区列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = StorageZone.objects.select_related('occupancy', 'created_by').order_by('-created_at')
        total, zones, page, page_size = _paginate(request, queryset)
        serializer = StorageZoneSerializer(zones, many=True)
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })

    def post(self, request):
        """创建保管区"""
        serializer = StorageZoneCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        zone = StorageZone.objects.create(
            name=serializer.validated_data['name'],
            description=serializer.validated_data['description'],
            created_by=request.user,
        )
        logger.info(f"User {request.user.username} created zone {zone.name}")
        return success_response(data=StorageZoneSerializer(zone).data, message='创建成功')


class ZoneAllView(APIView):
    """获取所有启用的保管区（用于下拉选择）"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        zones = StorageZone.objects.filter(is_active=True).order_by('name')
        serializer = StorageZoneSerializer(zones, many=True)
        return success_response(data=serializer.data)


class ZoneDetailView(APIView):
    """保管区详情视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            zone = StorageZone.objects.select_related('occupancy', 'created_by').get(pk=pk)
        except StorageZone.DoesNotExist:
            return error_response(message='保管区不存在', code=404)
        return success_response(data=StorageZoneSerializer(zone).data)

    def put(self, request, pk):
        """更新保管区基本信息（容量规则请通过发布新版本调整）"""
        try:
            zone = StorageZone.objects.get(pk=pk)
        except StorageZone.DoesNotExist:
            return error_response(message='保管区不存在', code=404)

        serializer = StorageZoneCreateSerializer(data=request.data, context={'instance': zone})
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        zone.name = serializer.validated_data['name']
        zone.description = serializer.validated_data['description']
        if 'is_active' in request.data:
            zone.is_active = bool(request.data['is_active'])
        zone.save()
        logger.info(f"User {request.user.username} updated zone {zone.name}")
        return success_response(data=StorageZoneSerializer(zone).data, message='更新成功')

    def delete(self, request, pk):
        """删除保管区（已有规则或业务记录的区域只能停用，以保留历史解释依据）"""
        try:
            zone = StorageZone.objects.get(pk=pk)
        except StorageZone.DoesNotExist:
            return error_response(message='保管区不存在', code=404)

        if zone.rule_versions.exists() or hasattr(zone, 'occupancy') or zone.stock_ins.exists():
            return error_response(message='该区域已有规则或业务记录，请改为停用')
        if zone.reservations.exists() or zone.goods_stocks.exists():
            return error_response(message='该区域已有规则或业务记录，请改为停用')

        name = zone.name
        zone.delete()
        logger.info(f"User {request.user.username} deleted zone {name}")
        return success_response(message='删除成功')


class ZoneRuleListView(APIView):
    """保管区容量规则版本视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """规则版本历史（新版本在前）"""
        try:
            zone = StorageZone.objects.get(pk=pk)
        except StorageZone.DoesNotExist:
            return error_response(message='保管区不存在', code=404)

        versions = zone.rule_versions.prefetch_related('allowances').order_by('-version')
        serializer = ZoneRuleVersionSerializer(versions, many=True)
        return success_response(data=serializer.data)

    def post(self, request, pk):
        """发布新规则版本（旧版本保留，历史记录仍按发生时版本解释）"""
        try:
            zone = StorageZone.objects.get(pk=pk)
        except StorageZone.DoesNotExist:
            return error_response(message='保管区不存在', code=404)

        serializer = ZoneRulePublishSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        last_version = zone.rule_versions.order_by('-version').first()
        version = (last_version.version + 1) if last_version else 1
        rule = ZoneRuleVersion.objects.create(
            zone=zone,
            version=version,
            max_weight=data['max_weight'],
            max_items=data['max_items'],
            effective_from=data.get('effective_from') or timezone.now(),
            created_by=request.user,
        )
        for category_id in data['allowed_category_ids']:
            ZoneCategoryAllowance.objects.create(rule_version=rule, category_id=category_id)

        logger.info(
            f"User {request.user.username} published rule v{version} for zone {zone.name}: "
            f"max_weight={rule.max_weight}, max_items={rule.max_items}"
        )
        return success_response(data=ZoneRuleVersionSerializer(rule).data, message='规则发布成功')


class ZoneOccupancyView(APIView):
    """保管区占用情况视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            zone = StorageZone.objects.get(pk=pk)
        except StorageZone.DoesNotExist:
            return error_response(message='保管区不存在', code=404)

        now = timezone.now()
        occupancy = ZoneOccupancy.objects.filter(zone=zone).first()
        rule = services.get_zone_rule_at(zone, now)

        categories = (
            ZoneCategoryOccupancy.objects.filter(zone=zone)
            .select_related('category')
            .order_by('category_id')
        )
        overrides = OverLimitApproval.objects.filter(
            zone=zone, is_revoked=False, expires_at__gt=now
        ).order_by('expires_at')

        data = {
            'zone': zone.id,
            'zone_name': zone.name,
            'used_weight': occupancy.used_weight if occupancy else 0,
            'used_items': occupancy.used_items if occupancy else 0,
            'reserved_weight': occupancy.reserved_weight if occupancy else 0,
            'reserved_items': occupancy.reserved_items if occupancy else 0,
            'current_rule': ZoneRuleVersionSerializer(rule).data if rule else None,
            'effective_limits': None,
            'categories': [
                {
                    'category': item.category_id,
                    'category_name': item.category.name,
                    'used_weight': item.used_weight,
                    'used_items': item.used_items,
                    'reserved_weight': item.reserved_weight,
                    'reserved_items': item.reserved_items,
                }
                for item in categories
            ],
            'active_overrides': OverLimitApprovalSerializer(overrides, many=True).data,
        }
        if rule is not None:
            max_weight, max_items = services.get_effective_limits(zone, rule, now)
            data['effective_limits'] = {'max_weight': max_weight, 'max_items': max_items}
        return success_response(data=data)


class ZoneValidateView(APIView):
    """摆放预检视图：与入库、转移、预约同一判断口径"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            zone = StorageZone.objects.get(pk=pk)
        except StorageZone.DoesNotExist:
            return error_response(message='保管区不存在', code=404)

        goods_id = request.data.get('goods')
        quantity = request.data.get('quantity')
        if not goods_id or quantity is None:
            return error_response(message='请提供货物与数量')
        try:
            goods = Goods.objects.get(pk=goods_id)
        except Goods.DoesNotExist:
            return error_response(message='货物不存在', code=404)

        try:
            quantity = Decimal(str(quantity))
        except InvalidOperation:
            return error_response(message='数量格式不正确')
        if quantity <= 0:
            return error_response(message='数量必须大于0')

        context = services.validate_placement(
            zone, goods.variety.category, quantity, goods.unit_weight,
        )
        return success_response(
            data={
                'valid': True,
                'weight': context['weight'],
                'max_weight': context['max_weight'],
                'max_items': context['max_items'],
                'rule_version': context['rule_version'].version,
                'compat_version': context['compat_version'].version if context['compat_version'] else None,
            },
            message='校验通过',
        )


# ==================== 相容性规则 ====================


class CompatibilityRuleListView(APIView):
    """相容性规则版本视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        versions = CompatibilityRuleVersion.objects.prefetch_related(
            'incompatibilities__category_a', 'incompatibilities__category_b'
        ).order_by('-version')
        serializer = CompatibilityRuleVersionSerializer(versions, many=True)
        return success_response(data=serializer.data)

    def post(self, request):
        """发布新相容性规则版本（旧版本保留）"""
        serializer = CompatibilityRulePublishSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        last_version = CompatibilityRuleVersion.objects.order_by('-version').first()
        version = (last_version.version + 1) if last_version else 1
        rule = CompatibilityRuleVersion.objects.create(
            version=version,
            effective_from=data.get('effective_from') or timezone.now(),
            created_by=request.user,
        )
        for category_a, category_b in data['pairs']:
            CategoryIncompatibility.objects.create(
                rule_version=rule, category_a_id=category_a, category_b_id=category_b
            )

        logger.info(
            f"User {request.user.username} published compatibility rule v{version} "
            f"with {len(data['pairs'])} pairs"
        )
        return success_response(
            data=CompatibilityRuleVersionSerializer(rule).data, message='规则发布成功'
        )


class CompatibilityRuleCurrentView(APIView):
    """当前生效的相容性规则"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rule = services.get_compat_rule_at(timezone.now())
        if rule is None:
            return success_response(data=None, message='尚未发布相容性规则')
        return success_response(data=CompatibilityRuleVersionSerializer(rule).data)


# ==================== 转移管理 ====================


class TransferListView(APIView):
    """转移记录视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = ZoneTransfer.objects.select_related(
            'goods', 'from_zone', 'to_zone', 'operator', 'rule_version', 'compat_version'
        ).order_by('-created_at')

        goods_id = request.query_params.get('goods_id')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)

        total, records, page, page_size = _paginate(request, queryset)
        serializer = ZoneTransferSerializer(records, many=True)
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })

    def post(self, request):
        """转移：与入库同一判断口径校验转入区域"""
        serializer = ZoneTransferCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        record = services.transfer_goods(
            goods=Goods.objects.get(pk=data['goods']),
            from_zone=StorageZone.objects.get(pk=data['from_zone']),
            to_zone=StorageZone.objects.get(pk=data['to_zone']),
            quantity=data['quantity'],
            operator=request.user,
            remark=data['remark'],
        )
        return success_response(data=ZoneTransferSerializer(record).data, message='转移成功')


# ==================== 容量预约 ====================


class ReservationListView(APIView):
    """容量预约视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = ZoneReservation.objects.select_related(
            'goods', 'zone', 'created_by', 'rule_version', 'compat_version'
        ).order_by('-created_at')

        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        zone_id = request.query_params.get('zone_id')
        if zone_id:
            queryset = queryset.filter(zone_id=zone_id)

        total, records, page, page_size = _paginate(request, queryset)
        serializer = ZoneReservationSerializer(records, many=True)
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })

    def post(self, request):
        """预约：与入库同一判断口径校验，占用预约容量"""
        serializer = ZoneReservationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        reservation = services.create_reservation(
            goods=Goods.objects.get(pk=data['goods']),
            zone=StorageZone.objects.get(pk=data['zone']),
            quantity=data['quantity'],
            expires_at=data['expires_at'],
            operator=request.user,
            remark=data['remark'],
        )
        return success_response(
            data=ZoneReservationSerializer(reservation).data, message='预约成功'
        )


class ReservationCancelView(APIView):
    """取消预约视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            reservation = ZoneReservation.objects.get(pk=pk)
        except ZoneReservation.DoesNotExist:
            return error_response(message='预约不存在', code=404)

        services.cancel_reservation(reservation=reservation, operator=request.user)
        reservation.refresh_from_db()
        return success_response(
            data=ZoneReservationSerializer(reservation).data, message='预约已取消'
        )


class ReservationFulfillView(APIView):
    """核销预约视图（预约容量转为实际入库）"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            reservation = ZoneReservation.objects.get(pk=pk)
        except ZoneReservation.DoesNotExist:
            return error_response(message='预约不存在', code=404)

        record = services.fulfill_reservation(
            reservation=reservation,
            operator=request.user,
            remark=request.data.get('remark', ''),
        )
        return success_response(data=StockInSerializer(record).data, message='预约核销成功')


# ==================== 临时超限批准 ====================


class OverLimitApprovalListView(APIView):
    """临时超限批准视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = OverLimitApproval.objects.select_related(
            'zone', 'approved_by', 'revoked_by'
        ).order_by('-created_at')

        zone_id = request.query_params.get('zone_id')
        if zone_id:
            queryset = queryset.filter(zone_id=zone_id)

        total, records, page, page_size = _paginate(request, queryset)
        serializer = OverLimitApprovalSerializer(records, many=True)
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })

    def post(self, request):
        """批准临时超限：仅管理员，必须设置失效时间"""
        _require_admin(request)

        serializer = OverLimitApprovalCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        approval = OverLimitApproval.objects.create(
            zone=StorageZone.objects.get(pk=data['zone']),
            approved_by=request.user,
            extra_weight=data['extra_weight'],
            extra_items=data['extra_items'],
            reason=data['reason'],
            expires_at=data['expires_at'],
        )
        logger.info(
            f"User {request.user.username} approved over-limit for zone "
            f"{approval.zone.name} until {approval.expires_at}"
        )
        return success_response(
            data=OverLimitApprovalSerializer(approval).data, message='临时超限已批准'
        )


class OverLimitApprovalRevokeView(APIView):
    """撤销临时超限视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_admin(request)

        try:
            approval = OverLimitApproval.objects.get(pk=pk)
        except OverLimitApproval.DoesNotExist:
            return error_response(message='批准记录不存在', code=404)

        if approval.is_revoked:
            return error_response(message='该批准已撤销')

        approval.is_revoked = True
        approval.revoked_by = request.user
        approval.revoked_at = timezone.now()
        approval.save(update_fields=['is_revoked', 'revoked_by', 'revoked_at'])
        logger.info(f"User {request.user.username} revoked over-limit approval {approval.id}")
        return success_response(
            data=OverLimitApprovalSerializer(approval).data, message='已撤销'
        )

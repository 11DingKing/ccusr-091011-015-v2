# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 保管区容量与相容性

保管区（`StorageZone`）对重量、件数和物资类别设有上限，替代原有的纯文本位置字段：

- **规则版本**：容量上限、准入品类、品类相容性（不得同区存放的品类对）按版本管理，调整只新增版本、历史版本不可变；每次校验都记录发生时的规则版本与上限快照，历史记录按发生时规则解释。
- **统一校验口径**：入库（`POST /api/stock-in/`）、转移（`POST /api/transfers/`）、预约（`POST /api/reservations/`）共用同一规则引擎，预约占用与实物占用合并计算容量。
- **临时超限**：仅管理员可批准（`POST /api/zones/<id>/overrides/`），必须设置失效时间，到期或撤销后自动失效。
- **并发安全**：容量增减全部通过数据库条件更新完成，并发占用不会超卖，容量释放不会出现负数；预约到期自动释放额度。

主要接口：

| 接口 | 说明 |
| --- | --- |
| `GET/POST /api/zones/`、`GET/PUT/DELETE /api/zones/<id>/` | 保管区管理（写操作限管理员） |
| `GET/POST /api/zones/<id>/rules/` | 规则版本列表与新增（新增限管理员） |
| `GET /api/zones/<id>/occupancy/` | 当前生效口径下的占用与剩余 |
| `GET/POST /api/zones/<id>/overrides/`、`POST /api/overrides/<id>/revoke/` | 临时超限批准与撤销（限管理员） |
| `GET/POST /api/reservations/`、`POST /api/reservations/<id>/cancel/` | 容量预约与取消 |
| `GET/POST /api/transfers/` | 区域间转移 |
| `GET /api/zones/<id>/validations/` | 容量校验记录（含发生时规则版本快照） |
| `GET /api/zones/<id>/placements/` | 区内存放明细 |

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```

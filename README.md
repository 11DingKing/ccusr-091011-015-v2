# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 保管区、容量与相容性

保管区对重量、件数和物资类别设有上限，入库、转移、预约共用同一套校验口径（`apps/warehouse/services.py` 的 `validate_placement`）：

- `POST /api/zones/` 建立保管区；`POST /api/zones/<id>/rules/` 发布容量规则（重量/件数上限、允许品类）。规则只增不改，每次调整生成新版本，历史记录保存发生时的规则版本快照，仍按当时规则解释。
- `POST /api/compatibility-rules/` 发布品类不相容规则（版本化）；同一保管区内不得同时存放互斥品类（含预约占用）。
- `POST /api/stock-in/`、`POST /api/transfers/`、`POST /api/reservations/` 均按同一口径校验；`POST /api/zones/<id>/validate/` 可预检。
- 临时超限由管理员通过 `POST /api/overrides/` 批准，必须设置失效时间，可撤销；生效上限 = 规则上限 + 有效临时额度。
- 预约占用容量，取消、核销（转入库）或过期后释放；`python manage.py release_expired_reservations` 可定期清理过期预约。
- 占用台账通过条件更新原子变更并带非负约束，容量释放不会为负，并发占用不会超卖。

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

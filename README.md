# 数控刀补复核台

操作员在「日券台」领取当日券并挂券交单；后台 worker 用 PostgreSQL 行锁（`select_for_update(skip_locked=True)`）认领待复核记录，按绝对值是否不超过 12 微米给出「合格」或「超差」。

## 日券规则

- **按自然日发放**：每个操作员每日五张当日券，幂等补齐（重复点分发不重发）。
- **交单必须挂券**：只能挂「当日、属于自己、仍有效」的券；券号不存在、挂他人券、挂旧券、挂已作废券一律挡回。
- **入队即作废（同一事务）**：交单入待复核与券作废在一个数据库事务内落库；任一步失败整体回滚，不会留下「已入队但券仍可复用」的中间态。
- **一券一单**：`OffsetSubmission.ticket` 为 OneToOne，从结构上禁止一张券对应两笔交单；并发两人同挂一张券，靠行锁串行化，只许一笔入队、另一笔挡回（接口层另以唯一约束兜底返回 409）。
- **只读观察账号**：复核员可翻看「在用券」与「作废簿」及交单列表，但不能发券、不能挂券交单、不能作废券。
- **作废簿只读留档**：作废券不可复活、不可复用。

## 导航

顶部导航两个区：**复核总览**（交单队列/结论）与**日券台**（分发券区 / 在用券 / 作废簿）。挂券交单表单位于「在用券」卡片内。

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Django 5 + django-ninja（ASGI / uvicorn） |
| 前端 | SolidJS + Vite，nginx 反代 `/api` |
| 数据库 | PostgreSQL 16 |
| 鉴权 | JWT（python-jose），令牌存浏览器 localStorage |

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3196 |
| 接口 | http://localhost:8196 |
| PostgreSQL | localhost:54396（库名 `cncoffset`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| machinist | machine123456 | 可发券、挂券交单 |
| auditor | audit123456 | 只读：翻看券、作废簿与交单 |

## 启动

```bash
cd projects/17-cnc-tool-offset-desk
docker compose up --build
```

健康检查：`GET http://localhost:8196/api/health` → `{"status":"ok"}`

## 主要接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tickets/distribute` | 按自然日幂等发放/补齐当日五张券（仅操作员） |
| GET | `/api/tickets/today` | 当日券（操作员看自己；复核员看全部） |
| GET | `/api/tickets/voided` | 作废簿 |
| POST | `/api/submissions` | 挂券交单，body 需含 `ticket_code/tool_code/offset_um`（仅操作员） |
| GET | `/api/submissions` | 交单列表（含 `ticket_code`） |

## 验收

1. machinist 登录后进入「日券台」，点发券得到当日五张在用券（种子已自动发）。
2. 选一张在用券交单，进入「待复核」，该券同时进入作废簿；数秒内 worker 处理为「已完成」并给出结论。
3. 拿同一张作废券再交第二笔，被挡回（400「该券已作废」）。
4. 两人几乎同时挂同一张有效券：只一笔成功，另一笔挡回（测试 `ConcurrencyTests` 用真实 PG 多线程验证）。
5. 挂昨日券、挂他人券、券号不存在，均被挡回，无交单入队。
6. auditor 登录只能翻看券与作废簿，没有发券按钮与交单表单，强调接口返回 403。

## 测试

```bash
cd backend
python manage.py test desk
```

需连接真实 PostgreSQL（行锁语义）。覆盖原子交单、故障注入回滚、12 轮并发争抢、幂等发券、只读权限。

## 目录

```text
backend/          Django 工程（config/、desk/、worker.py）
frontend/         SolidJS 单页
docker-compose.yml
PRD.md
```

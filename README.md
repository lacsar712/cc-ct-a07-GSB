# 数控刀补复核台

操作员提交刀具编号与刀补微米值；后台 worker 用 PostgreSQL 行锁（`select_for_update(skip_locked=True)`）认领待复核记录，按绝对值是否不超过 12 微米给出「合格」或「超差」。

本版新增**日券台**：操作员交单须挂一张当日仍有效的日券；日券按自然日每人只发一张，挂券入队与券核销在**同一数据库事务**落库。

## 日券规则

1. **自然日一张**：每个操作员每个自然日至多一张当日券，重复领取幂等返回同一张（唯一约束 `uniq_ticket_per_user_per_day` 兜底）。
2. **挂券交单**：在日券台把刀具编号、刀补微米值挂到一张券上交单。
   - 仅「当日 + 在用 + 本人名下」的券可交单；旧券、他人券、已用券、已作废券**一律挡回（409）**。
   - 入队（建待复核记录）与券核销（标记已用）在**同一事务**提交，杜绝「先入队、核销失败留下可复用券」。
3. **并发只许一笔**：两笔请求几乎同时挂同一张有效券时，`SELECT … FOR UPDATE` 锁住券行串行化——先到者入队成功并把券置为已用，后到者拿到锁后看到券已用，挡回。
4. **作废**：仅在用券可作废；券状态置为「已作废」与写入**作废簿**（`TicketVoidRecord`，只追加留痕）在同一事务落库。已用券不可作废，作废不可重复。拿作废券再交第二笔会被挡回。
5. **只读观察账号（auditor）**：可翻阅分发券区与作废簿，但不能发券、不能交单、不能作废（写操作返回 403）。
6. 今日新券挂上后，新刀补记录立即进「待复核」，由 worker 复核出结论。

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
| machinist | machine123456 | 可发券、挂券交单、作废、提交刀补 |
| auditor | audit123456 | 只读：可翻券与作废簿，不能发券/交单/作废 |

## 启动

```bash
docker compose up --build
```

健康检查：`GET http://localhost:8196/api/health` → `{"status":"ok"}`

## 日券接口（均需 Bearer JWT）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/tickets/issue` | 领取/取得当日券（幂等） | 操作员 |
| GET | `/api/tickets?status=valid` | 分发券区：券列表，可按状态过滤 | 登录即可 |
| GET | `/api/tickets/voided` | 作废簿 | 登录即可 |
| POST | `/api/tickets/{id}/redeem` | 挂券交单 `{tool_code, offset_um}` | 操作员 |
| POST | `/api/tickets/{id}/void` | 作废在用券 `{reason}` | 操作员 |

挡回统一返回 `409`，只读账号写操作返回 `403`。

## 验收

1. machinist 登录后，种子数据应显示刀具 T01 合格（刀补 5 µm）、T09 超差（刀补 20 µm），日券台有一张当日在用新券。
2. 在日券台把今日新券挂上刀具（如 T05 / 5 µm）交单：券变「已用」，复核列表出现一条「待复核」，数秒内 worker 处理为「已完成」并给出结论。
3. 用同一张券再交第二笔 → 被挡回（券已使用）。
4. 领一张券后作废：券进入作废簿；再拿它交单 → 被挡回。
5. 两个会话几乎同时用同一张有效券交单：只许一笔入队，另一笔挡回。
6. auditor 登录后能打开日券台翻阅分发券区与作废簿，但没有领取/交单/作废按钮，直接调写接口返回 403。
7. 昨日（旧）券交单 → 被挡回，提示领取当日券。

后端单元测试：`python manage.py test desk`（在 backend 容器内运行）。

## 目录

```text
backend/          Django 工程（config/、desk/、worker.py）
frontend/         SolidJS 单页
docker-compose.yml
```

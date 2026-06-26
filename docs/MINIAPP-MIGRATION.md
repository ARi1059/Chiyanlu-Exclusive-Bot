# 痴颜录 MiniApp 迁移技术方案

> 本文档为「整套迁移到 Telegram MiniApp」的技术基线，供后续迭代引用。
> 核心立场：**不是把 bot 换成网页，而是在现有单进程里挂一层 aiohttp web 服务 + 前端 SPA，API 层薄封装现有 [`bot/database.py`](../bot/database.py) 与 `bot/services`，bot 本体退化为「通知与群组引擎」。业务逻辑一行不重写，只换交互外壳。**
>
> **2026-06-26**：初版，覆盖 §〇–§十九 全文 —— 现状基线 / 目标架构 / 三项已定决策 / 路线图 + **P0–P4 五阶段细化设计全部完成**。
> 以本文为准的前置讨论结论：动机 = 减轻用户端 FSM 交互负担 + 富化展示（相册/图表）+ 一个像样的后台管理台；范围 = 整套迁。

## 目录

- [〇、决策状态](#〇决策状态) — 一眼看清已定 / 待定
- [一、现状基线](#一现状基线) — 贴代码事实，决定方案走向
- [二、目标架构](#二目标架构) — 拓扑 + 同进程挂载决策
- [三、鉴权](#三鉴权initdata-验签--会话) — initData 验签 + session
- [四、API 层](#四api-层薄封装不重写业务) — 薄封装原则 + 资源映射
- [五、图片/富媒体](#五图片富媒体混合方案) — 混合方案（代理兜底 + 新增走存储）
- [六、FSM → 前端表单](#六fsm--前端表单) — 减负本质 + 双轨过渡
- [七、前端技术栈](#七前端技术栈定稿) — 定稿
- [八、工程结构](#八工程结构) — 后端 `bot/web/` + 前端 `webapp/`
- [九、部署与运维](#九部署与运维)
- [十、数据并发与 SQLite 演进](#十数据并发与-sqlite-演进)
- [十一、分阶段路线图](#十一分阶段路线图) — P0–P4
- [十二、P0 细化设计](#十二p0-细化设计地基) — 地基
- [十三、P1 细化设计](#十三p1-细化设计富展示只读) — 富展示（只读）
- [十四、P2 细化设计](#十四p2-细化设计用户端写fsm表单) — 用户端写（FSM→表单）
- [十五、P3 细化设计](#十五p3-细化设计后台管理台) — 后台管理台
- [十六、P4 细化设计](#十六p4-细化设计老师端--全局收口) — 老师端 + 全局收口
- [十七、留在 Bot 的边界](#十七留在-bot-的边界)
- [十八、风险与技术债清单](#十八风险与技术债清单)
- [十九、开放问题 / 待决策](#十九开放问题--待决策)

---

## 〇、决策状态

| 决策点 | 状态 | 结论 |
|---|---|---|
| 进程拓扑 | ✅ 已定 | **同进程挂载**（aiohttp 与 polling 共用 asyncio loop），起步形态 |
| 图片承载 | ✅ 已定 | **混合**：存量 file_id 走 bot 代理 + 缓存，新上传走对象存储/静态目录 |
| 前端技术栈 | ✅ 已定 | **Vue 3 + TypeScript + Vite + Naive UI + Pinia + vue-echarts + @twa-dev/sdk** |
| SQLite → Postgres | ⏳ 待触发 | 第一阶段不动，达到换库信号（见 §十）再评估 |
| 双轨退役时机 | ⏳ 待定 | bot FSM 作降级路径长期保留，退役时机另议 |

---

## 一、现状基线

迁移方案的所有取舍都建立在以下代码事实之上（截至 2026-06-26）：

| 维度 | 现状 | 对迁移的影响 |
|---|---|---|
| 进程 | 单 asyncio loop，[`bot/main.py`](../bot/main.py) `dp.start_polling(bot)`；FSM 用 `MemoryStorage`（内存，重启丢、不跨进程） | 同进程挂 web 最省事；底层已是 aiohttp（aiogram 3 自带），**无需新增 web 框架依赖** |
| 调度 | APScheduler `AsyncIOScheduler` 同 loop（[`bot/scheduler/tasks.py`](../bot/scheduler/tasks.py)） | 调度全留 bot，不进前端 |
| DB | [`bot/database.py`](../bot/database.py) `get_db()` 每次 `aiosqlite.connect()`、无连接池；WAL + `synchronous=NORMAL` + `busy_timeout=5000` + `foreign_keys=ON` | 代码注释明确「单进程 polling，open/close 开销可接受」——该假设在 MiniApp 高并发下会被打破（§十） |
| 角色 | `is_admin()` / `is_super_admin()` 查 `admins` 表 + config 的 `SUPER_ADMIN_ID`；teacher 看 `teachers` 表 | 全是现成 db 函数，API 鉴权直接复用，**零新业务** |
| 图片 | 全是 Telegram `file_id`：`photo_file_id` / `photo_album` / `booking_screenshot_file_id` / `gesture_photo_file_id` / `cover_file_id` | **整个迁移最大技术债**：网页 `<img>` 无法直接渲染 file_id（§五） |
| FSM | 全项目约 550 处 FSM 调用，用得极广 | 长表单迁前端后绕开 FSM；bot FSM 保留作降级（§六） |
| 业务逻辑 | 集中在 6540 行 `database.py` + `bot/services` + 各 handler | API 层薄封装复用，**不重写**（§四） |

---

## 二、目标架构

### 2.1 拓扑

```
                  ┌───────────────────────────────────────┐
   Telegram 客户端 │  MiniApp (SPA, telegram-web-app.js)    │
   ├─ 群/私聊消息   │   用户端视图 / 老师端视图 / 管理后台    │
   └─ Menu Button  └──────────────┬────────────────────────┘
        │                         │ HTTPS (initData 鉴权 + session)
        │ polling                 ▼
   ┌────┴─────────────────────────────────────────────────┐
   │  单进程 (asyncio loop)                                 │
   │  ┌──────────────┐   ┌──────────────────────────────┐  │
   │  │ aiogram Dp    │   │ aiohttp Web App (新增)        │  │
   │  │ - 群组监听    │   │ - /api/* REST                │  │
   │  │ - 通知/调度   │   │ - /api/media/<file_id> 代理   │  │
   │  │ - FSM(降级)   │   │ - initData 验签 + session     │  │
   │  └──────┬───────┘   └───────────┬──────────────────┘  │
   │         └──────────┬────────────┘  共享 bot 对象/config │
   │                    ▼                                   │
   │       bot/database.py + bot/services（零改动复用）      │
   │                    ▼                                   │
   │              SQLite (WAL 单文件)                       │
   └───────────────────────────────────────────────────────┘
                    ▲ Nginx/Caddy 终止 TLS（WebApp 强制 HTTPS）
```

### 2.2 进程拓扑决策：同进程挂载（已定）

| | 同进程（采用） | 独立 web 进程（暂不） |
|---|---|---|
| 发通知 | 直接 `await bot.send_message`，共享 bot 对象 | 需另起 `Bot(token)`，`send_message` 无状态也能发 |
| 共享 config/services | 直接 import | 同样 import，但 SQLite 跨进程写 |
| FSM 共享 | `MemoryStorage` 同进程可读 | 不共享（但 MiniApp 表单本就不用 FSM） |
| SQLite 写 | 单进程串行，无跨进程锁竞争 | 两进程写同一文件，靠 WAL+busy_timeout 兜底 |
| 隔离/独立重启 | 弱（web 崩影响 polling） | 强 |
| 改动量 | 最小：`asyncio.gather(start_polling, web_runner)` | 需新 systemd unit + 部署管线 |

**采用同进程**：复用 bot 对象做通知回流，ROI 最高、改动最小。`bot/main.py` 改动仅一处（示意）：

```
await asyncio.gather(dp.start_polling(bot), start_web(bot))
```

工程边界仍按「可拆分」设计（API/service 解耦），等 API QPS 起来或要独立扩容时无痛迁独立进程（届时同步评估换 Postgres）。

---

## 三、鉴权：initData 验签 + 会话

MiniApp 启动时 `window.Telegram.WebApp.initData` 带签名串，后端验签四步：

1. `secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)`
2. 用 `secret_key` 对 `data_check_string` 算 HMAC，比对 `hash` 字段；
3. 校验 `auth_date` 时间窗（防重放，如 > 24h 拒绝）；
4. 通过 → 得可信 `user.id` → **复用 `is_super_admin()` / `is_admin()` / teacher 查询**定角色 → 签发短期 session token（自签 JWT，30–60 min），后续 `/api/*` 带 token，避免每请求重验。

四级权限 **user / teacher / admin / superadmin** 直接映射现有逻辑，鉴权零新业务。这是迁移最干净的一块。

---

## 四、API 层：薄封装，不重写业务

**铁律**：API handler 只做 `验权 → 调用现有 database.py / services 函数 → 序列化 JSON`，**不写业务逻辑**。6540 行 `database.py` 是资产，全部复用。

资源映射示例（REST，按现有 router 边界切）：

| MiniApp 页面 | Endpoint | 复用的现有逻辑 |
|---|---|---|
| 今日可约 | `GET /api/teachers/today` | 今日签到查询 |
| 老师详情 | `GET /api/teachers/{id}` | `teacher_detail` 查询部分 |
| 搜索 | `GET /api/teachers/search?q=` | `search_teachers_smart_and` |
| 收藏 toggle | `POST /api/favorites/{id}` | `bot/services/user_favorites.py` |
| 提交评价 | `POST /api/reviews` | `review_submit` 落库 + **回流通知超管** |
| 我的积分明细 | `GET /api/points` | `point_transactions` 查询 |
| 后台·待审核 | `GET /api/admin/reviews?status=pending` | `rreview_admin` 查询 |
| 后台·审核动作 | `POST /api/admin/reviews/{id}/approve` | 现有 approve 逻辑 + 通知用户 |

**写操作的通知回流**：写库后需通知的，`await bot.send_message(...)`（同进程直接拿 bot 对象）。这是「MiniApp 操作 → bot 推送」闭环的关键接缝。**限频校验（60s / 24h 等）必须复用 bot 侧同一套逻辑**，不能被 API 绕过。

---

## 五、图片/富媒体：混合方案

现状全是 `file_id`，而 file_id **不能**直接给网页 `<img>`，且换取的下载 URL 带 bot token、**绝不能暴露给前端**。采用**混合**：

| 半边 | 做法 | 落地位置 |
|---|---|---|
| 存量兜底 | `GET /api/media/{file_id}` → 命中磁盘缓存直回；未命中 → `bot.get_file` 下载 → 写缓存 → 流式返回 | `bot/web/media.py`，P1 落地 |
| 新增直存 | 上传时同步存对象存储 / 本地 Nginx 静态目录，db 存 URL | `bot/web/storage.py`，P2 写操作启用 |

前端统一用 `MediaImage.vue` 组件：拿到的就是可直接 `src` 的 URL（代理 URL 或存储 URL），组件无需关心来源。**「媒体代理 + 缓存」是 P1 第一个落地件**——后面所有富展示（相册轮播、评价手势照、审核媒体组）都依赖它。

token 安全红线：getFile 换来的 `api.telegram.org/file/bot<token>/...` 只在后端使用，任何情况下不出后端。

> P2 关联：进 Telegram 审核流的**新上传**图（约课截图 / 手势照 / 老师资料图）**不走对象存储**，而是「回灌 file_id」——后端把字节发回 Telegram 换取 file_id，使审核侧（`rreview_admin`）零改动。详见 §十四 14.1。对象存储仅用于纯展示、不进审核的图。

---

## 六、FSM → 前端表单

「减轻 FSM 负担」的本质 = 把 aiogram 多回合 FSM 换成**前端一次性收集 + 单次 API 提交**。MiniApp 表单天然不依赖 `MemoryStorage`，绕开了重启丢状态、每步等 callback 往返的痛点。

重点改造对象（现有最痛的 FSM）：

- **写评价 9 字段卡片**（[`bot/handlers/review_card.py`](../bot/handlers/review_card.py)）→ 一屏表单，实时校验（summary 50–300 字前端即时提示），图片直传；
- **老师档案 9 步录入**（[`bot/handlers/teacher_profile.py`](../bot/handlers/teacher_profile.py)）→ 后台分区表单 + 相册拖拽；
- **老师「我的资料」编辑**（[`bot/handlers/teacher_self.py`](../bot/handlers/teacher_self.py)）→ 多字段一次改；
- **手动加分 4 步 / 报销审核口令流** → 后台弹窗式表单。

**双轨过渡（已定为长期形态）**：bot 侧 FSM **保留不删**，作为「没打开 MiniApp / 群内」的降级路径，与 MiniApp 表单共用底层 service。一段时间内「同业务两入口」是整套迁的正常过渡，靠「共用 service 层」把双轨维护成本压到最低。

---

## 七、前端技术栈（定稿）

| 关注点 | 选型 | 理由 |
|---|---|---|
| 框架 | **Vue 3 + TypeScript + Vite** | 单人维护、模板心智负担低；后台表单密集，Vue 写起来比 React 省 |
| 后台 UI 库 | **Naive UI** | 免费、TS 原生、表格/表单/弹窗组件齐，中后台最省力 |
| 状态 | **Pinia** | 存 session / 角色 / 老师缓存，够轻 |
| 图表 | **vue-echarts（ECharts）** | 看板趋势线 / 下钻，生态最稳 |
| 路由 | **vue-router** + 角色守卫 | 一套工程按 session 角色分三视图，懒加载 |
| TG 集成 | **@twa-dev/sdk** | initData / themeParams / BackButton / MainButton 封装 |
| 请求 | **axios** + 拦截器 | 自动带 session token，401 静默换 token |

选型逻辑：不是 Vue 比 React 强，而是**这个项目的形状**（单人 + 表单密集中后台 + 要快出活）下，Vue 3 + Naive UI 的单位时间产出更高。

---

## 八、工程结构

### 8.1 后端：新增 `bot/web/`（同进程）

```
bot/web/
  server.py        # aiohttp AppRunner 构造，挂到 main 的 gather；复用同一 bot 对象
  auth.py          # initData 验签 + session(JWT) 签发/校验
  middleware.py    # 鉴权中间件 / 限流 / 统一错误包装 / CORS
  media.py         # /api/media/{file_id} 代理 + 磁盘缓存（混合方案·代理兜底）
  storage.py       # 新增上传写对象存储/静态目录（混合方案·新增直存）
  api/
    teachers.py  favorites.py  reviews.py  points.py  reimburse.py
    admin/  review.py  teachers.py  config.py  dashboard.py
  schemas.py       # 序列化（JSON 形状），不含业务
```

`bot/web/api/*` 内**只验权 + 调现有 `database.py` 函数 + 序列化**。

### 8.2 前端：新增 `webapp/`（独立 Vite 工程，repo 内）

```
webapp/src/
  tg.ts            # SDK 封装：取 initData、套 theme、接管 BackButton/MainButton
  api/             # axios + 拦截器（自动带 session、401 重新换 token）
  router/          # 角色守卫：user / teacher / admin
  stores/          # Pinia：session、角色、老师缓存
  components/  MediaImage.vue  TeacherCard.vue  ReviewForm.vue
  views/  user/  teacher/  admin/
```

---

## 九、部署与运维

| 项 | 现状 | 迁移后 |
|---|---|---|
| 进程 | systemd 单 service，polling | 同 service 内多挂一个 aiohttp（同进程） |
| 网络 | 仅出站（polling） | **必须 HTTPS 入站** → Nginx/Caddy 反代 + 证书（WebApp 硬性要求） |
| 静态前端 | 无 | Nginx 静态目录托管 SPA 构建产物 |
| 域名 | 无 | 需一个域名指向 VPS |
| BotFather | `/setcommands` | 增配 Menu Button / Web App URL |
| 备份 | `pull-backup.sh` 拉 bot.db+.env | 增加媒体缓存目录 / 存储目录 |

> 安全提示：从「纯出站 polling」变为「对公网开放入站」，攻击面扩大。本项目内容敏感，入站需严格鉴权（initData 验签不可绕过）、限流、最小暴露面。

---

## 十、数据并发与 SQLite 演进

`get_db()` 每请求 `connect()`+`close()` 在低频 polling 下无碍，但 MiniApp API 并发上来后：open/close 开销 + WAL 写锁竞争会显现。

- **第一阶段**：WAL + `busy_timeout=5000` 足以扛住读多写少，**先不改**，上线观察；
- **第二阶段**：引入单写连接复用 / 轻量连接池（读连接多开，写连接串行）；
- **换 Postgres 的触发信号**：持续 `SQLITE_BUSY`、写延迟 > 数百 ms、或决定拆独立 web 进程时。

---

## 十一、分阶段路线图

| Phase | 内容 | 目的 / 风险 | 细化 |
|---|---|---|---|
| **P0 地基** | aiohttp 挂载 + initData 验签 + session + `/api/me` + 前端脚手架 + HTTPS 反代 | 打通管道，零业务，低风险 | 见 §十二 |
| **P1 富展示（只读）** | 媒体代理 + 老师详情/相册/评价列表/今日可约/搜索 | 纯读，先享「富化展示」红利 | 见 §十三 |
| **P2 用户端写** | 写评价表单、收藏 toggle、提醒、积分/报销明细 | 「减轻 FSM」主战场，引入写回流通知 | 见 §十四 |
| **P3 后台管理台** | 审核台（资料/评价/报销）、老师档案录入、系统配置、看板图表 | 「像样的后台」，权限最敏感 | 见 §十五 |
| **P4 老师端 + 收尾** | 老师端首页 / 签到状态页；统一 startapp 打通群卡片；bot FSM 转降级 + 双轨可观测 | 收口 | 见 §十六 |

---

## 十二、P0 细化设计：地基

**目标**：零业务，只打通「前端 → 验签 → 角色 → session → 调 API」全链路。

**交付物**

| 模块 | 内容 |
|---|---|
| `bot/web/auth.py` | initData 验签四步（§三）+ 签发 30–60min session JWT + 校验中间件 |
| `bot/web/server.py` | aiohttp 挂载、健康检查 `GET /api/health` |
| `GET /api/me` | 验签后返回当前用户角色，验证全链路 |
| 前端脚手架 | Vite + `tg.ts` + api 封装 + 一个「你是 {role}」页 |
| 运维 | Nginx/Caddy 反代 + TLS 证书 + BotFather 配 Menu Button URL |

**`/api/me` 响应契约（设计示意）**

```json
{
  "user_id": 123456789,
  "role": "superadmin",
  "display_name": "...",
  "session_expires_at": 1750000000
}
```
（`role` ∈ `superadmin|admin|teacher|user`；`display_name` 仅 teacher 带艺名）

**验收**：Telegram 内点 Menu Button 打开 MiniApp → 验签通过 → 正确显示角色 → token 过期能静默续签。
**不做**：任何业务页面、任何写操作、任何图片。

---

## 十三、P1 细化设计：富展示（只读）

**先落媒体代理**（后续所有富展示依赖）：`GET /api/media/{file_id}` → 查磁盘缓存命中直回；未命中 → `bot.get_file` 下载 → 写缓存 → 流式返回。混合方案另一半 `storage.py` 在此预留新上传接口（P2 启用）。

**只读 API + 对应页面**

| Endpoint | 复用现有逻辑 | 前端页面 |
|---|---|---|
| `GET /api/teachers/today` | 今日签到查询 | 今日可约（网格/列表） |
| `GET /api/teachers/{id}` | `teacher_detail` 查询部分 | 详情页（相册轮播 + 评价摘要） |
| `GET /api/teachers/search?q=` | `search_teachers_smart_and` | 搜索（即时筛选） |
| `GET /api/teachers/{id}/reviews?page=` | 评价分页查询 | 评价列表（瀑布流） |

**老师详情响应契约（设计示意）**

```json
{
  "id": 0,
  "display_name": "...",
  "region": "...",
  "price": "...",
  "tags": ["..."],
  "description": "...",
  "service_content": "...",
  "taboos": "...",
  "album": ["/api/media/<file_id_1>", "/api/media/<file_id_2>"],
  "rating": { "count": 12, "avg": 4.6 },
  "recent_reviews": [
    { "rating": "good", "summary": "...", "signature": "****6789" }
  ],
  "contact_url": "https://...",
  "is_today_available": true
}
```
（`album` 内即 `MediaImage.vue` 可直接 `src` 的 URL）

**验收**：详情 / 今日可约 / 搜索 / 评价四页在 Telegram 内可用；图片经代理正常显示且缓存命中；深浅色主题自适应。
**注意**：① 只读接口同样要带 session 鉴权（内容敏感，不裸奔）；② 读路径不碰任何限频/写逻辑，写留到 P2；③ 群卡片按钮此阶段即可升级为 `t.me/<bot>/<app>?startapp=teacher_<id>` 直达详情页。

---

## 十四、P2 细化设计：用户端写（FSM→表单）

P2 是「减轻 FSM 负担」主战场，覆盖三块写操作：**写评价**（最复杂）、**收藏/提醒 toggle**、**老师资料编辑**。统一前提：**前端表单的即时校验只为体验，服务端复刻全部校验才是权威**——限频、必关、长度、分值范围、必传项一个都不能少，照搬 bot 侧常量与函数。

### 14.1 先解决：图片上传如何回灌 file_id（P2 地基）

现状审核流（`rreview`）靠 Telegram `file_id` 给超管发 media group 预览（`InputMediaPhoto`）。MiniApp 表单上传的是二进制，若直接存对象存储拿 URL，**审核侧会拿不到 file_id 而崩**。所以凡是要进 Telegram 审核流的图（约课截图 / 手势照 / 老师资料图），P2 采用「**回灌 file_id**」：

```
POST /api/uploads   (multipart 图片)
  后端 → bot.send_photo(BUFFER_CHAT_ID, BufferedInputFile(bytes))
       → 取 message.photo[-1].file_id
       → 返回 { "file_id": "AgAC..." }     # 或不透明 upload_token 映射到 file_id
前端提交表单时带回该 file_id；展示走 P1 的 /api/media 代理。
```

- `BUFFER_CHAT_ID`：一个专用「中转」会话（隐藏频道或超管私聊），仅用于换取 file_id。
- **与 §五的关系澄清**：§五「新增走对象存储」只适用于**纯展示、不进 TG 审核**的图；**进审核流的图一律回灌 file_id**，从而审核侧（`rreview_admin`）零改动。P2 主路径是 file_id 回灌，`storage.py` 对象存储 P2 可不启用。

### 14.2 写评价：9 字段 FSM → 一屏表单

**现状 FSM**（`CardReviewStates`，[`bot/handlers/review_card.py`](../bot/handlers/review_card.py)）：`choosing_reimburse_intent`（资格通过时）→ `card`（idle）+ 9 个 `editing_X` 子状态；字段落 `teacher_reviews`。

**两个端点。** `GET /api/teachers/{id}/review-context` —— 一次性返回 FSM 里分散的所有前置判定，前端一屏决策：

```json
{
  "teacher": { "id": 0, "display_name": "...", "price_tier": 9 },
  "rate_limit": { "blocked": false, "reason": null },
  "required_channels": { "ok": true, "missing": [] },
  "reimburse": {
    "eligible": true,
    "estimated_amount": 150,
    "required_channels": { "ok": false, "missing": [{ "display_name": "...", "invite_link": "..." }] },
    "ineligibility_hint": null
  }
}
```

`POST /api/reviews` —— 提交：

```json
{
  "teacher_id": 0,
  "rating": "positive",
  "booking_screenshot_file_id": "AgAC...",
  "gesture_photo_file_id": "AgAC...",
  "scores": { "humanphoto": 8, "appearance": 9, "body": 7,
              "service": 9, "attitude": 8, "environment": 7 },
  "summary": "...",
  "request_reimbursement": 1,
  "anonymous": 0
}
```
（`booking_screenshot_file_id` 必传；`gesture_photo_file_id` 仅 `request_reimbursement=1` 时必传；`summary` 50–300 字；6 维分 0–10）

**服务端校验顺序（复刻 bot 侧，权威）**：teacher active → `_check_rate_limit`（60s / 24h-teacher / 24h-user 三项，复用 `REVIEW_RATE_LIMIT_PER_USER_60S=1` / `REVIEW_RATE_LIMIT_PER_TEACHER_24H=3` / `REVIEW_RATE_LIMIT_PER_USER_DAY=10`）→ 全局必关 `check_user_subscribed` →（若参与报销）报销必关 `check_user_subscribed_for_reimburse` + 资格 `is_user_reimburse_eligible_for_review` → 字段校验（rating ∈ positive/neutral/negative；6 维分 0–10；summary 长度 `REVIEW_SUMMARY_MIN_LEN`–`REVIEW_SUMMARY_MAX_LEN`；evidence 必传；参与报销则手势照必传）→ `create_teacher_review(... status='pending')` → **回流通知超管**（§14.5）。

返回 `{ "review_id": 123, "status": "pending" }`；失败返回 4xx + 结构化错误（如 `rate_limited` / `need_subscribe` 带 `missing` 列表），前端据此提示。

**前端表单要点**：6 维分用滑杆/分段控件；summary 实时字数（50–300）；intent（参与报销）选中后动态要求手势照并显示预计金额；匿名/默认两个提交按钮对应 `anonymous` 0/1。

### 14.3 收藏 / 提醒 toggle

| Endpoint | 行为 | 复用 |
|---|---|---|
| `POST /api/favorites/{id}` | toggle 幂等；**首次收藏自动开 `notify_enabled`** | [`bot/services/user_favorites.py`](../bot/services/user_favorites.py) |
| `PUT /api/favorites/{id}/notify` | 单独开/关 TA 开课提醒（不取消收藏） | 同上 |
| `GET /api/favorites?mode=all\|today` | 列表（全部 / 仅今日可约），两 mode 切换 | 同上 |

纯状态写，无需回灌图片、无需通知回流（开课通知由 bot 调度侧负责，§十七）。

### 14.4 老师资料编辑（差异化写入，保留乐观/悲观语义）

**现状关键语义**（[`bot/handlers/teacher_self.py`](../bot/handlers/teacher_self.py)）必须在 API 层原样保留：

| 字段类 | 字段 | 写入策略 |
|---|---|---|
| 文字（5） | `display_name` / `region` / `price` / `tags` / `button_text` | **立即生效** `UPDATE teachers` + `create_edit_request` + 通知管理员（审核不通过回滚） |
| 图片 | `photo_file_id` | **不动 teachers**，仅 `create_edit_request`；展示位用旧图，审核通过才切换 |
| 锁定 | `button_url` | 拒绝（`403`），提示联系管理员 |

`PATCH /api/teacher/profile`（仅 teacher 角色）：body 仅允许 `EDITABLE_FIELDS` 白名单（须与 `database.TEACHER_EDITABLE_FIELDS` 一致）；图片字段值为 §14.1 回灌的 file_id；服务端按上表分流写入 + 回流通知管理员。

### 14.5 回流通知（统一接缝）

所有写操作落库后，经**共享 bot 对象**（同进程）发通知，内容/对象复用现有逻辑：

| 写操作 | 通知对象 | 内容 |
|---|---|---|
| 提交评价 | 超管 | 去 rreview 审核；DM 带 `startapp` 直达审核台该条目 |
| 资料编辑 | 管理员 | 待审核字段 before/after；带「前往审核」入口 |

`await bot.send_message(...)` 直接调用——这正是「MiniApp 操作 → bot 推送」闭环（§四接缝）。

### 14.6 交付物 / 验收 / 不做

**交付物**：`POST /api/uploads`（file_id 回灌）、`GET /api/teachers/{id}/review-context`、`POST /api/reviews`、收藏/提醒三端点、`PATCH /api/teacher/profile`；前端 `ReviewForm.vue`、收藏页写交互、老师端资料表单。

**验收**：① MiniApp 一屏提交评价，服务端校验与 bot 侧完全一致（限频/必关/长度/必传逐项验过）；② 提交后超管照常在 bot/审核台看到 media group（证明 file_id 回灌生效）；③ 收藏 toggle 幂等、首次自动开通知；④ 资料文字字段立即生效、图片审核后切换、`button_url` 拒改；⑤ 各写操作回流通知到达。

**不做**：审核台 UI（P3）；老师档案 9 步录入（P3 后台侧）；对象存储直存（留后续纯展示图）。

### 14.7 注意

- **校验权威在服务端**：前端即时校验仅体验，绝不可省服务端复刻——内容敏感 + 限频/必关是业务红线。
- **乐观写回滚**：资料文字字段「立即生效 + 审核回滚」语义跨 MiniApp/bot 必须一致，回滚路径仍由现有审核侧负责。
- **阈值单一来源**：API 复用 `REVIEW_RATE_LIMIT_*` / `REVIEW_SUMMARY_*` 常量，不得在前端或 API 层另设阈值。

---

## 十五、P3 细化设计：后台管理台

后台是「像样的管理台」诉求的落点，三块：**审核台**（资料/评价/报销，权限最敏感）、**老师档案录入**（最大 FSM）、**运营看板**（图表）。后台仅 admin/superadmin 可达，路由与 API 双重鉴权。

### 15.1 关键依赖：审核占用锁是「同进程红利」的最大受益者

现有并发审核靠 [`bot/utils/review_claim.py`](../bot/utils/review_claim.py) 的**内存锁**（`dict + RLock`，TTL 300s，`kind` ∈ `edit_request` / `teacher_review` / `reimbursement`，与 audit `target_type` 对齐）。因 P0 定了**同进程**，MiniApp 审核 API 可**直接 import 复用这把锁**——bot 端与 MiniApp 端的审核互斥天然一致，`try_claim` / `force_claim` / `release_claim` 零改写。

> ⚠️ 强约束：该锁是单副本内存锁（文件注释已写明「多副本部署失效，应改 Redis/DB」）。**审核台因此把「拆独立 web 进程」的前置条件钉死了**：一旦要拆（§二预留），必须先把 claim 锁升级为 Redis/DB，否则 bot 与 web 两进程的审核锁互不可见。列入 §十九。

### 15.2 审核台总览

三类 pending 复用现有查询，统一审核台外壳（左列表 + 右详情 + 占用态徽标）：

| Tab | 数据 | claim kind | 现有逻辑 |
|---|---|---|---|
| 资料审核（admin） | `teacher_edit_requests` pending | `edit_request` | [`bot/handlers/admin_review.py`](../bot/handlers/admin_review.py) |
| 评价审核（超管） | `teacher_reviews` pending | `teacher_review` | [`bot/handlers/rreview_admin.py`](../bot/handlers/rreview_admin.py) |
| 报销审核（超管） | `reimbursements` pending/queued | `reimbursement` | [`bot/handlers/admin_reimburse.py`](../bot/handlers/admin_reimburse.py) |

**占用锁交互**：打开详情 → `POST /api/admin/{kind}/{id}/claim`（= `try_claim`）；成功进编辑态，失败返回 `ClaimInfo`（谁在审、何时起），前端显示「另一管理员审核中」+ 强制接管按钮 → `POST .../force-claim`（写 audit `*_force_claim` + `previous_holder`）；提交或离开 → `release_claim`。锁 TTL 300s 不变。

### 15.3 资料审核（before/after）

`GET /api/admin/edit-requests?status=pending` 列表；`GET /api/admin/edit-requests/{id}` 返回字段 before/after：

```json
{
  "id": 0, "teacher_id": 0, "teacher_username": "...",
  "field_name": "price", "old_value": "...", "new_value": "...",
  "is_photo": false,
  "claim": { "held_by": null, "held_by_name": null, "acquired_at": null }
}
```

`POST .../approve` | `POST .../reject`（reject 带可选 `reason`）。**图片字段**（`is_photo=true`）approve 时才把新 file_id 写入 `teachers`（悲观切换，与 §14.4 对偶）；新旧图都走 `/api/media`。

### 15.4 评价审核（rreview，超管）

`GET /api/admin/reviews/{id}` 返回 6 维分 + 摘要 + 半匿名签名 + **媒体**（约课截图，参与报销含手势照，均为 `/api/media/<file_id>`）+ 报销 intent + 资格预判（min_pts 门槛 / 老师价位）。

- `POST .../approve`：body 带积分套餐 `points`（预设 `+1/+3/+5/+8/+0` 或自定义）。服务端复刻：落 approved + 加分 + `notify_review_approved` 通知用户 + 发讨论群 anchor（半匿名/匿名按 `anonymous`）+ **若 `request_reimbursement=1` 联动建 `reimbursements.pending`**。
- `POST .../reject`：body 带 `reason`，4 预设（`证据不充分` / `内容违规` / `重复提交` / `评分明显不合理`）或自定义或跳过。

MiniApp 优势：通过选套餐 + 驳回选原因在一个抽屉里点完，替代 bot 的多次 callback 往返。

### 15.5 报销审核（超管）+ 口令发放

`GET /api/admin/reimbursements/{id}` 返回金额 + 关联评价 + **配额徽标**（复刻 `admin_reimburse`）：周配额 `week_used/weekly_limit`、月池 `pool_remaining`、是否有未消耗 reset voucher → 四态：`可批 / 需消耗 voucher / 周配额满需重置 / 超月池`。

- `POST .../reset-week`（二次确认）→ 发放/消耗 reset voucher（`grant` / `consume_reimbursement_reset`）。
- **口令发放流**（现 `ReimbursePayoutStates` waiting_token→confirming）→ MiniApp 收敛成单表单：`POST .../payout` body `{ "token": "支付宝口令文本" }` → 服务端预览校验 → 确认 → **口令经 bot DM 发用户** + `approve_reimbursement`（保留原 audit）。口令送达仍走 bot（§十七）。
- queued（报销关闭期产生）：`POST .../activate` 转 pending。

### 15.6 老师档案录入（最大 FSM → 后台分区表单）

现状 [`bot/handlers/teacher_profile.py`](../bot/handlers/teacher_profile.py) 9 步主路径 + 10 图相册 + 草稿（`save/load/clear_teacher_draft`，admin_id 作 PK）+ 预览 caption + 发布频道帖。MiniApp 化：

- **一屏分区表单**替代 9 步：Step 1「转发老师消息抽取 user_id/username/contact」是**纯 Telegram bot 能力**（MiniApp 拿不到转发元数据）→ 保留 bot 侧触发，抽取结果回填表单。其余字段（艺名 / basic_info / price_detail 自动派生 price+description+taboos / service_content 可跳过 / region）一屏填。
- **相册**：拖拽上传，每张走 §14.1 回灌 file_id（≤ 10 张）。
- **草稿**：前端本地草稿 + 可选 `PUT /api/admin/teachers/draft`（复用 `save_teacher_draft`），跨设备恢复。
- **预览 + 发布**：`GET .../preview`（caption 渲染）→ `POST .../publish`（发 `archive_channel_id`，bot 能力）。`button_text` 仍自动 `{region} {display_name}`。
- 维护：编辑 12 字段、相册 add/remove/replace、`POST .../sync-caption` 刷频道帖。

> 后台唯一不能纯 MiniApp 的点：「转发消息抽取」依赖 bot → 录入入口保留 bot 侧（转发 → 拿 user_id → 回 MiniApp 填档）。

### 15.7 运营看板（图表）

把现有文本指标升级为 ECharts，数据零改、复用现有 service：

| 看板 | API | 复用 | 图表 |
|---|---|---|---|
| 运营总览 | `GET /api/admin/overview` | [`bot/services/admin_overview.py`](../bot/services/admin_overview.py) `get_admin_overview_stats` | 今日签到/用户/收藏/评价数字卡 + pending 徽标 |
| 数据分析（7 日） | `GET /api/admin/analytics?window=7d` | `user_events` + `admin_audit_logs` | DAU/评价/报销趋势线 |
| 报销池 | `GET /api/admin/reimbursement-pool` | [`bot/services/reimbursement_pool.py`](../bot/services/reimbursement_pool.py) | 月池额度/已批/剩余环形图 + 周通过 |
| 审计日志 | `GET /api/admin/audit-logs?action=` | `admin_audit_logs` 分页 | 表格 + action 过滤 |

`schema_migrations` 失败迁移（hard/soft）作为健康徽标常驻顶部。

### 15.8 交付物 / 验收 / 不做

**交付物**：审核台三 Tab（claim/force-claim/release + approve/reject/payout）、档案录入分区表单 + 相册 + 预览发布、四块看板。前端 `admin/` 视图集（Naive UI 表格/抽屉/表单 + vue-echarts）。

**验收**：① 两个管理员同时打开同一条 → 占用锁正确互斥（与 bot 端共享：bot 占了 MiniApp 也提示）；② 强制接管写 audit；③ 评价通过的加分 / 讨论群 anchor / 报销联动与 bot 完全一致；④ 报销口令经 bot DM 送达 + approve；⑤ 档案发布到频道、caption 同步生效；⑥ 看板数字与 bot 端一致。

**不做**：claim 锁升级 Redis（仅独立进程化时才需，§十九）；新增看板指标（先 1:1 搬现有）。

### 15.9 注意

- **审核动作权威在服务端**：approve/reject/payout 的副作用（加分、发群、建报销、发口令）复用现有函数，API 仅编排，不重写。
- **claim 锁 = 同进程契约**：审核台正确性依赖单进程共享内存锁；拆进程前必须先升级锁。
- **超管专属**：评价 / 报销审核仅 superadmin；资料审核 admin 可做——与现有角色一致。

---

## 十六、P4 细化设计：老师端 + 全局收口

P4 收口整套迁移：补齐**老师端视图**、统一 **startapp 入口体系**、把 **bot FSM 由主路径转为降级路径**，并建立**双轨可观测性**为退役提供判据。

### 16.1 老师端视图（壳，写能力 P2 已交付）

边界澄清：老师「资料编辑」的写能力已在 §14.4（`PATCH /api/teacher/profile`，差异化写入）交付。P4 老师端只做**视图组织**——把已有能力收进一个完整老师端首页：

- **首页**：艺名 / 今日签到态 / 资料完整度（复用 `is_teacher_profile_complete`）；入口卡片 → 资料编辑（P2）、签到状态、我的评价被审情况。
- **签到状态页**：`GET /api/teacher/checkin-status` → `{ "checked_in_today": false, "deadline": "14:00", "server_time": "..." }`（截止 = `PUBLISH_TIME`）；`POST /api/teacher/checkin` 一键签到（复用 `teacher_self:checkin`，幂等：已签 / 已截止 / 已停用各自返回）。
  > 签到动作本身极简（bot 发「签到」二字最快），MiniApp 化的价值在**状态可视化**（今天签没签、几点截止），不替代 bot 文字签到——后者作为最快降级路径保留。

### 16.2 统一 startapp 入口体系

现有 `/start <param>` deep link（§七，`parse_start_args`）是 bot 通道；MiniApp 平行新增 `startapp` 通道：`t.me/<bot>/<app>?startapp=<param>` 启动时 param 经 `Telegram.WebApp.initDataUnsafe.start_param` 传入，前端路由到对应页。两通道共存：

| 场景 | bot deep link（保留） | MiniApp startapp（新增） | 落地页 |
|---|---|---|---|
| 老师详情 | `/start teacher_<id>` | `startapp=teacher_<id>` | 详情页（P1） |
| 写评价 | `/start write_<id>` | `startapp=write_<id>` | 写评价表单（P2） |
| 今日可约 | `/start today` | `startapp=today` | 今日列表（P1） |
| 搜索 | `/start search` | `startapp=search` | 搜索页（P1） |
| 来源追踪 | `/start src_*` / `campaign_*` | `startapp=src_*` | 透传 → `user_sources` 埋点 |

- **群卡片按钮**：艺名命中卡片的「🔍 私聊详情」「📝 写评价」升级为 WebApp/startapp 按钮，点开直接进 MiniApp（P1 已先行）。
- **来源追踪不丢**：startapp 来源参数同样落 `user_sources` + 画像，与现有 deep link 埋点一致。
- 前端 `tg.ts` 统一解析 `start_param`，未知值回退首页（对齐现有「deep link 异常全部吞掉」原则）。

### 16.3 bot FSM 转降级（不删，弱化）

整套迁的收口动作：MiniApp 稳定后，bot 侧 FSM 从「主路径」转「降级路径」（§六双轨策略的落地），**保留不删**：

- **私聊菜单**：各功能入口首选项改为「🚀 打开小程序」（Menu Button / WebApp 按钮）；原 FSM 按钮降为次级「或用文字版」。
- **保留 FSM 的场景**：未升级的旧客户端、签到文字快捷、群内交互（群里本就没有 MiniApp，不变）。
- **回退保障**：MiniApp 故障时 bot FSM 仍是完整可用的兜底——这是双轨保留的核心价值，不是冗余。

### 16.4 双轨可观测性 + 退役判据

为 §十九 #5「双轨退役时机」提供数据：

- 写操作（评价 / 资料 / 收藏）按入口打标 `via=miniapp|bot_fsm`，落 `user_events`；
- 看板（§15.7）加一张「MiniApp vs bot_fsm 占比」趋势；
- **退役判据**：某功能 MiniApp 占比持续 > 阈值（如 95%）且 bot FSM 连续 N 周零使用 → 评估下线该 FSM 入口（仍保留群内 / 签到）。

### 16.5 交付物 / 验收 / 不做

**交付物**：老师端首页 + 签到状态页（`GET /checkin-status`、`POST /checkin`）；`tg.ts` 的 startapp 路由 + 群卡片 WebApp 按钮；私聊菜单「打开小程序」入口；双轨埋点 + 占比看板。

**验收**：① 老师端可看签到态并一键签到（与 bot 签到互斥幂等）；② `startapp=teacher_<id>` 从群卡片点开直达详情；③ 来源参数经 startapp 正确落 `user_sources`；④ 关掉 MiniApp，bot FSM 全流程仍可用（回退验证）；⑤ 看板能看到双轨占比。

**不做**：删除任何 bot FSM（仅弱化入口）；签到改造（保留文字签到最快路径）。

### 16.6 注意

- **双轨是特性不是债**：bot FSM 作降级长期保留，回退能力是内容敏感平台的稳健性保障。
- **startapp 与 deep link 同源参数**：两通道 param 命名对齐，避免维护两套语义。
- **来源埋点一致性**：startapp 来源必须与 `/start src_*` 落同一张 `user_sources`，否则推广追踪割裂。

---

## 十七、留在 Bot 的边界

以下**不迁**，留在 bot 本体，但与 MiniApp 咬合：

- 群组关键词 / 艺名命中 / 组合搜索 / 冷却防刷屏（群里没有 MiniApp）；
- APScheduler 全部调度（每日发布 / 签到提醒 / 收藏开课通知 / 日报周报）；
- 所有 DM 通知推送（MiniApp 关闭即推不到）；
- deep link 角色分流（[`bot/handlers/start_router.py`](../bot/handlers/start_router.py)）。

**两个接缝**：① 群/DM 里用 `startapp` 按钮跳进 MiniApp；② MiniApp 写操作经 API 回流，由共享 bot 对象发出通知（如审核台动作 → bot DM 当事人）。

---

## 十八、风险与技术债清单

按优先级：

1. **图片 file_id**（P1 前必须落地媒体代理，否则富展示无从谈起）；
2. **HTTPS 入站**：从纯出站 polling 变为对公网开放入站，安全面扩大，本项目内容敏感，需严格鉴权 / 限流 / 最小暴露；
3. **SQLite 并发**：连接模型迟早要动（§十）；
4. **双轨维护成本**：FSM 与表单并存期，改业务要顾两端入口（靠「共用 service 层」压成本）；
5. **限频复用**：现有限频（60s / 24h 等）在 bot 侧，API 层必须复用同一套校验，别被绕过。

---

## 十九、开放问题 / 待决策

| # | 问题 | 备注 |
|---|---|---|
| 1 | 域名与证书方案（Let's Encrypt / Cloudflare） | 部署前定 |
| 2 | session token 形态（自签 JWT 库选型 / 密钥管理） | P0 前定 |
| 3 | 对象存储选型（本地 Nginx 静态 vs S3 兼容） | P2 前定，影响 `storage.py` |
| 4 | 媒体缓存目录的容量与清理策略 | 关联 [VPS 磁盘满事故](../docs/) 教训，需纳入 `disk_alert.sh` 监控 |
| 5 | 双轨退役时机与判据 | 上线后据 MiniApp 使用率定 |
| 6 | 审核 claim 锁升级 Redis/DB | **独立 web 进程化的前置条件**；同进程期可不动（§十五 15.1） |

---

> 下一步可继续展开：**P2（写评价表单 + 收藏/资料，FSM→表单契约与回流通知）** / **P3（后台审核台 + 档案录入 + 看板图表）** / **P0 可执行任务清单（Nginx/BotFather/证书具体步骤）**。

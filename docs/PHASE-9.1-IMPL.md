# Phase 9.1 实施指南：老师档案数据扩展 + 后台录入 FSM

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：9.1.1 / 9.1.2 / 9.1.3 / 9.1.4
> 关联 spec：[REVIEW-FEATURE-DRAFT.md §10 Phase 9.1](./REVIEW-FEATURE-DRAFT.md)
> 后续：[PHASE-9.2-IMPL.md](./PHASE-9.2-IMPL.md)（待编写）

---

## 0. 目标

- 扩展 `teachers` 表的 10 个字段（age/height/weight/bra_size/description/service_content/price_detail/taboos/contact_telegram/photo_album）
- 完整 11 步老师录入 FSM（新建必须一次走完）
- 新增 admin 子菜单 [📋 老师档案管理]：增删改 + 照片相册 + 预览
- 档案 caption 生成函数（不发频道，仅返回字符串供预览）

**不做**：
- 频道发布老师档案帖（Phase 9.2）
- 评价 / 评论区 / 报告（Phase 9.3+）
- `teacher_channel_posts` 表只建 schema，不操作

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动量 | 改动点 |
|---|---|---|
| `bot/database.py` | +200 行 | schema migration + 新方法 9-10 个 |
| `bot/states/teacher_states.py` | +20 行 | 新增 `TeacherProfileAddStates` / `TeacherProfileEditStates` |
| `bot/handlers/admin_panel.py` | +30 行 | 注入 [📋 老师档案管理] 入口 + 路由 |
| `bot/keyboards/admin_kb.py` | +80 行 | 老师管理子菜单结构调整 |
| `bot/main.py` | +2 行 | 注册新 router（如新增 handler 文件）|

### 1.2 新增文件

| 文件 | 用途 | 估算行数 |
|---|---|---|
| `bot/handlers/teacher_profile.py` | 新增老师录入 FSM + 编辑 + 相册管理 | ~400 |
| `bot/utils/teacher_profile_render.py` | caption 生成（纯函数）| ~150 |

> 注：新建 handler 而非塞进 `teacher_flow.py`，是因为 `teacher_flow.py` 已 600 行，再加 11 步会过于臃肿。新文件聚焦"完整档案"流程。

---

## 2. 数据库变更

### 2.1 Schema migration（在 `init_db` 中追加）

```python
async def _migrate_teacher_profile_columns(db: aiosqlite.Connection) -> None:
    """Phase 9.1：teachers 表添加 10 个老师档案字段（全部 NULLABLE）

    幂等：PRAGMA table_info 检测后再 ADD，重复执行安全。
    """
    cur = await db.execute("PRAGMA table_info(teachers)")
    rows = await cur.fetchall()
    existing = {row["name"] for row in rows}

    additions: list[tuple[str, str]] = [
        ("age",              "INTEGER"),
        ("height_cm",        "INTEGER"),
        ("weight_kg",        "INTEGER"),
        ("bra_size",         "TEXT"),
        ("description",      "TEXT"),
        ("service_content",  "TEXT"),
        ("price_detail",     "TEXT"),
        ("taboos",           "TEXT"),
        ("contact_telegram", "TEXT"),
        ("photo_album",      "TEXT"),  -- JSON list of file_ids
    ]
    for col, type_def in additions:
        if col in existing:
            continue
        try:
            await db.execute(f"ALTER TABLE teachers ADD COLUMN {col} {type_def}")
        except Exception:
            pass
```

`teacher_channel_posts` 表也在本 phase 创建（schema only）：

```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS teacher_channel_posts (
        teacher_id              INTEGER PRIMARY KEY,
        channel_chat_id         INTEGER NOT NULL,
        channel_msg_id          INTEGER NOT NULL,
        media_group_msg_ids     TEXT,
        discussion_chat_id      INTEGER,
        discussion_anchor_id    INTEGER,
        review_count            INTEGER DEFAULT 0,
        positive_count          INTEGER DEFAULT 0,
        neutral_count           INTEGER DEFAULT 0,
        negative_count          INTEGER DEFAULT 0,
        avg_overall             REAL DEFAULT 0,
        avg_humanphoto          REAL DEFAULT 0,
        avg_appearance          REAL DEFAULT 0,
        avg_body                REAL DEFAULT 0,
        avg_service             REAL DEFAULT 0,
        avg_attitude            REAL DEFAULT 0,
        avg_environment         REAL DEFAULT 0,
        created_at              TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at              TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE
    )
""")
```

### 2.2 新增 DB 方法

写在 `bot/database.py` 末尾 `# ============ 老师档案 (Phase 9.1) ============` 区块下。

| 方法 | 签名 | 说明 |
|---|---|---|
| `update_teacher_profile_field` | `(user_id: int, field: str, value) -> bool` | 通用单字段更新，白名单校验 |
| `add_teacher_photo` | `(user_id: int, file_id: str) -> int` | 追加照片到 album，返回新 album 长度 |
| `remove_teacher_photo` | `(user_id: int, index: int) -> bool` | 按 index 删除照片 |
| `set_teacher_photos` | `(user_id: int, file_ids: list[str]) -> bool` | 整体替换 album |
| `get_teacher_photos` | `(user_id: int) -> list[str]` | 取 album，解析 JSON；空时退化到 photo_file_id |
| `parse_basic_info` | `(text: str) -> dict \| None` | 纯函数：解析 "25 172 90 B" 为 {age, height_cm, weight_kg, bra_size} |
| `is_teacher_profile_complete` | `(user_id: int) -> tuple[bool, list[str]]` | 校验必填字段，返回 (是否完整, 缺失字段列表) |
| `get_teacher_full_profile` | `(user_id: int) -> dict \| None` | 取全字段 + 解析 album JSON |
| `count_teacher_photos` | `(user_id: int) -> int` | 用于"已上传 X/10 张" 提示 |

**必填字段白名单**（用于 `is_teacher_profile_complete`）：

```python
TEACHER_PROFILE_REQUIRED_FIELDS = [
    "display_name", "age", "height_cm", "weight_kg", "bra_size",
    "price_detail", "contact_telegram",
    "region", "price", "tags", "button_url",
    # photo_album 单独校验，要求 ≥ 1 张
]
TEACHER_PROFILE_OPTIONAL_FIELDS = [
    "description", "service_content", "taboos", "button_text",
]
TEACHER_PROFILE_EDITABLE_FIELDS = (
    set(TEACHER_PROFILE_REQUIRED_FIELDS) |
    set(TEACHER_PROFILE_OPTIONAL_FIELDS) |
    {"photo_album"}
)
```

---

## 3. FSM 设计

### 3.1 状态类（`bot/states/teacher_states.py`）

```python
class TeacherProfileAddStates(StatesGroup):
    """Phase 9.1：完整老师档案录入 FSM"""
    waiting_display_name     = State()
    waiting_basic_info       = State()  # 一行"age height weight bra"
    waiting_description      = State()  # 可跳过
    waiting_service_content  = State()  # 可跳过
    waiting_price_detail     = State()
    waiting_taboos           = State()  # 可跳过
    waiting_contact_telegram = State()
    waiting_region           = State()  # 沿用现有
    waiting_price            = State()  # 沿用现有
    waiting_tags             = State()  # 沿用现有
    waiting_button_url       = State()  # 沿用现有
    waiting_button_text      = State()  # 可跳过，沿用现有
    waiting_photos           = State()  # 接收多张图，发"完成"结束
    waiting_confirm          = State()  # 确认页


class TeacherProfileEditStates(StatesGroup):
    """Phase 9.1：单字段编辑 FSM"""
    waiting_target_teacher = State()  # 选老师
    waiting_field_choice   = State()  # 选要改的字段
    waiting_field_value    = State()  # 输入新值（state.data 存 target_user_id + field_key）
```

### 3.2 转移图

```
[/start admin → menu:teacher → menu:teacher_profile → add]
   ↓
waiting_display_name (text)
   ↓
waiting_basic_info (text 解析 4 字段)
   ↓
waiting_description (text 或 "跳过")
   ↓
waiting_service_content (text 或 "跳过")
   ↓
waiting_price_detail (text)
   ↓
waiting_taboos (text 或 "跳过")
   ↓
waiting_contact_telegram (text，必须 @ 开头)
   ↓
waiting_region (text)
   ↓
waiting_price (text)
   ↓
waiting_tags (text，空格/逗号分隔)
   ↓
waiting_button_url (text)
   ↓
waiting_button_text (text 或 "跳过")
   ↓
waiting_photos (photo × N，文字"完成"结束)
   ↓
waiting_confirm (按钮 [✅ 保存] [✏️ 修改某项] [❌ 取消])
   ↓
DB add_teacher + set_teacher_photos + 返回老师管理子菜单
```

每一步都支持 `/cancel` 退出。

### 3.3 `state.data` 字段

```python
{
    "display_name": str,
    "age": int,
    "height_cm": int,
    "weight_kg": int,
    "bra_size": str,
    "description": Optional[str],     # None if 跳过
    "service_content": Optional[str],
    "price_detail": str,
    "taboos": Optional[str],
    "contact_telegram": str,           # 含 @
    "region": str,
    "price": str,
    "tags": list[str],
    "button_url": str,
    "button_text": Optional[str],
    "photos": list[str],               # file_ids
}
```

---

## 4. UI 设计

### 4.1 菜单层级（修改 `bot/keyboards/admin_kb.py`）

```
[🔧 痴颜录管理面板]
├── [👩‍🏫 老师管理]
│   ├── [➕ 添加老师 (旧版)]          ← 沿用现有 teacher_flow.py 简版录入
│   ├── [✏️ 编辑老师 (旧版)]          ← 沿用现有
│   ├── [📋 老师档案管理]   ← Phase 9.1 新增
│   │   ├── [➕ 完整档案录入]
│   │   ├── [✏️ 编辑老师档案]
│   │   ├── [🖼 管理照片相册]
│   │   ├── [👁 预览档案 caption]
│   │   └── [🔙 返回老师管理]
│   ├── [⛔ 停用老师]
│   ├── [✅ 启用老师]
│   └── [📋 老师列表]
├── ...其他主菜单按钮不变...
```

> 设计取舍：保留旧版"简版录入"，新版"完整档案"独立入口。给 admin 灵活性。

### 4.2 [➕ 完整档案录入] 第一屏

```
📋 完整档案录入

接下来你会回答 11 道题，全部完成后保存。
- 必填项不能跳过
- 可跳过的字段直接回复"跳过"两字
- 任意一步发 /cancel 中止

[🚀 开始] [❌ 取消]
```

点 [🚀 开始] → FSM 进入 `waiting_display_name`：

```
[Step 1/11] 老师艺名

请输入老师的艺名（如：丁小夏）：
👇 直接回复
[❌ 取消]
```

### 4.3 [Step 2/11] 基本信息单行解析

```
[Step 2/11] 基本信息

请用一行回复年龄、身高、体重、罩杯，空格分隔：
例如：25 172 90 B
👇 直接回复
[❌ 取消]
```

解析失败时（数字越界 / 格式不对 / bra 非字母）→ 给具体错误提示并停留。

```python
def parse_basic_info(text: str) -> Optional[dict]:
    parts = text.strip().split()
    if len(parts) != 4:
        return None
    try:
        age = int(parts[0])
        height = int(parts[1])
        weight = int(parts[2])
        bra = parts[3].strip().upper()
    except ValueError:
        return None
    if not (15 <= age <= 60): return None
    if not (140 <= height <= 200): return None
    if not (35 <= weight <= 120): return None
    if not (1 <= len(bra) <= 3 and bra.isalpha()): return None
    return {
        "age": age,
        "height_cm": height,
        "weight_kg": weight,
        "bra_size": bra,
    }
```

### 4.4 [Step 13/11] 照片上传交互

```
[Step 13/11] 上传照片相册

请发送 1-10 张图片（每发一张回复一次进度）。
全部发送完后，回复"完成"结束。
当前已上传：0/10
[❌ 取消]
```

每收到一张图：
- 累加 `state.data["photos"]`
- 回复 "✅ 已收到，当前 X/10"

收到"完成"文字：
- 校验：`len(photos) >= 1`，否则提示"至少上传 1 张"
- 进入 `waiting_confirm`

### 4.5 确认页（详见 spec §2.4 已有规范）

```
你的档案预览：

👤 丁小夏
📋 25 岁 · 172cm · 90kg · 胸 D
📋 描述：温柔可爱...
📋 服务：包夜 ¥3000...
💰 价格详述：包夜 3000 ¥
🚫 禁忌：...
☎ 联系电报：@xxxxx
📍 地区：天府一街
💰 价格（排序）：3000P
🏷 标签：#御姐 #高颜值
🔗 跳转链接：https://t.me/xxx
🔠 按钮文字：联系我

📸 已上传 5 张照片

[✅ 保存到 DB]
[✏️ 修改：艺名] [✏️ 修改:基本信息]
[✏️ 修改：描述] [✏️ 修改:服务]
...（每个字段一个修改按钮）
[❌ 取消]
```

[✅ 保存到 DB] → `add_teacher(data)` + `set_teacher_photos(user_id, photos)` → 提示成功 + 返回 [📋 老师档案管理]

### 4.6 [✏️ 编辑老师档案] 流程

```
[Step 1] 选择要编辑的老师
[列出最多 20 位老师，按 created_at DESC]
  [丁小夏] [小桃]
  [雨馨] [晚柠]
  ...
  [🔙 返回]

[Step 2] 选择要编辑的字段
（点选老师后）
  [✏️ 艺名]      [✏️ 基本信息]
  [✏️ 描述]      [✏️ 服务]
  [✏️ 价格详述]  [✏️ 禁忌]
  [✏️ 联系电报]  [✏️ 地区]
  [✏️ 价格(排序)] [✏️ 标签]
  [✏️ 跳转链接]  [✏️ 按钮文字]
  [🔙 返回]

[Step 3] 输入新值
（按字段类型走对应 FSM 状态）

[Step 4] 确认 → DB update_teacher_profile_field → 返回 Step 2
```

### 4.7 [🖼 管理照片相册] 流程

```
[Step 1] 选择老师 → [Step 2] 显示当前照片
  当前相册（5 张）：
  1. [photo preview thumb]
  2. [photo preview thumb]
  ...
  [➕ 添加照片]  [❌ 删除照片]
  [🔄 整体替换] [🔙 返回]

➕ 添加：等待图片 → append + 回到 Step 2
❌ 删除：选 index 1-N → 删除 + 回到 Step 2
🔄 替换：要求按 1-10 张顺序发，"完成"结束 → 替换
```

> 实现注意：display thumb 需要 bot 单独 send_photo（媒体组不能 inline 预览）。或者按"列表+索引"展示文字，不发 thumb。**首期建议文字列表 + 操作按钮，不发缩略图（避免刷屏）。**

### 4.8 [👁 预览档案 caption]

```
[Step 1] 选择老师 → 输出 caption 文字 + 提示是否能发布

调用 teacher_profile_render.render_teacher_channel_caption(teacher, stats=None)
  → 返回 caption 字符串
判断 is_teacher_profile_complete(user_id) → 标注"✅ 必填齐备，可发布频道（Phase 9.2 启用）" 或
  "⚠️ 缺以下必填字段：xxx / yyy（先补全后才能发频道）"

输出格式：
─── 档案 caption 预览 ───
👤 丁小夏

25 岁 · 172cm · 90kg · 胸 D
...

📊 0 条车评，综合评分 0.00
好评 ----  | 人照 ----  | 服务 ----
中评 ----  | 颜值 ----  | 态度 ----
差评 ----  | 身材 ----  | 环境 ----

☎ 联系方式
电报：@xxxxx

🏷 #御姐 #高颜值 #...

✳ Powered by @ChiYanBookBot
───────────────────
✅ 必填齐备，可发布频道（待 Phase 9.2 启用）

[🔙 返回]
```

---

## 5. caption 渲染（`bot/utils/teacher_profile_render.py`）

### 5.1 函数签名

```python
def render_teacher_channel_caption(
    teacher: dict,
    stats: Optional[dict] = None,
    bot_username: str = "ChiYanBookBot",
) -> str:
    """生成老师档案帖的 caption（spec §6.1 + 附录 D）

    Args:
        teacher: get_teacher_full_profile 返回的字典
        stats:   teacher_channel_posts 行（含 review_count/avg_overall/六维 avg 等）；
                 None 表示"暂无评价"，统计块用占位符
        bot_username: footer 显示用

    Returns:
        caption 字符串（< 1024 字符，含截断逻辑）

    截断优先级（超长时按顺序删除）：
        1. taboos（保留前 100 字 + ...）
        2. service_content（保留前 200 字 + ...）
        3. price_detail（保留前 100 字 + ...）
        4. description（保留前 80 字 + ...）
        5. 标签（最多 20 个，超出截断）
    """
```

### 5.2 占位符规则（spec 已定）

```python
def _format_stats_block(stats: Optional[dict]) -> str:
    if stats is None or stats.get("review_count", 0) == 0:
        return (
            "📊 0 条车评，综合评分 0.00\n"
            "好评 ----  | 人照 ----  | 服务 ----\n"
            "中评 ----  | 颜值 ----  | 态度 ----\n"
            "差评 ----  | 身材 ----  | 环境 ----"
        )
    rc = stats["review_count"]
    pos_pct = stats["positive_count"] / rc * 100
    neu_pct = stats["neutral_count"] / rc * 100
    neg_pct = stats["negative_count"] / rc * 100
    return (
        f"📊 {rc} 条车评，综合评分 {stats['avg_overall']:.2f}\n"
        f"好评 {pos_pct:>5.1f}% | 人照 {stats['avg_humanphoto']:>5.2f} | 服务 {stats['avg_service']:>5.2f}\n"
        f"中评 {neu_pct:>5.1f}% | 颜值 {stats['avg_appearance']:>5.2f} | 态度 {stats['avg_attitude']:>5.2f}\n"
        f"差评 {neg_pct:>5.1f}% | 身材 {stats['avg_body']:>5.2f} | 环境 {stats['avg_environment']:>5.2f}"
    )
```

### 5.3 缺字段处理

| 字段 | 缺失时 |
|---|---|
| `description` | 整段省略（连"📋"标题也不渲染）|
| `service_content` | 整段省略 |
| `taboos` | 整段省略 |
| `button_text` | caption 不含，按钮也不显示该字段 |
| `tags` 空 | 标签段省略 |
| **必填字段缺** | render 抛 `ValueError`，告知缺哪个字段；UI 层 catch 后显示错误 |

---

## 6. 实施顺序（4 次 commit）

### Commit 1: DB 层（约 250 行）

**改动文件**：
- `bot/database.py`：schema migration + `teacher_channel_posts` 表 + 9 个新方法 + 配置常量

**验收：**
- `python3 -m compileall bot` 通过
- 在 `/tmp/test.db` 上跑：
  - 老 teachers 数据迁移后新字段都为 NULL
  - 新方法 happy path 全通过
  - `is_teacher_profile_complete` 边界（全空 / 部分缺 / 齐备）

**commit 信息**：
```
feat: Phase 9.1.1 teachers 表扩展 10 字段 + teacher_channel_posts 表 + 9 个 DB 方法

- ALTER TABLE 增加 age/height_cm/weight_kg/bra_size/description/service_content/
  price_detail/taboos/contact_telegram/photo_album（全部 NULLABLE）
- 新建 teacher_channel_posts 表（schema only, 待 Phase 9.2 使用）
- 新方法：update_teacher_profile_field / add_teacher_photo / remove_teacher_photo /
  set_teacher_photos / get_teacher_photos / parse_basic_info /
  is_teacher_profile_complete / get_teacher_full_profile / count_teacher_photos
```

---

### Commit 2: FSM + 渲染工具（约 550 行）

**改动文件**：
- `bot/states/teacher_states.py`：2 个新 StatesGroup
- `bot/handlers/teacher_profile.py`（新）：完整 FSM + 注册函数
- `bot/utils/teacher_profile_render.py`（新）：caption 渲染
- `bot/main.py`：注册 router

**验收：**
- compileall 通过
- 端到端：从 admin 触发 → 11 步走完 → confirm 页正确 → DB 写入成功
- 边界：每步发不合法输入都能停留 + 提示
- `/cancel` 任意步退出

**commit 信息**：
```
feat: Phase 9.1.2 完整老师档案录入 FSM (11 步)

新 FSM TeacherProfileAddStates：
- 11 步从 display_name 走到 photos
- 必填字段强校验；可选字段支持"跳过"
- /cancel 全程可退出
新工具 bot/utils/teacher_profile_render.py：
- render_teacher_channel_caption（含统计块占位 + 字段截断）
```

---

### Commit 3: Admin 菜单 + 编辑/相册子流程（约 350 行）

**改动文件**：
- `bot/keyboards/admin_kb.py`：[📋 老师档案管理] 子菜单 + 相册管理键盘
- `bot/handlers/admin_panel.py`：路由新 callback
- `bot/handlers/teacher_profile.py`：补充编辑 FSM + 相册管理

**验收：**
- 主面板能进入 [📋 老师档案管理]
- 编辑：选老师 → 改字段 → 校验通过 → DB 更新
- 相册：选老师 → 增 / 删 / 替换照片 → DB 更新
- 旧的 [➕ 添加老师]（简版）仍可用，不受影响

**commit 信息**：
```
feat: Phase 9.1.3 [📋 老师档案管理] 子菜单 + 字段编辑 + 相册管理

主面板 → 老师管理 → [📋 老师档案管理]：
- ➕ 完整档案录入（已实现于 9.1.2）
- ✏️ 编辑老师档案（按字段单选 + 编辑 FSM）
- 🖼 管理照片相册（增 / 删 / 整体替换）
- 👁 预览档案 caption
旧的简版录入 [➕ 添加老师] 保持兼容，不删除。
```

---

### Commit 4: 预览 + 收尾（约 150 行）

**改动文件**：
- `bot/handlers/teacher_profile.py`：预览 callback
- `docs/PHASE-9.1-IMPL.md`：标记完成
- 任何 bug 修复

**验收：**
- 选老师 → [👁 预览档案 caption] → 输出格式正确
- 必填齐备的老师：显示 "✅ 可发布"
- 必填不齐备的老师：列出缺失字段
- `python3 -m compileall bot` + 真实 bot 走一遍完整流程

**commit 信息**：
```
feat: Phase 9.1.4 档案 caption 预览 + Phase 9.1 收尾

- [👁 预览档案 caption] 按钮：调 render_teacher_channel_caption 输出
- 必填字段齐备性提示
- compileall + 端到端测试通过

至此 Phase 9.1 全部完成。Phase 9.2 将基于此开始频道发布闭环。
```

---

## 7. 验收清单

### 7.1 DB 层
- [ ] teachers 表新增 10 列，老数据全为 NULL，未影响现有功能
- [ ] teacher_channel_posts 表已建（待 9.2 使用）
- [ ] 9 个新方法在 `/tmp/test.db` 跑通 happy path
- [ ] `is_teacher_profile_complete` 准确返回缺失字段列表
- [ ] `parse_basic_info` 处理边界（年龄/身高/体重越界、字母数字混用）

### 7.2 FSM 层
- [ ] 11 步完整走通 → DB 写入成功
- [ ] 必填字段非法输入 → 停留 + 提示
- [ ] 可跳过字段回复"跳过" → 进下一步且 DB 存 NULL
- [ ] photos 上传：发非图片 → 拒绝；发 1 张 → 累加；"完成" → 进确认页
- [ ] 确认页修改某项 → 跳回对应步 → 改完返回确认页
- [ ] `/cancel` 任意步退出

### 7.3 管理菜单
- [ ] 主面板 [👩‍🏫 老师管理] → [📋 老师档案管理] 可进入
- [ ] 旧的 [➕ 添加老师 (简版)] 仍可用
- [ ] 编辑老师档案：选老师 → 改字段 → 入库
- [ ] 相册管理：增 / 删 / 替换照片，count_teacher_photos 准确

### 7.4 caption 渲染
- [ ] render_teacher_channel_caption 输出符合 spec 附录 D
- [ ] 无评价时统计块显示 `----` 占位符
- [ ] 描述/服务/禁忌 缺失时整段省略
- [ ] 标签段空时省略
- [ ] caption 超 1024 字符时按优先级截断

### 7.5 兼容性
- [ ] 现有 75 老师数据完全不动
- [ ] daily 14:00 频道发布、群组关键词响应、收藏、签到等老功能均正常
- [ ] 旧 callback (menu:teacher:add 等) 仍工作

### 7.6 静态检查
- [ ] `python3 -m compileall bot` 通过
- [ ] 14 个核心 modules 都能 `import` 成功
- [ ] 服务器 `./update.sh` 完整跑通

---

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 现有 75 老师 photo_file_id 字段单图 → photo_album 空 | 高 | 9.2 发档案帖时该老师没相册 | photo_album 空时回退取 photo_file_id 作单图相册（在 `get_teacher_photos` 内处理） |
| FSM 11 步过长，admin 中途退出多 | 中 | admin 录入体验差 | 每步提示进度 (`Step X/11`)，最后 `/cancel` 可重启 |
| 单字段编辑容易破坏数据完整性 | 中 | 误删 / 字符串覆盖 | DB 层 `update_teacher_profile_field` 白名单 + 类型校验 |
| 相册管理 UX 复杂 | 低 | admin 用不来 | 首期不发 thumb，仅文字 + index 操作 |
| caption 超 1024 字符 | 低 | Telegram 拒收 | 截断逻辑 + 单元测试边界 |
| 数据迁移在线上跑失败 | 低 | bot 启动失败 | PRAGMA 检测 + try/except 包裹 ALTER |

---

## 9. 不在本 Phase 范围

明确**不做**的事情（避免范围蔓延）：

- ❌ 频道发布老师档案帖（Phase 9.2）
- ❌ teacher_channel_posts 数据维护（仅建表）
- ❌ 评价 / 评论区 / 报告任何相关功能
- ❌ 老师批量导入（如果有 75 老师需要批量录入，单独工具）
- ❌ 老师档案的导出 / 备份
- ❌ 修改老师 user_id（teacher 的 PK，不允许改）

---

## 10. 时间估算

| 工作项 | 估算 |
|---|---|
| Commit 1 DB 层 | 1-2 小时 |
| Commit 2 FSM + 渲染 | 2-3 小时 |
| Commit 3 菜单 + 编辑 + 相册 | 2-3 小时 |
| Commit 4 预览 + 收尾 | 0.5-1 小时 |
| 端到端测试 + 修复 | 1 小时 |
| **总计** | **6.5-10 小时** |

---

## 11. 完成后

Phase 9.1 完成后立即开 [PHASE-9.2-IMPL.md](./PHASE-9.2-IMPL.md)，实施频道档案帖发布闭环。

> 💡 Phase 9.2 开始前需要确认：
> - 公示频道 chat_id（已配置在 `publish_target_chat_ids`，沿用）
> - 频道是否绑定了讨论群（spec §6.3 前置条件）
> - 讨论群 chat_id（需要新建配置项 `discussion_chat_id`）

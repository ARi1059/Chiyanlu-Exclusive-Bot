"""普通用户私聊菜单的 inline keyboards（v2 §2.5 C1 私聊冷启动 + Phase 2 详情页）"""

from typing import Callable, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.utils.url import normalize_url


# ============ UX-3 第二批：teacher:view 来源感知 helper ============
#
# 设计：
#   旧 callback：teacher:view:<id>
#   新 callback：teacher:view:<id>:from:<source>  （source 在白名单内）
#
#   cb_teacher_view 一律走 parse_teacher_view_callback 解析；
#   产生 callback 的 kb / handler 走 format_teacher_view_callback；
#   teacher_detail_kb 根据 source 渲染对应"返回 X"按钮，未知 source 回退 main。
#
#   白名单严格限制——任意字符串都不会被当作有效 source 使用。

TEACHER_VIEW_SOURCES: frozenset[str] = frozenset({
    "main", "hot", "today", "filter",
    "search", "history", "recent", "favorites", "similar",
})

# (按钮文案, 返回 callback) — 详情页底部"返回 X"按钮配置
_BACK_BUTTON_BY_SOURCE: dict[str, tuple[str, str]] = {
    "main":      ("🔙 返回主菜单",   "user:main"),
    "hot":       ("🔙 返回热门推荐", "user:hot"),
    "today":     ("🔙 返回今日可约", "user:today"),
    "filter":    ("🔙 返回条件筛选", "user:filter"),
    "search":    ("🔙 返回搜索",     "user:search"),
    "history":   ("🔙 返回搜索历史", "user:search_history"),
    "recent":    ("🔙 返回最近看过", "user:recent"),
    "favorites": ("🔙 返回我的收藏", "user:favorites"),
    # similar 比较特殊：相似推荐点击其它老师后的详情页，本批不引入"返回相似"
    # 返回按钮——直接回退主菜单，避免造成跨老师对比链回环
    "similar":   ("🔙 返回主菜单",   "user:main"),
}


def format_teacher_view_callback(teacher_id: int, source: str = "main") -> str:
    """生成 teacher:view callback 字符串。

    - source 在白名单内且非 "main" → "teacher:view:<id>:from:<source>"
    - source 为 "main" 或不在白名单 → "teacher:view:<id>"（与旧格式完全一致）

    旧调用方传 source="main" 或不传，得到的字符串与旧格式逐字相同；新调用方
    传业务来源得到带 source 的格式。
    """
    if source != "main" and source in TEACHER_VIEW_SOURCES:
        return f"teacher:view:{teacher_id}:from:{source}"
    return f"teacher:view:{teacher_id}"


def parse_teacher_view_callback(data: str) -> tuple[int, str]:
    """解析 teacher:view callback 字符串，返回 (teacher_id, source)。

    支持两种格式：
        teacher:view:<id>               → (id, "main")
        teacher:view:<id>:from:<src>    → (id, src) if src ∈ TEACHER_VIEW_SOURCES else (id, "main")

    source 不在白名单时回退 "main"；teacher_id 解析失败抛 ValueError，由
    cb_teacher_view 兜底（保留与旧实现一致的失败语义）。
    """
    prefix = "teacher:view:"
    if not data.startswith(prefix):
        raise ValueError(f"不是 teacher:view callback: {data!r}")
    rest = data[len(prefix):]
    parts = rest.split(":from:", 1)
    teacher_id = int(parts[0])  # 旧实现同样直接 int()，失败语义一致
    source = parts[1] if len(parts) == 2 else "main"
    if source not in TEACHER_VIEW_SOURCES:
        source = "main"
    return teacher_id, source


# ============ 用户主菜单 ============

def user_main_menu_kb() -> InlineKeyboardMarkup:
    """普通用户私聊主菜单

    布局：
        [🔎 找老师]                       ← UX-3 第一批新增独占首行（聚合 4 个找老师入口）
        [📚 今天能约谁] [🎯 帮我推荐]
        [🔎 按条件找]   [🔥 热门推荐]
        [⭐ 我的收藏]   [🕘 最近看过]
        [🔍 直接搜索]   [💝 收藏开课]
        [🔔 我的提醒]   [📜 搜索历史]
        [💰 我的积分]   [🧾 我的报销]
        [📝 写评价]                       ← 2026-05-18 新增独占一行

    UX-3 第一批（2026-05）：新增「🔎 找老师」聚合入口（user:find），点击进入
    二级页（user_find_kb）含 热门 / 今日 / 按条件找 / 搜索历史 四个入口；
    旧 4 个 callback（user:hot / user:today / user:filter / user:search_history）
    在主菜单原位完全保留，进入双跑观察期。

    callback 复用既有命名空间。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔎 找老师", callback_data="user:find"),
        ],
        [
            InlineKeyboardButton(text="📚 今天能约谁", callback_data="user:today"),
            InlineKeyboardButton(text="🎯 帮我推荐", callback_data="user:recommend"),
        ],
        [
            InlineKeyboardButton(text="🔎 按条件找", callback_data="user:filter"),
            InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot"),
        ],
        [
            InlineKeyboardButton(text="⭐ 我的收藏", callback_data="user:favorites"),
            InlineKeyboardButton(text="🕘 最近看过", callback_data="user:recent"),
        ],
        [
            InlineKeyboardButton(text="🔍 直接搜索", callback_data="user:search"),
            InlineKeyboardButton(text="💝 收藏开课", callback_data="user:fav_today"),
        ],
        [
            InlineKeyboardButton(text="🔔 我的提醒", callback_data="user:reminders"),
            InlineKeyboardButton(text="📜 搜索历史", callback_data="user:search_history"),
        ],
        [
            InlineKeyboardButton(text="💰 我的积分", callback_data="user:points"),
            InlineKeyboardButton(text="🧾 我的报销", callback_data="user:reimburse"),
        ],
        [
            InlineKeyboardButton(text="📝 写评价", callback_data="user:write_review"),
            InlineKeyboardButton(text="🎁 抽奖中心", callback_data="user:lottery"),
        ],
    ])


# ============ 抽奖中心（UX-6.1） ============


def user_lottery_menu_kb(
    *, active_count: int, joined_count: int, drawn_count: int,
) -> InlineKeyboardMarkup:
    """「🎁 抽奖中心」二级菜单（UX-6.1）。

    三个 tab 入口（角标显示 count；count=0 时仍显示，避免按钮"消失"）：
        - 🎲 进行中可参与   user:lottery:active
        - 📋 我已参与       user:lottery:joined
        - 🏆 已开奖记录     user:lottery:drawn
    + 返回主菜单
    """
    def _badge(n: int) -> str:
        return f" ({n})" if n > 0 else ""

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🎲 进行中可参与{_badge(active_count)}",
            callback_data="user:lottery:active",
        )],
        [InlineKeyboardButton(
            text=f"📋 我已参与{_badge(joined_count)}",
            callback_data="user:lottery:joined",
        )],
        [InlineKeyboardButton(
            text=f"🏆 已开奖记录{_badge(drawn_count)}",
            callback_data="user:lottery:drawn",
        )],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def user_lottery_back_kb() -> InlineKeyboardMarkup:
    """抽奖中心 tab 页底部返回按钮（仅"返回抽奖中心"）。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回抽奖中心", callback_data="user:lottery")],
    ])


def user_find_kb() -> InlineKeyboardMarkup:
    """UX-3 第一批：「🔎 找老师」二级页 keyboard。

    聚合 4 个找老师入口（仅复用既有 callback，不引入新 callback）：

        🔥 热门推荐   → user:hot              当前热门老师
        📚 今天能约谁 → user:today            今日可约老师
        🔎 按条件找   → user:filter           地区 / 价格 / 标签筛选
        📜 搜索历史   → user:search_history   快速复用最近搜索

    返回按钮：⬅️ 返回主菜单 → user:main

    刻意不收纳的入口（保留在主菜单一级位置）：
        - ⭐ 我的收藏 / 🕘 最近看过       留存类，不应藏入二级
        - 🔍 直接搜索                       最直觉入口，不应藏入二级
        - 🎯 帮我推荐 / 💝 收藏开课         与找老师互补，本批不动
        - 🔔 我的提醒                       个人通知类，与找老师无关

    本 keyboard 仅做聚合视图，不引入新业务逻辑；4 个收纳 callback 仍由
    各自原 handler 处理（user:hot / user:today / user:filter / user:search_history）。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot"),
            InlineKeyboardButton(text="📚 今天能约谁", callback_data="user:today"),
        ],
        [
            InlineKeyboardButton(text="🔎 按条件找", callback_data="user:filter"),
            InlineKeyboardButton(text="📜 搜索历史", callback_data="user:search_history"),
        ],
        [
            InlineKeyboardButton(text="⬅️ 返回主菜单", callback_data="user:main"),
        ],
    ])


def user_points_menu_kb() -> InlineKeyboardMarkup:
    """积分页按钮组（Phase P.2，spec §2.2）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 积分明细", callback_data="user:points:list")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def user_reimburse_menu_kb(
    *, contact_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """报销页按钮组（UX-6.4：可选附「📩 联系客服申诉」URL 按钮）。

    Args:
        contact_url: 申诉客服 URL（caller 应通过
            `bot.utils.reimburse_notify.get_reimburse_contact_url()` 预查）；
            None / 空 → 不显示申诉按钮（避免死链）。
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📋 报销明细", callback_data="user:reimburse:list")],
    ]
    if contact_url:
        rows.append([InlineKeyboardButton(text="📩 联系客服申诉", url=contact_url)])
    rows.append([InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_reimburse_pagination_kb(
    page: int, total_pages: int,
    *, contact_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """报销明细分页（UX-6.4：可选附「📩 联系客服申诉」URL 按钮）。

    Args:
        contact_url: 同 user_reimburse_menu_kb，None 时不显示申诉按钮。
    """
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️ 上一页",
            callback_data=f"user:reimburse:list:{page - 1}",
        ))
    nav.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{max(1, total_pages)}",
        callback_data="noop:reimburse_page",
    ))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(
            text="➡️ 下一页",
            callback_data=f"user:reimburse:list:{page + 1}",
        ))
    rows: list[list[InlineKeyboardButton]] = [nav]
    if contact_url:
        rows.append([InlineKeyboardButton(text="📩 联系客服申诉", url=contact_url)])
    rows.append([InlineKeyboardButton(text="🔙 返回报销", callback_data="user:reimburse")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def onboarding_kb() -> InlineKeyboardMarkup:
    """Phase 7.1：新手引导按钮组（仅普通用户首次 /start 时展示）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 今日开课", callback_data="user:onboarding:today")],
        [InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:onboarding:hot")],
        [InlineKeyboardButton(text="🔍 直接搜索", callback_data="user:onboarding:search")],
        [InlineKeyboardButton(text="进入主菜单", callback_data="user:onboarding:main")],
    ])


# ============ 子菜单通用按钮 ============

def back_to_user_main_kb() -> InlineKeyboardMarkup:
    """单按钮：返回用户主菜单（v2 §2.5.4 所有子菜单都需要）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def search_cancel_kb() -> InlineKeyboardMarkup:
    """搜索引导：取消按钮（用户也可以发送 /cancel 退出）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def my_favorites_kb(favorites: list[dict]) -> InlineKeyboardMarkup:
    """"我的收藏"列表 keyboard（Phase 2：老师按钮进入详情页）

    每行：[老师名 · 地区 · 价格] [❌]
        · 老师按钮：进入 teacher:view:<id> 详情页（不再直接跳 URL）
        · ❌ 按钮：fav:rm_from_list:<teacher_id>，favorite handler 接住后取消并刷新列表
    末尾：[🔙 返回主菜单]

    Args:
        favorites: 已收藏老师列表（含 teachers 表全部字段）
    """
    rows: list[list[InlineKeyboardButton]] = []
    for t in favorites:
        label = f"{t['display_name']} · {t['region']} · {t['price']}"
        teacher_btn = InlineKeyboardButton(
            text=label,
            # UX-3 第二批：附带 from:favorites，详情页"返回"指向我的收藏
            callback_data=format_teacher_view_callback(t["user_id"], "favorites"),
        )
        rm_btn = InlineKeyboardButton(
            text="❌",
            callback_data=f"fav:rm_from_list:{t['user_id']}",
        )
        rows.append([teacher_btn, rm_btn])

    rows.append([
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============ 老师详情页 / 列表（Phase 2） ============


def review_cancelled_kb(teacher_id: Optional[int] = None) -> InlineKeyboardMarkup:
    """评价取消后的恢复键盘

    有 teacher_id（FSM 进到了 ReviewSubmit 阶段，已知评价对象）：
        [📋 返回老师详情页] [📝 重新写评价]
        [🔙 返回主菜单]

    无 teacher_id（仅 WriteReviewLookup 阶段就被取消）：
        [📝 重新写评价] [🔙 返回主菜单]
    """
    rows: list[list[InlineKeyboardButton]] = []
    if teacher_id is not None:
        rows.append([
            InlineKeyboardButton(
                text="📋 返回老师详情页",
                callback_data=f"teacher:view:{teacher_id}",
            ),
            InlineKeyboardButton(
                text="📝 重新写评价",
                callback_data="user:write_review",
            ),
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                text="📝 重新写评价",
                callback_data="user:write_review",
            ),
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def teacher_detail_kb(
    teacher: dict,
    *,
    is_favorited: bool,
    notify_enabled: bool = True,
    review_count: int = 0,
    source: str = "main",
) -> InlineKeyboardMarkup:
    """老师详情页按钮组（Phase 9.6：5 行布局；UX-3 第二批：返回按钮按来源切换）

    布局：
        [📩 联系老师]                              ← button_url 有效时显示
        [⭐ 收藏 / ✅ 已收藏，点击取消] [🔔/🔕 提醒按钮]
        [📖 查看全部评价 (N)]                       ← review_count > 0 时显示（9.6）
        [✨ 相似推荐]
        [📝 写评价]                                 ← 9.3 已加
        [🔙 返回 X]                                 ← UX-3 第二批：X 随 source 切换

    提醒按钮 3 态（Phase 7.3 §四）：
        - 未收藏              → "🔔 TA 开课提醒"
        - 已收藏 + notify=1   → "🔔 已开启提醒"
        - 已收藏 + notify=0   → "🔕 提醒已关闭，点击开启"

    UX-3 第二批：source 参数（默认 "main"）决定底部返回按钮：
        source=hot       → "🔙 返回热门推荐"     user:hot
        source=today     → "🔙 返回今日可约"     user:today
        source=filter    → "🔙 返回条件筛选"     user:filter
        source=search    → "🔙 返回搜索"         user:search
        source=history   → "🔙 返回搜索历史"     user:search_history
        source=recent    → "🔙 返回最近看过"     user:recent
        source=favorites → "🔙 返回我的收藏"     user:favorites
        source=similar / main / 未知 → "🔙 返回主菜单"  user:main

    收藏 / 写评价 / 相似推荐等其它按钮 callback 完全不变。
    """
    teacher_id = teacher["user_id"]
    fav_text = "✅ 已收藏，点击取消" if is_favorited else "⭐ 收藏"

    if not is_favorited:
        remind_text = "🔔 TA 开课提醒"
    elif notify_enabled:
        remind_text = "🔔 已开启提醒"
    else:
        remind_text = "🔕 提醒已关闭，点击开启"

    rows: list[list[InlineKeyboardButton]] = []

    # 第一行：联系老师
    url = normalize_url(teacher["button_url"])
    if url:
        button_text = teacher.get("button_text") or teacher["display_name"]
        rows.append([InlineKeyboardButton(
            text=f"📩 联系 {button_text}",
            url=url,
        )])

    # 第二行：收藏切换 + 开课提醒
    rows.append([
        InlineKeyboardButton(
            text=fav_text,
            callback_data=f"teacher:toggle_fav:{teacher_id}",
        ),
        InlineKeyboardButton(
            text=remind_text,
            callback_data=f"teacher:remind:{teacher_id}",
        ),
    ])

    # 查看全部评价 (Phase 9.6) —— 仅在已有评价时显示
    if review_count and review_count > 0:
        rows.append([
            InlineKeyboardButton(
                text=f"📖 查看全部评价 ({review_count})",
                callback_data=f"teacher:reviews:{teacher_id}",
            ),
        ])

    # 相似推荐
    rows.append([
        InlineKeyboardButton(
            text="✨ 相似推荐",
            callback_data=f"teacher:similar:{teacher_id}",
        ),
    ])

    # 写评价 (Phase 9.3)
    rows.append([
        InlineKeyboardButton(
            text="📝 写评价",
            callback_data=f"review:start:{teacher_id}",
        ),
    ])

    # 返回按钮（UX-3 第二批：按 source 渲染）
    back_text, back_cb = _BACK_BUTTON_BY_SOURCE.get(
        source, _BACK_BUTTON_BY_SOURCE["main"],
    )
    rows.append([InlineKeyboardButton(text=back_text, callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def teacher_detail_list_kb(
    teachers: list[dict],
    *,
    per_row: int = 1,
    label_fn: Optional[Callable[[dict], str]] = None,
    extra_back_buttons: Optional[list[list[InlineKeyboardButton]]] = None,
    source: str = "main",
) -> InlineKeyboardMarkup:
    """老师列表 keyboard：每个按钮进入 teacher:view 详情页

    Args:
        teachers: 老师 dict 列表
        per_row: 每行多少个老师按钮（默认 1）
        label_fn: 自定义按钮文案，默认为 display_name
        extra_back_buttons: 自定义返回按钮行；默认仅一行"🔙 返回主菜单"
        source: UX-3 第二批—— 列表的"业务来源"，决定每个老师 callback 是否
                附带 ":from:<source>" 后缀；source="main"（默认）与旧格式一致。
                调用方按入口语义传值：搜索结果 → "search"；热门 → "hot"；
                今日 → "today"；条件筛选 → "filter"；最近 → "recent"；收藏 → "favorites"。
    """
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for t in teachers:
        label = label_fn(t) if label_fn else t["display_name"]
        row.append(InlineKeyboardButton(
            text=label,
            callback_data=format_teacher_view_callback(t["user_id"], source),
        ))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if extra_back_buttons:
        rows.extend(extra_back_buttons)
    else:
        rows.append([
            InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recent_views_kb(views: list[dict]) -> InlineKeyboardMarkup:
    """最近浏览列表 keyboard（Phase 2）

    每行一位老师，文案 `{display_name} · {region} · {price}`，点击进 teacher:view 详情页。
    """
    return teacher_detail_list_kb(
        views,
        per_row=1,
        label_fn=lambda t: f"{t['display_name']} · {t['region']} · {t['price']}",
    )


def recent_views_rich_kb(items: list) -> InlineKeyboardMarkup:
    """最近看过增强版 keyboard（用户留存 Sprint）

    每位老师一行 [查看详情 #N（艺名）]，callback 复用 teacher:view:<id>。
    末尾两行：刷新 / 返回主菜单。

    Args:
        items: list[RecentTeacherViewItem] —— 用 list 类型注释而不绑 service 内
               dataclass，避免 keyboards 反向依赖 services。
    """
    rows: list[list[InlineKeyboardButton]] = []
    for i, it in enumerate(items, start=1):
        # 兼容 dict 与 dataclass —— attrgetter 失败时回退到 dict.get
        teacher_id = getattr(it, "teacher_id", None) or it.get("teacher_id")
        display_name = getattr(it, "display_name", None) or it.get("display_name") or "老师"
        label = f"📋 #{i} {display_name}"
        if len(label) > 40:
            label = label[:39] + "…"
        rows.append([InlineKeyboardButton(
            text=label,
            # UX-3 第二批：附带 from:recent，详情页"返回"指向最近看过
            callback_data=format_teacher_view_callback(teacher_id, "recent"),
        )])
    rows.append([
        InlineKeyboardButton(text="🔄 刷新", callback_data="user:recent:refresh"),
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recent_views_empty_kb() -> InlineKeyboardMarkup:
    """最近看过为空时的引导 keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot")],
        [InlineKeyboardButton(text="🔎 条件搜索", callback_data="user:filter")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def favorites_rich_kb(items: list, mode: str = "all") -> InlineKeyboardMarkup:
    """我的收藏增强版 keyboard。

    每位老师两行：
        [📋 #N 艺名]
        [👀 查看详情] [❌ 取消收藏]
    末尾：
        [只看今日可约 / 查看全部] ← 根据 mode 切换 label
        [🔄 刷新] [🔙 返回主菜单]

    callback：
        - teacher:view:<id>         复用既有详情页
        - user:favorites:rm:<id>    新增；handler 复用既有 remove_favorite + 重绘
        - user:favorites            mode='today' 时切回 [查看全部]
        - user:favorites:today      mode='all' 时切到 [只看今日可约]
        - user:favorites:refresh    刷新
        - user:main                 返回主菜单
    """
    rows: list[list[InlineKeyboardButton]] = []
    for i, it in enumerate(items, start=1):
        teacher_id = getattr(it, "teacher_id", None) or it.get("teacher_id")
        display_name = (
            getattr(it, "display_name", None)
            or it.get("display_name")
            or "老师"
        )
        label = f"📋 #{i} {display_name}"
        if len(label) > 40:
            label = label[:39] + "…"
        # UX-3 第二批：附带 from:favorites，详情页"返回"指向我的收藏
        view_cb = format_teacher_view_callback(teacher_id, "favorites")
        rows.append([InlineKeyboardButton(
            text=label, callback_data=view_cb,
        )])
        rows.append([
            InlineKeyboardButton(
                text="👀 查看详情",
                callback_data=view_cb,
            ),
            InlineKeyboardButton(
                text="❌ 取消收藏",
                callback_data=f"user:favorites:rm:{teacher_id}",
            ),
        ])

    # 模式切换 + 刷新 + 返回
    if mode == "today":
        mode_btn = InlineKeyboardButton(
            text="📋 查看全部", callback_data="user:favorites",
        )
    else:
        mode_btn = InlineKeyboardButton(
            text="📅 只看今日可约", callback_data="user:favorites:today",
        )
    rows.append([mode_btn])
    rows.append([
        InlineKeyboardButton(text="🔄 刷新", callback_data="user:favorites:refresh"),
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def favorites_empty_kb() -> InlineKeyboardMarkup:
    """收藏列表为空时的引导 keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot")],
        [InlineKeyboardButton(text="🔎 条件搜索", callback_data="user:filter")],
        [InlineKeyboardButton(text="👀 最近看过", callback_data="user:recent")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def search_history_rich_kb(queries: list[str]) -> InlineKeyboardMarkup:
    """搜索历史增强版 keyboard。

    保留现有 FSM-state-indexed 点选机制（避开 callback_data 长度限制）：
    每个历史词渲染为 [关键词] 按钮，callback_data 为 user:search_history:pick:<idx>，
    handler (user_history.cb_search_history_pick) 不变。

    末尾两行：
        [🔄 刷新]
        [🔙 返回主菜单]
    """
    rows: list[list[InlineKeyboardButton]] = []
    for i, q in enumerate(queries):
        # Telegram inline button 文案上限 64 字节，超长截断
        label = q if len(q) <= 30 else q[:29] + "…"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"user:search_history:pick:{i}",
        )])
    rows.append([
        InlineKeyboardButton(text="🔄 刷新", callback_data="user:search_history:refresh"),
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_history_empty_kb() -> InlineKeyboardMarkup:
    """搜索历史为空时的引导 keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 条件筛选", callback_data="user:filter")],
        [InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


# ============ 搜索失败推荐 / 搜索结果（Phase 2） ============


def search_suggestion_kb(keywords: list[str]) -> InlineKeyboardMarkup:
    """搜索 0 结果时的推荐键盘（Phase 2）

    布局：
        [📚 今日开课] [🔥 热门老师]
        [关键词1] [关键词2]
        [关键词3] [关键词4]
        ...
        [🔙 返回搜索] [🏠 返回主菜单]
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="📚 今日开课", callback_data="search:suggest:today"),
            InlineKeyboardButton(text="🔥 热门老师", callback_data="search:suggest:hot"),
        ],
    ]
    row: list[InlineKeyboardButton] = []
    for kw in keywords:
        row.append(InlineKeyboardButton(
            text=kw,
            callback_data=f"search:suggest:{kw}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(text="🔙 返回搜索", callback_data="user:search"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_list_pagination_kb(
    teacher_id: int,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """评价列表分页按钮（Phase 9.6.2）

    [⬅️ 上一页] [📄 X/Y] [➡️ 下一页]
    [🔙 返回老师详情]
    """
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️ 上一页",
            callback_data=f"teacher:reviews:{teacher_id}:{page - 1}",
        ))
    nav.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{max(1, total_pages)}",
        callback_data="noop:page",
    ))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(
            text="➡️ 下一页",
            callback_data=f"teacher:reviews:{teacher_id}:{page + 1}",
        ))
    return InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(
            text="🔙 返回老师详情",
            callback_data=f"teacher:view:{teacher_id}",
        )],
    ])


def suggestion_result_back_kb() -> InlineKeyboardMarkup:
    """推荐子页（今日 / 热门 / 单关键词）的返回按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 返回搜索", callback_data="user:search"),
            InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main"),
        ],
    ])


# ============ 个人评价主页（2026-05-18） ============


# 主页 status 过滤 3 个 + rating 过滤 3 个；rating 选中后兼作"写车评"预选评级。
_USER_REVIEW_STATUS_FILTERS: list[tuple[str, str]] = [
    ("pending",  "⏳ 未审核"),
    ("approved", "✅ 已审核"),
    ("rejected", "❌ 已驳回"),
]
_USER_REVIEW_RATING_FILTERS: list[tuple[str, str]] = [
    ("positive", "👍 好评"),
    ("neutral",  "😐 中评"),
    ("negative", "👎 差评"),
]


def user_reviews_home_kb(
    *,
    status_filter: Optional[str],
    rating_filter: Optional[str],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """个人评价主页键盘

    布局：
        [⏳ 未审核 / ✅ 已审核 / ❌ 已驳回]    ← 当前选中前缀 ●
        [👍 好评 / 😐 中评 / 👎 差评]            ← 同上；rating 选中后兼作预选评级
        [« 首页]  [‹ 上页]  [📄 X/Y]  [下页 ›]  [末页 »]
        [🤖 写车评]
        [🔙 返回主菜单]

    callback 命名空间：
        user:reviews:filter:status:<key|clear>
        user:reviews:filter:rating:<key|clear>
        user:reviews:page:<n>
        user:reviews:write
        user:main
    """
    rows: list[list[InlineKeyboardButton]] = []

    # 第一行：3 个 status 过滤
    row: list[InlineKeyboardButton] = []
    for key, label in _USER_REVIEW_STATUS_FILTERS:
        active = (key == status_filter)
        text = f"● {label}" if active else label
        cb = (
            "user:reviews:filter:status:clear" if active
            else f"user:reviews:filter:status:{key}"
        )
        row.append(InlineKeyboardButton(text=text, callback_data=cb))
    rows.append(row)

    # 第二行：3 个 rating 过滤
    row = []
    for key, label in _USER_REVIEW_RATING_FILTERS:
        active = (key == rating_filter)
        text = f"● {label}" if active else label
        cb = (
            "user:reviews:filter:rating:clear" if active
            else f"user:reviews:filter:rating:{key}"
        )
        row.append(InlineKeyboardButton(text=text, callback_data=cb))
    rows.append(row)

    # 第三行：分页
    nav: list[InlineKeyboardButton] = []
    cur_page = max(0, min(page, max(0, total_pages - 1)))
    last = max(0, total_pages - 1)
    if cur_page > 0:
        nav.append(InlineKeyboardButton(
            text="« 首页", callback_data="user:reviews:page:0",
        ))
        nav.append(InlineKeyboardButton(
            text="‹ 上页",
            callback_data=f"user:reviews:page:{cur_page - 1}",
        ))
    nav.append(InlineKeyboardButton(
        text=f"📄 {cur_page + 1}/{max(1, total_pages)}",
        callback_data="noop:reviews_page",
    ))
    if cur_page < last:
        nav.append(InlineKeyboardButton(
            text="下页 ›",
            callback_data=f"user:reviews:page:{cur_page + 1}",
        ))
        nav.append(InlineKeyboardButton(
            text="末页 »", callback_data=f"user:reviews:page:{last}",
        ))
    rows.append(nav)

    # 写车评 + 返回
    write_label = "🤖 写车评"
    if rating_filter:
        emoji = next(
            (lab for key, lab in _USER_REVIEW_RATING_FILTERS if key == rating_filter),
            "",
        )
        write_label = f"🤖 写车评（预选 {emoji}）"
    rows.append([InlineKeyboardButton(
        text=write_label,
        callback_data="user:reviews:write",
    )])
    rows.append([InlineKeyboardButton(
        text="🔙 返回主菜单", callback_data="user:main",
    )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============ 卡片驱动评价 FSM 键盘（2026-05-18 Phase 2） ============


_CARD_FIELDS: list[dict] = [
    {"key": "evidence",    "label": "🖼 出击证明",
     "data_keys": ["booking_screenshot_file_id", "gesture_photo_file_id"]},
    {"key": "rating",      "label": "⭐ 评级",       "data_keys": ["rating"]},
    {"key": "humanphoto",  "label": "🎨 人照",       "data_keys": ["score_humanphoto"]},
    {"key": "appearance",  "label": "💅 颜值",       "data_keys": ["score_appearance"]},
    {"key": "body",        "label": "💃 身材",       "data_keys": ["score_body"]},
    {"key": "service",     "label": "🛎 服务",       "data_keys": ["score_service"]},
    {"key": "attitude",    "label": "😊 态度",       "data_keys": ["score_attitude"]},
    {"key": "environment", "label": "🏠 环境",       "data_keys": ["score_environment"]},
    {"key": "summary",     "label": "📝 过程描述",   "data_keys": ["summary"]},
]


def _card_field_filled(data: dict, field: dict) -> bool:
    """字段是否已填齐"""
    for k in field["data_keys"]:
        v = data.get(k)
        if v is None or (isinstance(v, str) and not v):
            return False
    return True


def review_card_kb(state_data: dict) -> InlineKeyboardMarkup:
    """评价卡片键盘（card_view 状态）

    布局：
        Row 1: [🖼 出击证明✓ / ⭐ 评级✓]
        Row 2: [🎨 人照 / 💅 颜值]
        Row 3: [💃 身材 / 🛎 服务]
        Row 4: [😊 态度 / 🏠 环境]
        Row 5: [📝 过程描述]
        Row 6: [😟 匿名提交] [😎 默认提交]
        Row 7: [❌ 取消]

    callback：card:edit:<field_key> / card:submit:<anon|default> / card:cancel
    """
    rows: list[list[InlineKeyboardButton]] = []
    # 2 列布局：evidence+rating / 6 维 / summary 独占
    pairs: list[list[dict]] = [
        [_CARD_FIELDS[0], _CARD_FIELDS[1]],   # evidence + rating
        [_CARD_FIELDS[2], _CARD_FIELDS[3]],   # humanphoto + appearance
        [_CARD_FIELDS[4], _CARD_FIELDS[5]],   # body + service
        [_CARD_FIELDS[6], _CARD_FIELDS[7]],   # attitude + environment
        [_CARD_FIELDS[8]],                    # summary
    ]
    for pair in pairs:
        row: list[InlineKeyboardButton] = []
        for f in pair:
            mark = "✓ " if _card_field_filled(state_data, f) else ""
            row.append(InlineKeyboardButton(
                text=f"{mark}{f['label']}",
                callback_data=f"card:edit:{f['key']}",
            ))
        rows.append(row)

    rows.append([
        InlineKeyboardButton(text="😟 匿名提交", callback_data="card:submit:anon"),
        InlineKeyboardButton(text="😎 默认提交", callback_data="card:submit:default"),
    ])
    rows.append([InlineKeyboardButton(text="❌ 取消", callback_data="card:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_card_rating_kb() -> InlineKeyboardMarkup:
    """评级编辑子键盘"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍 好评", callback_data="card:rating:positive"),
            InlineKeyboardButton(text="😐 中评", callback_data="card:rating:neutral"),
            InlineKeyboardButton(text="👎 差评", callback_data="card:rating:negative"),
        ],
        [InlineKeyboardButton(text="🔙 返回卡片", callback_data="card:back")],
    ])


def review_card_edit_cancel_kb() -> InlineKeyboardMarkup:
    """编辑子状态的返回键盘"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回卡片（保留已填字段）", callback_data="card:back")],
    ])


def review_card_reimburse_kb(amount: int) -> InlineKeyboardMarkup:
    """卡片提交流程内的报销意愿询问"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💰 是，申请 {amount} 元",
            callback_data="card:reimburse:yes",
        )],
        [InlineKeyboardButton(text="否，不申请", callback_data="card:reimburse:no")],
        [InlineKeyboardButton(text="❌ 取消提交", callback_data="card:cancel")],
    ])


# ============ 评价 FSM 键盘（Phase 9.3） ============

def review_cancel_kb() -> InlineKeyboardMarkup:
    """评价 FSM 各步的取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ 取消", callback_data="review:cancel")],
    ])


def review_subscribe_links_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """关注校验失败时：展示必关链接列表 + 返回详情"""
    rows: list[list[InlineKeyboardButton]] = []
    for it in items:
        rows.append([InlineKeyboardButton(
            text=f"📺 {it['display_name']}",
            url=it["invite_link"],
        )])
    rows.append([InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_rating_kb() -> InlineKeyboardMarkup:
    """Step 1 评级：3 个按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍 好评", callback_data="review:rating:positive"),
            InlineKeyboardButton(text="😐 中评", callback_data="review:rating:neutral"),
            InlineKeyboardButton(text="👎 差评", callback_data="review:rating:negative"),
        ],
        [InlineKeyboardButton(text="❌ 取消", callback_data="review:cancel")],
    ])


def review_score_kb(
    dim_key: str,
    quick_buttons: list[float],
    *,
    per_row: int = 5,
) -> InlineKeyboardMarkup:
    """评分快捷按钮（6 维 / 综合通用）

    dim_key: humanphoto/appearance/.../overall
    quick_buttons: 数字列表（不同维度可能不同）
    """
    rows: list[list[InlineKeyboardButton]] = []
    cur: list[InlineKeyboardButton] = []
    for v in quick_buttons:
        # 整数显示为 "8"，否则保留 1 位小数 "8.5"
        label = f"{v:.0f}" if v == int(v) else f"{v:.1f}"
        cur.append(InlineKeyboardButton(
            text=label,
            callback_data=f"review:score:{dim_key}:{v}",
        ))
        if len(cur) >= per_row:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append([InlineKeyboardButton(text="❌ 取消", callback_data="review:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_summary_skip_cancel_kb() -> InlineKeyboardMarkup:
    """Step 9 过程描述：[⏭ 跳过] [❌ 取消]"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏭ 跳过", callback_data="review:summary_skip"),
            InlineKeyboardButton(text="❌ 取消", callback_data="review:cancel"),
        ],
    ])


def review_reimbursement_choice_kb(amount: int) -> InlineKeyboardMarkup:
    """报销意愿询问：[💰 是，申请 X 元] [否，不申请]"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 是，申请 {amount} 元",
                              callback_data="review:reimburse_yes")],
        [InlineKeyboardButton(text="否，不申请",
                              callback_data="review:reimburse_no")],
        [InlineKeyboardButton(text="❌ 取消评价",
                              callback_data="review:cancel")],
    ])


_REVIEW_EDIT_KEYS: list[tuple[str, str]] = [
    ("evidence", "证据照片"),  # 替换原 booking + gesture（合并为媒体组）
    ("rating", "评级"),
    ("humanphoto", "人照"),
    ("appearance", "颜值"),
    ("body", "身材"),
    ("service", "服务"),
    ("attitude", "态度"),
    ("environment", "环境"),
    # 综合评分由 6 维自动平均，无独立编辑项
    ("summary", "过程"),
]


def review_confirm_kb() -> InlineKeyboardMarkup:
    """确认页：[✅ 提交] + 11 个 [✏️ 修改:xxx] + [❌ 取消]"""
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(text="✅ 提交审核", callback_data="review:submit")])
    # 每行 2 个修改按钮
    cur: list[InlineKeyboardButton] = []
    for key, label in _REVIEW_EDIT_KEYS:
        cur.append(InlineKeyboardButton(
            text=f"✏️ 修改：{label}",
            callback_data=f"review:edit:{key}",
        ))
        if len(cur) >= 2:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append([InlineKeyboardButton(text="❌ 取消", callback_data="review:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

"""普通用户私聊菜单的 inline keyboards（v2 §2.5 C1 私聊冷启动 + Phase 2 详情页）"""

from typing import Callable, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.utils.url import normalize_url


# ============ 用户主菜单 ============

def user_main_menu_kb() -> InlineKeyboardMarkup:
    """普通用户私聊主菜单（Phase P.2：第 6 行独占新增 💰 我的积分）

    布局：
        [📚 今天能约谁] [🎯 帮我推荐]
        [🔎 按条件找]   [🔥 热门推荐]
        [⭐ 我的收藏]   [🕘 最近看过]
        [🔍 直接搜索]   [💝 收藏开课]
        [🔔 我的提醒]   [📜 搜索历史]
        [💰 我的积分]                     ← Phase P.2 新增，独占一行（spec §2.1）

    callback 复用既有命名空间。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
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
        [InlineKeyboardButton(text="💰 我的积分", callback_data="user:points")],
    ])


def user_points_menu_kb() -> InlineKeyboardMarkup:
    """积分页按钮组（Phase P.2，spec §2.2）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 积分明细", callback_data="user:points:list")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


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
            callback_data=f"teacher:view:{t['user_id']}",
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


def teacher_detail_kb(
    teacher: dict,
    *,
    is_favorited: bool,
    notify_enabled: bool = True,
    review_count: int = 0,
) -> InlineKeyboardMarkup:
    """老师详情页按钮组（Phase 9.6：5 行布局，新增 [📖 查看全部评价]）

    布局：
        [📩 联系老师]                              ← button_url 有效时显示
        [⭐ 收藏 / ✅ 已收藏，点击取消] [🔔/🔕 提醒按钮]
        [📖 查看全部评价 (N)]                       ← review_count > 0 时显示（9.6）
        [✨ 相似推荐]
        [📝 写评价]                                 ← 9.3 已加
        [🔙 返回主菜单]

    提醒按钮 3 态（Phase 7.3 §四）：
        - 未收藏              → "🔔 TA 开课提醒"
        - 已收藏 + notify=1   → "🔔 已开启提醒"
        - 已收藏 + notify=0   → "🔕 提醒已关闭，点击开启"
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

    # 返回主菜单
    rows.append([
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def teacher_detail_list_kb(
    teachers: list[dict],
    *,
    per_row: int = 1,
    label_fn: Optional[Callable[[dict], str]] = None,
    extra_back_buttons: Optional[list[list[InlineKeyboardButton]]] = None,
) -> InlineKeyboardMarkup:
    """老师列表 keyboard：每个按钮进入 teacher:view 详情页

    Args:
        teachers: 老师 dict 列表
        per_row: 每行多少个老师按钮（默认 1）
        label_fn: 自定义按钮文案，默认为 display_name
        extra_back_buttons: 自定义返回按钮行；默认仅一行"🔙 返回主菜单"
    """
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for t in teachers:
        label = label_fn(t) if label_fn else t["display_name"]
        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"teacher:view:{t['user_id']}",
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


_REVIEW_EDIT_KEYS: list[tuple[str, str]] = [
    ("booking", "约课截图"),
    ("gesture", "手势照片"),
    ("rating", "评级"),
    ("overall", "综合"),
    ("humanphoto", "人照"),
    ("appearance", "颜值"),
    ("body", "身材"),
    ("service", "服务"),
    ("attitude", "态度"),
    ("environment", "环境"),
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

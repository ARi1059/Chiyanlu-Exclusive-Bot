"""老师详情页 handlers（Phase 2）

Callbacks:
    teacher:view:<teacher_id>         展示老师详情（私聊场景）
    teacher:toggle_fav:<teacher_id>   切换该老师的收藏状态并刷新详情页

详情页入口（Phase 2 后所有这些位置都会进入此页）：
    - 搜索结果（艺名精确命中 / 单人命中 / 多人列表）
    - 我的收藏列表
    - 收藏开课列表
    - 最近看过列表
    - 今日开课老师（私聊菜单）

频道 14:00 自动发布 / 群组关键词响应 不走详情页，行为不变。
"""

import json
import logging
from datetime import datetime

from aiogram import Router, F, types
from pytz import timezone

from bot.config import config
from bot.database import (
    get_teacher,
    get_teacher_daily_status,
    is_checked_in,
    is_favorited,
    list_recent_teacher_views,
    record_teacher_view,
    toggle_favorite,
    update_user_tags_from_teacher_action,
    upsert_user,
)
from bot.keyboards.user_kb import (
    back_to_user_main_kb,
    recent_views_kb,
    teacher_detail_kb,
)

logger = logging.getLogger(__name__)

router = Router(name="teacher_detail")

_tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(_tz).strftime("%Y-%m-%d")


def format_teacher_detail_text(
    teacher: dict,
    *,
    is_signed_in_today: bool,
    is_fav: bool,
    daily_status_row: dict | None = None,
) -> str:
    """构造详情页文本（被 teacher_detail handler 和 user_search 共用）

    Phase 5：在原 6 行基础上追加今日状态 / 可约时间 / 备注（按 daily_status_row 派生）。
    daily_status_row 的字段:
        status: available / full / unavailable / unknown
        available_time: 全天 / 下午 / 晚上 / 自定义 / 未设置 / NULL
        note: 自由文本 / NULL
    """
    try:
        tags = json.loads(teacher["tags"]) if teacher["tags"] else []
    except (json.JSONDecodeError, TypeError):
        tags = []
    tags_str = " | ".join(tags) if tags else "（无标签）"
    fav_label = "✅ 已收藏" if is_fav else "未收藏"

    # Phase 5：今日状态 / 可约时间 / 备注 派生（spec §七）
    status_val = (daily_status_row or {}).get("status") if daily_status_row else None
    avt_val = (daily_status_row or {}).get("available_time") if daily_status_row else None
    note_val = (daily_status_row or {}).get("note") if daily_status_row else None

    if not is_signed_in_today and status_val != "unavailable":
        today_status_label = "⏳ 今日暂未开课"
        avt_label = "—"
    elif status_val == "unavailable":
        today_status_label = "❌ 今日已取消"
        avt_label = "—"
    elif status_val == "full":
        today_status_label = "🈵 今日已满"
        avt_label = (avt_val or "").strip() or "未设置"
    elif status_val == "available":
        today_status_label = "✅ 今日可约"
        avt_label = (avt_val or "").strip() or "未设置"
    else:
        # 已签到但 daily_status_row 为空 → 视为可约
        today_status_label = "✅ 今日可约"
        avt_label = "未设置"

    lines = [
        f"👤 {teacher['display_name']}",
        f"📍 地区：{teacher['region']}",
        f"💰 价格：{teacher['price']}",
        f"🏷 标签：{tags_str}",
        f"📅 今日状态：{today_status_label}",
        f"⏰ 可约时间：{avt_label}",
    ]
    if note_val and str(note_val).strip():
        lines.append(f"📝 备注：{str(note_val).strip()}")
    lines.append(f"⭐ 收藏状态：{fav_label}")
    return "\n".join(lines)


async def _build_detail_payload(
    user_id: int,
    teacher: dict,
) -> tuple[str, types.InlineKeyboardMarkup]:
    """聚合详情页文本 + 键盘，供本文件和 user_search 共用"""
    today = _today_str()
    is_signed_in = await is_checked_in(teacher["user_id"], today)
    is_fav = await is_favorited(user_id, teacher["user_id"])
    # Phase 5：今日状态
    daily_row = await get_teacher_daily_status(teacher["user_id"], today)
    text = format_teacher_detail_text(
        teacher,
        is_signed_in_today=is_signed_in,
        is_fav=is_fav,
        daily_status_row=daily_row,
    )
    kb = teacher_detail_kb(teacher, is_favorited=is_fav)
    return text, kb


async def send_teacher_detail_message(
    message: types.Message,
    user_id: int,
    teacher: dict,
    *,
    record_view: bool = True,
) -> None:
    """以"新消息"的形式发送详情页（用于 message handler 场景，如搜索 FSM 收到文字）

    callback 场景请改用 _render_detail（edit_text）。
    """
    text, kb = await _build_detail_payload(user_id, teacher)
    await message.answer(text, reply_markup=kb)
    if record_view:
        await record_teacher_view(user_id, teacher["user_id"])
        # Phase 6.1：用户画像 view_teacher 动作
        await update_user_tags_from_teacher_action(
            user_id, teacher["user_id"], "view_teacher",
        )


async def _render_detail(
    callback: types.CallbackQuery,
    teacher_id: int,
    *,
    record_view: bool,
) -> None:
    """以"编辑当前消息"的形式渲染详情页（用于 callback 场景）"""
    teacher = await get_teacher(teacher_id)
    if not teacher or not teacher.get("is_active"):
        await callback.answer("该老师暂不可查看", show_alert=True)
        return

    user = callback.from_user
    # 用户首次点详情可能尚未在 users 表（如管理员 / 老师），保险刷新
    try:
        await upsert_user(user.id, user.username, user.first_name)
    except Exception as e:
        logger.debug("upsert_user 失败 (user=%s): %s", user.id, e)

    if record_view:
        await record_teacher_view(user.id, teacher_id)
        # Phase 6.1：用户画像 view_teacher 动作
        await update_user_tags_from_teacher_action(
            user.id, teacher_id, "view_teacher",
        )

    text, kb = await _build_detail_payload(user.id, teacher)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        # 上一条是图片消息 / 内容相同 / 已无法编辑 → 退化为新发一条
        await callback.message.answer(text, reply_markup=kb)


# ============ teacher:view —— 打开详情页 ============


@router.callback_query(F.data.startswith("teacher:view:"))
async def cb_teacher_view(callback: types.CallbackQuery):
    """打开老师详情页（仅私聊场景）"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("详情页仅在私聊中可用", show_alert=True)
        return

    try:
        teacher_id = int(callback.data[len("teacher:view:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    await _render_detail(callback, teacher_id, record_view=True)
    await callback.answer()


# ============ teacher:toggle_fav —— 详情页内切换收藏 ============


@router.callback_query(F.data.startswith("teacher:toggle_fav:"))
async def cb_teacher_toggle_fav(callback: types.CallbackQuery):
    """详情页内切换收藏，切换后刷新当前页（v2 §2.1 + 第二阶段要求 10）"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("收藏切换仅在私聊中可用", show_alert=True)
        return

    try:
        teacher_id = int(callback.data[len("teacher:toggle_fav:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    teacher = await get_teacher(teacher_id)
    if not teacher or not teacher.get("is_active"):
        await callback.answer("该老师暂不可查看", show_alert=True)
        return

    user = callback.from_user
    try:
        await upsert_user(user.id, user.username, user.first_name)
    except Exception as e:
        logger.debug("upsert_user 失败 (user=%s): %s", user.id, e)

    is_fav_now = await toggle_favorite(user.id, teacher_id)
    if is_fav_now:
        # Phase 6.1：仅收藏成功时累加画像分；取消不扣分
        await update_user_tags_from_teacher_action(
            user.id, teacher_id, "favorite_add",
        )
        await callback.answer(f"✅ 已收藏 {teacher['display_name']}")
    else:
        await callback.answer(f"已取消收藏 {teacher['display_name']}")

    # 切换后刷新当前详情页（不再 record_view 以免覆盖 viewed_at）
    await _render_detail(callback, teacher_id, record_view=False)


# ============ user:recent —— 最近浏览列表 ============


@router.callback_query(F.data == "user:recent")
async def cb_user_recent(callback: types.CallbackQuery):
    """最近浏览过的老师列表（Phase 2 新增主菜单入口）"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    user_id = callback.from_user.id
    views = await list_recent_teacher_views(user_id, limit=10)
    if not views:
        await callback.message.edit_text(
            "🕘 最近看过\n\n你还没有浏览过老师。\n可以先去 🔍 搜索老师 看看。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    text = f"🕘 最近看过（{len(views)} 位）\n\n最近浏览的老师如下："
    await callback.message.edit_text(text, reply_markup=recent_views_kb(views))
    await callback.answer()

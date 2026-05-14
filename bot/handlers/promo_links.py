"""推广链接生成器（Phase 4 §四）

Callbacks:
    admin:promo_links           推广链接主菜单
    admin:promo:channel         频道来源
    admin:promo:group           群组来源
    admin:promo:teacher         老师来源（同时生成"收藏 + 老师来源"复合链接）
    admin:promo:campaign        活动来源
    admin:promo:invite          邀请来源

FSM (PromoLinkStates.waiting_input):
    state.data = {"link_type": "channel|group|teacher|campaign|invite"}
"""

import logging
from typing import Optional

from aiogram import Bot, Router, F, types
from aiogram.fsm.context import FSMContext

from bot.keyboards.admin_kb import (
    promo_cancel_kb,
    promo_links_menu_kb,
)
from bot.states.teacher_states import PromoLinkStates
from bot.utils.permissions import admin_required

logger = logging.getLogger(__name__)

router = Router(name="promo_links")

# bot username 懒加载缓存
_BOT_USERNAME: Optional[str] = None

# 类型 → 提示文案
_TYPE_PROMPTS: dict[str, str] = {
    "channel": (
        "📺 生成「频道来源」推广链接\n\n"
        "请输入频道标识：\n"
        "・可以是频道数字 ID（如 -1001234567890）\n"
        "・也可以是简短别名（如 daily, news, official）\n\n"
        "输入后会生成 t.me/<bot>?start=src_channel_<标识> 链接。"
    ),
    "group": (
        "👥 生成「群组来源」推广链接\n\n"
        "请输入群组标识：\n"
        "・群组数字 ID（如 -1009876543210）\n"
        "・或别名（如 onepiece_group）\n\n"
        "输入后会生成 t.me/<bot>?start=src_group_<标识> 链接。"
    ),
    "teacher": (
        "👤 生成「老师来源」推广链接\n\n"
        "请输入老师 Telegram 数字 ID。\n\n"
        "会同时生成两条链接：\n"
        "・纯来源：start=src_teacher_<id>\n"
        "・收藏 + 来源：start=fav_<id>_src_teacher_<id>"
    ),
    "campaign": (
        "🎯 生成「活动来源」推广链接\n\n"
        "请输入活动代号，例如 may_campaign / 618 / spring_promo。\n"
        "建议字母数字下划线，避免特殊字符。"
    ),
    "invite": (
        "🎟️ 生成「邀请来源」推广链接\n\n"
        "请输入邀请码（如 admin001 / inviter_ari）。\n"
        "建议字母数字下划线。"
    ),
}

_TYPE_LABELS: dict[str, str] = {
    "channel": "频道来源",
    "group": "群组来源",
    "teacher": "老师来源",
    "campaign": "活动来源",
    "invite": "邀请来源",
}


async def _bot_username(bot: Bot) -> str:
    """懒加载 bot username，避免每次都 get_me"""
    global _BOT_USERNAME
    if _BOT_USERNAME:
        return _BOT_USERNAME
    try:
        me = await bot.get_me()
        _BOT_USERNAME = me.username or ""
    except Exception as e:
        logger.warning("get_me 失败: %s", e)
        _BOT_USERNAME = ""
    return _BOT_USERNAME


async def _safe_log_admin_audit(
    admin_id: int,
    action: str,
    **kwargs,
) -> None:
    """兼容降级：log_admin_audit 不存在或失败时静默跳过"""
    try:
        from bot.database import log_admin_audit  # type: ignore
    except ImportError:
        return
    try:
        await log_admin_audit(admin_id=admin_id, action=action, **kwargs)
    except Exception as e:
        logger.debug("log_admin_audit 失败 (action=%s): %s", action, e)


async def _safe_log_user_event(
    user_id: int,
    event_type: str,
    payload: object | None = None,
) -> None:
    """兼容降级：log_user_event 不存在或失败时静默跳过"""
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(user_id, event_type, payload)
    except Exception as e:
        logger.debug("log_user_event 失败 (type=%s): %s", event_type, e)


def _build_start_param(link_type: str, code: str) -> str:
    """根据 link_type 拼出 /start 参数"""
    if link_type == "channel":
        return f"src_channel_{code}"
    if link_type == "group":
        return f"src_group_{code}"
    if link_type == "teacher":
        return f"src_teacher_{code}"
    if link_type == "campaign":
        return f"campaign_{code}"
    if link_type == "invite":
        return f"invite_{code}"
    return code


# ============ 主菜单 ============


@router.callback_query(F.data == "admin:promo_links")
@admin_required
async def cb_promo_main(callback: types.CallbackQuery, state: FSMContext):
    """🔗 推广链接主面板（兼作 FSM 取消的目标）"""
    await state.clear()
    text = (
        "🔗 推广链接生成器\n\n"
        "请选择要生成的链接类型："
    )
    try:
        await callback.message.edit_text(text, reply_markup=promo_links_menu_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=promo_links_menu_kb())
    await callback.answer()


# ============ 各类型入口（统一进 FSM） ============


@router.callback_query(F.data.startswith("admin:promo:"))
@admin_required
async def cb_promo_type(callback: types.CallbackQuery, state: FSMContext):
    """统一入口：根据 callback 后缀决定 link_type，进入 FSM 等待输入"""
    link_type = callback.data[len("admin:promo:"):]
    if link_type not in _TYPE_PROMPTS:
        await callback.answer("⚠️ 未知链接类型", show_alert=True)
        return

    await state.set_state(PromoLinkStates.waiting_input)
    await state.update_data(link_type=link_type)
    await callback.message.edit_text(
        _TYPE_PROMPTS[link_type],
        reply_markup=promo_cancel_kb(),
    )
    await callback.answer()


# ============ FSM 接收输入并生成链接 ============


@router.message(PromoLinkStates.waiting_input)
@admin_required
async def on_promo_input(message: types.Message, state: FSMContext):
    """接收输入，生成推广链接并展示"""
    data = await state.get_data()
    link_type = data.get("link_type")
    if not link_type or link_type not in _TYPE_PROMPTS:
        await state.clear()
        await message.answer("⚠️ 会话已失效，请重新选择类型")
        await message.answer(
            "🔗 推广链接生成器\n\n请选择要生成的链接类型：",
            reply_markup=promo_links_menu_kb(),
        )
        return

    raw_code = (message.text or "").strip()
    if not raw_code:
        await message.reply("请输入有效内容", reply_markup=promo_cancel_kb())
        return

    # 简单校验：禁止空格，防止 start param 被截断
    if any(ch.isspace() for ch in raw_code):
        await message.reply(
            "❌ 内容不能包含空格 / 换行，请重新输入",
            reply_markup=promo_cancel_kb(),
        )
        return

    # teacher 类型额外校验为数字
    if link_type == "teacher" and not raw_code.isdigit():
        await message.reply(
            "❌ 老师 ID 必须是纯数字",
            reply_markup=promo_cancel_kb(),
        )
        return

    username = await _bot_username(message.bot)
    if not username:
        await state.clear()
        await message.answer("⚠️ 无法获取 bot username，请稍后再试")
        return

    start_param = _build_start_param(link_type, raw_code)

    # Telegram /start 参数推荐 ≤ 64 字符；超长不影响生成，但提示
    if len(start_param) > 64:
        warning = f"\n\n⚠️ 参数长度 {len(start_param)} > 64，部分客户端可能截断"
    else:
        warning = ""

    url = f"https://t.me/{username}?start={start_param}"

    # 额外：teacher 类型同时生成"收藏 + 老师来源"复合链接
    extra_lines: list[str] = []
    if link_type == "teacher":
        fav_param = f"fav_{raw_code}_src_teacher_{raw_code}"
        fav_url = f"https://t.me/{username}?start={fav_param}"
        extra_lines.append("")
        extra_lines.append("📌 收藏 + 老师来源 复合链接：")
        extra_lines.append(f"`{fav_url}`")

    label = _TYPE_LABELS.get(link_type, link_type)
    text_lines = [
        f"✅ 已生成「{label}」推广链接{warning}",
        "",
        "📋 复制下方链接发给目标渠道：",
        f"`{url}`",
        "",
        f"start 参数：`{start_param}`",
    ]
    text_lines.extend(extra_lines)

    # 双日志：admin_audit_logs + user_events
    detail = {"link_type": link_type, "code": raw_code, "url": url}
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="promo_link_generate",
        target_type="promo_link",
        target_id=f"{link_type}:{raw_code}",
        detail=detail,
    )
    await _safe_log_user_event(
        user_id=message.from_user.id,
        event_type="promo_link_generate",
        payload=detail,
    )

    await state.clear()
    await message.answer(
        "\n".join(text_lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
    # 回到 promo 主菜单方便继续生成
    await message.answer(
        "🔗 推广链接生成器\n\n请选择要生成的链接类型：",
        reply_markup=promo_links_menu_kb(),
    )

"""用户复访入口（Phase A0 已删除 search_history / continue_last）

Callbacks:
    user:reminders                  → 展示"我的开课提醒"（= 收藏 + notify_enabled）
    user:reminders:enable_notify    → 一键开启通知

Phase A0（2026-05-23）变更：
    - 删除 search_history 全套（user:search_history / :pick / :refresh）
    - 删除 continue_last（user:continue_last，依赖已删的 user_teacher_views 表）
    - 简化 reminders 中 _short_today_status：移除对 get_teacher_daily_status 的依赖
"""

import logging
from datetime import datetime

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pytz import timezone

from bot.config import config
from bot.database import (
    get_user,
    is_checked_in,
    list_user_favorites,
    set_user_notify_enabled,
)

logger = logging.getLogger(__name__)

router = Router(name="user_history")

_tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(_tz).strftime("%Y-%m-%d")


# ============ log_user_event 兼容降级 ============


async def _safe_log_event(user_id: int, event_type: str, payload=None) -> None:
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(user_id, event_type, payload)
    except Exception as e:
        logger.debug("log_user_event(%s) 失败: %s", event_type, e)


# ============ 渲染工具 ============


async def _edit_or_send(
    callback: types.CallbackQuery,
    text: str,
    kb: InlineKeyboardMarkup,
) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)


# ============ 我的提醒（Phase 7.3 §四） ============


def _reminders_off_kb() -> InlineKeyboardMarkup:
    """通知关闭时的引导键盘"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔔 开启通知",
            callback_data="user:reminders:enable_notify",
        )],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def _reminders_list_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """已开启提醒的老师列表 → 每行进详情页"""
    rows: list[list[InlineKeyboardButton]] = []
    for it in items:
        label = it["label"]
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"teacher:view:{it['user_id']}",
        )])
    rows.append([
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _reminders_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 直接搜索", callback_data="user:search"),
         InlineKeyboardButton(text="📚 今日开课", callback_data="user:today")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


async def _short_today_status(teacher_id: int, today: str) -> str:
    """单个老师的今日状态短文案（Phase A0：移除 daily_status 依赖）"""
    try:
        signed = await is_checked_in(teacher_id, today)
    except Exception:
        signed = False
    return "今日可约" if signed else "今日暂未开课"


@router.callback_query(F.data == "user:reminders")
async def cb_reminders(callback: types.CallbackQuery, state: FSMContext):
    """展示我的开课提醒

    规则（第一版）：
        - notify_enabled=0 → 引导开启通知
        - 收藏为空        → 引导用户去搜索/热门
        - 否则             → 列出收藏并附今日状态
    """
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    user_id = callback.from_user.id
    await state.clear()

    # 1. notify_enabled 判定
    notify_enabled = True
    try:
        user_row = await get_user(user_id)
        if user_row is not None:
            val = user_row.get("notify_enabled")
            notify_enabled = bool(val) if val is not None else True
    except Exception as e:
        logger.debug("get_user 失败 user=%s: %s", user_id, e)

    if not notify_enabled:
        text = (
            "🔔 我的开课提醒\n\n"
            "你当前关闭了通知提醒。\n"
            "开启后，收藏的老师今日开课时会自动推送给你。"
        )
        await _edit_or_send(callback, text, _reminders_off_kb())
        await callback.answer()
        return

    # 2. 收藏列表
    try:
        favorites = await list_user_favorites(user_id, active_only=True)
    except Exception as e:
        logger.warning("list_user_favorites 失败 user=%s: %s", user_id, e)
        favorites = []

    if not favorites:
        text = (
            "🔔 我的开课提醒\n\n"
            "你还没有收藏老师，开课提醒暂无对象。\n"
            "去收藏几位老师，开课时即可收到推送。"
        )
        await _edit_or_send(callback, text, _reminders_empty_kb())
        await callback.answer()
        return

    today = _today_str()
    items: list[dict] = []
    lines = [
        "🔔 我的开课提醒",
        "",
        f"已开启提醒的老师（{len(favorites)} 位）：",
        "",
    ]
    for i, t in enumerate(favorites, start=1):
        try:
            status = await _short_today_status(t["user_id"], today)
        except Exception:
            status = "今日暂未开课"
        name = t.get("display_name") or "?"
        region = (t.get("region") or "?").strip() or "?"
        price = (t.get("price") or "?").strip() or "?"
        lines.append(f"{i}. {name}｜{region}｜{price}｜{status}")
        items.append({
            "user_id": t["user_id"],
            "label": f"{name} · {status}",
        })

    await _edit_or_send(callback, "\n".join(lines), _reminders_list_kb(items))
    await callback.answer()


@router.callback_query(F.data == "user:reminders:enable_notify")
async def cb_reminders_enable(callback: types.CallbackQuery, state: FSMContext):
    """开启用户级 notify_enabled 并跳回提醒页"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    user_id = callback.from_user.id
    try:
        await set_user_notify_enabled(user_id, True)
    except Exception as e:
        logger.warning("set_user_notify_enabled 失败 user=%s: %s", user_id, e)
        await callback.answer("开启失败，请稍后再试", show_alert=True)
        return

    await callback.answer("✅ 已开启通知")
    # 重新渲染提醒页（此时 notify_enabled=1，会走列表分支）
    await cb_reminders(callback, state)

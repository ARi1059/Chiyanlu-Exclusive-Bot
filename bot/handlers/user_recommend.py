"""智能推荐 handlers（Phase 7.2 §六）

Callbacks:
    user:recommend          → 展示推荐列表（按用户画像）
    user:recommend:refresh  → 换一批（在候选池中随机打散后取前 N）

数据源：bot.database.get_recommended_teachers_for_user（无画像时自动回退到 hot）
"""

import logging
import random

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import get_recommended_teachers_for_user

logger = logging.getLogger(__name__)

router = Router(name="user_recommend")


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


def _short_status(t: dict) -> str:
    """复用 user_filter 同款短状态文案"""
    status = t.get("daily_status")
    if status == "unavailable":
        return "今日已取消"
    if status == "full":
        return "今日已满"
    if bool(t.get("signed_in_today")):
        return "今日可约"
    return "今日暂未开课"


def _empty_kb() -> InlineKeyboardMarkup:
    """无推荐结果时的引导键盘"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📚 今日开课", callback_data="user:today"),
            InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot"),
        ],
        [
            InlineKeyboardButton(text="🔎 按条件找", callback_data="user:filter"),
        ],
        [
            InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
        ],
    ])


def _result_kb(teachers: list[dict]) -> InlineKeyboardMarkup:
    """推荐结果：每位老师一行进详情页 + 换一批/筛选/返回"""
    rows: list[list[InlineKeyboardButton]] = []
    for t in teachers:
        label = t.get("button_text") or t.get("display_name") or "?"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"teacher:view:{t['user_id']}",
        )])
    rows.append([
        InlineKeyboardButton(text="🔄 换一批", callback_data="user:recommend:refresh"),
        InlineKeyboardButton(text="🔎 按条件找", callback_data="user:filter"),
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_or_send(
    callback: types.CallbackQuery,
    text: str,
    kb: InlineKeyboardMarkup,
) -> None:
    """优先编辑当前消息，失败则新发一条"""
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)


async def _render(
    callback: types.CallbackQuery,
    teachers: list[dict],
) -> None:
    """统一渲染推荐页（含空态分支）"""
    if not teachers:
        text = (
            "🎯 暂时还没有足够数据为你推荐\n\n"
            "你可以先试试："
        )
        await _edit_or_send(callback, text, _empty_kb())
        return

    lines = [
        "🎯 为你推荐",
        "",
        "根据你的浏览、搜索和收藏，为你找到以下老师：",
        "",
    ]
    for i, t in enumerate(teachers, start=1):
        name = t.get("display_name") or "?"
        region = (t.get("region") or "?").strip() or "?"
        price = (t.get("price") or "?").strip() or "?"
        status = _short_status(t)
        lines.append(f"{i}. {name}｜{region}｜{price}｜{status}")
    await _edit_or_send(callback, "\n".join(lines), _result_kb(teachers))


# ============ user:recommend —— 首屏推荐 ============


@router.callback_query(F.data == "user:recommend")
async def cb_recommend(callback: types.CallbackQuery, state: FSMContext):
    """根据用户画像推荐 5 位老师；无画像时自动回退到 hot"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    await state.clear()
    user_id = callback.from_user.id

    try:
        teachers = await get_recommended_teachers_for_user(user_id, limit=5)
    except Exception as e:
        logger.warning("get_recommended_teachers_for_user 失败 (user=%s): %s", user_id, e)
        teachers = []

    await _render(callback, teachers)
    await callback.answer()
    await _safe_log_event(user_id, "user_recommend_view", {"count": len(teachers)})


# ============ user:recommend:refresh —— 换一批（在候选池里打散） ============


@router.callback_query(F.data == "user:recommend:refresh")
async def cb_recommend_refresh(callback: types.CallbackQuery, state: FSMContext):
    """换一批：取候选池 (top 20)，random.shuffle 后取前 5"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    user_id = callback.from_user.id
    try:
        candidates = await get_recommended_teachers_for_user(user_id, limit=20)
    except Exception as e:
        logger.warning(
            "get_recommended_teachers_for_user(refresh) 失败 (user=%s): %s", user_id, e,
        )
        candidates = []

    if candidates:
        random.shuffle(candidates)
    teachers = candidates[:5]

    await _render(callback, teachers)
    await callback.answer()
    await _safe_log_event(user_id, "user_recommend_refresh", {"count": len(teachers)})

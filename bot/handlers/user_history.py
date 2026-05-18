"""Phase 7.3 §二/三/四的复访入口

Callbacks:
    user:search_history             → 展示用户最近 10 次搜索词
    user:search_history:pick:<idx>  → 从 FSM state 中读真实 query 回放
    user:continue_last              → 打开用户上次看过的老师详情页
    user:reminders                  → 展示"我的开课提醒"（= 收藏 + notify_enabled）
    user:reminders:enable_notify    → 一键开启通知

设计要点：
    - 搜索词可能含中文长字符串，不直接塞 callback_data，用 FSM state 索引映射
    - 用 SearchHistoryStates.waiting_pick 与 FilterStates 隔离，互不影响
    - 我的提醒第一版 = 我的收藏 + 用户级 notify_enabled 状态
"""

import logging
from datetime import datetime

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pytz import timezone

from bot.config import config
from bot.database import (
    get_teacher,
    get_teacher_daily_status,
    get_user,
    is_checked_in,
    list_recent_teacher_views,
    list_user_favorites,
    set_user_notify_enabled,
)
from bot.keyboards.user_kb import (
    search_history_empty_kb,
    search_history_rich_kb,
    user_main_menu_kb,
)
from bot.states.user_states import SearchHistoryStates

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


def _back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


# ============ 搜索历史（Phase 7.3 §二，用户留存增强：富数据展示 + 刷新） ============


async def _render_search_history(
    user_id: int,
    state: FSMContext,
) -> tuple[str, InlineKeyboardMarkup, list[str]]:
    """生成搜索历史的文本 + keyboard + 用于 FSM 索引的 query 列表。

    被 user:search_history 与 user:search_history:refresh 共用。
    """
    from bot.services.search_history import (
        get_user_search_history_detailed,
        render_search_history,
    )
    try:
        items = await get_user_search_history_detailed(user_id, limit=10)
    except Exception as e:
        logger.warning(
            "get_user_search_history_detailed 失败 user=%s: %s", user_id, e,
        )
        items = []

    now_local = datetime.now(_tz)
    text = render_search_history(items, generated_at=now_local, now_local=now_local)
    if not items:
        return text, search_history_empty_kb(), []
    queries = [it.query for it in items]
    return text, search_history_rich_kb(queries), queries


@router.callback_query(F.data == "user:search_history")
async def cb_search_history(callback: types.CallbackQuery, state: FSMContext):
    """打开搜索历史页：读 user_events → 富数据渲染 → FSM 暂存原始 queries"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    user_id = callback.from_user.id
    text, kb, queries = await _render_search_history(user_id, state)

    if not queries:
        await state.clear()
        await _edit_or_send(callback, text, kb)
        await callback.answer()
        await _safe_log_event(user_id, "user_search_history_open", {"count": 0})
        return

    # FSM 索引点选机制保持不变（cb_search_history_pick 仍可工作）
    await state.set_state(SearchHistoryStates.waiting_pick)
    await state.update_data(queries=queries)

    await _edit_or_send(callback, text, kb)
    await callback.answer()
    await _safe_log_event(user_id, "user_search_history_open", {"count": len(queries)})


@router.callback_query(F.data == "user:search_history:refresh")
async def cb_search_history_refresh(callback: types.CallbackQuery, state: FSMContext):
    """刷新搜索历史（重新拉取 + 重绘 + 刷新 FSM queries 索引）。"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    user_id = callback.from_user.id
    text, kb, queries = await _render_search_history(user_id, state)

    # 刷新后必须同步更新 FSM 中的 queries 索引，否则 pick:<idx> 会取到旧序列
    if queries:
        await state.set_state(SearchHistoryStates.waiting_pick)
        await state.update_data(queries=queries)
    else:
        await state.clear()

    try:
        await _edit_or_send(callback, text, kb)
    except Exception:
        pass
    await callback.answer("已刷新")


@router.callback_query(F.data.startswith("user:search_history:pick:"))
async def cb_search_history_pick(callback: types.CallbackQuery, state: FSMContext):
    """从 FSM state 中取真实 query，调 user_search._execute_search 回放"""
    raw = callback.data[len("user:search_history:pick:"):]
    try:
        idx = int(raw)
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    data = await state.get_data()
    queries = data.get("queries") or []
    if not isinstance(queries, list) or idx < 0 or idx >= len(queries):
        await callback.answer("搜索记录已失效，请重新打开", show_alert=True)
        await state.clear()
        return

    query = str(queries[idx])
    await callback.answer(f"🔍 {query}")
    await _safe_log_event(
        callback.from_user.id,
        "user_search_history_pick",
        {"query": query, "index": idx},
    )

    # 调用 user_search 的共享搜索逻辑（结果通过 message.answer 新发）
    try:
        from bot.handlers.user_search import _execute_search
    except ImportError:
        await callback.message.answer(
            "搜索模块不可用，请直接点「🔍 直接搜索」",
            reply_markup=_back_to_main_kb(),
        )
        return

    try:
        await _execute_search(callback.from_user.id, query, callback.message)
    except Exception as e:
        logger.warning("回放搜索失败 user=%s query=%s: %s",
                       callback.from_user.id, query, e)
        await callback.message.answer(
            "搜索执行失败，请稍后再试",
            reply_markup=_back_to_main_kb(),
        )


@router.message(SearchHistoryStates.waiting_pick, Command("cancel"))
async def cancel_search_history(message: types.Message, state: FSMContext):
    """搜索历史页 /cancel 兜底"""
    await state.clear()
    await message.answer("已退出搜索历史。", reply_markup=user_main_menu_kb())


# ============ 继续上次浏览（Phase 7.3 §三） ============


@router.callback_query(F.data == "user:continue_last")
async def cb_continue_last(callback: types.CallbackQuery, state: FSMContext):
    """打开用户最近浏览过的老师详情页

    在 callback 时点重新查询 last view，避免依赖陈旧的 message_id。
    """
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    user_id = callback.from_user.id
    try:
        views = await list_recent_teacher_views(user_id, limit=1)
    except Exception as e:
        logger.warning("list_recent_teacher_views 失败 user=%s: %s", user_id, e)
        views = []

    if not views:
        await callback.answer("最近浏览记录已被清除")
        await _edit_or_send(
            callback,
            "👋 欢迎使用痴颜录 Bot\n\n你想怎么找？",
            user_main_menu_kb(),
        )
        return

    teacher_id = views[0]["user_id"]
    await _safe_log_event(user_id, "user_continue_last", {"teacher_id": teacher_id})
    await state.clear()

    # 复用 teacher_detail._render_detail 渲染（避免重复实现 UI 拼装）
    try:
        from bot.handlers.teacher_detail import _render_detail
        await _render_detail(callback, teacher_id, record_view=False)
        await callback.answer()
    except Exception as e:
        logger.warning("渲染上次浏览详情页失败 user=%s tid=%s: %s",
                       user_id, teacher_id, e)
        await callback.answer("打开失败，请重试", show_alert=True)


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
         InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


async def _short_today_status(teacher_id: int, today: str) -> str:
    """单个老师的今日状态短文案（轻量查询，仅供 reminders 列表使用）"""
    try:
        daily = await get_teacher_daily_status(teacher_id, today)
    except Exception:
        daily = None
    status = (daily or {}).get("status") if daily else None
    if status == "unavailable":
        return "今日已取消"
    if status == "full":
        return "今日已满"
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

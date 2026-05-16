"""条件筛选器 handlers（Phase 7.2 §二）

Callbacks:
    user:filter             → 筛选首页
    user:filter:region      → 按地区选项列表
    user:filter:price       → 按价格选项列表
    user:filter:tag         → 按标签选项列表
    user:filter:today       → 今日可约（直接出结果）
    user:filter:hot         → 热门推荐（直接出结果）
    user:filter:new         → 最近上新（直接出结果）
    user:filter:pick:<idx>  → 从 FSM state 中读取 options[idx] 并查询

FSM 状态:
    FilterStates.waiting_pick + state.data = {"filter_type": ..., "options": [...]}

callback_data 长度处理:
    地区/价格/标签可能含中文长字符串 → 不直接塞进 callback_data，改用 FSM 索引映射。
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
    get_filter_options,
    search_teachers_by_filter,
)
from bot.keyboards.user_kb import back_to_user_main_kb, user_main_menu_kb
from bot.states.user_states import FilterStates

logger = logging.getLogger(__name__)

router = Router(name="user_filter")

_tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(_tz).strftime("%Y-%m-%d")


# ============ log_user_event 兼容降级 ============


async def _safe_log_event(user_id: int, event_type: str, payload=None) -> None:
    """log_user_event 缺失或异常时静默跳过"""
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
    """从一行老师 dict 派生短状态文案（结果列表用）"""
    status = t.get("daily_status")
    if status == "unavailable":
        return "今日已取消"
    if status == "full":
        return "今日已满"
    if bool(t.get("signed_in_today")):
        return "今日可约"
    return "今日暂未开课"


def _filter_home_kb() -> InlineKeyboardMarkup:
    """筛选首页键盘（6 个分类入口 + 返回主菜单）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📍 按地区", callback_data="user:filter:region"),
            InlineKeyboardButton(text="💰 按价格", callback_data="user:filter:price"),
        ],
        [
            InlineKeyboardButton(text="🏷 按标签", callback_data="user:filter:tag"),
            InlineKeyboardButton(text="✅ 今日可约", callback_data="user:filter:today"),
        ],
        [
            InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:filter:hot"),
            InlineKeyboardButton(text="🆕 最近上新", callback_data="user:filter:new"),
        ],
        [
            InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
        ],
    ])


def _filter_options_kb(options: list[dict]) -> InlineKeyboardMarkup:
    """渲染动态选项按钮组：每行 2 个 + 末尾返回行"""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, opt in enumerate(options):
        label = str(opt.get("value", "")).strip() or "?"
        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"user:filter:pick:{i}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(text="🔙 返回筛选", callback_data="user:filter"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _filter_result_kb(teachers: list[dict]) -> InlineKeyboardMarkup:
    """结果列表按钮（每位老师一行，进入详情页）"""
    rows: list[list[InlineKeyboardButton]] = []
    for t in teachers:
        label = t.get("button_text") or t.get("display_name") or "?"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"teacher:view:{t['user_id']}",
        )])
    rows.append([
        InlineKeyboardButton(text="🔙 返回筛选", callback_data="user:filter"),
        InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot"),
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _no_result_kb() -> InlineKeyboardMarkup:
    """0 结果时的返回入口组"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔎 返回筛选", callback_data="user:filter"),
            InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot"),
        ],
        [
            InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
        ],
    ])


async def _edit_or_send(
    callback: types.CallbackQuery,
    text: str,
    kb: InlineKeyboardMarkup,
) -> None:
    """优先编辑当前消息；上一条不可编辑（如图片）→ 新发一条"""
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)


async def _render_result(
    callback: types.CallbackQuery,
    title: str,
    teachers: list[dict],
) -> None:
    """统一渲染筛选结果页"""
    if not teachers:
        text = (
            f"🔎 筛选结果：{title}\n\n"
            "暂无符合条件的老师。"
        )
        await _edit_or_send(callback, text, _no_result_kb())
        return

    lines = [
        f"🔎 筛选结果：{title}",
        "",
        f"找到 {len(teachers)} 位老师：",
        "",
    ]
    for i, t in enumerate(teachers, start=1):
        name = t.get("display_name") or "?"
        region = (t.get("region") or "?").strip() or "?"
        price = (t.get("price") or "?").strip() or "?"
        status = _short_status(t)
        lines.append(f"{i}. {name}｜{region}｜{price}｜{status}")
    await _edit_or_send(callback, "\n".join(lines), _filter_result_kb(teachers))


# ============ user:filter —— 筛选首页 ============


@router.callback_query(F.data == "user:filter")
async def cb_filter_home(callback: types.CallbackQuery, state: FSMContext):
    """筛选首页：清空旧 state 后展示 6 个分类入口"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    await state.clear()
    text = "🔎 条件筛选\n\n你想怎么找？"
    await _edit_or_send(callback, text, _filter_home_kb())
    await callback.answer()
    await _safe_log_event(callback.from_user.id, "user_filter_open")


# ============ user:filter:region / :price / :tag —— 动态选项列表 ============


@router.callback_query(F.data.in_({"user:filter:region", "user:filter:price", "user:filter:tag"}))
async def cb_filter_picker(callback: types.CallbackQuery, state: FSMContext):
    """加载某维度可选值并写入 FSM state，等待用户点选"""
    parts = callback.data.split(":")
    opt_type = parts[2]  # region / price / tag

    # tag 最多 16 项，region/price 12 项（spec §二）
    limit = 16 if opt_type == "tag" else 12
    try:
        options = await get_filter_options(opt_type, limit=limit)
    except Exception as e:
        logger.warning("get_filter_options(%s) 失败: %s", opt_type, e)
        options = []

    if not options:
        await callback.answer("暂无可用选项", show_alert=True)
        return

    # 写 FSM state（options 顺序与按钮 index 一一对应）
    await state.set_state(FilterStates.waiting_pick)
    await state.update_data(
        filter_type=opt_type,
        options=[o["value"] for o in options],
    )

    title_map = {
        "region": "📍 选择地区",
        "price": "💰 选择价格",
        "tag": "🏷 选择标签",
    }
    await _edit_or_send(
        callback,
        f"{title_map[opt_type]}\n\n点击下方选项查看符合条件的老师：",
        _filter_options_kb(options),
    )
    await callback.answer()


# ============ user:filter:pick:<idx> —— 从 state 中查 value 并出结果 ============


@router.callback_query(F.data.startswith("user:filter:pick:"))
async def cb_filter_pick(callback: types.CallbackQuery, state: FSMContext):
    """根据 callback index 从 FSM state.options 取真实 value，调 search_teachers_by_filter"""
    raw = callback.data[len("user:filter:pick:"):]
    try:
        idx = int(raw)
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    data = await state.get_data()
    options = data.get("options") or []
    filter_type = data.get("filter_type") or ""

    if not isinstance(options, list) or idx < 0 or idx >= len(options):
        await callback.answer("筛选项已失效，请重新选择", show_alert=True)
        # 重新引导到筛选首页
        await state.clear()
        await _edit_or_send(callback, "🔎 条件筛选\n\n你想怎么找？", _filter_home_kb())
        return

    value = str(options[idx])
    try:
        teachers = await search_teachers_by_filter(filter_type, value, limit=20)
    except Exception as e:
        logger.warning("search_teachers_by_filter(%s, %s) 失败: %s", filter_type, value, e)
        teachers = []

    title_map = {
        "region": f"地区：{value}",
        "price": f"价格：{value}",
        "tag": f"标签：{value}",
    }
    await _render_result(callback, title_map.get(filter_type, value), teachers)
    await callback.answer()
    await _safe_log_event(
        callback.from_user.id,
        "user_filter_select",
        {"filter_type": filter_type, "value": value, "count": len(teachers)},
    )


# ============ user:filter:today / :hot / :new —— 直查直出 ============


@router.callback_query(F.data.in_({"user:filter:today", "user:filter:hot", "user:filter:new"}))
async def cb_filter_direct(callback: types.CallbackQuery, state: FSMContext):
    """无需选项的三类筛选：直接调 search_teachers_by_filter"""
    await state.clear()
    parts = callback.data.split(":")
    ftype = parts[2]  # today / hot / new

    try:
        teachers = await search_teachers_by_filter(ftype, value=None, limit=20)
    except Exception as e:
        logger.warning("search_teachers_by_filter(%s) 失败: %s", ftype, e)
        teachers = []

    title_map = {
        "today": "今日可约",
        "hot": "热门推荐",
        "new": "最近上新",
    }
    await _render_result(callback, title_map[ftype], teachers)
    await callback.answer()
    await _safe_log_event(
        callback.from_user.id,
        "user_filter_select",
        {"filter_type": ftype, "value": None, "count": len(teachers)},
    )


# ============ FSM /cancel 兜底 ============


@router.message(FilterStates.waiting_pick, Command("cancel"))
async def cancel_filter(message: types.Message, state: FSMContext):
    """筛选选项页 /cancel：清状态并把用户带回主菜单"""
    await state.clear()
    await message.answer(
        "已退出筛选。",
        reply_markup=user_main_menu_kb(),
    )

"""普通用户私聊菜单的 callback handlers（v2 §2.5 C1 + Phase 2 详情页接入）

主菜单 5 个按钮:
    📚 user:today      → 今日所有开课老师（点击老师进入 teacher:view 详情页）
    ⭐ user:favorites  → 我的收藏（老师按钮 → 详情页；❌ → 移除收藏）
    💝 user:fav_today  → 收藏 ∩ 已签到（老师按钮 → 详情页）
    🕘 user:recent     → 最近看过（Phase 2 新增；handler 在 teacher_detail.py）
    🔍 user:search     → 进入搜索 FSM（user_search.py 接管）

user:main → 返回主菜单（通用按钮）
"""

from datetime import datetime

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from pytz import timezone

from bot.config import config
from bot.database import (
    add_user_tag,
    get_checked_in_teachers,
    get_display_time_group,
    get_sorted_teachers,
    list_user_favorites,
    list_user_favorites_signed_in,
)
from bot.keyboards.user_kb import (
    user_main_menu_kb,
    back_to_user_main_kb,
    search_cancel_kb,
    my_favorites_kb,
    teacher_detail_list_kb,
)
from bot.states.user_states import SearchStates

router = Router(name="user_panel")

tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")


# ============ 返回主菜单 ============

@router.callback_query(F.data == "user:main")
async def cb_user_main(callback: types.CallbackQuery, state: FSMContext):
    """返回用户主菜单（任何子菜单 / 搜索状态都可以走这里退出）"""
    await state.clear()
    await callback.message.edit_text(
        "👋 欢迎使用痴颜录 Bot\n\n请选择下方功能：",
        reply_markup=user_main_menu_kb(),
    )
    await callback.answer()


# ============ 📚 今日开课老师 ============


_USER_TODAY_GROUP_ORDER: list[tuple[str, str]] = [
    ("all", "🌞 全天可约"),
    ("afternoon", "🌤 下午可约"),
    ("evening", "🌙 晚上可约"),
    ("other", "📝 其他时间"),
    ("full", "🈵 今日已满"),
]


@router.callback_query(F.data == "user:today")
async def cb_today(callback: types.CallbackQuery):
    """展示当天所有已签到老师（Phase 5：按时间段分组 + teacher:view 按钮）

    范围：当天已签到 + 启用 + daily_status != 'unavailable'
    分组：5 个 bucket（全天 / 下午 / 晚上 / 其他时间 / 今日已满）
    按钮：每个老师 → teacher:view:<id>（私聊详情页）
    频道 14:00 自动发布走另一条 build_daily_checkin_payload 路径，URL 按钮不变。
    """
    today = _today_str()
    # Phase 5：try 排序版（带 daily_status）；老 schema 异常时回退
    try:
        teachers = await get_sorted_teachers(
            active_only=True,
            signed_in_date=today,
            exclude_unavailable=True,
        )
        groupable = True
    except Exception:
        teachers = await get_checked_in_teachers(today)
        groupable = False

    if not teachers:
        await callback.message.edit_text(
            f"📚 {today}\n\n今日暂无老师开课。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    # 老师按钮文案
    def _label(t: dict) -> str:
        return t.get("button_text") or t["display_name"]

    # 分组渲染：每个 group 一行标题占位（noop callback）+ 该组的老师按钮（per_row=2）
    rows: list[list[types.InlineKeyboardButton]] = []

    if not groupable:
        # 回退到不分组
        row: list[types.InlineKeyboardButton] = []
        for t in teachers:
            row.append(types.InlineKeyboardButton(
                text=_label(t),
                callback_data=f"teacher:view:{t['user_id']}",
            ))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    else:
        # 分组
        buckets: dict[str, list[dict]] = {key: [] for key, _ in _USER_TODAY_GROUP_ORDER}
        for t in teachers:
            key = get_display_time_group(t)
            if key not in buckets:
                key = "other"
            buckets[key].append(t)

        for key, header in _USER_TODAY_GROUP_ORDER:
            bucket = buckets[key]
            if not bucket:
                continue
            # 组标题
            rows.append([types.InlineKeyboardButton(
                text=header,
                callback_data="noop:section",
            )])
            row: list[types.InlineKeyboardButton] = []
            for t in bucket:
                row.append(types.InlineKeyboardButton(
                    text=_label(t),
                    callback_data=f"teacher:view:{t['user_id']}",
                ))
                if len(row) == 2:
                    rows.append(row)
                    row = []
            if row:
                rows.append(row)

    rows.append([types.InlineKeyboardButton(
        text="🔙 返回主菜单",
        callback_data="user:main",
    )])

    text = (
        f"📚 今日开课老师 · {today}（{len(teachers)} 位）\n\n"
        "点击老师查看详情。"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

    # Phase 5 §九：记录用户查看今日事件（log_user_event 缺失时降级）
    try:
        from bot.database import log_user_event  # type: ignore
        await log_user_event(
            callback.from_user.id,
            "user_view_today",
            {"date": today, "count": len(teachers)},
        )
    except Exception:
        pass

    # Phase 6.1：今日开课关注者 + 活跃用户画像标签
    try:
        await add_user_tag(callback.from_user.id, "今日开课关注者", 1, "today")
        await add_user_tag(callback.from_user.id, "活跃用户", 1, "today")
    except Exception:
        pass


# ============ ⭐ 我的收藏 ============

@router.callback_query(F.data == "user:favorites")
async def cb_favorites(callback: types.CallbackQuery):
    """展示当前用户的收藏列表（v2 §2.1）

    keyboard 形态：每行 [老师名 · 地区 · 价格] [❌]，点击 ❌ 触发 fav:rm_from_list
    （由 favorite.py 处理 + 刷新列表）。
    """
    favorites = await list_user_favorites(callback.from_user.id, active_only=True)
    if not favorites:
        await callback.message.edit_text(
            "⭐ 我的收藏\n\n你还没有收藏任何老师。\n试试 🔍 搜索老师 找一个。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    text = (
        f"⭐ 我的收藏（{len(favorites)} 位）\n\n"
        "点击老师查看详情，点击 ❌ 取消收藏。"
    )
    await callback.message.edit_text(
        text,
        reply_markup=my_favorites_kb(favorites),
    )
    await callback.answer()


# ============ 💝 收藏开课（收藏 ∩ 今日签到） ============

@router.callback_query(F.data == "user:fav_today")
async def cb_fav_today(callback: types.CallbackQuery):
    """收藏老师中当天已签到的（Phase 2：点击进入 teacher:view 详情页）"""
    today = _today_str()
    teachers = await list_user_favorites_signed_in(callback.from_user.id, today)
    if not teachers:
        await callback.message.edit_text(
            f"💝 收藏开课 · {today}\n\n你的收藏老师今日均未开课。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    text = (
        f"💝 收藏开课 · {today}（{len(teachers)} 位）\n\n"
        "点击老师查看详情。"
    )
    kb = teacher_detail_list_kb(
        teachers,
        per_row=2,
        label_fn=lambda t: t.get("button_text") or t["display_name"],
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ============ 🔍 搜索老师 ============

@router.callback_query(F.data == "user:search")
async def cb_search_entry(callback: types.CallbackQuery, state: FSMContext):
    """进入搜索 FSM，等待用户输入关键词"""
    await state.set_state(SearchStates.waiting_query)
    await callback.message.edit_text(
        "🔍 搜索老师\n\n"
        "请输入关键词：\n"
        "・艺名（精确命中直接返回该老师）\n"
        "・标签 / 地区 / 价格 的组合（例：御姐 1000P 天府一街）\n\n"
        "支持空格、逗号分隔多个词；同类型 OR，跨类型 AND。\n"
        "随时点击下方按钮退出搜索。",
        reply_markup=search_cancel_kb(),
    )
    await callback.answer()

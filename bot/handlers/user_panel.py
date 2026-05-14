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
    get_checked_in_teachers,
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

@router.callback_query(F.data == "user:today")
async def cb_today(callback: types.CallbackQuery):
    """展示当天所有已签到老师（Phase 2：点击进入 teacher:view 详情页）

    频道 14:00 自动发布行为不变（仍使用 build_daily_checkin_payload + URL 按钮）。
    """
    today = _today_str()
    teachers = await get_checked_in_teachers(today)
    if not teachers:
        await callback.message.edit_text(
            f"📚 {today}\n\n今日暂无老师开课。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    text = (
        f"📚 今日开课老师 · {today}（{len(teachers)} 位）\n\n"
        "点击老师查看详情。"
    )
    kb = teacher_detail_list_kb(
        teachers,
        per_row=2,
        label_fn=lambda t: t.get("button_text") or t["display_name"],
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


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

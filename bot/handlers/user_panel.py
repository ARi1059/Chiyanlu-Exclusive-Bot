"""普通用户私聊菜单的 callback handlers（v2 §2.5 C1）

主菜单 4 个按钮:
    📚 user:today      → 今日所有开课老师（同 14:00 频道发布内容）
    ⭐ user:favorites  → 我的收藏（Step 2 数据为空，Step 3 后自然填充）
    💝 user:fav_today  → 收藏 ∩ 已签到（Step 2 数据为空，Step 3 后自然填充）
    🔍 user:search     → 进入搜索 FSM（user_search.py 接管）

user:main → 返回主菜单（通用按钮）
"""

from datetime import datetime
from html import escape

from aiogram import Router, types, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from pytz import timezone

from bot.config import config
from bot.database import (
    list_user_favorites,
    list_user_favorites_signed_in,
)
from bot.keyboards.user_kb import (
    user_main_menu_kb,
    back_to_user_main_kb,
    search_cancel_kb,
)
from bot.scheduler.tasks import build_daily_checkin_payload
from bot.states.user_states import SearchStates
from bot.utils.url import normalize_url

router = Router(name="user_panel")

tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")


def _build_signed_in_buttons_kb(teachers: list[dict]) -> types.InlineKeyboardMarkup:
    """把"开课老师"列表渲染成按钮组 + 返回主菜单按钮

    每行最多 3 个按钮，跳过 button_url 无效的老师。
    """
    buttons: list[list[types.InlineKeyboardButton]] = []
    row: list[types.InlineKeyboardButton] = []
    for t in teachers:
        button_url = normalize_url(t["button_url"])
        if not button_url:
            continue
        button_text = t["button_text"] or t["display_name"]
        row.append(types.InlineKeyboardButton(text=button_text, url=button_url))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        types.InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


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
    """展示当天所有已签到老师（同 14:00 频道发布内容）"""
    today = _today_str()
    payload = await build_daily_checkin_payload(today)
    if payload is None:
        await callback.message.edit_text(
            f"📚 {today}\n\n今日暂无老师开课。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    text, kb_url_only = payload
    # 复用 build_daily_checkin_payload 的按钮，再追加"返回主菜单"
    merged = types.InlineKeyboardMarkup(
        inline_keyboard=list(kb_url_only.inline_keyboard) + [
            [types.InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=merged)
    await callback.answer()


# ============ ⭐ 我的收藏 ============

@router.callback_query(F.data == "user:favorites")
async def cb_favorites(callback: types.CallbackQuery):
    """展示当前用户的收藏列表（Step 2 数据为空，Step 3 完整启用）"""
    favorites = await list_user_favorites(callback.from_user.id, active_only=True)
    if not favorites:
        await callback.message.edit_text(
            "⭐ 我的收藏\n\n你还没有收藏任何老师。\n试试 🔍 搜索老师 找一个。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    # 以超链接列表展示（点击文字跳 button_url）
    lines = [f"⭐ 我的收藏（{len(favorites)} 位）\n"]
    for t in favorites:
        url = normalize_url(t["button_url"])
        display_name = escape(t["display_name"])
        region = escape(t["region"])
        price = escape(t["price"])
        if url:
            lines.append(
                f'<a href="{escape(url, quote=True)}">{display_name} - {region} - {price}</a>'
            )
        else:
            lines.append(f"{display_name} - {region} - {price}")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_to_user_main_kb(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await callback.answer()


# ============ 💝 收藏开课（收藏 ∩ 今日签到） ============

@router.callback_query(F.data == "user:fav_today")
async def cb_fav_today(callback: types.CallbackQuery):
    """收藏老师中当天已签到的（Step 2 数据为空，Step 3 完整启用）"""
    today = _today_str()
    teachers = await list_user_favorites_signed_in(callback.from_user.id, today)
    if not teachers:
        await callback.message.edit_text(
            f"💝 收藏开课 · {today}\n\n你的收藏老师今日均未开课。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    text = f"💝 收藏开课 · {today}\n\n你收藏的老师中今日开课共 {len(teachers)} 位："
    await callback.message.edit_text(
        text,
        reply_markup=_build_signed_in_buttons_kb(teachers),
    )
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

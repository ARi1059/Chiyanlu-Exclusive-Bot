"""用户「我的积分」入口（Phase P.2）

callback:
    user:points              → 积分总览页（余额 + 累计获得 + 累计消耗）
    user:points:list         → 积分明细 page 0
    user:points:list:<page>  → 积分明细 page N（每页 20 条）
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F

from bot.database import (
    count_user_point_transactions,
    get_user_points_summary,
    list_user_point_transactions,
)
from bot.keyboards.user_kb import (
    user_points_menu_kb,
)
from bot.utils.user_points_render import (
    POINTS_DETAIL_PAGE_SIZE,
    fetch_teacher_names_for_txs,
    format_points_detail_block,
    format_points_summary_page,
)

logger = logging.getLogger(__name__)

router = Router(name="user_points")


@router.callback_query(F.data == "user:points")
async def cb_user_points(callback: types.CallbackQuery):
    """[💰 我的积分] 总览页"""
    user_id = callback.from_user.id
    summary = await get_user_points_summary(user_id)
    text = format_points_summary_page(summary)
    try:
        await callback.message.edit_text(text, reply_markup=user_points_menu_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=user_points_menu_kb())
    await callback.answer()


def _parse_list_page(data: str) -> Optional[int]:
    """解析 user:points:list 或 user:points:list:<page> → page；非法返回 None"""
    parts = data.split(":")
    # ["user", "points", "list"] 或 ["user", "points", "list", "<page>"]
    if len(parts) < 3 or parts[0] != "user" or parts[1] != "points" or parts[2] != "list":
        return None
    if len(parts) == 3:
        return 0
    try:
        return max(0, int(parts[3]))
    except ValueError:
        return None


def _pagination_kb(page: int, total_pages: int):
    """积分明细分页按钮（独立简版，不复用 review_list_pagination_kb 避免命名空间冲突）"""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️ 上一页",
            callback_data=f"user:points:list:{page - 1}",
        ))
    nav.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{max(1, total_pages)}",
        callback_data="noop:page",
    ))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(
            text="➡️ 下一页",
            callback_data=f"user:points:list:{page + 1}",
        ))
    return InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(text="🔙 返回积分", callback_data="user:points")],
        [InlineKeyboardButton(text="🏠 主菜单", callback_data="user:main")],
    ])


@router.callback_query(F.data.startswith("user:points:list"))
async def cb_user_points_list(callback: types.CallbackQuery):
    """[📋 积分明细] 分页页面"""
    page = _parse_list_page(callback.data or "")
    if page is None:
        await callback.answer("参数错误", show_alert=True)
        return
    user_id = callback.from_user.id

    total = await count_user_point_transactions(user_id)
    if total == 0:
        text = (
            "📋 积分明细\n\n"
            "ℹ️ 暂无积分记录。提交并通过审核的报告会自动加分。"
        )
        try:
            await callback.message.edit_text(text, reply_markup=user_points_menu_kb())
        except Exception:
            await callback.message.answer(text, reply_markup=user_points_menu_kb())
        await callback.answer()
        return

    total_pages = (total + POINTS_DETAIL_PAGE_SIZE - 1) // POINTS_DETAIL_PAGE_SIZE
    if page >= total_pages:
        page = total_pages - 1
    offset = page * POINTS_DETAIL_PAGE_SIZE
    txs = await list_user_point_transactions(
        user_id, limit=POINTS_DETAIL_PAGE_SIZE, offset=offset,
    )
    teachers_map, review_teacher_map = await fetch_teacher_names_for_txs(txs)
    detail_block = format_points_detail_block(
        txs, teachers_map, review_teacher_map,
        start_idx=offset + 1,
    )

    text = (
        f"📋 积分明细（共 {total} 条 · 第 {page + 1}/{total_pages} 页）\n\n"
        f"{detail_block}"
    )
    if len(text) > 4000:
        text = text[:3990] + "\n…(本页过长，已截断)"
    try:
        await callback.message.edit_text(
            text, reply_markup=_pagination_kb(page, total_pages),
        )
    except Exception:
        # 同样内容 edit → BadRequest，忽略
        pass
    await callback.answer()

"""评价列表分页页面（Phase 9.6.2）

入口：详情页 [📖 查看全部评价 (N)] callback teacher:reviews:<id>
分页：teacher:reviews:<id>:<page>（page 从 0 开始）

每页 REVIEWS_PAGE_SIZE 条；只展示 approved 评价（与详情页统计一致）。
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F

from bot.database import (
    count_approved_reviews,
    get_teacher,
    list_approved_reviews,
)
from bot.keyboards.user_kb import review_list_pagination_kb
from bot.utils.review_detail_render import (
    REVIEWS_PAGE_SIZE,
    fetch_signer_names,
    format_recent_reviews_block,
)

logger = logging.getLogger(__name__)

router = Router(name="review_list")


def _parse_callback(data: str) -> Optional[tuple[int, int]]:
    """解析 teacher:reviews:<id> 或 teacher:reviews:<id>:<page>
    → (teacher_id, page)；失败返回 None。
    """
    parts = data.split(":")
    # parts = ["teacher","reviews","<id>"] 或 ["teacher","reviews","<id>","<page>"]
    if len(parts) < 3 or parts[0] != "teacher" or parts[1] != "reviews":
        return None
    try:
        teacher_id = int(parts[2])
    except ValueError:
        return None
    page = 0
    if len(parts) >= 4:
        try:
            page = max(0, int(parts[3]))
        except ValueError:
            page = 0
    return teacher_id, page


@router.callback_query(F.data.startswith("teacher:reviews:"))
async def cb_teacher_reviews(callback: types.CallbackQuery):
    """评价列表分页页面"""
    parsed = _parse_callback(callback.data or "")
    if not parsed:
        await callback.answer("参数错误", show_alert=True)
        return
    teacher_id, page = parsed

    teacher = await get_teacher(teacher_id)
    if not teacher:
        await callback.answer("该老师不存在", show_alert=True)
        return

    total = await count_approved_reviews(teacher_id)
    if total == 0:
        await callback.answer("该老师暂无评价", show_alert=True)
        return
    total_pages = (total + REVIEWS_PAGE_SIZE - 1) // REVIEWS_PAGE_SIZE
    page = min(page, total_pages - 1)  # 边界保护
    if page < 0:
        page = 0

    offset = page * REVIEWS_PAGE_SIZE
    reviews = await list_approved_reviews(
        teacher_id, limit=REVIEWS_PAGE_SIZE, offset=offset,
    )
    signer_names = await fetch_signer_names(reviews)
    list_block = format_recent_reviews_block(reviews, signer_names)
    if list_block.startswith("最近评价："):
        # format 函数同时被详情页用 → 头部是"最近评价："；列表页改成自定义标题
        list_block = list_block[len("最近评价："):].lstrip("\n")

    title = (
        f"📖 {teacher.get('display_name', '?')} 的评价列表\n"
        f"共 {total} 条 · 第 {page + 1}/{total_pages} 页\n"
    )
    text = f"{title}\n{list_block}"
    if len(text) > 4000:
        text = text[:3990] + "\n…(本页过长，已截断)"

    try:
        await callback.message.edit_text(
            text,
            reply_markup=review_list_pagination_kb(teacher_id, page, total_pages),
        )
    except Exception:
        # 同一页 edit 同文本 → BadRequest，安全忽略
        pass
    await callback.answer()

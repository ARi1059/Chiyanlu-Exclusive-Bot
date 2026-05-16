"""noop:* callback 占位（Phase 9.5.3）

讨论群评价评论的中间按钮 [{rating_emoji} {rating_label}] 是纯视觉徽章，
用 callback_data = "noop:rating" 表示无动作；点击仅 callback.answer() 消除转圈。
"""
from __future__ import annotations

from aiogram import Router, types, F

router = Router(name="noop_handlers")


@router.callback_query(F.data.startswith("noop:"))
async def cb_noop(callback: types.CallbackQuery):
    """noop:rating 等占位 callback：仅 answer 消除转圈，不做任何动作"""
    await callback.answer()

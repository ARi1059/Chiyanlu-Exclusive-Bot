"""noop:* callback 占位（Phase 9.5.3）

讨论群评价评论的中间按钮 [{rating_emoji} {rating_label}] 是纯视觉徽章，
用 callback_data = "noop:rating" 表示无动作；点击仅 callback.answer() 消除转圈。

⚠️ noop 双 handler 分工：
   - 本文件 (noop_handlers.py)：处理**带冒号**的 ``noop:*`` 占位 callback
     （例如 ``noop:rating`` / ``noop:page``）—— routers.py 第 2 条注册，优先匹配
   - bot/handlers/teacher_daily_status.py 中另有一处 ``F.data.startswith("noop")``
     （**无冒号**），用作裸 ``noop`` / ``noop_xxx`` 的兜底
   - 两者前缀语义不同，**不是重复 bug**；切勿合并到 ``F.data.startswith("noop")``，
     否则会扩大命中范围吃掉无关 callback
"""
from __future__ import annotations

from aiogram import Router, types, F

router = Router(name="noop_handlers")


# 仅匹配 ``noop:<...>``（带冒号），将裸 ``noop`` / ``noop_xxx`` 留给
# teacher_daily_status.py:cb_noop 兜底。
@router.callback_query(F.data.startswith("noop:"))
async def cb_noop(callback: types.CallbackQuery):
    """noop:rating 等占位 callback：仅 answer 消除转圈，不做任何动作"""
    await callback.answer()

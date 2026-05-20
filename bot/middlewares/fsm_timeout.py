"""FSM 状态超时中间件（UX-9.2）。

历史：bot/handlers/teacher_flow.py:37-66 已有 5 分钟超时实现，但仅注册到
teacher_flow router。UX-9.2 把它抽到独立模块，允许其它长 FSM router
（如 teacher_profile 录入 9 步、admin_lottery 创建 11 步、review_card 评价 9 字段）
按需注入不同 timeout。

设计：
    - 类构造接受 timeout_seconds 参数（默认 300 = 5 分钟）；teacher_profile 等
      录入流程长的 router 应传入更大的值（建议 1800 = 30 分钟）。
    - 仅当 state 已经在某个 FSM state 时才更新 `_last_active`；空状态不污染。
    - 超时后 await state.clear()，并通知用户"已自动取消"——避免用户继续
      在已废弃的会话里输入。
    - 超时后不再调用下游 handler（return）。

为避免引入循环 import，本模块只依赖 aiogram；不知道任何业务模块。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, types
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)


# 默认超时秒数（5 分钟，与历史 teacher_flow 行为一致）。
DEFAULT_FSM_TIMEOUT_SECONDS: int = 300
# 长录入流程建议使用的超时（30 分钟），caller 显式传入。
LONG_FSM_TIMEOUT_SECONDS: int = 1800


class FSMTimeoutMiddleware(BaseMiddleware):
    """FSM 状态超时自动 clear 中间件。

    Args:
        timeout_seconds: 无操作超时秒数；默认 300（与 teacher_flow 历史一致）。
    """

    def __init__(self, timeout_seconds: int = DEFAULT_FSM_TIMEOUT_SECONDS):
        super().__init__()
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds 必须 > 0，得到 {timeout_seconds}")
        self.timeout_seconds = int(timeout_seconds)

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext = data.get("state")
        if state is None:
            return await handler(event, data)

        current_state = await state.get_state()
        if not current_state:
            # 无 FSM state 时不做任何更新；也不污染 _last_active
            return await handler(event, data)

        state_data = await state.get_data()
        last_active = state_data.get("_last_active", 0)
        now = time.time()

        if last_active and (now - last_active) > self.timeout_seconds:
            try:
                await state.clear()
            except Exception as e:
                logger.warning("[UX-9.2] state.clear 失败: %s", e)
            # 通知用户超时
            minutes = self.timeout_seconds // 60
            msg = (
                f"⏰ 已超过 {minutes} 分钟无操作，"
                "本次录入已自动取消。请重新开始。"
            )
            try:
                if isinstance(event, types.Message):
                    await event.answer(msg)
                elif isinstance(event, types.CallbackQuery):
                    await event.answer(msg, show_alert=True)
            except Exception as e:
                logger.info("[UX-9.2] 超时通知发送失败: %s", e)
            return None  # 不再调下游 handler

        # 更新最后活跃时间
        try:
            await state.update_data(_last_active=now)
        except Exception as e:
            logger.warning("[UX-9.2] state.update_data(_last_active) 失败: %s", e)

        return await handler(event, data)

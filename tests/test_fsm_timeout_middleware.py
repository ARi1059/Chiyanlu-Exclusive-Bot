"""Sprint UX-9 第二项（UX-9.2）：FSM 状态超时中间件抽取 + teacher_profile 接入契约测试。

范围：
    - bot.middlewares.fsm_timeout.FSMTimeoutMiddleware 新模块（从 teacher_flow 抽取）
    - bot.handlers.teacher_flow router 重构为 import 新模块（保持 5 分钟行为）
    - bot.handlers.teacher_profile router 新接入（30 分钟超时）
    - DEFAULT_FSM_TIMEOUT_SECONDS (300) / LONG_FSM_TIMEOUT_SECONDS (1800) 常量

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §6 痛点 2 + §11.3）：
    teacher_profile 9 步录入 + 10 张照片上传，服务重启 / 长时间无操作 →
    MemoryStorage 中卡死的 FSM 数据（含 photos file_id）丢失或污染。本批接入
    超时中间件，30 分钟无操作自动 clear，让用户重新开始（明确流程结束）。

约束：
    - 不动 admin_lottery / review_card 等其它长 FSM router（单 PR 单范围）
    - teacher_flow 行为保持 5 分钟超时（向后兼容）
    - 不引入 schema 迁移
"""
from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


def _src(module) -> str:
    return inspect.getsource(module)


# ============================================================
# 1. middleware 类签名与常量
# ============================================================


def test_module_exists_and_exposes_class():
    """bot.middlewares.fsm_timeout 应导出 FSMTimeoutMiddleware。"""
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    assert FSMTimeoutMiddleware is not None


def test_default_timeout_300_seconds():
    """DEFAULT_FSM_TIMEOUT_SECONDS = 300（5 分钟），与历史 teacher_flow 一致。"""
    from bot.middlewares.fsm_timeout import DEFAULT_FSM_TIMEOUT_SECONDS
    assert DEFAULT_FSM_TIMEOUT_SECONDS == 300


def test_long_timeout_1800_seconds():
    """LONG_FSM_TIMEOUT_SECONDS = 1800（30 分钟），供长录入流程使用。"""
    from bot.middlewares.fsm_timeout import LONG_FSM_TIMEOUT_SECONDS
    assert LONG_FSM_TIMEOUT_SECONDS == 1800


def test_constructor_accepts_custom_timeout():
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    mw = FSMTimeoutMiddleware(timeout_seconds=600)
    assert mw.timeout_seconds == 600


def test_constructor_rejects_non_positive_timeout():
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    with pytest.raises(ValueError):
        FSMTimeoutMiddleware(timeout_seconds=0)
    with pytest.raises(ValueError):
        FSMTimeoutMiddleware(timeout_seconds=-1)


# ============================================================
# 2. middleware 行为
# ============================================================


def _make_state(current_state: str | None, last_active: float | None) -> MagicMock:
    """构造一个伪 FSMContext mock。"""
    state = MagicMock()
    state.get_state = AsyncMock(return_value=current_state)
    state_data = {"_last_active": last_active} if last_active is not None else {}
    state.get_data = AsyncMock(return_value=state_data)
    state.update_data = AsyncMock(return_value=None)
    state.clear = AsyncMock(return_value=None)
    return state


def test_middleware_passes_through_when_no_state():
    """data 中无 state → 直接调下游 handler。"""
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    mw = FSMTimeoutMiddleware(timeout_seconds=300)
    handler = AsyncMock(return_value="ok")
    event = MagicMock()
    result = _run(mw(handler, event, {}))
    assert result == "ok"
    handler.assert_awaited_once()


def test_middleware_passes_through_when_state_is_none_string():
    """state.get_state 返回 None → 不更新 _last_active，调下游。"""
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    mw = FSMTimeoutMiddleware(timeout_seconds=300)
    state = _make_state(current_state=None, last_active=None)
    handler = AsyncMock(return_value="ok")
    event = MagicMock()
    result = _run(mw(handler, event, {"state": state}))
    assert result == "ok"
    handler.assert_awaited_once()
    # 不应污染 _last_active
    state.update_data.assert_not_called()


def test_middleware_updates_last_active_on_active_state():
    """state 已在某个 FSM state + 未超时 → 更新 _last_active 后调下游。"""
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    mw = FSMTimeoutMiddleware(timeout_seconds=300)
    state = _make_state(
        current_state="TestStates:step1", last_active=time.time() - 10,
    )
    handler = AsyncMock(return_value="ok")
    event = MagicMock()
    _run(mw(handler, event, {"state": state}))
    handler.assert_awaited_once()
    state.update_data.assert_awaited_once()
    # update_data 收到 _last_active key
    call = state.update_data.await_args
    assert "_last_active" in call.kwargs


def test_middleware_clears_state_when_timeout():
    """state 超过 timeout_seconds → state.clear() + 通知用户 + 不调下游。"""
    from aiogram.types import Message
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    mw = FSMTimeoutMiddleware(timeout_seconds=300)
    state = _make_state(
        current_state="TestStates:step1",
        last_active=time.time() - 1000,  # 远超 300 秒
    )
    handler = AsyncMock()
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock(return_value=None)
    result = _run(mw(handler, msg, {"state": state}))
    # 应 clear + 不调下游
    state.clear.assert_awaited_once()
    handler.assert_not_called()
    # 应给用户通知
    msg.answer.assert_awaited_once()
    text = msg.answer.await_args.args[0] if msg.answer.await_args.args else msg.answer.await_args.kwargs.get("text", "")
    assert "超过" in text or "超时" in text or "已自动取消" in text


def test_middleware_timeout_notification_for_callback_query():
    """CallbackQuery 类型事件超时时调 callback.answer with show_alert=True。"""
    from aiogram.types import CallbackQuery
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    mw = FSMTimeoutMiddleware(timeout_seconds=300)
    state = _make_state(
        current_state="TestStates:step1",
        last_active=time.time() - 1000,
    )
    handler = AsyncMock()
    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock(return_value=None)
    _run(mw(handler, cb, {"state": state}))
    cb.answer.assert_awaited_once()
    call = cb.answer.await_args
    assert call.kwargs.get("show_alert") is True


def test_middleware_first_visit_no_last_active_does_not_timeout():
    """首次进入 FSM 时 _last_active=0 → 不应判定超时（避免新进 FSM 立即被清）。"""
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    mw = FSMTimeoutMiddleware(timeout_seconds=300)
    # last_active 字段不存在（首次进入）
    state = MagicMock()
    state.get_state = AsyncMock(return_value="TestStates:step1")
    state.get_data = AsyncMock(return_value={})  # 无 _last_active
    state.update_data = AsyncMock(return_value=None)
    state.clear = AsyncMock(return_value=None)
    handler = AsyncMock(return_value="ok")
    event = MagicMock()
    result = _run(mw(handler, event, {"state": state}))
    assert result == "ok"
    handler.assert_awaited_once()
    state.clear.assert_not_called()


def test_middleware_notification_failure_swallowed():
    """通知发送失败（如用户屏蔽 bot）不应阻塞 state.clear。"""
    from aiogram.types import Message
    from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
    mw = FSMTimeoutMiddleware(timeout_seconds=300)
    state = _make_state(
        current_state="TestStates:step1",
        last_active=time.time() - 1000,
    )
    handler = AsyncMock()
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock(side_effect=RuntimeError("blocked"))
    # 不应抛
    _run(mw(handler, msg, {"state": state}))
    state.clear.assert_awaited_once()


# ============================================================
# 3. teacher_flow 重构（兼容性）
# ============================================================


def test_teacher_flow_imports_new_middleware():
    """teacher_flow.py 应 import bot.middlewares.fsm_timeout。"""
    import bot.handlers.teacher_flow as mod
    src = _src(mod)
    assert "from bot.middlewares.fsm_timeout import" in src
    assert "FSMTimeoutMiddleware" in src


def test_teacher_flow_no_longer_defines_class_locally():
    """teacher_flow.py 不应再定义 FSMTimeoutMiddleware 类（已抽到 middlewares）。"""
    import bot.handlers.teacher_flow as mod
    src = _src(mod)
    assert "class FSMTimeoutMiddleware" not in src


def test_teacher_flow_uses_default_5min_timeout():
    """teacher_flow router 应用 DEFAULT_FSM_TIMEOUT_SECONDS（5 分钟）。"""
    import bot.handlers.teacher_flow as mod
    src = _src(mod)
    assert "FSM_TIMEOUT = DEFAULT_FSM_TIMEOUT_SECONDS" in src
    # 中间件注册仍存在
    assert "router.message.middleware" in src
    assert "router.callback_query.middleware" in src


# ============================================================
# 4. teacher_profile 接入（UX-9.2 主体）
# ============================================================


def test_teacher_profile_imports_middleware():
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    assert "from bot.middlewares.fsm_timeout import" in src
    assert "FSMTimeoutMiddleware" in src


def test_teacher_profile_registers_middleware_on_router():
    """teacher_profile router 应注册 FSMTimeoutMiddleware。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    assert "router.message.middleware(" in src
    assert "router.callback_query.middleware(" in src
    assert "FSMTimeoutMiddleware(" in src


def test_teacher_profile_uses_long_timeout():
    """teacher_profile 应用 LONG_FSM_TIMEOUT_SECONDS（30 分钟），不用默认 5 分钟。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    assert "LONG_FSM_TIMEOUT_SECONDS" in src
    # 注册时使用该常量
    assert "timeout_seconds=LONG_FSM_TIMEOUT_SECONDS" in src


# ============================================================
# 5. 其它长 FSM router 本批不动（业务保护）
# ============================================================


# Phase A0（2026-05-23）已下线：test_admin_lottery_router_unchanged_by_this_pr
# （抽奖功能整体下线）


def test_review_card_router_unchanged_by_this_pr():
    import bot.handlers.review_card as mod
    src = _src(mod)
    assert "FSMTimeoutMiddleware" not in src


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS

"""报销审核 + 支付宝口令红包发放流程 - 完整契约测试（2026-05）。

覆盖 spec 测试要求 1-34：
    报告审核通过提醒超管 (1-5)
    报销审核通过后输入口令 (6-15)
    确认发送 (16-23)
    权限 (24-26)
    兼容性 (27-32)
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import uuid

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_payout_{uuid.uuid4().hex}_", suffix=".db",
    )
    os.close(fd)
    from bot.config import config as _config
    original_path = _config.database_path
    _config.database_path = path
    try:
        from bot.database import init_db
        asyncio.run(init_db())
        yield path
    finally:
        _config.database_path = original_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass


def _run(coro):
    return asyncio.run(coro)


def _src(module) -> str:
    return inspect.getsource(module)


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


# ============================================================
# 1. POWERED_BY_FOOTER 常量与所有文案
# ============================================================


def test_powered_by_footer_constant_exists():
    from bot.utils.reimburse_notify import POWERED_BY_FOOTER
    assert POWERED_BY_FOOTER == "✳ Powered by @CDCChiYanLog"


def test_supers_pending_text_includes_footer_and_buttons_info():
    """超管收到的报销待审核通知文案：含金额 / 用户 / 老师 / 报销 id / footer。"""
    from bot.utils.reimburse_notify import format_supers_pending_text, POWERED_BY_FOOTER
    text = format_supers_pending_text(
        reimb_id=42, user_id=10001, user_label="@alice",
        teacher_label="老师A", review_id=99, amount=100, status="pending",
    )
    assert "@alice" in text
    assert "10001" in text
    assert "老师A" in text
    assert "#99" in text
    assert "#42" in text
    assert "100 元" in text
    assert "待审核" in text
    assert POWERED_BY_FOOTER in text


def test_payout_waiting_token_text_includes_footer():
    from bot.utils.reimburse_notify import format_payout_waiting_token_text, POWERED_BY_FOOTER
    text = format_payout_waiting_token_text()
    assert "请输入支付宝口令红包口令" in text
    assert POWERED_BY_FOOTER in text


def test_payout_confirm_text_includes_amount_user_token_and_footer():
    from bot.utils.reimburse_notify import format_payout_confirm_text, POWERED_BY_FOOTER
    text = format_payout_confirm_text(
        user_id=10001, user_label="@alice", amount=100, token="TESTTOKEN123",
    )
    assert "@alice" in text
    assert "10001" in text
    assert "100 元" in text
    assert "TESTTOKEN123" in text
    assert POWERED_BY_FOOTER in text


def test_user_payout_message_includes_token_amount_and_footer():
    from bot.utils.reimburse_notify import format_user_payout_message, POWERED_BY_FOOTER
    text = format_user_payout_message(token="ABCDEFG", amount=88)
    assert "ABCDEFG" in text
    assert "88 元" in text
    assert "已通过" in text
    assert POWERED_BY_FOOTER in text


def test_payout_done_text_includes_user_amount_and_footer():
    from bot.utils.reimburse_notify import format_payout_done_text, POWERED_BY_FOOTER
    text = format_payout_done_text(user_label="@alice", user_id=10001, amount=50)
    assert "@alice" in text
    assert "10001" in text
    assert "50 元" in text
    assert "已发送" in text or "完成" in text
    assert POWERED_BY_FOOTER in text


# ============================================================
# 2. mask_token 不保存完整口令
# ============================================================


def test_mask_token_long_string():
    from bot.utils.reimburse_notify import mask_token
    assert mask_token("ABCDEFGH") == "AB***GH"
    assert mask_token("HelloWorld") == "He***ld"


def test_mask_token_short_returns_stars():
    from bot.utils.reimburse_notify import mask_token
    assert mask_token("AB") == "***"
    assert mask_token("ABCD") == "***"
    assert mask_token("") == ""


# ============================================================
# 3. notify_supers_reimburse_pending：通知所有超管，失败不影响
# ============================================================


def test_notify_supers_reimburse_pending_sends_to_all_supers(temp_db):
    """通知所有 super_admin（含主超管 + DB is_super=1）。"""
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.reimburse_notify import notify_supers_reimburse_pending

    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(notify_supers_reimburse_pending(
        bot, reimb_id=1, user_id=10001, user_label="@u",
        teacher_label="T", review_id=5, amount=100, status="pending",
    ))
    # 至少通知主超管一次
    assert bot.send_message.await_count >= 1
    # 每次 send_message 的 text 都应含 footer
    for call in bot.send_message.await_args_list:
        kwargs = call.kwargs
        assert "✳ Powered by @CDCChiYanLog" in kwargs.get("text", "")


def test_notify_supers_failure_does_not_raise(temp_db):
    """super 发送失败不应抛出异常给调用方。"""
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.reimburse_notify import notify_supers_reimburse_pending

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("boom"))
    # 不应 raise
    _run(notify_supers_reimburse_pending(
        bot, reimb_id=1, user_id=10001, user_label="@u",
        teacher_label="T", review_id=5, amount=100, status="pending",
    ))


# ============================================================
# 4. 报告审核通过提醒超管：rreview_admin 接入点
# ============================================================


def test_rreview_admin_calls_notify_supers_after_create_reimbursement():
    """_do_approve_inner 在 create_reimbursement 成功后调用 notify_supers_reimburse_pending。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    idx = src.find("async def _do_approve_inner(")
    assert idx > 0
    body = src[idx:idx + 12000]
    assert "notify_supers_reimburse_pending" in body, (
        "_do_approve_inner 应在 create_reimbursement 成功后调用 notify_supers_reimburse_pending"
    )


def test_rreview_admin_notify_inside_reimb_created_id_branch():
    """通知逻辑应在 if reimb_created_id: 分支内（即报销创建成功后才通知）。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    idx = src.find("if reimb_created_id:")
    assert idx > 0
    # 取 if 分支内的 ~3000 字符（直到下一个外层 except 或顶级语句）
    body = src[idx:idx + 3000]
    assert "notify_supers_reimburse_pending" in body


def test_rreview_admin_does_not_notify_when_reimb_not_created():
    """create_reimbursement 失败时，notify 不应被调用——通过静态检查
    notify 调用在 if reimb_created_id 分支内（前一条 test 已验证）。"""
    pass  # 由 test_rreview_admin_notify_inside_reimb_created_id_branch 覆盖


# ============================================================
# 5. 超管通知 keyboard
# ============================================================


def test_reimburse_pending_super_notice_kb_buttons():
    from bot.keyboards.admin_kb import reimburse_pending_super_notice_kb
    cbs = _cbs(reimburse_pending_super_notice_kb())
    assert "reimburse:enter" in cbs
    assert "admin:review_tasks" in cbs


# ============================================================
# 6-15. 报销审核同意 → FSM → 输入口令 → 校验
# ============================================================


def test_cb_reimburse_approve_does_not_call_approve_reimbursement_synchronously():
    """点击同意报销后，不立即调 approve_reimbursement —— 应进入 FSM。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_approve(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    # 函数体内不应有 approve_reimbursement( 调用（旧实现有）
    assert "approve_reimbursement(" not in body, (
        "cb_reimburse_approve 不应再直接调用 approve_reimbursement（应延迟到 payout confirm）"
    )
    # 必须进入 FSM
    assert "ReimbursePayoutStates.waiting_token" in body
    assert "set_state" in body


def test_payout_states_imported_in_admin_reimburse():
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "ReimbursePayoutStates" in src
    # 应来自 teacher_states
    assert "from bot.states.teacher_states import" in src and "ReimbursePayoutStates" in src


def test_payout_token_handler_validates_empty_short_long(temp_db):
    """step_reimburse_payout_token 校验空 / 过短 / 过长。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def step_reimburse_payout_token(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    # 空校验
    assert "不能为空" in body
    # 过短 / 过长校验
    assert "_TOKEN_MIN_LEN" in body or "过短" in body
    assert "_TOKEN_MAX_LEN" in body or "过长" in body


def test_payout_token_min_max_constants_exist():
    """常量定义在 admin_reimburse.py 中。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "_TOKEN_MIN_LEN" in src
    assert "_TOKEN_MAX_LEN" in src


def test_payout_waiting_kb_has_cancel_only():
    from bot.keyboards.admin_kb import reimburse_payout_waiting_cancel_kb
    cbs = _cbs(reimburse_payout_waiting_cancel_kb(reimb_id=42))
    assert "reimburse:payout:cancel:42" in cbs
    # 不应有 confirm（confirm 在 confirming 状态显示）
    assert "reimburse:payout:confirm:42" not in cbs


def test_payout_confirm_kb_has_confirm_retry_cancel():
    from bot.keyboards.admin_kb import reimburse_payout_confirm_kb
    cbs = _cbs(reimburse_payout_confirm_kb(reimb_id=42))
    assert "reimburse:payout:confirm:42" in cbs
    assert "reimburse:payout:retry:42" in cbs
    assert "reimburse:payout:cancel:42" in cbs


def test_payout_done_kb_has_next_and_review_tasks():
    from bot.keyboards.admin_kb import reimburse_payout_done_kb
    cbs = _cbs(reimburse_payout_done_kb())
    assert "reimburse:enter" in cbs       # 处理下一条
    assert "admin:review_tasks" in cbs    # 返回审核处理


# ============================================================
# 16-23. 确认发送 + audit log
# ============================================================


def test_payout_confirm_handler_sends_user_before_approving():
    """cb_reimburse_payout_confirm 必须先 safe_send_user_payout，成功后才 approve_reimbursement。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_payout_confirm(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    send_pos = body.find("safe_send_user_payout")
    approve_pos = body.find("approve_reimbursement(")
    assert send_pos > 0 and approve_pos > 0
    assert send_pos < approve_pos, (
        "应先 safe_send_user_payout，成功后才 approve_reimbursement"
    )


def test_payout_confirm_writes_audit_log_with_masked_token():
    """payout confirm 必须写 audit log 且仅含 masked token。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_payout_confirm(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "log_admin_audit" in body
    assert "reimburse_payout_sent" in body
    assert "mask_token" in body
    # 不应把完整 token 直接写入 audit detail
    # 静态匹配："token" key 字面量出现，但其值用 mask_token 包裹
    assert '"token": token' not in body
    assert '"token": str(token)' not in body


def test_payout_confirm_clears_fsm_after_success():
    """成功后 state.clear() 清理 FSM。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_payout_confirm(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "state.clear()" in body


def test_payout_confirm_does_not_approve_on_send_failure():
    """如果 safe_send_user_payout 返回 (False, err)，不应 approve_reimbursement。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_payout_confirm(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    # 静态保证：失败分支应在 approve 之前 return
    assert "if not ok:" in body
    # 失败分支应含 return
    fail_idx = body.find("if not ok:")
    assert "return" in body[fail_idx:fail_idx + 500]


# ============================================================
# 24-26. 权限：仅超管
# ============================================================


def test_all_payout_handlers_super_admin_required():
    """所有 payout 流程的 handler / message handler 都使用 _super_admin_required。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    for fn_name in (
        "cb_reimburse_approve",
        "step_reimburse_payout_token",
        "cb_reimburse_payout_retry",
        "cb_reimburse_payout_cancel",
        "cb_reimburse_payout_confirm",
    ):
        idx = src.find(f"async def {fn_name}(")
        assert idx > 0, f"找不到 {fn_name}"
        window = src[max(0, idx - 300):idx]
        assert "@_super_admin_required" in window, (
            f"{fn_name} 应使用 @_super_admin_required"
        )


# ============================================================
# 27-32. 兼容性 / 业务隔离
# ============================================================


def test_reject_callback_handler_unchanged():
    """reimburse:reject:* handler 仍存在。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "reimburse:reject:" in src or 'F.data.startswith("reimburse:reject:")' in src


def test_queued_handlers_unchanged():
    """reimburse:queued / activate 仍存在。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "reimburse:queued" in src
    assert "reimburse:activate" in src


def test_reset_voucher_handler_unchanged():
    """reset voucher 流程仍存在。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "reimburse:reset:" in src
    assert "reimburse:reset_ok:" in src


def test_compute_reimbursement_amount_unchanged():
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)


def test_approve_reimbursement_db_function_unchanged():
    """approve_reimbursement DB 函数体未触动（仍把 pending → approved）。"""
    from bot.database import approve_reimbursement
    src = inspect.getsource(approve_reimbursement)
    assert "approved" in src
    assert "pending" in src


def test_schema_migrations_baseline_unchanged():
    """本批不动 schema（仅 FSM + handler 改动）。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []


def test_reimburse_subreq_gate_unchanged():
    """报销专用必关 gate 未受影响。"""
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    assert callable(check_user_subscribed_for_reimburse)


def test_global_required_channels_unchanged():
    """全局 subreq helper 未受影响。"""
    from bot.utils.required_channels import check_user_subscribed
    assert callable(check_user_subscribed)


# ============================================================
# Bonus：safe_send_user_payout 返回值约定
# ============================================================


def test_safe_send_user_payout_returns_true_on_success():
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.reimburse_notify import safe_send_user_payout
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    ok, err = _run(safe_send_user_payout(
        bot, user_id=10001, token="TOKEN1234", amount=100,
    ))
    assert ok is True
    assert err is None
    bot.send_message.assert_awaited_once()


def test_safe_send_user_payout_returns_false_on_exception():
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.reimburse_notify import safe_send_user_payout
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("blocked"))
    ok, err = _run(safe_send_user_payout(
        bot, user_id=10001, token="TOKEN1234", amount=100,
    ))
    assert ok is False
    assert err is not None
    assert "RuntimeError" in err


def test_safe_send_user_payout_message_text_includes_token_and_footer():
    """实际发送给用户的文本含 token + footer。"""
    from unittest.mock import AsyncMock, MagicMock
    from bot.utils.reimburse_notify import safe_send_user_payout
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(safe_send_user_payout(
        bot, user_id=10001, token="SPECIFIC_TOKEN_XYZ", amount=100,
    ))
    call = bot.send_message.await_args
    text = call.kwargs.get("text", "")
    assert "SPECIFIC_TOKEN_XYZ" in text
    assert "100 元" in text
    assert "✳ Powered by @CDCChiYanLog" in text


# ============================================================
# 新增 FSM 状态可 import
# ============================================================


def test_reimburse_payout_states_importable():
    from bot.states.teacher_states import ReimbursePayoutStates
    assert ReimbursePayoutStates.waiting_token is not None
    assert ReimbursePayoutStates.confirming is not None
    # 与 ReimburseRejectStates 隔离
    from bot.states.teacher_states import ReimburseRejectStates
    assert ReimbursePayoutStates is not ReimburseRejectStates


# ============================================================
# UX-10.1 支付口令 chat type 守卫
# ============================================================


def test_payout_token_handler_rejects_non_private_chat():
    """step_reimburse_payout_token 必须在读取 token 前拒绝非私聊消息。

    超管若在群里粘贴口令，消息已被群成员看到；守卫至少要保证
    bot 端不再继续处理（避免 confirming page 进一步回显 token）
    且给出提示，让超管意识到泄露风险。
    """
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def step_reimburse_payout_token(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]

    # 1. 必须有 chat.type 守卫
    assert 'message.chat.type != "private"' in body, "需 chat.type 守卫"

    # 2. 守卫必须在 token 读取之前（用精确的代码 anchor 避免命中注释）
    guard_pos = body.find('message.chat.type != "private"')
    token_read_pos = body.find("token = (message.text")
    assert 0 < guard_pos < token_read_pos, (
        "chat.type 守卫必须早于 token 读取，避免下游路径意外回显 token"
    )

    # 3. 守卫必须在 state 写入 / 校验之前
    state_write_pos = body.find("state.update_data")
    set_state_pos = body.find("state.set_state")
    if state_write_pos > 0:
        assert guard_pos < state_write_pos
    if set_state_pos > 0:
        assert guard_pos < set_state_pos

    # 4. 守卫命中后必须给提示（避免静默 → 超管不知道发错地方）
    guard_block = body[guard_pos:guard_pos + 800]
    assert "私聊" in guard_block, "守卫命中后应明确提示需在私聊发送"

    # 5. 守卫必须 return（不能 fallthrough）
    assert "return" in guard_block

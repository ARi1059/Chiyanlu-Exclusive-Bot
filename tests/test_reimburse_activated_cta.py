"""Sprint UX-4 第四项（UX-4.4）：queued 激活通知 + CTA 按钮契约测试。

范围：cb_reimburse_activate 成功激活 queued → pending 后给用户的中间状态通知。

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C1 + §4.2 痛点 6 + §11.3）：
    POLICY-reimbursement §9.6 标注：queued 激活后**不通知用户**，用户对状态变化
    完全被动；本批补这条通知，文案 + CTA keyboard：

        - [📋 我的报销]    callback=user:reimburse  含当前状态
        - [🏠 返回主菜单]  callback=user:main       兜底

约束：
    - 不写 mark_reimbursement_notified（POLICY §12.7 该字段语义是"已通过/驳回"终态）
    - 通知失败仅 logger.warning，不影响 cb_reimburse_activate 主流程
    - 不改 callback_data；user:reimburse / user:main 早已存在
    - 不改 audit log 写入
    - 不改 reimburse:activate 状态机（仍是 queued → pending）
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest  # noqa: F401


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


def _src(module) -> str:
    return inspect.getsource(module)


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


# ============================================================
# 1. 文案 helper
# ============================================================


def test_activated_text_contains_required_fields():
    from bot.utils.reimburse_notify import (
        format_user_reimburse_activated_text,
        POWERED_BY_FOOTER,
    )
    text = format_user_reimburse_activated_text(reimb_id=42, amount=80)
    assert "#42" in text
    assert "80 元" in text
    # 应清晰传达"激活进入审核队列"语义
    assert "激活" in text or "审核队列" in text
    assert POWERED_BY_FOOTER in text


def test_activated_text_does_not_promise_approval():
    """文案不应让用户误以为已通过（"已批准 / 已通过 / 红包" 等终态语言）。"""
    from bot.utils.reimburse_notify import format_user_reimburse_activated_text
    text = format_user_reimburse_activated_text(reimb_id=42, amount=80)
    assert "已通过" not in text
    assert "已批准" not in text
    assert "口令" not in text
    assert "红包" not in text


# ============================================================
# 2. keyboard 契约
# ============================================================


def test_activated_kb_has_two_buttons():
    from bot.utils.reimburse_notify import build_user_reimburse_activated_kb
    kb = build_user_reimburse_activated_kb()
    assert len(_flat_buttons(kb)) == 2


def test_activated_kb_contains_user_reimburse_and_main():
    from bot.utils.reimburse_notify import build_user_reimburse_activated_kb
    kb = build_user_reimburse_activated_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:reimburse" in cbs
    assert "user:main" in cbs


def test_activated_kb_no_url_buttons():
    from bot.utils.reimburse_notify import build_user_reimburse_activated_kb
    kb = build_user_reimburse_activated_kb()
    for b in _flat_buttons(kb):
        assert b.url is None


def test_activated_kb_order_my_reimburse_first():
    from bot.utils.reimburse_notify import build_user_reimburse_activated_kb
    kb = build_user_reimburse_activated_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert cbs.index("user:reimburse") < cbs.index("user:main")


# ============================================================
# 3. safe_notify_user_reimburse_activated 行为
# ============================================================


def test_safe_notify_activated_success_attaches_keyboard():
    """成功路径：bot.send_message 被调用一次，含 chat_id / text / reply_markup。"""
    from bot.utils.reimburse_notify import safe_notify_user_reimburse_activated
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    ok = _run(safe_notify_user_reimburse_activated(
        bot, user_id=1001, reimb_id=42, amount=80,
    ))
    assert ok is True
    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args
    assert call.kwargs["chat_id"] == 1001
    text = call.kwargs["text"]
    assert "#42" in text
    assert "80 元" in text
    kb = call.kwargs["reply_markup"]
    assert kb is not None
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:reimburse" in cbs
    assert "user:main" in cbs


def test_safe_notify_activated_swallows_exceptions_returns_false():
    """bot.send_message 抛异常时返回 False，不向上抛。"""
    from bot.utils.reimburse_notify import safe_notify_user_reimburse_activated

    class BoomError(Exception):
        pass

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=BoomError("forbidden"))
    ok = _run(safe_notify_user_reimburse_activated(
        bot, user_id=1001, reimb_id=42, amount=80,
    ))
    assert ok is False


# ============================================================
# 4. cb_reimburse_activate 接入静态契约
# ============================================================


def test_activate_handler_uses_safe_notify():
    """cb_reimburse_activate 必须调用 safe_notify_user_reimburse_activated。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_activate(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "safe_notify_user_reimburse_activated" in body


def test_safe_notify_activated_imported_in_admin_reimburse():
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "safe_notify_user_reimburse_activated" in src


def test_activate_handler_still_writes_audit_log():
    """UX-4.4 不改 reimburse_activate audit log。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_activate(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert 'action="reimburse_activate"' in body
    assert "log_admin_audit" in body


def test_activate_handler_does_not_mark_notified():
    """关键约束：激活通知不应写入 mark_reimbursement_notified
    （POLICY §12.7 该字段语义是"已通过/驳回 终态通知"）。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_activate(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "mark_reimbursement_notified" not in body


def test_activate_handler_still_calls_activate_queued():
    """业务逻辑保护：仍调用 activate_queued_reimbursement 切换状态。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_activate(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "activate_queued_reimbursement" in body


def test_activate_handler_notification_after_db_success():
    """通知应在 activate_queued_reimbursement 成功之后才发；
    否则会出现"数据库未切换但用户已收到 '已激活' 通知"的不一致。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_activate(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    activate_pos = body.find("activate_queued_reimbursement")
    notify_pos = body.find("safe_notify_user_reimburse_activated")
    assert 0 < activate_pos < notify_pos


# ============================================================
# 5. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}

"""Sprint UX-4 第二项（UX-4.2）：报销通过 / 口令发放通知 + CTA 按钮契约测试。

范围：build_user_reimburse_approved_kb（新增）+ safe_send_user_payout（注入 keyboard）。

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C1 + §11.3）：
    用户拿到支付宝口令红包后是纯文本死胡同，兑换完成想看本月统计 / 回主菜单
    需要手动 /start 或滚回历史。本批让通知附 2 个按钮：

        - [📋 我的报销]    callback=user:reimburse
        - [🏠 返回主菜单]  callback=user:main

约束：
    - 不改 callback_data；user:reimburse / user:main 早已存在
    - 不改 safe_send_user_payout 的签名与返回值结构（仍是 (ok, err)）
    - 不改 mark_reimbursement_notified 时机
    - 不引入"报销池剩余"独立按钮（信息已在 user:reimburse 总览页呈现）
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest  # noqa: F401  保持与其它 _cta 测试一致的 import 风格


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
# 1. build_user_reimburse_approved_kb 契约
# ============================================================


def test_approved_kb_has_exactly_two_buttons():
    """approved keyboard 必有且仅有 2 个按钮（不引入"报销池剩余"独立按钮）。"""
    from bot.utils.reimburse_notify import build_user_reimburse_approved_kb
    kb = build_user_reimburse_approved_kb()
    btns = _flat_buttons(kb)
    assert len(btns) == 2


def test_approved_kb_contains_my_reimburse_callback():
    from bot.utils.reimburse_notify import build_user_reimburse_approved_kb
    kb = build_user_reimburse_approved_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:reimburse" in cbs


def test_approved_kb_contains_user_main_callback():
    """主菜单兜底应用 user:main（用户侧），不是 menu:main（管理员侧）。"""
    from bot.utils.reimburse_notify import build_user_reimburse_approved_kb
    kb = build_user_reimburse_approved_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:main" in cbs
    assert "menu:main" not in cbs


def test_approved_kb_order_my_reimburse_first():
    """[📋 我的报销] 应排在 [🏠 返回主菜单] 之前（高频在前）。"""
    from bot.utils.reimburse_notify import build_user_reimburse_approved_kb
    kb = build_user_reimburse_approved_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert cbs.index("user:reimburse") < cbs.index("user:main")


def test_approved_kb_no_url_buttons():
    """approved keyboard 不应含 URL 按钮（与 reject 通知不同，这里不需要客服群链接）。"""
    from bot.utils.reimburse_notify import build_user_reimburse_approved_kb
    kb = build_user_reimburse_approved_kb()
    for b in _flat_buttons(kb):
        assert b.url is None


# ============================================================
# 2. safe_send_user_payout 行为：附 keyboard + 不破坏既有契约
# ============================================================


def test_safe_send_user_payout_attaches_keyboard():
    """成功路径：bot.send_message 调用应含 reply_markup（含 user:reimburse 按钮）。"""
    from bot.utils.reimburse_notify import safe_send_user_payout
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    ok, err = _run(safe_send_user_payout(
        bot, user_id=1001, token="TOKEN_X", amount=80,
    ))
    assert ok is True
    assert err is None
    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args
    kb = call.kwargs.get("reply_markup")
    assert kb is not None, "口令通知必须带 keyboard"
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:reimburse" in cbs
    assert "user:main" in cbs


def test_safe_send_user_payout_message_text_still_contains_token_and_footer():
    """UX-4.2 不应影响既有 payout 文案（含 token + 金额 + footer）。"""
    from bot.utils.reimburse_notify import safe_send_user_payout
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(safe_send_user_payout(
        bot, user_id=1001, token="UNIQUE_TOKEN_42", amount=80,
    ))
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert "UNIQUE_TOKEN_42" in text
    assert "80 元" in text
    assert "✳ Powered by @CDCChiYanLog" in text


def test_safe_send_user_payout_keeps_failure_contract():
    """失败路径：bot 抛异常时仍返回 (False, error_str) 元组，不抛。"""
    from bot.utils.reimburse_notify import safe_send_user_payout

    class BoomError(Exception):
        pass

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=BoomError("forbidden"))
    ok, err = _run(safe_send_user_payout(
        bot, user_id=1001, token="x", amount=10,
    ))
    assert ok is False
    assert err is not None
    assert "BoomError" in err and "forbidden" in err


def test_safe_send_user_payout_signature_unchanged():
    """签名保护：调用方仍按 (bot, *, user_id, token, amount) 调用。"""
    from bot.utils.reimburse_notify import safe_send_user_payout
    sig = inspect.signature(safe_send_user_payout)
    params = list(sig.parameters)
    assert params == ["bot", "user_id", "token", "amount"]
    # user_id / token / amount 仍为 keyword-only
    assert sig.parameters["user_id"].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["token"].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["amount"].kind == inspect.Parameter.KEYWORD_ONLY


# ============================================================
# 3. callback handler 存在性（防止本批接入死按钮）
# ============================================================


def test_user_reimburse_callback_handler_registered():
    """user:reimburse callback 必须有 handler 注册。"""
    import bot.handlers.user_reimburse as mod
    src = _src(mod)
    assert 'F.data == "user:reimburse"' in src


def test_user_main_callback_handler_registered():
    """user:main callback 必须有 handler 注册（用户主菜单）。"""
    import bot.handlers.user_panel as mod
    src = _src(mod)
    assert 'F.data == "user:main"' in src


# ============================================================
# 4. 调用方 cb_reimburse_payout_confirm 仍走 safe_send_user_payout
# ============================================================


def test_payout_confirm_still_uses_safe_send_user_payout():
    """UX-4.2 不改 confirm handler；仍通过 safe_send_user_payout 发送给用户。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_reimburse_payout_confirm(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "safe_send_user_payout" in body


# ============================================================
# 5. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}

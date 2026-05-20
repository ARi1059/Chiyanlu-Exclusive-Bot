"""Sprint UX-4 第一项（UX-4.1）：报销驳回通知 + CTA 按钮契约测试。

范围：driver `safe_notify_user_reimburse_reject` 与对应 keyboard / 文案 helper。

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C1 + §11.1）：
    用户收到报销驳回通知时是纯文本死胡同，需要主动重新进 bot 才能查看历史 / 联系客服。
    本批新增 keyboard：
        - [📩 联系客服申诉]  url=<contact_url>  仅当 config 配置时显示
        - [📋 我的报销]      callback=user:reimburse  始终显示
    contact_url 读取优先级：reimburse_contact_url → lottery_contact_url。
    config 双空时只显示「我的报销」一个按钮，**不引入死链**。

约束：
    - 不改 callback_data；user:reimburse 早已存在。
    - 不引入 schema 迁移。
    - 不引入 reverse approval；申诉按钮仅 URL 跳转。
    - admin_reimburse handler 必须改用 safe_notify_user_reimburse_reject，
      不再直接 inline 拼 send_message 文案。
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_reim_cta_{uuid.uuid4().hex}_", suffix=".db",
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


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


# ============================================================
# 1. 文案 helper
# ============================================================


def test_format_user_reimburse_reject_text_contains_required_fields():
    """文案应含 reimb_id、金额、原因、未通过提示、统一页脚。"""
    from bot.utils.reimburse_notify import (
        format_user_reimburse_reject_text,
        POWERED_BY_FOOTER,
    )
    text = format_user_reimburse_reject_text(
        reimb_id=123, amount=50, reason="证据不充分",
    )
    assert "#123" in text
    assert "50 元" in text
    assert "证据不充分" in text
    assert "未通过" in text or "❌" in text
    assert POWERED_BY_FOOTER in text


# ============================================================
# 2. keyboard 构造（异步，依赖 config）
# ============================================================


def test_reject_kb_when_no_contact_url_has_only_my_reimburse(temp_db):
    """config 双空时：keyboard 只含 [📋 我的报销] 一个按钮，不应有 url 按钮。"""
    from bot.utils.reimburse_notify import build_user_reimburse_reject_kb
    kb = _run(build_user_reimburse_reject_kb())
    btns = _flat_buttons(kb)
    assert len(btns) == 1
    assert btns[0].callback_data == "user:reimburse"
    assert btns[0].url is None


def test_reject_kb_falls_back_to_lottery_contact_url(temp_db):
    """reimburse_contact_url 未配，但 lottery_contact_url 已配 → 使用后者。"""
    from bot.database import set_config
    from bot.utils.reimburse_notify import build_user_reimburse_reject_kb
    _run(set_config("lottery_contact_url", "https://t.me/lottery_admin"))
    kb = _run(build_user_reimburse_reject_kb())
    btns = _flat_buttons(kb)
    assert len(btns) == 2
    # 第一个按钮：申诉 URL
    assert "申诉" in btns[0].text or "客服" in btns[0].text
    assert btns[0].url == "https://t.me/lottery_admin"
    # 第二个按钮：我的报销 callback
    assert btns[1].callback_data == "user:reimburse"


def test_reject_kb_prefers_reimburse_contact_url_over_lottery(temp_db):
    """两个 config 都配时优先 reimburse_contact_url。"""
    from bot.database import set_config
    from bot.utils.reimburse_notify import build_user_reimburse_reject_kb
    _run(set_config("lottery_contact_url", "https://t.me/lottery_admin"))
    _run(set_config("reimburse_contact_url", "https://t.me/reimburse_admin"))
    kb = _run(build_user_reimburse_reject_kb())
    btns = _flat_buttons(kb)
    assert len(btns) == 2
    assert btns[0].url == "https://t.me/reimburse_admin"


def test_reject_kb_blank_contact_url_treated_as_unconfigured(temp_db):
    """空字符串 / 仅空白的 config 视为未配，回落到下一级。"""
    from bot.database import set_config
    from bot.utils.reimburse_notify import build_user_reimburse_reject_kb
    _run(set_config("reimburse_contact_url", "   "))
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    kb = _run(build_user_reimburse_reject_kb())
    btns = _flat_buttons(kb)
    # 空白被 strip 视为未配，回落到 lottery_contact_url
    assert len(btns) == 2
    assert btns[0].url == "https://t.me/L"


# ============================================================
# 3. safe_notify_user_reimburse_reject 行为
# ============================================================


def test_safe_notify_success_path_sends_with_keyboard(temp_db):
    """成功路径：bot.send_message 被调用一次，含 chat_id / text / reply_markup。"""
    from bot.database import set_config
    from bot.utils.reimburse_notify import safe_notify_user_reimburse_reject
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    ok = _run(safe_notify_user_reimburse_reject(
        bot, user_id=1001, reimb_id=42, amount=80, reason="价格异常",
    ))
    assert ok is True
    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args
    assert call.kwargs["chat_id"] == 1001
    text = call.kwargs["text"]
    assert "#42" in text
    assert "80 元" in text
    assert "价格异常" in text
    # keyboard 一并下发
    kb = call.kwargs["reply_markup"]
    assert kb is not None
    btns = _flat_buttons(kb)
    assert any(b.callback_data == "user:reimburse" for b in btns)


def test_safe_notify_swallows_exceptions_returns_false(temp_db):
    """bot.send_message 抛异常时返回 False，不向上抛（审批主流程不应被通知失败影响）。"""
    from bot.utils.reimburse_notify import safe_notify_user_reimburse_reject

    class BoomError(Exception):
        pass

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=BoomError("forbidden"))
    ok = _run(safe_notify_user_reimburse_reject(
        bot, user_id=1001, reimb_id=42, amount=80, reason="any",
    ))
    assert ok is False


# ============================================================
# 4. admin_reimburse handler 集成（静态契约）
# ============================================================


def test_reject_reason_handler_uses_safe_notify():
    """on_reimburse_reject_reason 必须调用 safe_notify_user_reimburse_reject，
    且不再直接 inline 拼 send_message 驳回文案。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def on_reimburse_reject_reason(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]

    # 必须用 safe_notify_user_reimburse_reject
    assert "safe_notify_user_reimburse_reject" in body, (
        "on_reimburse_reject_reason 应改用 safe_notify_user_reimburse_reject"
    )
    # 不应再 inline 拼老式驳回文案
    assert "你的报销申请 #" not in body, (
        "旧 inline 文案应已被 safe_notify_user_reimburse_reject 替代"
    )


def test_safe_notify_imported_in_admin_reimburse():
    """admin_reimburse.py 顶部应 import safe_notify_user_reimburse_reject。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "safe_notify_user_reimburse_reject" in src


def test_reject_audit_log_still_written():
    """UX-4.1 不应影响 reimburse_reject audit log 写入（保护契约）。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def on_reimburse_reject_reason(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert 'action="reimburse_reject"' in body
    assert "log_admin_audit" in body


def test_reject_done_next_kb_still_used():
    """UX-4.1 不动 UX-2 的 admin_review_done_next_kb 接入。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def on_reimburse_reject_reason(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert 'admin_review_done_next_kb("reimburse")' in body


# ============================================================
# 5. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords"}

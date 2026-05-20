"""评价 footer 推广 config 化（2026-05）契约 + 集成测试。

测试范围：
    1. 常量值
    2. get/set helper 行为（默认 / 空串合法 / 长度边界 / URL 协议校验）
    3. admin_reimburse_config_kb 新增 2 个 footer 入口
    4. keyboard 契约（promo_text / promo_url menu / cancel / confirm + clear）
    5. handler 源码静态契约（callback 字面量 / audit / 必经 set helper）
    6. publish_review_comment 读 config 注入 render（空 config 时不渲染 footer）
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sqlite3
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============================================================
# 1. 常量值
# ============================================================


def test_promo_constants():
    from bot.database import (
        REIMBURSE_PROMO_TEXT_DEFAULT,
        REIMBURSE_PROMO_TEXT_MAX_LEN,
        REIMBURSE_PROMO_URL_DEFAULT,
        REIMBURSE_PROMO_URL_MAX_LEN,
    )
    assert REIMBURSE_PROMO_TEXT_DEFAULT == "出击报销八折"
    assert REIMBURSE_PROMO_URL_DEFAULT == "https://t.me/ChiYanDairy/553"
    assert REIMBURSE_PROMO_TEXT_MAX_LEN == 100
    assert REIMBURSE_PROMO_URL_MAX_LEN == 500


# ============================================================
# 2. get/set helper 行为
# ============================================================


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr("bot.config.config.database_path", path)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def _run(coro):
    return asyncio.run(coro)


def test_get_text_default_when_unset(temp_db):
    from bot.database import get_reimburse_promo_text, REIMBURSE_PROMO_TEXT_DEFAULT
    assert _run(get_reimburse_promo_text()) == REIMBURSE_PROMO_TEXT_DEFAULT


def test_get_url_default_when_unset(temp_db):
    from bot.database import get_reimburse_promo_url, REIMBURSE_PROMO_URL_DEFAULT
    assert _run(get_reimburse_promo_url()) == REIMBURSE_PROMO_URL_DEFAULT


def test_set_and_get_text(temp_db):
    from bot.database import (
        get_reimburse_promo_text,
        set_reimburse_promo_text,
    )
    _run(set_reimburse_promo_text("新文案"))
    assert _run(get_reimburse_promo_text()) == "新文案"


def test_set_text_empty_allowed(temp_db):
    """空串合法（=禁用 footer）。"""
    from bot.database import (
        get_reimburse_promo_text,
        set_reimburse_promo_text,
    )
    _run(set_reimburse_promo_text(""))
    assert _run(get_reimburse_promo_text()) == ""


def test_set_text_too_long_raises(temp_db):
    from bot.database import set_reimburse_promo_text, REIMBURSE_PROMO_TEXT_MAX_LEN
    with pytest.raises(ValueError):
        _run(set_reimburse_promo_text("x" * (REIMBURSE_PROMO_TEXT_MAX_LEN + 1)))


def test_set_url_valid_https(temp_db):
    from bot.database import (
        get_reimburse_promo_url,
        set_reimburse_promo_url,
    )
    _run(set_reimburse_promo_url("https://example.com/promo"))
    assert _run(get_reimburse_promo_url()) == "https://example.com/promo"


def test_set_url_valid_http(temp_db):
    from bot.database import set_reimburse_promo_url, get_reimburse_promo_url
    _run(set_reimburse_promo_url("http://example.com/promo"))
    assert _run(get_reimburse_promo_url()) == "http://example.com/promo"


def test_set_url_empty_allowed(temp_db):
    """空串合法（=禁用 footer）。"""
    from bot.database import set_reimburse_promo_url, get_reimburse_promo_url
    _run(set_reimburse_promo_url(""))
    assert _run(get_reimburse_promo_url()) == ""


def test_set_url_without_protocol_raises(temp_db):
    from bot.database import set_reimburse_promo_url
    with pytest.raises(ValueError):
        _run(set_reimburse_promo_url("example.com/promo"))


def test_set_url_with_ftp_protocol_raises(temp_db):
    """仅允许 http(s)://。"""
    from bot.database import set_reimburse_promo_url
    with pytest.raises(ValueError):
        _run(set_reimburse_promo_url("ftp://example.com/file"))


def test_set_url_too_long_raises(temp_db):
    from bot.database import set_reimburse_promo_url, REIMBURSE_PROMO_URL_MAX_LEN
    long_url = "https://example.com/" + "x" * REIMBURSE_PROMO_URL_MAX_LEN
    with pytest.raises(ValueError):
        _run(set_reimburse_promo_url(long_url))


# ============================================================
# 3. admin_reimburse_config_kb 新增按钮
# ============================================================


def _flat(kb):
    return [b for row in kb.inline_keyboard for b in row]


def test_admin_reimburse_config_kb_has_promo_text_entry():
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    kb = admin_reimburse_config_kb()
    cbs = [b.callback_data for b in _flat(kb)]
    assert "system:reimburse_promo_text" in cbs


def test_admin_reimburse_config_kb_has_promo_url_entry():
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    kb = admin_reimburse_config_kb()
    cbs = [b.callback_data for b in _flat(kb)]
    assert "system:reimburse_promo_url" in cbs


# ============================================================
# 4. promo keyboard 契约
# ============================================================


def test_promo_text_menu_kb_has_edit_clear_back():
    from bot.keyboards.admin_kb import reimburse_promo_text_menu_kb
    kb = reimburse_promo_text_menu_kb()
    cbs = [b.callback_data for b in _flat(kb)]
    assert "system:reimburse_promo_text:edit" in cbs
    assert "system:reimburse_promo_text:clear" in cbs
    assert "admin:reimburse_config" in cbs


def test_promo_url_menu_kb_has_edit_clear_back():
    from bot.keyboards.admin_kb import reimburse_promo_url_menu_kb
    kb = reimburse_promo_url_menu_kb()
    cbs = [b.callback_data for b in _flat(kb)]
    assert "system:reimburse_promo_url:edit" in cbs
    assert "system:reimburse_promo_url:clear" in cbs
    assert "admin:reimburse_config" in cbs


def test_all_promo_callbacks_within_64b():
    from bot.keyboards.admin_kb import (
        reimburse_promo_text_cancel_kb,
        reimburse_promo_text_confirm_kb,
        reimburse_promo_text_menu_kb,
        reimburse_promo_url_cancel_kb,
        reimburse_promo_url_confirm_kb,
        reimburse_promo_url_menu_kb,
    )
    for kb in (
        reimburse_promo_text_menu_kb(),
        reimburse_promo_text_cancel_kb(),
        reimburse_promo_text_confirm_kb(),
        reimburse_promo_url_menu_kb(),
        reimburse_promo_url_cancel_kb(),
        reimburse_promo_url_confirm_kb(),
    ):
        for b in _flat(kb):
            assert b.callback_data is not None
            assert len(b.callback_data.encode("utf-8")) <= 64


# ============================================================
# 5. handler 源码静态契约
# ============================================================


def _src(mod):
    return inspect.getsource(mod)


def test_handler_module_registers_promo_callbacks():
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    for cb in (
        "system:reimburse_promo_text",
        "system:reimburse_promo_text:edit",
        "system:reimburse_promo_text:clear",
        "system:reimburse_promo_text:confirm",
        "system:reimburse_promo_url",
        "system:reimburse_promo_url:edit",
        "system:reimburse_promo_url:clear",
        "system:reimburse_promo_url:confirm",
    ):
        assert cb in src, f"缺少 {cb!r}"


def test_handler_audit_log_actions():
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    assert "reimburse_promo_text_set" in src
    assert "reimburse_promo_url_set" in src


def test_handler_uses_set_helper_not_direct_set_config():
    """confirm handler 必须经 set_reimburse_promo_* 落库（保证校验生效）。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    for func_name in ("cb_promo_text_confirm", "cb_promo_url_confirm"):
        idx = src.find(f"async def {func_name}(")
        assert idx > 0, f"找不到 {func_name}"
        end = src.find("\n@router", idx + 1)
        body = src[idx:end if end > 0 else idx + 4000]
        if "text" in func_name:
            assert "set_reimburse_promo_text" in body
            assert "REIMBURSE_PROMO_TEXT_KEY" not in body
        else:
            assert "set_reimburse_promo_url" in body
            assert "REIMBURSE_PROMO_URL_KEY" not in body


# ============================================================
# 6. publish_review_comment 读 config 注入 render
# ============================================================


def _fake_review(**overrides):
    base = {
        "id": 42, "user_id": 12345678, "teacher_id": 99,
        "rating": "positive", "anonymous": 0,
        "score_humanphoto": 9.0, "score_appearance": 8.5,
        "score_body": 8.0, "score_service": 9.5,
        "score_attitude": 9.0, "score_environment": 8.0,
        "overall_score": 8.67, "summary": "很不错",
    }
    base.update(overrides)
    return base


def _fake_teacher(**overrides):
    base = {
        "user_id": 99, "display_name": "林老师",
        "button_url": "https://t.me/example",
    }
    base.update(overrides)
    return base


def _setup_publish_mocks(monkeypatch, promo_text: str, promo_url: str):
    """通用 publish_review_comment mock 集合。"""
    from bot.utils import review_comment as mod

    async def _get_review(rid):
        return _fake_review(id=rid)
    async def _get_teacher(tid):
        return _fake_teacher(user_id=tid)
    async def _get_post(tid):
        return {
            "discussion_chat_id": -1001234567890,
            "discussion_anchor_id": 555,
        }
    async def _noop_update(*a, **kw):
        return None
    async def _get_promo_text():
        return promo_text
    async def _get_promo_url():
        return promo_url

    monkeypatch.setattr(mod, "get_teacher_review", _get_review)
    monkeypatch.setattr(mod, "get_teacher", _get_teacher)
    monkeypatch.setattr(mod, "get_teacher_channel_post", _get_post)
    monkeypatch.setattr(mod, "update_review_discussion_msg", _noop_update)
    monkeypatch.setattr(mod, "get_reimburse_promo_text", _get_promo_text)
    monkeypatch.setattr(mod, "get_reimburse_promo_url", _get_promo_url)


def test_publish_renders_footer_when_both_configs_set(monkeypatch):
    from bot.utils.review_comment import publish_review_comment
    _setup_publish_mocks(monkeypatch, "新文案", "https://new.example/promo")
    bot = MagicMock()
    me = MagicMock(); me.username = "ChiYanBookBot"
    bot.get_me = AsyncMock(return_value=me)
    sent = MagicMock()
    sent.chat = MagicMock(); sent.chat.id = -1001234567890
    sent.message_id = 888
    bot.send_message = AsyncMock(return_value=sent)

    _run(publish_review_comment(bot, 42))
    text = bot.send_message.await_args.kwargs["text"]
    assert '<a href="https://new.example/promo">新文案</a>' in text


def test_publish_skips_footer_when_text_empty(monkeypatch):
    from bot.utils.review_comment import publish_review_comment
    _setup_publish_mocks(monkeypatch, "", "https://x.example/promo")
    bot = MagicMock()
    me = MagicMock(); me.username = "ChiYanBookBot"
    bot.get_me = AsyncMock(return_value=me)
    sent = MagicMock()
    sent.chat = MagicMock(); sent.chat.id = -1001234567890
    sent.message_id = 888
    bot.send_message = AsyncMock(return_value=sent)

    _run(publish_review_comment(bot, 42))
    text = bot.send_message.await_args.kwargs["text"]
    assert "<a href=" not in text
    assert "Powered by" in text  # Powered by 仍渲染


def test_publish_skips_footer_when_url_empty(monkeypatch):
    from bot.utils.review_comment import publish_review_comment
    _setup_publish_mocks(monkeypatch, "出击报销八折", "")
    bot = MagicMock()
    me = MagicMock(); me.username = "ChiYanBookBot"
    bot.get_me = AsyncMock(return_value=me)
    sent = MagicMock()
    sent.chat = MagicMock(); sent.chat.id = -1001234567890
    sent.message_id = 888
    bot.send_message = AsyncMock(return_value=sent)

    _run(publish_review_comment(bot, 42))
    text = bot.send_message.await_args.kwargs["text"]
    assert "<a href=" not in text

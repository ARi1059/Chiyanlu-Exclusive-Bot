"""bot.handlers.start_router._handle_reimb_deep_link 单元测试（MiniApp 报销同意深链）。

覆盖：非超管返回 False（走常规分流）/ 无效 id / 报销不存在 / 超管渲染详情+键盘。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import bot.handlers.start_router as sr


def _run(coro):
    return asyncio.run(coro)


def _msg():
    m = AsyncMock()
    m.answer = AsyncMock(return_value=None)
    return m


def test_reimb_deeplink_non_super_returns_false(monkeypatch):
    """非超管 → False（不处理，交回常规菜单分流）。"""
    # handler 内 `from bot.database import is_super_admin`，须 patch 源模块
    import bot.database as db
    async def fake_is_super(uid):
        return False
    monkeypatch.setattr(db, "is_super_admin", fake_is_super)
    monkeypatch.setattr(sr.config, "super_admin_id", 999, raising=False)

    msg = _msg()
    handled = _run(sr._handle_reimb_deep_link(msg, user_id=123, raw_id="5"))
    assert handled is False
    msg.answer.assert_not_awaited()


def test_reimb_deeplink_invalid_id_returns_false(monkeypatch):
    """超管但 id 非数字 → False。"""
    monkeypatch.setattr(sr.config, "super_admin_id", 123, raising=False)
    msg = _msg()
    handled = _run(sr._handle_reimb_deep_link(msg, user_id=123, raw_id="abc"))
    assert handled is False


def test_reimb_deeplink_not_found_answers(monkeypatch):
    """超管 + 报销不存在 → True 且回提示。"""
    monkeypatch.setattr(sr.config, "super_admin_id", 123, raising=False)

    async def fake_get_reimb(rid):
        return None
    # get_reimbursement 在函数内 from bot.database import
    import bot.database as db
    monkeypatch.setattr(db, "get_reimbursement", fake_get_reimb)

    msg = _msg()
    handled = _run(sr._handle_reimb_deep_link(msg, user_id=123, raw_id="5"))
    assert handled is True
    msg.answer.assert_awaited()


def test_reimb_deeplink_super_renders_detail(monkeypatch):
    """超管 + 报销存在 → True 且发详情（含操作键盘）。"""
    monkeypatch.setattr(sr.config, "super_admin_id", 123, raising=False)

    async def fake_get_reimb(rid):
        return {"id": rid, "user_id": 888, "teacher_id": 99, "amount": 80, "status": "pending"}
    import bot.database as db
    monkeypatch.setattr(db, "get_reimbursement", fake_get_reimb)

    async def fake_render(reimb):
        return "报销详情文本"
    import bot.handlers.admin_reimburse as ar
    monkeypatch.setattr(ar, "_render_reimbursement_detail", fake_render)

    msg = _msg()
    handled = _run(sr._handle_reimb_deep_link(msg, user_id=123, raw_id="5"))
    assert handled is True
    msg.answer.assert_awaited()
    # 带了 reply_markup（操作键盘）
    _, kwargs = msg.answer.call_args
    assert kwargs.get("reply_markup") is not None

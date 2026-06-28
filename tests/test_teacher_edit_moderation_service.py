"""老师资料审核共享 service 测试（阶段1）。

approve_teacher_edit / reject_teacher_edit：落库 + 通知老师 + 非 pending 兜底。
叶子函数 monkeypatch（get_edit_request / approve_edit_request / reject_edit_request）；
bot.send_message 用 AsyncMock 验证通知老师。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.services.teacher_edit_moderation as tem


def _run(coro):
    return asyncio.run(coro)


def _bot():
    b = MagicMock()
    b.send_message = AsyncMock()
    return b


def test_approve_applies_and_notifies_teacher(monkeypatch):
    async def fake_get(rid):
        return {"status": "pending", "teacher_id": 1001, "field_name": "region", "new_value": "心岛"}

    async def fake_approve(rid, reviewer):
        return True

    monkeypatch.setattr(tem, "get_edit_request", fake_get)
    monkeypatch.setattr(tem, "approve_edit_request", fake_approve)
    bot = _bot()
    res = _run(tem.approve_teacher_edit(bot, 5, 999))
    assert res["ok"] is True
    assert res["teacher_id"] == 1001 and res["field"] == "region"
    bot.send_message.assert_awaited()
    sent = str(bot.send_message.call_args)
    assert "通过审核" in sent and "1001" in sent  # 通知老师(私聊 chat_id=teacher)


def test_approve_gone_when_not_pending(monkeypatch):
    async def fake_get(rid):
        return {"status": "approved", "teacher_id": 1, "field_name": "x"}

    monkeypatch.setattr(tem, "get_edit_request", fake_get)
    bot = _bot()
    res = _run(tem.approve_teacher_edit(bot, 5, 999))
    assert res["ok"] is False and res["error"] == "gone"
    bot.send_message.assert_not_awaited()  # 不通知


def test_approve_gone_when_db_returns_false(monkeypatch):
    async def fake_get(rid):
        return {"status": "pending", "teacher_id": 1, "field_name": "x", "new_value": "y"}

    async def fake_approve(rid, reviewer):
        return False  # 竞态：已被别人处理

    monkeypatch.setattr(tem, "get_edit_request", fake_get)
    monkeypatch.setattr(tem, "approve_edit_request", fake_approve)
    bot = _bot()
    res = _run(tem.approve_teacher_edit(bot, 5, 999))
    assert res["ok"] is False and res["error"] == "gone"
    bot.send_message.assert_not_awaited()


def test_reject_rolls_back_and_notifies_with_reason(monkeypatch):
    captured = {}

    async def fake_get(rid):
        return {"status": "pending", "teacher_id": 1001, "field_name": "price", "new_value": "1000P"}

    async def fake_reject(rid, reviewer, reason):
        captured["reason"] = reason
        return True

    monkeypatch.setattr(tem, "get_edit_request", fake_get)
    monkeypatch.setattr(tem, "reject_edit_request", fake_reject)
    bot = _bot()
    res = _run(tem.reject_teacher_edit(bot, 5, 999, "内容违规"))
    assert res["ok"] is True
    assert captured["reason"] == "内容违规"
    sent = str(bot.send_message.call_args)
    assert "驳回" in sent and "内容违规" in sent


def test_reject_gone_when_not_pending(monkeypatch):
    async def fake_get(rid):
        return None

    monkeypatch.setattr(tem, "get_edit_request", fake_get)
    bot = _bot()
    res = _run(tem.reject_teacher_edit(bot, 5, 999, None))
    assert res["ok"] is False and res["error"] == "gone"
    bot.send_message.assert_not_awaited()

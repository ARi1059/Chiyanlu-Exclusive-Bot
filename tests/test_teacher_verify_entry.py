"""bot 侧「申请验证」入口测试（teacher_detail 私聊详情页）。

  - teacher_detail_kb 含 teacher:verify:<id> 按钮（与写评价同行）
  - cb_teacher_verify：私聊成功/失败透传 service；群聊不调 service；无效 id 不调

service send_verification_to_teacher 在 teacher_detail 模块命名空间，monkeypatch 隔离。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.handlers.teacher_detail as td
from bot.keyboards.user_kb import teacher_detail_kb
from bot.services.verification import VerifyResult


def _run(coro):
    return asyncio.run(coro)


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


def _teacher(uid: int = 42) -> dict:
    return {"user_id": uid, "button_url": "", "button_text": "", "display_name": "小美"}


# ============ kb 结构 ============

def test_detail_kb_has_verify_button():
    kb = teacher_detail_kb(_teacher(42), is_favorited=False, review_count=0)
    assert "teacher:verify:42" in _cbs(kb)
    # 写评价仍在（同行并存，未被替换）
    assert "review:start:42" in _cbs(kb)


# ============ handler ============

def _fake_cb(*, data: str, chat_type: str = "private", uid: int = 555):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=uid, username="stud", first_name="S")
    cb.message = MagicMock()
    cb.message.chat = MagicMock(type=chat_type)
    cb.bot = MagicMock()
    cb.answer = AsyncMock()
    return cb


def _patch(monkeypatch, result: VerifyResult):
    rec = {}

    async def fake_send(bot, *, user_id, teacher_id):
        rec.update(user_id=user_id, teacher_id=teacher_id)
        return result

    async def fake_upsert(*a, **k):
        return None

    monkeypatch.setattr(td, "send_verification_to_teacher", fake_send)
    monkeypatch.setattr(td, "upsert_user", fake_upsert)
    return rec


def test_verify_private_success(monkeypatch):
    rec = _patch(monkeypatch, VerifyResult(ok=True))
    cb = _fake_cb(data="teacher:verify:100", uid=555)
    _run(td.cb_teacher_verify(cb))
    assert rec == {"user_id": 555, "teacher_id": 100}
    text = cb.answer.call_args.args[0]
    assert "已把你的约课证明发给老师" in text


def test_verify_private_business_error(monkeypatch):
    rec = _patch(monkeypatch, VerifyResult(ok=False, error="需先设置 Telegram 用户名才能申请验证"))
    cb = _fake_cb(data="teacher:verify:100")
    _run(td.cb_teacher_verify(cb))
    assert rec["teacher_id"] == 100
    assert "用户名" in cb.answer.call_args.args[0]


def test_verify_group_blocked(monkeypatch):
    rec = _patch(monkeypatch, VerifyResult(ok=True))
    cb = _fake_cb(data="teacher:verify:100", chat_type="supergroup")
    _run(td.cb_teacher_verify(cb))
    assert rec == {}  # service 未被调用
    assert "私聊" in cb.answer.call_args.args[0]


def test_verify_invalid_id(monkeypatch):
    rec = _patch(monkeypatch, VerifyResult(ok=True))
    cb = _fake_cb(data="teacher:verify:abc")
    _run(td.cb_teacher_verify(cb))
    assert rec == {}  # 未调 service
    assert cb.answer.await_count == 1

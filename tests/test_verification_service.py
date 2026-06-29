"""申请验证 service 单测（services/verification）。

覆盖资格分支 + 发送 + 记录的关键性质：
  - 无用户名 → 拒绝、不发送、不记录
  - 无 approved 评价 → 拒绝
  - 冷却命中 → 拒绝、不发送
  - happy：发约课截图 media + 文字（含 @username + 6 维分），记录写入
  - 发送 Forbidden → 拒绝且不记录

DB / bot 全 monkeypatch（service 是编排逻辑）。
"""
from __future__ import annotations

import asyncio

from aiogram.exceptions import TelegramForbiddenError

import bot.services.verification as m


def _run(coro):
    return asyncio.run(coro)


def _review(**over) -> dict:
    d = {
        "id": 7, "user_id": 555, "teacher_id": 100, "rating": "positive",
        "overall_score": 8.2, "score_humanphoto": 8.0, "score_appearance": 9.0,
        "score_body": 7.5, "score_service": 8.5, "score_attitude": 9.0,
        "score_environment": 7.0, "summary": "体验不错。",
        "booking_screenshot_file_id": "BOOKING_FID", "status": "approved",
    }
    d.update(over)
    return d


class _FakeBot:
    def __init__(self, *, raise_on_send=None):
        self.media_calls = []
        self.text_calls = []
        self._raise = raise_on_send

    async def send_media_group(self, *, chat_id, media):
        if self._raise:
            raise self._raise
        self.media_calls.append({"chat_id": chat_id, "media": media})

    async def send_message(self, *, chat_id, text):
        if self._raise:
            raise self._raise
        self.text_calls.append({"chat_id": chat_id, "text": text})


def _setup(monkeypatch, *, teacher=None, user=None, recent=0, reviews=None):
    rec = {"added": []}

    async def fake_get_teacher(tid):
        return teacher if teacher is not None else {"user_id": tid, "display_name": "小美", "is_deleted": 0}

    async def fake_get_user(uid):
        return user if user is not None else {"user_id": uid, "username": "stud"}

    async def fake_count(uid, tid, secs):
        return recent

    async def fake_reviews(uid, status_filter=None, limit=1, **kw):
        return reviews if reviews is not None else [_review()]

    async def fake_add(uid, tid, rid):
        rec["added"].append((uid, tid, rid))
        return 1

    monkeypatch.setattr(m, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(m, "get_user", fake_get_user)
    monkeypatch.setattr(m, "count_recent_verifications", fake_count)
    monkeypatch.setattr(m, "list_user_reviews_paged", fake_reviews)
    monkeypatch.setattr(m, "add_verification_request", fake_add)
    return rec


def test_no_username_rejected(monkeypatch):
    rec = _setup(monkeypatch, user={"user_id": 555, "username": None})
    bot = _FakeBot()
    res = _run(m.send_verification_to_teacher(bot, user_id=555, teacher_id=100))
    assert res.ok is False and "用户名" in res.error
    assert bot.media_calls == [] and rec["added"] == []


def test_no_approved_review_rejected(monkeypatch):
    rec = _setup(monkeypatch, reviews=[])
    bot = _FakeBot()
    res = _run(m.send_verification_to_teacher(bot, user_id=555, teacher_id=100))
    assert res.ok is False and "已通过" in res.error
    assert bot.media_calls == [] and rec["added"] == []


def test_cooldown_rejected(monkeypatch):
    rec = _setup(monkeypatch, recent=1)
    bot = _FakeBot()
    res = _run(m.send_verification_to_teacher(bot, user_id=555, teacher_id=100))
    assert res.ok is False and "1 小时" in res.error
    assert bot.media_calls == [] and rec["added"] == []


def test_teacher_not_found(monkeypatch):
    rec = _setup(monkeypatch, teacher=None)

    async def none_teacher(tid):
        return None

    monkeypatch.setattr(m, "get_teacher", none_teacher)
    bot = _FakeBot()
    res = _run(m.send_verification_to_teacher(bot, user_id=555, teacher_id=100))
    assert res.ok is False and "老师不存在" in res.error
    assert bot.media_calls == []


def test_happy_sends_and_records(monkeypatch):
    rec = _setup(monkeypatch)
    bot = _FakeBot()
    res = _run(m.send_verification_to_teacher(bot, user_id=555, teacher_id=100))
    assert res.ok is True
    # 发了约课截图 media group 到老师
    assert len(bot.media_calls) == 1
    mc = bot.media_calls[0]
    assert mc["chat_id"] == 100
    assert mc["media"][0].media == "BOOKING_FID"
    # 文字含 @username + 6 维分线索
    assert len(bot.text_calls) == 1
    txt = bot.text_calls[0]["text"]
    assert "@stud" in txt and "综合 8.2" in txt and "服务 8.5" in txt
    # 记录写入（冷却以成功为准）
    assert rec["added"] == [(555, 100, 7)]


def test_send_forbidden_not_recorded(monkeypatch):
    rec = _setup(monkeypatch)
    bot = _FakeBot(raise_on_send=TelegramForbiddenError(method=None, message="blocked"))
    res = _run(m.send_verification_to_teacher(bot, user_id=555, teacher_id=100))
    assert res.ok is False and "无法接收" in res.error
    assert rec["added"] == []  # 失败不记录，可重试

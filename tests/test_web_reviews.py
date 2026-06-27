"""bot/web 写评价端点测试（P2）。

覆盖：
  - GET /api/teachers/{id}/review-context：鉴权 + 委托 build_review_context + 老师不存在 404
  - POST /api/reviews：鉴权 + 委托 submit_review + 成功 {review_id,status} + 失败 4xx 结构化
  - POST /api/uploads：鉴权 + mock bot.send_photo 回灌 file_id + 发后删除

service / db / bot 全 monkeypatch；token 用 issue_session 直接签。
"""
from __future__ import annotations

import asyncio

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.reviews as rmod
import bot.web.api.uploads as umod
from bot.config import config
from bot.services.review_submit import SubmitResult
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _user(uid: int = 1001) -> str:
    return issue_session(uid, "user", config.bot_token)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ============ review-context ============

def test_context_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/teachers/5/review-context")
            assert r.status == 401
    _run(_t())


def test_context_delegates(monkeypatch):
    async def fake_get_teacher(tid):
        return {"user_id": tid, "display_name": "苏乔晚", "is_active": 1, "price": "1000P"}

    async def fake_ctx(bot, uid, teacher):
        return {"teacher": {"id": teacher["user_id"], "display_name": teacher["display_name"]},
                "rate_limit": {"blocked": False, "reason": None},
                "required_channels": {"ok": True, "missing": []},
                "reimburse": {"eligible": True, "estimated_amount": 150,
                              "ineligibility_hint": None, "required_channels": {"ok": True, "missing": []}}}

    monkeypatch.setattr(rmod, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(rmod, "build_review_context", fake_ctx)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/teachers/5/review-context", headers=_hdr(_user()))
            assert r.status == 200
            d = await r.json()
            assert d["reimburse"]["estimated_amount"] == 150
    _run(_t())


def test_context_teacher_not_found_404(monkeypatch):
    async def fake_get_teacher(tid):
        return None
    monkeypatch.setattr(rmod, "get_teacher", fake_get_teacher)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/teachers/5/review-context", headers=_hdr(_user()))
            assert r.status == 404
    _run(_t())


# ============ submit ============

def test_submit_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/reviews", json={"teacher_id": 5})
            assert r.status == 401
    _run(_t())


def test_submit_success(monkeypatch):
    rec: dict = {}

    async def fake_submit(bot, uid, payload):
        rec.update(uid=uid, payload=payload)
        return SubmitResult(ok=True, review_id=123)

    monkeypatch.setattr(rmod, "submit_review", fake_submit)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/reviews", headers=_hdr(_user()),
                             json={"teacher_id": 5, "rating": "positive"})
            assert r.status == 200
            d = await r.json()
            assert d["review_id"] == 123 and d["status"] == "pending"
    _run(_t())
    assert rec["uid"] == 1001
    assert rec["payload"]["teacher_id"] == 5


def test_submit_invalid_fields_400(monkeypatch):
    async def fake_submit(bot, uid, payload):
        return SubmitResult(ok=False, error_code="invalid_fields", fields=["缺约课截图"])
    monkeypatch.setattr(rmod, "submit_review", fake_submit)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/reviews", headers=_hdr(_user()), json={"teacher_id": 5})
            assert r.status == 400
            d = await r.json()
            assert d["error"] == "invalid_fields" and "缺约课截图" in d["fields"]
    _run(_t())


def test_submit_need_subscribe_400(monkeypatch):
    async def fake_submit(bot, uid, payload):
        return SubmitResult(ok=False, error_code="need_subscribe", message="请先关注",
                            missing=[{"display_name": "频道A", "invite_link": "https://t.me/x"}])
    monkeypatch.setattr(rmod, "submit_review", fake_submit)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/reviews", headers=_hdr(_user()), json={"teacher_id": 5})
            assert r.status == 400
            d = await r.json()
            assert d["error"] == "need_subscribe" and d["missing"][0]["display_name"] == "频道A"
    _run(_t())


# ============ uploads（回灌 file_id）============

class _FakePhoto:
    file_id = "AgACtest_fileid"


class _FakeMsg:
    photo = [_FakePhoto()]
    message_id = 777


class _FakeBot:
    def __init__(self):
        self.deleted = None
        self.sent_chat = None

    async def send_photo(self, chat_id, file, **k):
        self.sent_chat = chat_id
        return _FakeMsg()

    async def delete_message(self, chat_id, message_id):
        self.deleted = (chat_id, message_id)


def test_upload_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=_FakeBot()))) as c:
            form = FormData()
            form.add_field("file", b"\xff\xd8\xff\xe0", filename="t.jpg", content_type="image/jpeg")
            r = await c.post("/api/uploads", data=form)
            assert r.status == 401
    _run(_t())


def test_upload_returns_file_id_and_deletes(monkeypatch):
    async def fake_get_config(key):
        return None  # 回退 super_admin_id

    monkeypatch.setattr(umod, "get_config", fake_get_config)
    fake_bot = _FakeBot()

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=fake_bot))) as c:
            form = FormData()
            form.add_field("file", b"\xff\xd8\xff\xe0\x00\x10JFIF", filename="t.jpg", content_type="image/jpeg")
            r = await c.post("/api/uploads", headers=_hdr(_user()), data=form)
            assert r.status == 200
            d = await r.json()
            assert d["file_id"] == "AgACtest_fileid"
    _run(_t())
    # 发到回退超管私聊 + 发后即删
    assert fake_bot.sent_chat == config.super_admin_id
    assert fake_bot.deleted == (config.super_admin_id, 777)


def test_upload_rejects_non_image(monkeypatch):
    async def fake_get_config(key):
        return None
    monkeypatch.setattr(umod, "get_config", fake_get_config)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=_FakeBot()))) as c:
            form = FormData()
            form.add_field("file", b"%PDF-1.4", filename="t.pdf", content_type="application/pdf")
            r = await c.post("/api/uploads", headers=_hdr(_user()), data=form)
            assert r.status == 415
    _run(_t())

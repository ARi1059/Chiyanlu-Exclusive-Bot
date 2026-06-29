"""bot/web 申请验证端点测试。

POST /api/teachers/{id}/verify：未登录 401；委托 service；ok/error 透传；bot 缺失 503。
service monkeypatch（业务核心另测）。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.verify as mod
from bot.config import config
from bot.services.verification import VerifyResult
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _user(uid: int = 555) -> str:
    return issue_session(uid, "user", config.bot_token)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_requires_auth(monkeypatch):
    called = {"n": 0}

    async def fake(*a, **k):
        called["n"] += 1
        return VerifyResult(ok=True)

    monkeypatch.setattr(mod, "send_verification_to_teacher", fake)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/teachers/100/verify")  # 无 token
            assert r.status == 401

    _run(_t())
    assert called["n"] == 0


def test_delegates_and_passes_ids(monkeypatch):
    rec = {}

    async def fake(bot, *, user_id, teacher_id):
        rec.update(user_id=user_id, teacher_id=teacher_id)
        return VerifyResult(ok=True)

    monkeypatch.setattr(mod, "send_verification_to_teacher", fake)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/teachers/100/verify", headers=_hdr(_user(555)))
            assert r.status == 200
            assert (await r.json())["ok"] is True

    _run(_t())
    assert rec == {"user_id": 555, "teacher_id": 100}


def test_business_failure_ok_false(monkeypatch):
    async def fake(*a, **k):
        return VerifyResult(ok=False, error="需先设置 Telegram 用户名才能申请验证")

    monkeypatch.setattr(mod, "send_verification_to_teacher", fake)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/teachers/100/verify", headers=_hdr(_user()))
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and "用户名" in d["error"]

    _run(_t())


def test_bot_unavailable_503(monkeypatch):
    async def fake(*a, **k):
        raise AssertionError("service 不应被调用")

    monkeypatch.setattr(mod, "send_verification_to_teacher", fake)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/teachers/100/verify", headers=_hdr(_user()))
            assert r.status == 503

    _run(_t())


def test_invalid_teacher_id_400(monkeypatch):
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/teachers/abc/verify", headers=_hdr(_user()))
            assert r.status == 400  # {id} 匹配 abc → int() 抛 → HTTPBadRequest

    _run(_t())

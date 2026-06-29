"""bot/web 老师收到的申请验证记录端点测试。

GET /api/me/verifications：非 teacher→403；未登录 401；teacher→序列化（露名 / 尾号兜底）。
list_teacher_verifications 在 profile 模块命名空间，monkeypatch 隔离 DB。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.profile as prof_mod
from bot.config import config
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _hdr(uid: int = 555, role: str = "teacher") -> dict:
    return {"Authorization": f"Bearer {issue_session(uid, role, config.bot_token)}"}


def test_requires_teacher():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/verifications", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/me/verifications")).status == 401
    _run(_t())


def test_serialize(monkeypatch):
    async def fake_list(teacher_id, limit=50):
        return [
            {"id": 2, "user_id": 88887777, "created_at": "2026-06-30 12:34:56",
             "username": "stud", "review_rating": "positive",
             "review_summary": "体验不错", "review_overall": 8.2},
            {"id": 1, "user_id": 12345678, "created_at": "2026-06-29 09:00:00",
             "username": "", "review_rating": "neutral",
             "review_summary": "", "review_overall": 0},
        ]

    monkeypatch.setattr(prof_mod, "list_teacher_verifications", fake_list)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/verifications", headers=_hdr())
            assert r.status == 200
            items = (await r.json())["verifications"]
            assert len(items) == 2
            # 有用户名 → @username + username 字段
            assert items[0]["user"] == "@stud" and items[0]["username"] == "stud"
            assert items[0]["time"] == "06-30 12:34" and items[0]["overall"] == 8.2
            # 无用户名 → 尾号兜底，username 空（前端不可拼链接）
            assert items[1]["user"] == "用户 5678" and items[1]["username"] == ""

    _run(_t())

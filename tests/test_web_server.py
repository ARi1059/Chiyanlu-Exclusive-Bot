"""bot/web 端到端集成测试（P0·T4 + T5）。

用 aiohttp TestClient 起 app，验证：健康检查放行 / initData 换 token /
带 token 取 /api/me / 无 token 与坏 initData 回 401。

角色解析走 config.super_admin_id 路径（uid = conftest 的 SUPER_ADMIN_ID），
因此不依赖真实 db 建表（:memory: 每连接独立，无法跨连接持有表 —— 与既有报销
测试踩到的是同一限制）。async 经 asyncio.run 包裹。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer

from bot.config import config
from bot.web.server import create_web_app

_TOKEN = config.bot_token          # conftest: "dummy:token"
_SUPER = config.super_admin_id     # conftest: 123456789


def _run(coro):
    return asyncio.run(coro)


def _signed_init_data(uid: int, auth_date: int = 2_147_483_647) -> str:
    """造合法 initData。auth_date 用一个远未来值，确保不触发过期窗口。"""
    fields = {
        "user": json.dumps({"id": uid, "first_name": "T"}),
        "auth_date": str(auth_date),
    }
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", _TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})


def test_health_no_auth():
    async def _t():
        app = create_web_app(bot=None)
        async with TestClient(TestServer(app)) as c:
            r = await c.get("/api/health")
            assert r.status == 200
            assert (await r.json())["status"] == "ok"

    _run(_t())


def test_session_and_me_roundtrip():
    async def _t():
        app = create_web_app(bot=None)
        async with TestClient(TestServer(app)) as c:
            r = await c.post(
                "/api/auth/session",
                json={"init_data": _signed_init_data(_SUPER)},
            )
            assert r.status == 200
            data = await r.json()
            assert data["role"] == "superadmin"
            assert data["user_id"] == _SUPER
            token = data["token"]

            r2 = await c.get("/api/me", headers={"Authorization": f"Bearer {token}"})
            assert r2.status == 200
            me = await r2.json()
            assert me["user_id"] == _SUPER
            assert me["role"] == "superadmin"
            assert "session_expires_at" in me

    _run(_t())


def test_me_without_token_401():
    async def _t():
        app = create_web_app(bot=None)
        async with TestClient(TestServer(app)) as c:
            r = await c.get("/api/me")
            assert r.status == 401

    _run(_t())


def test_session_bad_init_data_401():
    async def _t():
        app = create_web_app(bot=None)
        async with TestClient(TestServer(app)) as c:
            r = await c.post("/api/auth/session", json={"init_data": "garbage"})
            assert r.status == 401

    _run(_t())


def test_me_bad_token_401():
    async def _t():
        app = create_web_app(bot=None)
        async with TestClient(TestServer(app)) as c:
            r = await c.get("/api/me", headers={"Authorization": "Bearer not.a.token"})
            assert r.status == 401

    _run(_t())

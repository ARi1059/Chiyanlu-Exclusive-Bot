"""bot/web 老师自助编辑资料端点测试（§16.3）。

覆盖：
  - GET  /api/me/teacher-profile  非 teacher→403；teacher→6 字段 + 锁定 button_url
  - POST /api/me/teacher-profile  非 teacher→403；非白名单字段→400；
    合法提交透传 service 结果；tags 数组拼成串；校验失败回 200+ok:false

service.submit_field_edit 在 profile 模块命名空间，monkeypatch 之即可隔离 DB/bot。
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


def _tok(uid: int = 555, role: str = "teacher") -> str:
    return issue_session(uid, role, config.bot_token)


def _hdr(uid: int = 555, role: str = "teacher") -> dict:
    return {"Authorization": f"Bearer {_tok(uid, role)}"}


# ============ GET ============

def test_get_edit_profile_requires_teacher():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/teacher-profile",
                            headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_get_edit_profile_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/me/teacher-profile")).status == 401
    _run(_t())


def test_get_edit_profile_shape(monkeypatch):
    async def fake_full(uid):
        return {
            "user_id": uid, "display_name": "苏乔晚", "region": "天府一街",
            "price": "1000P", "tags": ["御姐", "颜值"], "button_text": "约我",
            "photo_file_id": "fid", "button_url": "https://t.me/x",
        }

    monkeypatch.setattr(prof_mod, "get_teacher_full_profile", fake_full)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/teacher-profile", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["fields"]["display_name"] == "苏乔晚"
            assert d["fields"]["tags"] == ["御姐", "颜值"]
            assert d["fields"]["has_photo"] is True
            assert d["button_url"] == "https://t.me/x"   # 锁定字段回显
            assert "display_name" in d["editable_fields"]
    _run(_t())


def test_get_edit_profile_not_registered_403(monkeypatch):
    async def fake_full(uid):
        return None

    monkeypatch.setattr(prof_mod, "get_teacher_full_profile", fake_full)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/teacher-profile", headers=_hdr())
            assert r.status == 403
    _run(_t())


# ============ POST ============

def test_post_edit_requires_teacher():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-profile",
                             headers=_hdr(role="user"),
                             json={"field": "region", "value": "x"})
            assert r.status == 403
    _run(_t())


def test_post_edit_invalid_field_400():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-profile", headers=_hdr(),
                             json={"field": "button_url", "value": "x"})
            assert r.status == 400
    _run(_t())


def test_post_edit_text_passthrough(monkeypatch):
    rec: dict = {}

    async def fake_submit(bot, uid, field, value):
        rec.update(uid=uid, field=field, value=value)
        return {"ok": True, "applied": True, "request_id": 1,
                "field": field, "label": "地区",
                "message": "✅ 地区修改已生效", "error": None}

    monkeypatch.setattr(prof_mod, "submit_field_edit", fake_submit)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-profile", headers=_hdr(uid=42),
                             json={"field": "region", "value": "金融城"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["applied"] is True
    _run(_t())
    assert rec == {"uid": 42, "field": "region", "value": "金融城"}


def test_post_edit_tags_array_joined(monkeypatch):
    rec: dict = {}

    async def fake_submit(bot, uid, field, value):
        rec.update(field=field, value=value)
        return {"ok": True, "applied": True, "request_id": 1,
                "field": field, "label": "标签", "message": "ok", "error": None}

    monkeypatch.setattr(prof_mod, "submit_field_edit", fake_submit)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-profile", headers=_hdr(),
                             json={"field": "tags", "value": ["御姐", "颜值"]})
            assert r.status == 200
    _run(_t())
    # 数组被拼成空格分隔串交给 service
    assert rec["field"] == "tags"
    assert rec["value"] == "御姐 颜值"


def test_post_edit_validation_failure_returns_200_ok_false(monkeypatch):
    async def fake_submit(bot, uid, field, value):
        return {"ok": False, "applied": False, "request_id": None,
                "field": field, "label": "艺名",
                "message": "艺名过长（最多 40 字）", "error": "too_long"}

    monkeypatch.setattr(prof_mod, "submit_field_edit", fake_submit)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-profile", headers=_hdr(),
                             json={"field": "display_name", "value": "x" * 41})
            # 业务校验失败仍 200，前端据 ok:false 内联提示
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "too_long"
    _run(_t())

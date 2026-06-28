"""bot/web 老师资料审核端点测试（阶段1）。

  GET  /api/admin/teacher-edits            非 admin→403；list 组装 + photo 脱敏
  POST /api/admin/teacher-edits/{id}/approve  透传 service 结果
  POST /api/admin/teacher-edits/{id}/reject   reason 透传

service.approve/reject_teacher_edit + list_pending_edits 在端点模块命名空间，monkeypatch。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin_teacher_edits as te_mod
from bot.config import config
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _hdr(uid: int = 7, role: str = "admin") -> dict:
    return {"Authorization": f"Bearer {issue_session(uid, role, config.bot_token)}"}


# ============ GET ============

def test_list_requires_admin():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teacher-edits", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_list_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/admin/teacher-edits")).status == 401
    _run(_t())


def test_list_shape_and_photo_mask(monkeypatch):
    async def fake_list(limit=50):
        return [
            {"id": 1, "teacher_id": 100, "teacher_display_name": "苏乔晚",
             "field_name": "region", "old_value": "天府", "new_value": "心岛",
             "created_at": "2026-06-28 09:10:00"},
            {"id": 2, "teacher_id": 200, "teacher_display_name": "Muse",
             "field_name": "photo_file_id", "old_value": "oldfid", "new_value": "newfid",
             "created_at": "2026-06-28 09:11:00"},
        ]

    monkeypatch.setattr(te_mod, "list_pending_edits", fake_list)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teacher-edits", headers=_hdr())
            assert r.status == 200
            edits = (await r.json())["edits"]
            by = {e["id"]: e for e in edits}
            assert by[1]["teacher"] == "苏乔晚"
            assert by[1]["field_label"] == "地区" and by[1]["old"] == "天府" and by[1]["new"] == "心岛"
            assert by[1]["is_photo"] is False
            # photo 字段脱敏：不暴露 file_id
            assert by[2]["is_photo"] is True
            assert by[2]["old"] == "已上传" and "newfid" not in by[2]["new"]
    _run(_t())


# ============ approve / reject ============

def test_approve_passthrough(monkeypatch):
    rec = {}

    async def fake_approve(bot, rid, reviewer):
        rec.update(rid=rid, reviewer=reviewer)
        return {"ok": True, "teacher_id": 100, "field": "region"}

    monkeypatch.setattr(te_mod, "approve_teacher_edit", fake_approve)

    async def _t():
        # bot 非 None 才能过 APP_BOT 取值；用占位对象
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teacher-edits/5/approve", headers=_hdr(uid=42))
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["teacher_id"] == 100
    _run(_t())
    assert rec == {"rid": 5, "reviewer": 42}


def test_approve_requires_admin():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teacher-edits/5/approve", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_reject_reason_passthrough(monkeypatch):
    rec = {}

    async def fake_reject(bot, rid, reviewer, reason):
        rec.update(rid=rid, reviewer=reviewer, reason=reason)
        return {"ok": True, "teacher_id": 100, "field": "price"}

    monkeypatch.setattr(te_mod, "reject_teacher_edit", fake_reject)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teacher-edits/9/reject", headers=_hdr(uid=42),
                             json={"reason": "内容违规"})
            assert r.status == 200
            assert (await r.json())["ok"] is True
    _run(_t())
    assert rec == {"rid": 9, "reviewer": 42, "reason": "内容违规"}


def test_reject_gone_returns_ok_false(monkeypatch):
    async def fake_reject(bot, rid, reviewer, reason):
        return {"ok": False, "error": "gone"}

    monkeypatch.setattr(te_mod, "reject_teacher_edit", fake_reject)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teacher-edits/9/reject", headers=_hdr(), json={})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "gone"
    _run(_t())

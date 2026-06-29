"""bot/web 老师自助多图相册端点测试（即时生效）。

  GET    /api/me/teacher-album            非 teacher→403；列表组装（签名 url + cache-bust v）
  POST   /api/me/teacher-album            add（含满 10 拦截）
  DELETE /api/me/teacher-album/{index}    0-based 删（转 1-based 调 DB）；越界 bad_index

DB 叶子函数（get_teacher_photos / add_teacher_photo / remove_teacher_photo）
在 profile 模块命名空间，monkeypatch。
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


# ============ GET ============

def test_album_requires_teacher():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/teacher-album", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_album_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/me/teacher-album")).status == 401
    _run(_t())


def test_album_list_shape_signed_and_cachebust(monkeypatch):
    async def fake_photos(uid):
        return ["AgACfileAAA111", "AgACfileBBB222"]

    monkeypatch.setattr(prof_mod, "get_teacher_photos", fake_photos)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/teacher-album", headers=_hdr(uid=100))
            assert r.status == 200
            d = await r.json()
            assert d["count"] == 2 and d["max"] == 10
            p0, p1 = d["photos"]
            assert p0["index"] == 0 and p1["index"] == 1
            # 封面 i=0 无 &i；第二张含 &i=1
            assert "sig=" in p0["url"] and "&i=1" in p1["url"]
            # cache-bust：URL 末尾含按 file_id 片段的 v=
            assert "v=AgACfile" in p0["url"]
            assert p0["url"] != p1["url"]  # 不同图不同 URL（破浏览器缓存）
    _run(_t())


# ============ POST add ============

def test_album_add_ok(monkeypatch):
    rec = {}

    async def fake_photos(uid):
        return ["one"]  # 未满

    async def fake_add(uid, fid):
        rec.update(uid=uid, fid=fid)
        return 2

    monkeypatch.setattr(prof_mod, "get_teacher_photos", fake_photos)
    monkeypatch.setattr(prof_mod, "add_teacher_photo", fake_add)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-album", headers=_hdr(uid=42),
                             json={"file_id": "newfid"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["count"] == 2
    _run(_t())
    assert rec == {"uid": 42, "fid": "newfid"}


def test_album_add_full_blocked(monkeypatch):
    async def fake_photos(uid):
        return [f"f{i}" for i in range(10)]  # 已满 10

    async def boom(uid, fid):
        raise AssertionError("满 10 不应调 add_teacher_photo")

    monkeypatch.setattr(prof_mod, "get_teacher_photos", fake_photos)
    monkeypatch.setattr(prof_mod, "add_teacher_photo", boom)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-album", headers=_hdr(),
                             json={"file_id": "x"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "full" and d["count"] == 10
    _run(_t())


def test_album_add_missing_file_id_400():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-album", headers=_hdr(), json={})
            assert r.status == 400
    _run(_t())


def test_album_add_requires_teacher():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/teacher-album", headers=_hdr(role="user"),
                             json={"file_id": "x"})
            assert r.status == 403
    _run(_t())


# ============ DELETE ============

def test_album_delete_converts_to_1based(monkeypatch):
    rec = {}

    async def fake_remove(uid, idx_1based):
        rec.update(uid=uid, idx=idx_1based)
        return True

    async def fake_photos(uid):
        return ["a", "b"]  # 删后剩 2（仅用于 count）

    monkeypatch.setattr(prof_mod, "remove_teacher_photo", fake_remove)
    monkeypatch.setattr(prof_mod, "get_teacher_photos", fake_photos)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.delete("/api/me/teacher-album/0", headers=_hdr(uid=7))
            assert r.status == 200
            assert (await r.json())["ok"] is True
    _run(_t())
    # 0-based 0 → 1-based 1
    assert rec == {"uid": 7, "idx": 1}


def test_album_delete_bad_index(monkeypatch):
    async def fake_remove(uid, idx_1based):
        return False  # 越界

    monkeypatch.setattr(prof_mod, "remove_teacher_photo", fake_remove)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.delete("/api/me/teacher-album/99", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "bad_index"
    _run(_t())


def test_album_delete_requires_teacher():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.delete("/api/me/teacher-album/0", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())

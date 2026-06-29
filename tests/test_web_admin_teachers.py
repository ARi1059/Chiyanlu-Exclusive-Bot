"""bot/web 老师管理端点测试（阶段2）。

  GET  /api/admin/teachers?status=...   名册（admin+）；按状态路由取数 + 三态计数
  POST /api/admin/teachers/{id}/status  enable/disable=admin；delete/restore=超管（403 gate）
  POST /api/admin/teachers/{id}/field   admin+；字段白名单 + tags list→str；透传 service 结果

DB 生命周期函数 + admin_set_field 在端点模块命名空间，monkeypatch。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin_teachers as at_mod
from bot.config import config
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _hdr(uid: int = 7, role: str = "admin") -> dict:
    return {"Authorization": f"Bearer {issue_session(uid, role, config.bot_token)}"}


# ============ GET /api/admin/teachers ============

def test_list_requires_admin():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_list_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/admin/teachers")).status == 401
    _run(_t())


def _patch_roster(monkeypatch, *, all_=None, deleted=None, counts=None):
    """patch 名册三个取数函数；记录 get_all_teachers 的调用参数。"""
    calls = {"all_args": []}

    async def fake_get_all(active_only=True, include_deleted=False):
        calls["all_args"].append((active_only, include_deleted))
        return list(all_ or [])

    async def fake_get_deleted():
        return list(deleted or [])

    async def fake_counts():
        return dict(counts or {"active": 0, "inactive": 0, "total": 0})

    monkeypatch.setattr(at_mod, "get_all_teachers", fake_get_all)
    monkeypatch.setattr(at_mod, "get_deleted_teachers", fake_get_deleted)
    monkeypatch.setattr(at_mod, "get_teacher_counts", fake_counts)
    return calls


def test_list_active_shape_and_counts(monkeypatch):
    teacher = {
        "user_id": 100, "display_name": "苏乔晚", "region": "心岛", "price": "1000P",
        "tags": '["御姐","颜值"]', "button_text": "约", "button_url": "https://t.me/x",
        "is_active": 1, "is_deleted": 0, "photo_file_id": "fid",
    }
    calls = _patch_roster(monkeypatch, all_=[teacher],
                          counts={"active": 3, "inactive": 2, "total": 5})

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers?status=active", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            t = d["teachers"][0]
            assert t["id"] == 100 and t["name"] == "苏乔晚"
            assert t["tags"] == ["御姐", "颜值"]
            assert t["is_active"] is True and t["is_deleted"] is False
            assert t["has_photo"] is True
            # 三态计数：inactive→disabled，deleted=已删名册长度
            assert d["counts"]["active"] == 3 and d["counts"]["disabled"] == 2
            assert d["counts"]["deleted"] == 0
    _run(_t())
    # active 分支：active_only=True, include_deleted=False
    assert (True, False) in calls["all_args"]


def test_list_deleted_uses_deleted_source(monkeypatch):
    deleted_t = {"user_id": 9, "display_name": "已删", "is_active": 0, "is_deleted": 1}
    _patch_roster(monkeypatch, deleted=[deleted_t], counts={"active": 0, "inactive": 0})

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers?status=deleted", headers=_hdr())
            d = await r.json()
            assert [x["id"] for x in d["teachers"]] == [9]
            assert d["teachers"][0]["is_deleted"] is True
            assert d["counts"]["deleted"] == 1
    _run(_t())


def test_list_disabled_filters_inactive(monkeypatch):
    rows = [
        {"user_id": 1, "is_active": 1, "is_deleted": 0},
        {"user_id": 2, "is_active": 0, "is_deleted": 0},
    ]
    calls = _patch_roster(monkeypatch, all_=rows, counts={"active": 1, "inactive": 1})

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers?status=disabled", headers=_hdr())
            d = await r.json()
            # disabled：get_all_teachers(active_only=False) 后过滤 not is_active
            assert [x["id"] for x in d["teachers"]] == [2]
    _run(_t())
    assert (False, False) in calls["all_args"]


def test_list_all_includes_deleted(monkeypatch):
    calls = _patch_roster(monkeypatch, all_=[{"user_id": 1, "is_active": 1, "is_deleted": 0}],
                          counts={"active": 1, "inactive": 0})

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers?status=all", headers=_hdr())
            assert r.status == 200
    _run(_t())
    # all 分支：include_deleted=True
    assert (False, True) in calls["all_args"]


# ============ POST /api/admin/teachers/{id}/status ============

def _patch_status(monkeypatch):
    calls = {}

    async def fake_enable(tid): calls["enable"] = tid; return True
    async def fake_disable(tid): calls["disable"] = tid; return True
    async def fake_delete(tid): calls["delete"] = tid; return True
    async def fake_restore(tid): calls["restore"] = tid; return True

    monkeypatch.setattr(at_mod, "enable_teacher", fake_enable)
    monkeypatch.setattr(at_mod, "remove_teacher", fake_disable)
    monkeypatch.setattr(at_mod, "soft_delete_teacher", fake_delete)
    monkeypatch.setattr(at_mod, "restore_teacher", fake_restore)
    return calls


def test_status_requires_admin(monkeypatch):
    _patch_status(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/status", headers=_hdr(role="user"),
                             json={"action": "enable"})
            assert r.status == 403
    _run(_t())


def test_status_enable_calls_enable(monkeypatch):
    calls = _patch_status(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/status", headers=_hdr(role="admin"),
                             json={"action": "enable"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["action"] == "enable"
    _run(_t())
    assert calls.get("enable") == 55


def test_status_disable_calls_remove(monkeypatch):
    calls = _patch_status(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/status", headers=_hdr(),
                             json={"action": "disable"})
            assert r.status == 200
    _run(_t())
    assert calls.get("disable") == 55


def test_status_delete_requires_super(monkeypatch):
    calls = _patch_status(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            # admin 不能软删 → 403，且不触达 DB
            r = await c.post("/api/admin/teachers/55/status", headers=_hdr(role="admin"),
                             json={"action": "delete"})
            assert r.status == 403
    _run(_t())
    assert "delete" not in calls


def test_status_delete_super_ok(monkeypatch):
    calls = _patch_status(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/status", headers=_hdr(role="superadmin"),
                             json={"action": "delete"})
            assert r.status == 200
    _run(_t())
    assert calls.get("delete") == 55


def test_status_restore_requires_super(monkeypatch):
    _patch_status(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/status", headers=_hdr(role="admin"),
                             json={"action": "restore"})
            assert r.status == 403
    _run(_t())


def test_status_invalid_action_400(monkeypatch):
    _patch_status(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/status", headers=_hdr(),
                             json={"action": "frobnicate"})
            assert r.status == 400
    _run(_t())


# ============ POST /api/admin/teachers/{id}/field ============

def test_field_requires_admin():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/field", headers=_hdr(role="user"),
                             json={"field": "price", "value": "2000P"})
            assert r.status == 403
    _run(_t())


def test_field_invalid_field_400():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            # user_id 不在白名单 → 端点 400（不进 service）
            r = await c.post("/api/admin/teachers/55/field", headers=_hdr(),
                             json={"field": "user_id", "value": "9"})
            assert r.status == 400
    _run(_t())


def test_field_tags_list_joined_then_passthrough(monkeypatch):
    rec = {}

    async def fake_set(tid, field, value):
        rec.update(tid=tid, field=field, value=value)
        return {"ok": True, "field": field, "label": "标签", "message": "✅ 标签已更新", "error": None}

    monkeypatch.setattr(at_mod, "admin_set_field", fake_set)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/field", headers=_hdr(),
                             json={"field": "tags", "value": ["御姐", "颜值"]})
            assert r.status == 200
            assert (await r.json())["ok"] is True
    _run(_t())
    # tags list 在端点被 join 成空格串再交给 service
    assert rec == {"tid": 55, "field": "tags", "value": "御姐 颜值"}


def test_field_passthrough_failure(monkeypatch):
    async def fake_set(tid, field, value):
        return {"ok": False, "field": field, "label": "联系链接",
                "message": "链接格式不正确（需 http/https）", "error": "bad_url"}

    monkeypatch.setattr(at_mod, "admin_set_field", fake_set)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/field", headers=_hdr(),
                             json={"field": "button_url", "value": "garbage"})
            assert r.status == 200  # 业务失败仍 200，error 在 body
            d = await r.json()
            assert d["ok"] is False and d["error"] == "bad_url"
    _run(_t())

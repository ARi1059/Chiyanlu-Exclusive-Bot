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
from bot.utils.teacher_channel_publish import PublishError
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


# ============ 老师相册（GET/POST/DELETE /api/admin/teachers/{id}/album）============

def _patch_album(monkeypatch, *, photos=None):
    """fake 相册三函数（内存 store）；记录 add/remove 调用参数（验 teacher_id 来源 + index 转换）。"""
    store = list(photos or [])
    calls = {"added": [], "removed": []}

    async def fake_get(tid):
        return list(store)

    async def fake_add(tid, fid):
        calls["added"].append((tid, fid))
        store.append(fid)
        return len(store)

    async def fake_remove(tid, idx):  # DB 1-based
        calls["removed"].append((tid, idx))
        if idx < 1 or idx > len(store):
            return False
        del store[idx - 1]
        return True

    monkeypatch.setattr(at_mod, "get_teacher_photos", fake_get)
    monkeypatch.setattr(at_mod, "add_teacher_photo", fake_add)
    monkeypatch.setattr(at_mod, "remove_teacher_photo", fake_remove)
    return calls, store


# --- GET ---

def test_album_get_requires_admin(monkeypatch):
    _patch_album(monkeypatch, photos=["fa"])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers/55/album", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_album_get_no_token_401(monkeypatch):
    _patch_album(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/admin/teachers/55/album")).status == 401
    _run(_t())


def test_album_get_shape_signed_and_cachebust(monkeypatch):
    _patch_album(monkeypatch, photos=["AgACfileA111", "AgACfileB222"])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers/55/album", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["count"] == 2 and d["max"] == 10
            p0, p1 = d["photos"]
            assert p0["index"] == 0 and p1["index"] == 1
            # 该老师的签名照片 URL；封面 i=0 无 &i，第二张含 &i=1
            assert "/api/teachers/55/photo?sig=" in p0["url"] and "&i=1" in p1["url"]
            # cache-bust：v= 按 file_id 片段，不同图不同 URL
            assert "v=AgACfile" in p0["url"] and p0["url"] != p1["url"]
    _run(_t())


# --- POST add ---

def test_album_post_requires_admin(monkeypatch):
    calls, _ = _patch_album(monkeypatch, photos=["fa"])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/album", headers=_hdr(role="user"),
                             json={"file_id": "x"})
            assert r.status == 403
    _run(_t())
    assert calls["added"] == []  # 门禁拦在 DB 前


def test_album_post_add_ok(monkeypatch):
    calls, _ = _patch_album(monkeypatch, photos=["one"])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/album", headers=_hdr(),
                             json={"file_id": "newfid"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["count"] == 2
    _run(_t())
    # teacher_id 来自 URL（55，非 session uid），file_id 透传
    assert calls["added"] == [(55, "newfid")]


def test_album_post_full_blocked(monkeypatch):
    calls, _ = _patch_album(monkeypatch, photos=[f"f{i}" for i in range(10)])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/album", headers=_hdr(),
                             json={"file_id": "x"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "full" and d["count"] == 10
    _run(_t())
    assert calls["added"] == []  # 满额短路，未调 add


def test_album_post_missing_file_id_400(monkeypatch):
    _patch_album(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/album", headers=_hdr(), json={})
            assert r.status == 400
    _run(_t())


# --- DELETE ---

def test_album_delete_requires_admin(monkeypatch):
    calls, _ = _patch_album(monkeypatch, photos=["a", "b"])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.delete("/api/admin/teachers/55/album/0", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())
    assert calls["removed"] == []


def test_album_delete_converts_to_1based(monkeypatch):
    calls, _ = _patch_album(monkeypatch, photos=["a", "b", "c"])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.delete("/api/admin/teachers/55/album/0", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["count"] == 2
    _run(_t())
    # 前端 0-based 0 → DB 1-based 1
    assert calls["removed"] == [(55, 1)]


def test_album_delete_bad_index(monkeypatch):
    _patch_album(monkeypatch, photos=["a"])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.delete("/api/admin/teachers/55/album/5", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "bad_index"
    _run(_t())


def test_album_delete_invalid_index_400(monkeypatch):
    _patch_album(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.delete("/api/admin/teachers/55/album/abc", headers=_hdr())
            assert r.status == 400
    _run(_t())


# ============ 频道档案帖（publish-status / publish / sync / repost / delete）============
# service（teacher_channel_publish）被 mock，bot 用 object() 占位（不真发 Telegram）。

def _patch_publish(monkeypatch, *, status_post=None):
    """fake 发布 service 函数；记录调用参数。默认成功。"""
    calls = {}

    async def fake_publish(bot, tid):
        calls["publish"] = tid
        return {"chat_id": -100123, "channel_msg_id": 555, "media_count": 3}

    async def fake_sync(bot, tid, *, force=False):
        calls["sync"] = (tid, force)
        return True

    async def fake_repost(bot, tid):
        calls["repost"] = tid
        return {"chat_id": -100123, "channel_msg_id": 777, "media_count": 2}

    async def fake_delete(bot, tid):
        calls["delete"] = tid
        return True

    async def fake_status(tid):
        return status_post

    monkeypatch.setattr(at_mod, "publish_teacher_post", fake_publish)
    monkeypatch.setattr(at_mod, "update_teacher_post_caption", fake_sync)
    monkeypatch.setattr(at_mod, "repost_teacher_post", fake_repost)
    monkeypatch.setattr(at_mod, "delete_teacher_post", fake_delete)
    monkeypatch.setattr(at_mod, "get_teacher_channel_post", fake_status)
    return calls


# --- publish-status（不需 bot）---

def test_publish_status_requires_admin(monkeypatch):
    _patch_publish(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers/55/publish-status", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_publish_status_unpublished(monkeypatch):
    _patch_publish(monkeypatch, status_post=None)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers/55/publish-status", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["published"] is False and d["media_count"] == 0 and d["channel_msg_id"] is None
    _run(_t())


def test_publish_status_published(monkeypatch):
    _patch_publish(monkeypatch, status_post={
        "channel_msg_id": 555, "media_group_msg_ids": [555, 556, 557],
        "updated_at": "2026-06-29 10:00:00",
    })

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/teachers/55/publish-status", headers=_hdr())
            d = await r.json()
            assert d["published"] is True and d["channel_msg_id"] == 555 and d["media_count"] == 3
    _run(_t())


# --- publish ---

def test_publish_requires_admin(monkeypatch):
    calls = _patch_publish(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teachers/55/publish", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())
    assert "publish" not in calls


def test_publish_bot_unavailable_503(monkeypatch):
    _patch_publish(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/teachers/55/publish", headers=_hdr())
            assert r.status == 503
    _run(_t())


def test_publish_ok(monkeypatch):
    calls = _patch_publish(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teachers/55/publish", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["media_count"] == 3 and d["channel_msg_id"] == 555
    _run(_t())
    assert calls["publish"] == 55


def test_publish_incomplete_maps_error(monkeypatch):
    async def fake_publish(bot, tid):
        raise PublishError("incomplete", "档案缺以下必填字段，请先补全：price", missing=["price"])

    monkeypatch.setattr(at_mod, "publish_teacher_post", fake_publish)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teachers/55/publish", headers=_hdr())
            assert r.status == 200  # 业务失败仍 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "incomplete" and d["missing"] == ["price"]
            assert "必填" in d["message"]
    _run(_t())


def test_publish_no_channel_maps_error(monkeypatch):
    async def fake_publish(bot, tid):
        raise PublishError("no_channel", "未配置档案频道；请先配置 chat_id。")

    monkeypatch.setattr(at_mod, "publish_teacher_post", fake_publish)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teachers/55/publish", headers=_hdr())
            d = await r.json()
            assert d["ok"] is False and d["error"] == "no_channel" and d["missing"] == []
    _run(_t())


# --- sync ---

def test_publish_sync_passes_force(monkeypatch):
    calls = _patch_publish(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teachers/55/publish/sync", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["edited"] is True
    _run(_t())
    # 管理员显式同步必须 force=True（绕过 60s debounce）
    assert calls["sync"] == (55, True)


def test_publish_sync_not_published(monkeypatch):
    async def fake_sync(bot, tid, *, force=False):
        raise PublishError("not_published", "该老师尚未发布档案帖，无法更新 caption。")

    monkeypatch.setattr(at_mod, "update_teacher_post_caption", fake_sync)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teachers/55/publish/sync", headers=_hdr())
            d = await r.json()
            assert d["ok"] is False and d["error"] == "not_published"
    _run(_t())


# --- repost / delete ---

def test_publish_repost_ok(monkeypatch):
    calls = _patch_publish(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/teachers/55/publish/repost", headers=_hdr())
            assert r.status == 200 and (await r.json())["ok"] is True
    _run(_t())
    assert calls["repost"] == 55


def test_publish_delete_ok(monkeypatch):
    calls = _patch_publish(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.delete("/api/admin/teachers/55/publish", headers=_hdr())
            assert r.status == 200 and (await r.json())["ok"] is True
    _run(_t())
    assert calls["delete"] == 55


def test_publish_delete_requires_admin(monkeypatch):
    calls = _patch_publish(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.delete("/api/admin/teachers/55/publish", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())
    assert "delete" not in calls

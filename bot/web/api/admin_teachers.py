"""管理台老师管理端点（阶段2）。

    GET  /api/admin/teachers?status=active|disabled|deleted|all   名册（ROLE_ADMIN+）
    POST /api/admin/teachers/{id}/status  {action: enable|disable|delete|restore}
         enable/disable → ROLE_ADMIN+；delete(软删)/restore → ROLE_SUPERADMIN（破坏性）
    POST /api/admin/teachers/{id}/field   {field, value}  管理员直改字段（ROLE_ADMIN+，无审核）
    *    /api/admin/teachers/{id}/album*    老师相册 看/加/删（ROLE_ADMIN+，即时生效）
    *    /api/admin/teachers/{id}/publish*  频道档案帖 状态/发布/同步/重发/撤帖（ROLE_ADMIN+）

复用 DB 名册/生命周期函数 + teacher_self_edit.admin_set_field + teacher_channel_publish（发布薄封装）。
"""
from __future__ import annotations

import json
import logging

from aiohttp import web

from bot.database import (
    add_teacher_photo,
    enable_teacher,
    get_all_teachers,
    get_deleted_teachers,
    get_teacher_channel_post,
    get_teacher_counts,
    get_teacher_photos,
    remove_teacher,
    remove_teacher_photo,
    restore_teacher,
    soft_delete_teacher,
)
from bot.services.teacher_self_edit import ADMIN_EDITABLE_FIELDS, admin_set_field
from bot.utils.teacher_channel_publish import (
    PublishError,
    delete_teacher_post,
    publish_teacher_post,
    repost_teacher_post,
    update_teacher_post_caption,
)
from bot.web.api.photo import album_payload, TEACHER_ALBUM_MAX
from bot.web.keys import APP_BOT
from bot.web.roles import ROLE_ADMIN, ROLE_SUPERADMIN

logger = logging.getLogger(__name__)


def _require_admin(request: web.Request) -> None:
    if request["session"]["role"] not in (ROLE_ADMIN, ROLE_SUPERADMIN):
        raise web.HTTPForbidden(reason="admin only")


def _require_super(request: web.Request) -> None:
    if request["session"]["role"] != ROLE_SUPERADMIN:
        raise web.HTTPForbidden(reason="superadmin only")


def _teacher_id(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid teacher id")


def _parse_tags(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    try:
        v = json.loads(raw or "[]")
        return [str(x) for x in v if x] if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _item(t: dict) -> dict:
    return {
        "id": t["user_id"],
        "name": t.get("display_name") or "",
        "region": t.get("region") or "",
        "price": t.get("price") or "",
        "tags": _parse_tags(t.get("tags")),
        "button_text": t.get("button_text") or "",
        "button_url": t.get("button_url") or "",
        "is_active": bool(t.get("is_active")),
        "is_deleted": bool(t.get("is_deleted")),
        "has_photo": bool(t.get("photo_file_id")),
    }


async def get_admin_teachers(request: web.Request) -> web.Response:
    """老师名册（按状态过滤）+ 三态计数。"""
    _require_admin(request)
    status = request.query.get("status", "active")

    if status == "deleted":
        rows = await get_deleted_teachers()
    elif status == "disabled":
        rows = [t for t in await get_all_teachers(active_only=False, include_deleted=False)
                if not t.get("is_active")]
    elif status == "all":
        rows = await get_all_teachers(active_only=False, include_deleted=True)
    else:  # active
        rows = await get_all_teachers(active_only=True, include_deleted=False)

    counts = await get_teacher_counts()
    try:
        deleted_count = len(await get_deleted_teachers())
    except Exception:
        deleted_count = 0

    return web.json_response({
        "teachers": [_item(t) for t in rows],
        "counts": {
            "active": counts.get("active", 0),
            "disabled": counts.get("inactive", 0),
            "deleted": deleted_count,
        },
    })


_STATUS_ACTIONS = {"enable", "disable", "delete", "restore"}


async def post_admin_teacher_status(request: web.Request) -> web.Response:
    """启停 / 软删 / 恢复。enable/disable=admin；delete/restore=超管。"""
    _require_admin(request)
    tid = _teacher_id(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    action = (body or {}).get("action")
    if action not in _STATUS_ACTIONS:
        raise web.HTTPBadRequest(reason="invalid action")

    if action in ("delete", "restore"):
        _require_super(request)  # 破坏性操作仅超管

    if action == "enable":
        ok = await enable_teacher(tid)
    elif action == "disable":
        ok = await remove_teacher(tid)
    elif action == "delete":
        ok = await soft_delete_teacher(tid)
    else:  # restore
        ok = await restore_teacher(tid)

    return web.json_response({"ok": bool(ok), "action": action})


async def post_admin_teacher_field(request: web.Request) -> web.Response:
    """管理员直改老师文字字段（即时生效，无审核）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    field = (body or {}).get("field")
    value = (body or {}).get("value")
    if field not in ADMIN_EDITABLE_FIELDS:
        raise web.HTTPBadRequest(reason="invalid field")
    if field == "tags" and isinstance(value, list):
        value = " ".join(str(x) for x in value)

    result = await admin_set_field(tid, field, value)
    return web.json_response(result)


# ── 老师相册（阶段2：管理员改任意老师相册，即时生效、无审核）──────────────────
# 语义照搬老师端 /api/me/teacher-album（profile.py），差异仅：门禁 admin+、
# teacher_id 取自 URL（而非 session）。复用 DB 相册函数 + photo.album_payload。

async def get_admin_teacher_album(request: web.Request) -> web.Response:
    """指定老师的相册照片列表（admin+）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    file_ids = await get_teacher_photos(tid)
    return web.json_response(album_payload(request, tid, file_ids))


async def post_admin_teacher_album(request: web.Request) -> web.Response:
    """给指定老师相册追加一张（admin+）。body: {file_id}（先经 /api/uploads 换得）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    file_id = str((body or {}).get("file_id") or "").strip()
    if not file_id:
        raise web.HTTPBadRequest(reason="missing file_id")

    before = await get_teacher_photos(tid)
    if len(before) >= TEACHER_ALBUM_MAX:
        return web.json_response({
            "ok": False, "error": "full", "count": len(before),
            "message": f"相册已满（最多 {TEACHER_ALBUM_MAX} 张），请先删除再添加。",
        })
    count = await add_teacher_photo(tid, file_id)
    return web.json_response({"ok": True, "count": count})


async def delete_admin_teacher_album(request: web.Request) -> web.Response:
    """删除指定老师相册第 index 张（0-based，即时生效）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    try:
        index = int(request.match_info["index"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid index")
    # DB remove_teacher_photo 是 1-based；越界返回 False。
    ok = await remove_teacher_photo(tid, index + 1)
    if not ok:
        return web.json_response({"ok": False, "error": "bad_index"})
    count = len(await get_teacher_photos(tid))
    return web.json_response({"ok": True, "count": count})


# ── 频道档案帖（阶段2：管理员发布/同步/重发/撤帖；薄封装 teacher_channel_publish）──
# 发布逻辑是 bot-agnostic 纯函数，本层只取 bot + 调函数 + 映射 PublishError → JSON。
# 全部 admin+（档案帖运营、可逆，不涉及老师账户）。

def _bot(request: web.Request):
    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")
    return bot


def _publish_fail(e: PublishError) -> dict:
    return {"ok": False, "error": e.reason, "message": str(e), "missing": e.missing}


async def get_admin_teacher_publish_status(request: web.Request) -> web.Response:
    """老师频道档案帖状态（admin+）：是否已发布 + 帖子元信息。"""
    _require_admin(request)
    tid = _teacher_id(request)
    post = await get_teacher_channel_post(tid)
    return web.json_response({
        "published": post is not None,
        "channel_msg_id": post.get("channel_msg_id") if post else None,
        "media_count": len(post.get("media_group_msg_ids") or []) if post else 0,
        "updated_at": post.get("updated_at") if post else None,
    })


async def post_admin_teacher_publish(request: web.Request) -> web.Response:
    """首次发布老师档案帖到频道（admin+）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    bot = _bot(request)
    try:
        result = await publish_teacher_post(bot, tid)
    except PublishError as e:
        return web.json_response(_publish_fail(e))
    return web.json_response({"ok": True, **result})


async def post_admin_teacher_publish_sync(request: web.Request) -> web.Response:
    """同步频道帖 caption（admin+，force 绕过 60s debounce）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    bot = _bot(request)
    try:
        edited = await update_teacher_post_caption(bot, tid, force=True)
    except PublishError as e:
        return web.json_response(_publish_fail(e))
    return web.json_response({"ok": True, "edited": bool(edited)})


async def post_admin_teacher_publish_repost(request: web.Request) -> web.Response:
    """重发档案帖（admin+，相册改后用：删旧媒体组 + 重发）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    bot = _bot(request)
    try:
        result = await repost_teacher_post(bot, tid)
    except PublishError as e:
        return web.json_response(_publish_fail(e))
    return web.json_response({"ok": True, **result})


async def delete_admin_teacher_publish(request: web.Request) -> web.Response:
    """撤帖：删频道媒体组 + DB row（admin+，不删老师本身）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    bot = _bot(request)
    try:
        ok = await delete_teacher_post(bot, tid)
    except PublishError as e:
        return web.json_response(_publish_fail(e))
    return web.json_response({"ok": bool(ok)})

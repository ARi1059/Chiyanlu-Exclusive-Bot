"""老师照片代理（P1·MiniApp）。

    GET /api/teachers/{id}/photo

老师照片以 Telegram file_id 存库，浏览器无法直读。这里用同进程共享的 aiogram
Bot（app[APP_BOT]，§二零拷贝）把 file 拉成字节流代发，并按 file_id 进程内缓存，
避免每次请求都打 Telegram。无照片 / 取不到 → 404，前端回退渐变占位。
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict

from aiohttp import web

from bot.database import get_teacher
from bot.web.auth import sign_photo, verify_photo
from bot.web.keys import APP_BOT, APP_BOT_TOKEN

logger = logging.getLogger(__name__)


def _album(teacher) -> list:
    """老师相册 file_id 列表：解析 photo_album JSON，空则回退 [photo_file_id]。"""
    raw = (teacher or {}).get("photo_album")
    out: list = []
    try:
        parsed = json.loads(raw) if raw else []
        if isinstance(parsed, list):
            out = [str(x) for x in parsed if x]
    except (json.JSONDecodeError, TypeError):
        out = []
    if not out and (teacher or {}).get("photo_file_id"):
        out = [teacher["photo_file_id"]]
    return out


def signed_photo_url(request: web.Request, teacher_id: int, has_photo: bool, index: int = 0):
    """构造带签名的照片 URL（index 选相册第几张）。无照片返回 None。
    签名只覆盖 teacher_id（相册全是该老师的图、对已鉴权用户全可见）。"""
    if not has_photo:
        return None
    sig = sign_photo(teacher_id, request.app[APP_BOT_TOKEN])
    base = f"/api/teachers/{teacher_id}/photo?sig={sig}"
    return base + (f"&i={index}" if index else "")


TEACHER_ALBUM_MAX = 10


def album_payload(request: web.Request, teacher_id: int, file_ids: list[str]) -> dict:
    """组装相册响应：每张带签名 URL + cache-bust（按 file_id 片段）。

    照片端点回 max-age=86400 且 URL 含 ?sig=&i=N；删/换图后同一 i 指向新 file_id，
    必须用按内容变化的 &v= 破除浏览器缓存（端点忽略未知 query）。
    老师自助（profile）与管理员改他人相册（admin_teachers）共用，杜绝漂移。
    """
    photos = []
    for i, fid in enumerate(file_ids):
        url = signed_photo_url(request, teacher_id, True, i)
        if url:
            url = f"{url}{'&' if '?' in url else '?'}v={str(fid)[:8]}"
        photos.append({"index": i, "url": url})
    return {"photos": photos, "count": len(file_ids), "max": TEACHER_ALBUM_MAX}


# file_id → (content_type, bytes)。OrderedDict 当简易 LRU，超额淘汰最旧。
_CACHE: "OrderedDict[str, tuple[str, bytes]]" = OrderedDict()
_CACHE_MAX = 128
# 单日强缓存：照片更新极少，浏览器/反代各自缓存一天。
_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


def _content_type(file_path: str | None) -> str:
    p = (file_path or "").lower()
    if p.endswith(".png"):
        return "image/png"
    if p.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


async def get_teacher_photo(request: web.Request) -> web.Response:
    try:
        tid = int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid teacher id")

    # 鉴权：URL 签名（中间件已放行本路径；<img> 无法带 Bearer）。
    sig = request.query.get("sig") or ""
    if not verify_photo(tid, sig, request.app[APP_BOT_TOKEN]):
        raise web.HTTPForbidden(reason="invalid photo signature")

    # i：相册索引（默认 0=封面）
    try:
        i = max(0, int(request.query.get("i", "0")))
    except (TypeError, ValueError):
        i = 0

    teacher = await get_teacher(tid)
    album = _album(teacher)
    if not album or i >= len(album):
        raise web.HTTPNotFound(reason="no photo")
    file_id = album[i]

    # 命中缓存
    cached = _CACHE.get(file_id)
    if cached:
        _CACHE.move_to_end(file_id)
        ctype, body = cached
        return web.Response(body=body, content_type=ctype, headers=_CACHE_HEADERS)

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    try:
        tg_file = await bot.get_file(file_id)
        buf = await bot.download_file(tg_file.file_path)
        body = buf.getvalue() if hasattr(buf, "getvalue") else buf.read()
        ctype = _content_type(tg_file.file_path)
    except Exception:
        logger.warning("拉取老师照片失败 teacher=%s", tid, exc_info=True)
        raise web.HTTPNotFound(reason="photo fetch failed")

    _CACHE[file_id] = (ctype, body)
    _CACHE.move_to_end(file_id)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)

    return web.Response(body=body, content_type=ctype, headers=_CACHE_HEADERS)

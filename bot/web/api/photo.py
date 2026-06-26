"""老师照片代理（P1·MiniApp）。

    GET /api/teachers/{id}/photo

老师照片以 Telegram file_id 存库，浏览器无法直读。这里用同进程共享的 aiogram
Bot（app[APP_BOT]，§二零拷贝）把 file 拉成字节流代发，并按 file_id 进程内缓存，
避免每次请求都打 Telegram。无照片 / 取不到 → 404，前端回退渐变占位。
"""
from __future__ import annotations

import logging
from collections import OrderedDict

from aiohttp import web

from bot.database import get_teacher
from bot.web.keys import APP_BOT

logger = logging.getLogger(__name__)

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

    teacher = await get_teacher(tid)
    file_id = (teacher or {}).get("photo_file_id")
    if not file_id:
        raise web.HTTPNotFound(reason="no photo")

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

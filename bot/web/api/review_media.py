"""评价审核媒体代理（P3·§15.4，超管审核台）。

    GET /api/admin/reviews/{id}/media/{kind}   kind ∈ booking | gesture

约课截图 / 现场手势照以 Telegram file_id 存在 teacher_reviews 行上（非老师相册），
浏览器无法直读，且 <img> 不带 Bearer。故照 photo.py 同款：URL 短期签名（覆盖
"rev<id>:<kind>"）+ 同进程 bot 代理拉字节 + 共享 LRU 缓存。签名 URL 只在超管鉴权的
详情端点（admin_reviews.get_review_detail）里下发，未授权方无从构造。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import get_teacher_review
from bot.web.api._media_proxy import CACHE_HEADERS, proxy_telegram_file
from bot.web.auth import sign_media, verify_media
from bot.web.keys import APP_BOT, APP_BOT_TOKEN

logger = logging.getLogger(__name__)

# kind → review 行上的 file_id 列名
_KIND_COLUMN = {
    "booking": "booking_screenshot_file_id",
    "gesture": "gesture_photo_file_id",
}


def _media_key(review_id: int, kind: str) -> str:
    return f"rev{int(review_id)}:{kind}"


def signed_review_media_url(
    request: web.Request, review_id: int, kind: str, *, present: bool,
):
    """构造带签名的评价媒体 URL；对应 file_id 不存在时返回 None。"""
    if not present:
        return None
    sig = sign_media(_media_key(review_id, kind), request.app[APP_BOT_TOKEN])
    return f"/api/admin/reviews/{review_id}/media/{kind}?sig={sig}"


async def get_review_media(request: web.Request) -> web.Response:
    try:
        review_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid review id")
    kind = request.match_info.get("kind", "")
    column = _KIND_COLUMN.get(kind)
    if column is None:
        raise web.HTTPBadRequest(reason="invalid media kind")

    # 鉴权：URL 签名（中间件已放行本路径；<img> 无法带 Bearer）。
    sig = request.query.get("sig") or ""
    if not verify_media(_media_key(review_id, kind), sig, request.app[APP_BOT_TOKEN]):
        raise web.HTTPForbidden(reason="invalid media signature")

    review = await get_teacher_review(review_id)
    file_id = (review or {}).get(column)
    if not file_id:
        # 普通评价路径无手势照（gesture NULL）→ 404，前端隐藏即可。
        raise web.HTTPNotFound(reason="no media")

    try:
        ctype, body = await proxy_telegram_file(request.app.get(APP_BOT), file_id)
    except Exception:
        logger.warning("拉取评价媒体失败 review=%s kind=%s", review_id, kind, exc_info=True)
        raise web.HTTPNotFound(reason="media fetch failed")

    return web.Response(body=body, content_type=ctype, headers=CACHE_HEADERS)

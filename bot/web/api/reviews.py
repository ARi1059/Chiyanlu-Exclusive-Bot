"""写评价端点（P2·MiniApp，docs §14.2）。

    GET  /api/teachers/{id}/review-context   一屏前置判定（限频/必关/报销资格）
    POST /api/reviews                        提交评价（整 payload）

复用 bot.services.review_submit（校验编排，叶子函数与 bot 同源）。bot 取 app[APP_BOT]
（查必关订阅）。身份取自 session。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import get_teacher
from bot.services.review_submit import build_review_context, submit_review
from bot.web.keys import APP_BOT

logger = logging.getLogger(__name__)


async def get_review_context(request: web.Request) -> web.Response:
    uid = request["session"]["uid"]
    try:
        tid = int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid teacher id")

    teacher = await get_teacher(tid)
    if not teacher or not teacher.get("is_active"):
        raise web.HTTPNotFound(reason="teacher not found")

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    ctx = await build_review_context(bot, uid, teacher)
    return web.json_response(ctx)


async def post_review(request: web.Request) -> web.Response:
    uid = request["session"]["uid"]
    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(reason="invalid payload")

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    res = await submit_review(bot, uid, payload)
    if res.ok:
        return web.json_response({"review_id": res.review_id, "status": "pending"})

    # 失败：4xx + 结构化错误，前端据 error_code 提示
    return web.json_response(
        {
            "error": res.error_code,
            "message": res.message,
            "missing": res.missing,
            "fields": res.fields,
        },
        status=400,
    )

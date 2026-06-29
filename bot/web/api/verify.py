"""申请验证端点（MiniApp·用户向老师自证约课）。

    POST /api/teachers/{id}/verify

用户在老师详情页一键发起，服务端校验资格（有用户名 + ≥1 条已通过评价 + 1h 冷却）后，
经 bot 把约课截图 + 评价摘要发到该老师私聊并露名。业务核心在 services/verification。
任意已登录用户可调（资格在 service 内权威校验）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.services.verification import send_verification_to_teacher
from bot.web.keys import APP_BOT

logger = logging.getLogger(__name__)


async def post_verify_teacher(request: web.Request) -> web.Response:
    uid = request["session"]["uid"]
    try:
        tid = int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid teacher id")

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    res = await send_verification_to_teacher(bot, user_id=uid, teacher_id=tid)
    if not res.ok:
        # 业务失败（无资格 / 冷却 / 不可达）→ 200 + ok:false，前端内联提示
        return web.json_response({"ok": False, "error": res.error})
    return web.json_response({"ok": True})

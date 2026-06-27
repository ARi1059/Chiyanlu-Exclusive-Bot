"""图片上传回灌 file_id（P2·MiniApp，docs §14.1）。

    POST /api/uploads   (multipart: field "file" 单图)

web 表单上传二进制，但 Telegram 审核流靠 file_id。这里把字节发到「中转会话」
（config media_buffer_chat_id，未配置回退超管私聊），取 message.photo[-1].file_id 返回，
发后即删（容错）。展示走 P1 的 /api/teachers/{id}/photo 代理（此处只为换 id）。

session 鉴权由中间件覆盖；bot 取 app[APP_BOT]。大小上限 + content-type 限制防滥用。
"""
from __future__ import annotations

import logging

from aiogram.types import BufferedInputFile
from aiohttp import web

from bot.config import config
from bot.database import get_config
from bot.web.keys import APP_BOT

logger = logging.getLogger(__name__)

_MAX_BYTES = 10 * 1024 * 1024  # 10MB
_ALLOWED = {"image/jpeg", "image/png", "image/webp"}


async def _buffer_chat_id():
    """中转会话：config media_buffer_chat_id（数字转 int），未配置回退超管私聊。"""
    raw = await get_config("media_buffer_chat_id")
    if raw:
        s = str(raw).strip()
        return int(s) if s.lstrip("-").isdigit() else s
    return config.super_admin_id


async def post_upload(request: web.Request) -> web.Response:
    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    try:
        reader = await request.multipart()
        part = await reader.next()
    except Exception:
        raise web.HTTPBadRequest(reason="expected multipart/form-data")
    # 找到名为 file 的图片字段
    while part is not None and part.name != "file":
        part = await reader.next()
    if part is None:
        raise web.HTTPBadRequest(reason="missing file field")

    ctype = (part.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype and ctype not in _ALLOWED:
        raise web.HTTPUnsupportedMediaType(reason="only jpeg/png/webp")

    # 读取并限制大小
    buf = bytearray()
    while True:
        chunk = await part.read_chunk()
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > _MAX_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=_MAX_BYTES, actual_size=len(buf))
    if not buf:
        raise web.HTTPBadRequest(reason="empty file")

    chat_id = await _buffer_chat_id()
    try:
        msg = await bot.send_photo(chat_id, BufferedInputFile(bytes(buf), filename="upload.jpg"))
    except Exception:
        logger.warning("回灌 file_id：send_photo 失败 chat=%s", chat_id, exc_info=True)
        raise web.HTTPBadGateway(reason="upload relay failed")

    file_id = msg.photo[-1].file_id if msg.photo else None
    # 发后即删（容错，不影响已取到的 file_id）
    try:
        await bot.delete_message(chat_id, msg.message_id)
    except Exception:
        logger.info("中转图删除失败（无碍）chat=%s msg=%s", chat_id, msg.message_id)

    if not file_id:
        raise web.HTTPBadGateway(reason="no file_id from telegram")
    return web.json_response({"file_id": file_id})

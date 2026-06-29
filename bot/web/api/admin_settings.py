"""管理台系统配置端点（阶段2：档案发布配置）。

    GET  /api/admin/settings/archive   读档案频道 + 品牌设置（ROLE_ADMIN+）
    POST /api/admin/settings/archive   逐项校验落库（ROLE_ADMIN+，body 只含要改的键）

老师档案帖发布依赖的 3 项全局配置（archive_channel_id / archive_brand_name /
archive_brand_channels）。复用通用 KV get_config/set_config + set/get_archive_channel_id
（含回退 publish_channel_id）。校验照搬 bot admin_panel 的 archive 三项 handler。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import (
    get_archive_channel_id,
    get_config,
    set_archive_channel_id,
    set_config,
)
from bot.web.roles import ROLE_ADMIN, ROLE_SUPERADMIN

logger = logging.getLogger(__name__)

BRAND_NAME_DEFAULT = "《痴颜录》"
BRAND_NAME_MAX = 30
BRAND_CHANNELS_MAX = 200


def _require_admin(request: web.Request) -> None:
    if request["session"]["role"] not in (ROLE_ADMIN, ROLE_SUPERADMIN):
        raise web.HTTPForbidden(reason="admin only")


def _fail(code: str, field: str, message: str) -> dict:
    return {"ok": False, "error": code, "field": field, "message": message}


async def get_archive_settings(request: web.Request) -> web.Response:
    """档案频道 + 品牌设置（含生效频道值，区分独立配置与回退）。"""
    _require_admin(request)
    return web.json_response({
        "channel_id": await get_config("archive_channel_id") or "",        # 独立配置原始值
        "effective_channel_id": await get_archive_channel_id(),            # 实际生效（含回退）
        "brand_name": await get_config("archive_brand_name") or "",
        "brand_channels": await get_config("archive_brand_channels") or "",
        "brand_name_default": BRAND_NAME_DEFAULT,
    })


async def post_archive_settings(request: web.Request) -> web.Response:
    """逐项校验 + 落库（body 只含要改的键）。校验失败 200 + {ok:false}。"""
    _require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(reason="invalid json body")

    # 档案频道：空串=清空（回退 publish_channel_id）；否则 int（正负均可）
    if "channel_id" in body:
        raw = str(body.get("channel_id") or "").strip()
        if not raw:
            await set_config("archive_channel_id", "")
        else:
            try:
                chat_id = int(raw)
            except ValueError:
                return web.json_response(
                    _fail("bad_channel_id", "channel_id", "频道 ID 必须是数字（正负均可），留空清除"))
            await set_archive_channel_id(chat_id)

    # 品牌名：>30 拒；空=清空（渲染回退默认《痴颜录》）
    if "brand_name" in body:
        name = str(body.get("brand_name") or "").strip()
        if len(name) > BRAND_NAME_MAX:
            return web.json_response(
                _fail("bad_brand_name", "brand_name", f"品牌名过长（最多 {BRAND_NAME_MAX} 字）"))
        await set_config("archive_brand_name", name)

    # 品牌频道：每段须 @ 开头、>200 拒；空=清空
    if "brand_channels" in body:
        chans = str(body.get("brand_channels") or "").strip()
        if chans:
            invalid = [p for p in chans.split() if not p.startswith("@")]
            if invalid:
                return web.json_response(_fail(
                    "bad_brand_channels", "brand_channels",
                    f"以下未以 @ 开头：{', '.join(invalid[:3])}；格式 @xxx @yyy 空格分隔"))
            if len(chans) > BRAND_CHANNELS_MAX:
                return web.json_response(
                    _fail("too_long", "brand_channels", f"内容过长（最多 {BRAND_CHANNELS_MAX} 字）"))
        await set_config("archive_brand_channels", chans)

    return web.json_response({"ok": True, "message": "已保存"})

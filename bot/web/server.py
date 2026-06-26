"""aiohttp web 服务挂载（P0·T4）。

与 aiogram polling 共用同一 asyncio loop（§二 同进程决策）：main.py 用
asyncio.gather(dp.start_polling(bot), start_web(bot)) 并起。本模块只负责构造
aiohttp Application、挂路由、用 AppRunner 起监听，不碰 polling。

注入 app 的运行时对象：
    app["bot"]        共享的 aiogram Bot（通知回流用，同进程零拷贝）
    app["bot_token"]  initData 验签 + session 校验的密钥来源

路由（P0）：
    GET  /api/health         健康检查（中间件白名单，免鉴权）
    POST /api/auth/session   initData 换 session token（api/auth.py）
    GET  /api/me             返回当前角色（需 session，api/me.py）
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiohttp import web

from bot.config import config
from bot.web.keys import APP_BOT, APP_BOT_TOKEN
from bot.web.middleware import auth_middleware

logger = logging.getLogger(__name__)


async def _health(request: web.Request) -> web.Response:
    """健康检查：白名单放行，用于反代 / 监控探活。"""
    return web.json_response({"status": "ok"})


def create_web_app(bot: Optional[Bot], *, bot_token: Optional[str] = None) -> web.Application:
    """构造 aiohttp Application + 挂 P0 路由。

    bot 允许为 None（仅鉴权链路的集成测试用）；生产传入共享的 Bot 对象。
    """
    app = web.Application(middlewares=[auth_middleware])
    app[APP_BOT] = bot
    app[APP_BOT_TOKEN] = bot_token or config.bot_token

    app.router.add_get("/api/health", _health)
    # 资源路由集中在 api 子包注册，避免本文件随 Phase 膨胀。
    from bot.web.api import register_api_routes
    register_api_routes(app)
    return app


async def start_web(
    bot: Bot,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    bot_token: Optional[str] = None,
) -> web.AppRunner:
    """启动 web 服务（与 polling 同 loop，§二）。返回 AppRunner 供 shutdown cleanup。

    默认绑 127.0.0.1：生产由 Nginx/Caddy 终止 TLS 后反代到本地端口（§九），
    web 服务本身不直接对公网暴露。
    """
    app = create_web_app(bot, bot_token=bot_token)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("Web 服务已启动: http://%s:%d", host, port)
    return runner

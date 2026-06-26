"""MiniApp REST 路由注册（P0·T5）。

集中注册端点；后续 Phase（P1 富展示 / P2 写 / P3 后台）在此追加资源路由，
保持 server.py 不随业务膨胀。
"""
from __future__ import annotations

from aiohttp import web

from bot.web.api.auth import post_session
from bot.web.api.me import get_me


def register_api_routes(app: web.Application) -> None:
    """挂载 P0 端点。"""
    app.router.add_post("/api/auth/session", post_session)
    app.router.add_get("/api/me", get_me)

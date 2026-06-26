"""MiniApp REST 路由注册（P0·T5）。

集中注册端点；后续 Phase（P1 富展示 / P2 写 / P3 后台）在此追加资源路由，
保持 server.py 不随业务膨胀。
"""
from __future__ import annotations

from aiohttp import web

from bot.web.api.auth import post_session
from bot.web.api.admin import get_admin_stats
from bot.web.api.admin_reviews import post_approve_review, post_reject_review
from bot.web.api.favorites import delete_favorite, get_favorites, post_favorite
from bot.web.api.me import get_me
from bot.web.api.photo import get_teacher_photo
from bot.web.api.profile import get_profile
from bot.web.api.teachers import get_teacher_detail, get_teachers


def register_api_routes(app: web.Application) -> None:
    """挂载 API 端点。"""
    # P0：鉴权
    app.router.add_post("/api/auth/session", post_session)
    app.router.add_get("/api/me", get_me)
    app.router.add_get("/api/profile", get_profile)
    # P1：老师数据（MiniApp）
    app.router.add_get("/api/teachers", get_teachers)
    app.router.add_get("/api/teachers/{id}", get_teacher_detail)
    app.router.add_get("/api/teachers/{id}/photo", get_teacher_photo)
    # P1：收藏
    app.router.add_get("/api/favorites", get_favorites)
    app.router.add_post("/api/favorites", post_favorite)
    app.router.add_delete("/api/favorites/{id}", delete_favorite)
    # P1：管理台（仅 admin/superadmin，端点内校验）
    app.router.add_get("/api/admin/stats", get_admin_stats)
    # P1：评价审核落库（仅 superadmin，端点内校验）
    app.router.add_post("/api/admin/reviews/{id}/approve", post_approve_review)
    app.router.add_post("/api/admin/reviews/{id}/reject", post_reject_review)

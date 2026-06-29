"""MiniApp REST 路由注册（P0·T5）。

集中注册端点；后续 Phase（P1 富展示 / P2 写 / P3 后台）在此追加资源路由，
保持 server.py 不随业务膨胀。
"""
from __future__ import annotations

from aiohttp import web

from bot.web.api.auth import post_session
from bot.web.api.admin import get_admin_stats
from bot.web.api.admin_audit import get_audit_logs
from bot.web.api.admin_reviews import (
    get_review_detail,
    post_approve_review,
    post_claim_review,
    post_force_claim_review,
    post_reject_review,
    post_release_review,
)
from bot.web.api.review_media import get_review_media
from bot.web.api.admin_teacher_edits import (
    get_teacher_edits,
    post_approve_teacher_edit,
    post_reject_teacher_edit,
)
from bot.web.api.admin_teachers import (
    delete_admin_teacher_album,
    delete_admin_teacher_publish,
    get_admin_teacher_album,
    get_admin_teacher_publish_status,
    get_admin_teachers,
    post_admin_teacher_album,
    post_admin_teacher_create,
    post_admin_teacher_field,
    post_admin_teacher_publish,
    post_admin_teacher_publish_repost,
    post_admin_teacher_publish_sync,
    post_admin_teacher_status,
)
from bot.web.api.admin_settings import (
    get_archive_settings,
    post_archive_settings,
)
from bot.web.api.admin_reimbursements import (
    get_reimbursement_detail,
    get_reimbursements,
    post_activate_reimbursement,
    post_payout_reimbursement,
    post_reject_reimbursement,
    post_reset_week_reimbursement,
)
from bot.web.api.favorites import delete_favorite, get_favorites, post_favorite
from bot.web.api.me import get_me
from bot.web.api.photo import get_teacher_photo
from bot.web.api.profile import (
    delete_teacher_album,
    get_my_points,
    get_my_reviews,
    get_profile,
    get_teacher_album,
    get_teacher_edit_profile,
    get_teacher_home,
    post_checkin,
    post_notify,
    post_teacher_album,
    post_teacher_edit_profile,
)
from bot.web.api.reviews import get_review_context, post_review
from bot.web.api.teachers import get_teacher_detail, get_teachers
from bot.web.api.uploads import post_upload
from bot.web.api.verify import post_verify_teacher


def register_api_routes(app: web.Application) -> None:
    """挂载 API 端点。"""
    # P0：鉴权
    app.router.add_post("/api/auth/session", post_session)
    app.router.add_get("/api/me", get_me)
    app.router.add_get("/api/profile", get_profile)
    app.router.add_get("/api/me/points", get_my_points)
    app.router.add_get("/api/me/reviews", get_my_reviews)
    app.router.add_post("/api/me/notify", post_notify)
    app.router.add_post("/api/me/checkin", post_checkin)
    app.router.add_get("/api/me/teacher-home", get_teacher_home)
    # §16.3：老师自助编辑资料（仅 teacher，端点内校验；同源 service，过审+回滚）
    app.router.add_get("/api/me/teacher-profile", get_teacher_edit_profile)
    app.router.add_post("/api/me/teacher-profile", post_teacher_edit_profile)
    # 老师自助多图相册（即时生效，不走审核；仅 teacher）
    app.router.add_get("/api/me/teacher-album", get_teacher_album)
    app.router.add_post("/api/me/teacher-album", post_teacher_album)
    app.router.add_delete("/api/me/teacher-album/{index}", delete_teacher_album)
    # P1：老师数据（MiniApp）
    app.router.add_get("/api/teachers", get_teachers)
    app.router.add_get("/api/teachers/{id}", get_teacher_detail)
    app.router.add_get("/api/teachers/{id}/photo", get_teacher_photo)
    # 申请验证：用户在老师页一键自证约课 → bot 把约课截图+摘要发老师（任意登录用户，资格在 service 校验）
    app.router.add_post("/api/teachers/{id}/verify", post_verify_teacher)
    # P2：写评价（in-app 表单）
    app.router.add_get("/api/teachers/{id}/review-context", get_review_context)
    app.router.add_post("/api/reviews", post_review)
    app.router.add_post("/api/uploads", post_upload)
    # P1：收藏
    app.router.add_get("/api/favorites", get_favorites)
    app.router.add_post("/api/favorites", post_favorite)
    app.router.add_delete("/api/favorites/{id}", delete_favorite)
    # P1：管理台（仅 admin/superadmin，端点内校验）
    app.router.add_get("/api/admin/stats", get_admin_stats)
    # P1：评价审核落库（仅 superadmin，端点内校验）
    app.router.add_post("/api/admin/reviews/{id}/approve", post_approve_review)
    app.router.add_post("/api/admin/reviews/{id}/reject", post_reject_review)
    # §15.4：评价审核详情 + claim 占用锁（仅 superadmin；媒体端点 URL 签名放行 session）
    app.router.add_get("/api/admin/reviews/{id}", get_review_detail)
    app.router.add_post("/api/admin/reviews/{id}/claim", post_claim_review)
    app.router.add_post("/api/admin/reviews/{id}/force-claim", post_force_claim_review)
    app.router.add_post("/api/admin/reviews/{id}/release", post_release_review)
    app.router.add_get("/api/admin/reviews/{id}/media/{kind}", get_review_media)
    # 阶段1：老师资料审核（ROLE_ADMIN+，端点内校验；复用同源 service 通知老师）
    app.router.add_get("/api/admin/teacher-edits", get_teacher_edits)
    app.router.add_post("/api/admin/teacher-edits/{id}/approve", post_approve_teacher_edit)
    app.router.add_post("/api/admin/teacher-edits/{id}/reject", post_reject_teacher_edit)
    # 阶段2：老师管理（名册/启停/软删恢复/直改字段；端点内分级校验）
    app.router.add_get("/api/admin/teachers", get_admin_teachers)
    app.router.add_post("/api/admin/teachers", post_admin_teacher_create)
    app.router.add_post("/api/admin/teachers/{id}/status", post_admin_teacher_status)
    app.router.add_post("/api/admin/teachers/{id}/field", post_admin_teacher_field)
    # 阶段2：老师相册（管理员改任意老师相册，admin+；语义同 /api/me/teacher-album）
    app.router.add_get("/api/admin/teachers/{id}/album", get_admin_teacher_album)
    app.router.add_post("/api/admin/teachers/{id}/album", post_admin_teacher_album)
    app.router.add_delete("/api/admin/teachers/{id}/album/{index}", delete_admin_teacher_album)
    # 阶段2：频道档案帖（管理员发布/同步/重发/撤帖，admin+；薄封装 teacher_channel_publish）
    app.router.add_get("/api/admin/teachers/{id}/publish-status", get_admin_teacher_publish_status)
    app.router.add_post("/api/admin/teachers/{id}/publish", post_admin_teacher_publish)
    app.router.add_post("/api/admin/teachers/{id}/publish/sync", post_admin_teacher_publish_sync)
    app.router.add_post("/api/admin/teachers/{id}/publish/repost", post_admin_teacher_publish_repost)
    app.router.add_delete("/api/admin/teachers/{id}/publish", delete_admin_teacher_publish)
    # 阶段2：档案发布配置（档案频道 + 品牌，admin+；老师档案帖发布依赖）
    app.router.add_get("/api/admin/settings/archive", get_archive_settings)
    app.router.add_post("/api/admin/settings/archive", post_archive_settings)
    # P1/§15.5：报销审核（仅 superadmin）。打款=支付宝口令经 bot DM 发用户，core 编排
    app.router.add_get("/api/admin/reimbursements", get_reimbursements)
    app.router.add_get("/api/admin/reimbursements/{id}", get_reimbursement_detail)
    app.router.add_post("/api/admin/reimbursements/{id}/reject", post_reject_reimbursement)
    app.router.add_post("/api/admin/reimbursements/{id}/activate", post_activate_reimbursement)
    app.router.add_post("/api/admin/reimbursements/{id}/payout", post_payout_reimbursement)
    app.router.add_post("/api/admin/reimbursements/{id}/reset-week", post_reset_week_reimbursement)
    # §15.7：审计日志台（仅 superadmin；分页 + action 过滤，复用现成查询 helper）
    app.router.add_get("/api/admin/audit-logs", get_audit_logs)

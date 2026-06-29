"""管理台评价审核端点（P1·MiniApp，仅超管）。

    POST /api/admin/reviews/{id}/approve   通过 + 加分套餐（body: {package_key} 或 {delta}）
    POST /api/admin/reviews/{id}/reject    驳回（body: {reason?}）

复用 bot.services.review_moderation —— 与 bot Telegram 审核同一套业务逻辑（含频道发布/
讨论群/私聊通知/报销联动），避免逻辑漂移。bot 对象取自 app[APP_BOT]（同进程共享）。
仅 superadmin 可操作（对齐 bot 的 _super_admin_required）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import (
    POINT_CUSTOM_MAX,
    POINT_CUSTOM_MIN,
    POINT_PACKAGE_OPTIONS,
    REVIEW_RATINGS,
    compute_reimbursement_amount,
    get_reimbursement_min_points,
    get_teacher,
    get_teacher_review,
    get_user,
    get_user_total_points,
    log_admin_audit,
)
from bot.services.review_moderation import approve_review, reject_review
from bot.utils.review_claim import force_claim, get_claim, release_claim, try_claim
from bot.web.api.review_media import signed_review_media_url
from bot.web.keys import APP_BOT
from bot.web.roles import ROLE_SUPERADMIN

logger = logging.getLogger(__name__)

# claim 锁命名空间（与 audit target_type / bot rreview_admin 对齐）
_CLAIM_KIND = "teacher_review"


def _require_super(request: web.Request) -> int:
    """校验 superadmin；返回 reviewer_id（当前超管 uid）。否则 403。"""
    session = request["session"]
    if session["role"] != ROLE_SUPERADMIN:
        raise web.HTTPForbidden(reason="superadmin only")
    return session["uid"]


def _review_id(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid review id")


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _resolve_delta(body: dict) -> tuple[int, str]:
    """解析加分量：优先 package_key（预设套餐），否则 delta（自定义 0..100）。
    delta 由后端权威解析，不信前端传的 label。"""
    key = body.get("package_key")
    if key:
        pkg = next((o for o in POINT_PACKAGE_OPTIONS if o["key"] == key), None)
        if not pkg:
            raise web.HTTPBadRequest(reason="unknown package_key")
        return int(pkg["delta"]), str(pkg["label"])
    raw = body.get("delta")
    if raw is None:
        raise web.HTTPBadRequest(reason="missing package_key or delta")
    try:
        delta = int(raw)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="invalid delta")
    if not (POINT_CUSTOM_MIN <= delta <= POINT_CUSTOM_MAX):
        raise web.HTTPBadRequest(
            reason=f"delta out of range [{POINT_CUSTOM_MIN},{POINT_CUSTOM_MAX}]"
        )
    return delta, f"自定义 +{delta}"


# ============ 详情 + claim 占用锁（§15.4）============

def _mask_uid(user_id) -> str:
    """半匿名展示：尾 4 位（****6204）。对齐 bot rreview _anonymize_user_id。"""
    s = str(user_id)
    if len(s) <= 4:
        return "****"
    return "*" * (len(s) - 4) + s[-4:]


async def _user_label(user_id) -> str:
    """脱敏用户标识：优先 @username / first_name，否则尾号（与报销端点同款）。"""
    try:
        u = await get_user(int(user_id))
    except Exception:
        u = None
    if u and u.get("username"):
        return f"@{u['username']}"
    if u and u.get("first_name"):
        return u["first_name"]
    return _mask_uid(user_id)


async def _serialize_claim(review_id: int, viewer_id: int) -> dict:
    """只读 claim 信息：held_by / held_by_name / acquired_at / by_me。"""
    info = get_claim(_CLAIM_KIND, review_id)
    if info is None:
        return {"held_by": None, "held_by_name": None, "acquired_at": None, "by_me": False}
    return {
        "held_by": info.admin_id,
        "held_by_name": await _user_label(info.admin_id),
        "acquired_at": int(info.acquired_at),
        "by_me": int(info.admin_id) == int(viewer_id),
    }


async def _build_detail(request: web.Request, review: dict, viewer_id: int) -> dict:
    """组装评价审核详情：6 维分 + 媒体签名 URL + 报销资格预判 + claim 态。"""
    review_id = int(review["id"])
    teacher_id = review["teacher_id"]
    user_id = review["user_id"]
    teacher = await get_teacher(teacher_id)
    teacher_name = (teacher or {}).get("display_name") or f"#{teacher_id}"

    rating_meta = {r["key"]: r for r in REVIEW_RATINGS}.get(
        review.get("rating"),
        {"emoji": "❓", "label": review.get("rating") or "?"},
    )

    # 报销资格预判：金额（按老师价位）+ 实时积分 vs 门槛
    teacher_price = (teacher or {}).get("price")
    amount = compute_reimbursement_amount(teacher_price)
    min_pts = await get_reimbursement_min_points()
    user_pts = await get_user_total_points(user_id)
    req_flag = int(review.get("request_reimbursement") or 0)
    eligible = amount > 0 and (min_pts == 0 or user_pts >= min_pts)

    return {
        "id": review_id,
        "teacher_id": teacher_id,
        "teacher_name": teacher_name,
        "user_masked": _mask_uid(user_id),
        "anonymous": int(review.get("anonymous") or 0) == 1,
        "created_at": str(review.get("created_at") or ""),
        "rating": {"key": review.get("rating"), "emoji": rating_meta["emoji"], "label": rating_meta["label"]},
        "scores": {
            "humanphoto": review.get("score_humanphoto"),
            "appearance": review.get("score_appearance"),
            "body": review.get("score_body"),
            "service": review.get("score_service"),
            "attitude": review.get("score_attitude"),
            "environment": review.get("score_environment"),
            "overall": review.get("overall_score"),
        },
        "summary": review.get("summary") or "",
        "media": {
            "booking_url": signed_review_media_url(
                request, review_id, "booking",
                present=bool(review.get("booking_screenshot_file_id")),
            ),
            "gesture_url": signed_review_media_url(
                request, review_id, "gesture",
                present=bool(review.get("gesture_photo_file_id")),
            ),
        },
        "reimbursement": {
            "requested": req_flag,
            "amount": amount,
            "teacher_price": teacher_price,
            "user_total_points": user_pts,
            "min_points": min_pts,
            "eligible": eligible,
        },
        "claim": await _serialize_claim(review_id, viewer_id),
    }


async def _load_review(review_id: int) -> dict:
    """取一条 review；不存在 → 404。非 pending 不拦（详情对已审也可看，前端按 status 处理）。"""
    review = await get_teacher_review(review_id)
    if not review:
        raise web.HTTPNotFound(reason="review not found")
    return review


async def get_review_detail(request: web.Request) -> web.Response:
    """GET /api/admin/reviews/{id} —— 审核详情（仅超管）。"""
    viewer_id = _require_super(request)
    review_id = _review_id(request)
    review = await _load_review(review_id)
    detail = await _build_detail(request, review, viewer_id)
    return web.json_response({"ok": True, "detail": detail})


async def post_claim_review(request: web.Request) -> web.Response:
    """POST /api/admin/reviews/{id}/claim —— 声明占用，成功带回详情。"""
    viewer_id = _require_super(request)
    review_id = _review_id(request)
    review = await _load_review(review_id)

    ok, existing = try_claim(_CLAIM_KIND, review_id, viewer_id)
    if not ok and existing is not None:
        return web.json_response({
            "ok": False,
            "claim": {
                "held_by": existing.admin_id,
                "held_by_name": await _user_label(existing.admin_id),
                "acquired_at": int(existing.acquired_at),
            },
        })
    detail = await _build_detail(request, review, viewer_id)
    return web.json_response({"ok": True, "detail": detail})


async def post_force_claim_review(request: web.Request) -> web.Response:
    """POST /api/admin/reviews/{id}/force-claim —— 强制接管（写 audit）。"""
    viewer_id = _require_super(request)
    review_id = _review_id(request)
    review = await _load_review(review_id)

    existing = get_claim(_CLAIM_KIND, review_id)
    prev_holder = existing.admin_id if existing else None
    force_claim(_CLAIM_KIND, review_id, viewer_id)
    try:
        await log_admin_audit(
            admin_id=viewer_id,
            action="rreview_force_claim",
            target_type=_CLAIM_KIND,
            target_id=str(review_id),
            detail={"previous_holder": prev_holder},
        )
    except Exception:
        logger.warning("rreview_force_claim audit 失败 review=%s", review_id)

    detail = await _build_detail(request, review, viewer_id)
    return web.json_response({"ok": True, "detail": detail})


async def post_release_review(request: web.Request) -> web.Response:
    """POST /api/admin/reviews/{id}/release —— 释放占用（关闭详情时）。"""
    viewer_id = _require_super(request)
    review_id = _review_id(request)
    release_claim(_CLAIM_KIND, review_id, viewer_id)
    return web.json_response({"ok": True})


async def post_approve_review(request: web.Request) -> web.Response:
    reviewer_id = _require_super(request)
    review_id = _review_id(request)
    delta, package_label = _resolve_delta(await _json_body(request))

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    result = await approve_review(
        bot, review_id=review_id, reviewer_id=reviewer_id,
        delta=delta, package_label=package_label,
    )
    if not result.ok:
        # 业务失败（不存在/已审）→ 200 + ok:false，前端统一读 body
        return web.json_response({"ok": False, "error": result.error})
    return web.json_response({
        "ok": True,
        "review_id": result.review_id,
        "delta": result.delta,
        "new_total": result.new_total,
        "reimb_amount": result.reimb_amount,
        "reimb_status": result.reimb_status,
    })


async def post_reject_review(request: web.Request) -> web.Response:
    reviewer_id = _require_super(request)
    review_id = _review_id(request)
    body = await _json_body(request)
    reason = body.get("reason")
    if reason is not None:
        reason = str(reason).strip() or None

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    result = await reject_review(
        bot, review_id=review_id, reviewer_id=reviewer_id, reason=reason,
    )
    if not result.ok:
        return web.json_response({"ok": False, "error": result.error})
    return web.json_response({"ok": True, "review_id": result.review_id})

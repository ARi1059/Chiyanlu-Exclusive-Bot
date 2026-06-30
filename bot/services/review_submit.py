"""写评价共享 service（MiniApp web 端整 payload 提交 + 前置上下文）。

bot 侧是增量收集的卡片 FSM(review_card.py)；web 是一次性 payload，模型不同，故本 service
只服务 web。但**校验调用的叶子函数与 bot 同源**(同一限频/必关/资格/落库/通知函数)，仅编排顺序
按 docs §14.2 复刻 → 单一真相源、低漂移。

校验顺序(权威)：teacher active → 限频(3 档) → 全局必关频道 → (报销) 报销必关 + 资格
→ 字段校验 → create_teacher_review(status=pending) → 回流通知超管。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from bot.database import (
    REVIEW_DIMENSIONS,
    REVIEW_RATE_LIMIT_PER_TEACHER_24H,
    REVIEW_RATE_LIMIT_PER_USER_60S,
    REVIEW_RATE_LIMIT_PER_USER_DAY,
    REVIEW_SUMMARY_MAX_LEN,
    REVIEW_SUMMARY_MIN_LEN,
    count_recent_user_reviews,
    count_recent_user_teacher_reviews,
    create_teacher_review,
    derive_rating,
    get_teacher,
    parse_review_score,
)
from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
from bot.utils.required_channels import check_user_subscribed

logger = logging.getLogger(__name__)

_DIM_KEYS = [d["key"] for d in REVIEW_DIMENSIONS]  # humanphoto/appearance/...
_DIM_COLUMN = {d["key"]: d["column"] for d in REVIEW_DIMENSIONS}


@dataclass
class SubmitResult:
    ok: bool
    error_code: Optional[str] = None      # rate_limited / need_subscribe / reimburse_ineligible / invalid_fields / create_failed / teacher_inactive
    message: Optional[str] = None
    missing: list = field(default_factory=list)   # need_subscribe 时的缺失频道
    fields: list = field(default_factory=list)     # invalid_fields 时的字段错
    review_id: Optional[int] = None


async def check_rate_limit(user_id: int, teacher_id: int) -> Optional[str]:
    """三档限频，命中返回中文文案，否则 None（复刻 review_card._check_rate_limit）。"""
    if await count_recent_user_reviews(user_id, 60) >= REVIEW_RATE_LIMIT_PER_USER_60S:
        return "提交太频繁，请 1 分钟后再试"
    if await count_recent_user_teacher_reviews(user_id, teacher_id, 86400) >= REVIEW_RATE_LIMIT_PER_TEACHER_24H:
        return f"今天该老师已超出限制（{REVIEW_RATE_LIMIT_PER_TEACHER_24H} 条/24h）"
    if await count_recent_user_reviews(user_id, 86400) >= REVIEW_RATE_LIMIT_PER_USER_DAY:
        return f"今天已超出全平台限制（{REVIEW_RATE_LIMIT_PER_USER_DAY} 条/24h）"
    return None


def compute_overall(scores: dict) -> float:
    """6 维均值保留 1 位（复刻 _compute_overall_avg）。"""
    try:
        vals = [float(scores[k]) for k in _DIM_KEYS]
    except (TypeError, ValueError, KeyError):
        return 0.0
    return round(sum(vals) / len(vals), 1)


def validate_payload(payload: dict) -> list:
    """字段校验，返回错误列表（空=通过）。复刻 _missing_fields + 字段范围。"""
    errs: list = []
    # rating 不再由用户传入：2026-06-30 起按 6 维综合分自动判定（derive_rating），此处不校验。
    # 6 维分（parse_review_score：0–10，≤1 位小数）
    scores = payload.get("scores") or {}
    for k in _DIM_KEYS:
        raw = scores.get(k)
        if raw is None or parse_review_score(str(raw)) is None:
            errs.append(f"评分 {k} 非法（0–10）")
    # summary 长度
    summary = (payload.get("summary") or "").strip()
    if not (REVIEW_SUMMARY_MIN_LEN <= len(summary) <= REVIEW_SUMMARY_MAX_LEN):
        errs.append(f"过程描述需 {REVIEW_SUMMARY_MIN_LEN}–{REVIEW_SUMMARY_MAX_LEN} 字")
    # evidence：约课截图必传；参与报销则手势照必传
    if not payload.get("booking_screenshot_file_id"):
        errs.append("缺约课截图")
    if int(payload.get("request_reimbursement") or 0) == 1 and not payload.get("gesture_photo_file_id"):
        errs.append("参与报销需上传现场手势照")
    return errs


async def build_review_context(bot, user_id: int, teacher: dict) -> dict:
    """一屏决策上下文：限频 / 全局必关 / 报销资格 + 报销必关。"""
    rate_msg = await check_rate_limit(user_id, teacher["user_id"])
    glob_ok, glob_missing = await check_user_subscribed(bot, user_id)
    elig, info = await is_user_reimburse_eligible_for_review(user_id, teacher.get("price"))
    reimb_ok, reimb_missing = await check_user_subscribed_for_reimburse(bot, user_id)
    hint = None
    if not elig:
        try:
            hint = format_reimburse_ineligibility_hint(
                amount=int(info.get("amount") or 0),
                points=int(info.get("points") or 0),
                min_pts=int(info.get("min_pts") or 0),
                reason=info.get("reason"),
                pool_remaining=info.get("pool_remaining"),
            )
        except Exception:
            hint = None
    return {
        "teacher": {
            "id": teacher["user_id"],
            "display_name": teacher.get("display_name") or "",
        },
        "rate_limit": {"blocked": rate_msg is not None, "reason": rate_msg},
        "required_channels": {"ok": glob_ok, "missing": glob_missing},
        "reimburse": {
            "eligible": bool(elig),
            "estimated_amount": int(info.get("amount") or 0),
            "ineligibility_hint": hint,
            "required_channels": {"ok": reimb_ok, "missing": reimb_missing},
        },
    }


async def submit_review(bot, user_id: int, payload: dict) -> SubmitResult:
    """按 §14.2 顺序校验 + 落库 + 回流。payload 见 docs §14.2。"""
    try:
        teacher_id = int(payload.get("teacher_id"))
    except (TypeError, ValueError):
        return SubmitResult(ok=False, error_code="invalid_fields", fields=["teacher_id 非法"])

    # 1. teacher active
    teacher = await get_teacher(teacher_id)
    if not teacher or not teacher.get("is_active"):
        return SubmitResult(ok=False, error_code="teacher_inactive", message="该老师暂不可评价")

    # 2. 限频
    rate_msg = await check_rate_limit(user_id, teacher_id)
    if rate_msg:
        return SubmitResult(ok=False, error_code="rate_limited", message=rate_msg)

    # 3. 全局必关频道
    glob_ok, glob_missing = await check_user_subscribed(bot, user_id)
    if not glob_ok:
        return SubmitResult(ok=False, error_code="need_subscribe", message="请先关注必关频道", missing=glob_missing)

    req_reimburse = int(payload.get("request_reimbursement") or 0)
    # 4. 报销路径：报销必关 + 资格
    if req_reimburse == 1:
        reimb_ok, reimb_missing = await check_user_subscribed_for_reimburse(bot, user_id)
        if not reimb_ok:
            return SubmitResult(ok=False, error_code="need_subscribe", message="参与报销需关注指定频道", missing=reimb_missing)
        elig, info = await is_user_reimburse_eligible_for_review(user_id, teacher.get("price"))
        if not elig:
            return SubmitResult(ok=False, error_code="reimburse_ineligible",
                                message="不符合报销条件，可取消报销后再提交")

    # 5. 字段校验
    errs = validate_payload(payload)
    if errs:
        return SubmitResult(ok=False, error_code="invalid_fields", fields=errs)

    # 6. 落库
    scores = payload["scores"]
    overall = compute_overall(scores)
    review_data = {
        "teacher_id": teacher_id,
        "user_id": int(user_id),
        "booking_screenshot_file_id": payload["booking_screenshot_file_id"],
        "gesture_photo_file_id": payload.get("gesture_photo_file_id"),
        "rating": derive_rating(overall),  # 2026-06-30：按综合分自动判定，不再用 payload.rating
        "overall_score": overall,
        "summary": (payload.get("summary") or "").strip() or None,
        "request_reimbursement": req_reimburse,
        "anonymous": 0,  # 2026-06：取消匿名提交，一律实名落库（忽略 payload.anonymous）
    }
    for k in _DIM_KEYS:
        review_data[_DIM_COLUMN[k]] = float(scores[k])

    review_id = await create_teacher_review(review_data)
    if review_id is None:
        return SubmitResult(ok=False, error_code="create_failed", message="提交失败，请稍后重试")

    # 7. 回流通知超管（fire-and-forget）
    try:
        from bot.utils.rreview_notify import notify_super_admins_new_review
        asyncio.create_task(notify_super_admins_new_review(bot, review_id))
    except Exception as e:
        logger.warning("notify_super_admins schedule 失败 review=%s: %s", review_id, e)

    return SubmitResult(ok=True, review_id=review_id)

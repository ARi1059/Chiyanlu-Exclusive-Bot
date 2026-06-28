"""老师资料审核共享 service（bot FSM + MiniApp web 同源）。

teacher_edit_requests 的通过/驳回核心：DB 落库(approve_edit_request /
reject_edit_request) + **通知老师**。两端复用同一套通知文案，杜绝漂移
（对齐 review_moderation / reimbursement_moderation 架构）。

通过/驳回的 DB 语义见 database.approve_edit_request / reject_edit_request：
    - 文字字段：通过=保持已生效新值；驳回=回滚旧值。
    - photo_file_id：通过=切换新图；驳回=保持旧图（审核期从未切换）。
"""
from __future__ import annotations

import logging

from bot.database import (
    approve_edit_request,
    get_edit_request,
    reject_edit_request,
)
from bot.keyboards.teacher_self_kb import FIELD_LABELS

logger = logging.getLogger(__name__)


async def _notify_teacher_approved(
    bot,
    teacher_id: int,
    field_name: str,
    new_value: str | None,
) -> None:
    """通过时给老师私聊推送通知（UX-5.2）。photo_file_id 不展示 file_id 串。
    失败仅 logger.warning，不影响调用方主流程。"""
    label = FIELD_LABELS.get(field_name, field_name)
    if field_name == "photo_file_id":
        value_line = "新图片已生效。"
    else:
        value_repr = new_value if new_value else "（空）"
        value_line = f"当前生效值：{value_repr}"
    text = (
        f"✅ 你的资料修改已通过审核\n"
        f"━━━━━━━━━━━━━━━\n"
        f"字段：{label}\n"
        f"{value_line}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"感谢配合！"
    )
    try:
        await bot.send_message(chat_id=teacher_id, text=text)
    except Exception as e:
        logger.warning("通知老师 %s 通过失败: %s", teacher_id, e)


async def _notify_teacher_rejected(
    bot,
    teacher_id: int,
    field_name: str,
    new_value: str | None,
    reason: str | None,
) -> None:
    """驳回时给老师私聊推送通知（v2 §2.3.5）。失败仅 logger.warning。"""
    label = FIELD_LABELS.get(field_name, field_name)
    if field_name == "photo_file_id":
        rollback_note = "线上展示仍是旧图（图片字段在审核期间从未切换）。"
        value_repr = "你提交的新图"
    else:
        rollback_note = "资料已恢复为原值。"
        value_repr = new_value if new_value else "（空）"
    reason_line = f"原因: {reason}" if reason else "原因: （未填写）"
    text = (
        f"❌ 你的资料修改已被驳回\n"
        f"━━━━━━━━━━━━━━━\n"
        f"字段: {label}\n"
        f"你提交的值: {value_repr}\n"
        f"{reason_line}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{rollback_note}\n"
        f"如有疑问请联系管理员。"
    )
    try:
        await bot.send_message(chat_id=teacher_id, text=text)
    except Exception as e:
        logger.warning("通知老师 %s 驳回失败: %s", teacher_id, e)


async def approve_teacher_edit(bot, request_id: int, reviewer_id: int) -> dict:
    """通过一条老师资料修改（web 整流程入口）。

    Returns {ok, error?, teacher_id?, field?}：
        非 pending / 不存在 → {ok:False, error:"gone"}
        成功 → {ok:True, teacher_id, field}（已通知老师）
    """
    req = await get_edit_request(request_id)
    if not req or req.get("status") != "pending":
        return {"ok": False, "error": "gone"}
    ok = await approve_edit_request(request_id, reviewer_id)
    if not ok:
        return {"ok": False, "error": "gone"}
    teacher_id = int(req["teacher_id"])
    field = str(req["field_name"])
    await _notify_teacher_approved(bot, teacher_id, field, req.get("new_value"))
    return {"ok": True, "teacher_id": teacher_id, "field": field}


async def reject_teacher_edit(
    bot, request_id: int, reviewer_id: int, reason: str | None = None,
) -> dict:
    """驳回一条老师资料修改（web 整流程入口）。对称于 approve_teacher_edit。"""
    req = await get_edit_request(request_id)
    if not req or req.get("status") != "pending":
        return {"ok": False, "error": "gone"}
    ok = await reject_edit_request(request_id, reviewer_id, reason)
    if not ok:
        return {"ok": False, "error": "gone"}
    teacher_id = int(req["teacher_id"])
    field = str(req["field_name"])
    await _notify_teacher_rejected(bot, teacher_id, field, req.get("new_value"), reason)
    return {"ok": True, "teacher_id": teacher_id, "field": field}

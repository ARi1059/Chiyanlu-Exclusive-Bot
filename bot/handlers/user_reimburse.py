"""用户「我的报销」入口

callback:
    user:reimburse              → 报销总览页（最近 5 条 + 本月统计）
    user:reimburse:list         → 报销明细 page 0
    user:reimburse:list:<page>  → 报销明细 page N（每页 10 条）
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F

from bot.database import (
    count_approved_reimbursements_in_week,
    count_user_reimbursements,
    current_month_key,
    current_week_key,
    get_config,
    get_teacher,
    list_user_reimbursements_paged,
    sum_approved_reimbursements_in_month,
)
from bot.keyboards.user_kb import (
    user_reimburse_menu_kb,
    user_reimburse_pagination_kb,
)

logger = logging.getLogger(__name__)

router = Router(name="user_reimburse")


REIMBURSE_PAGE_SIZE = 10


_STATUS_LABEL = {
    "pending":   "⏳ 待审核",
    "approved":  "✅ 已通过",
    "rejected":  "❌ 已驳回",
    "cancelled": "🚫 已取消",
    "queued":    "📋 已录入名单（待启用）",
}


@router.callback_query(F.data == "user:reimburse")
async def cb_user_reimburse(callback: types.CallbackQuery):
    """[🧾 我的报销] 总览页"""
    user_id = callback.from_user.id
    week_key = current_week_key()
    month_key = current_month_key()

    total = await count_user_reimbursements(user_id)
    week_used = await count_approved_reimbursements_in_week(user_id, week_key)
    month_total = await sum_approved_reimbursements_in_month(month_key)
    pool_raw = await get_config("reimbursement_monthly_pool")
    try:
        pool = int(pool_raw or 0)
    except (TypeError, ValueError):
        pool = 0

    # 最近 5 条
    recent = await list_user_reimbursements_paged(user_id, limit=5, offset=0)
    lines = [
        "🧾 我的报销",
        "━━━━━━━━━━━━━━━",
        f"本周已通过：{week_used}/1 笔",
        f"本月已通过总额：{month_total} 元"
        + (f"（池 {pool} 元）" if pool > 0 else "（池不限）"),
        f"累计申请：{total} 笔",
        "━━━━━━━━━━━━━━━",
    ]
    if recent:
        lines.append("")
        lines.append("最近 5 笔：")
        for r in recent:
            status_lab = _STATUS_LABEL.get(r["status"], r["status"])
            teacher_name = "?"
            if r.get("teacher_id"):
                t = await get_teacher(r["teacher_id"])
                teacher_name = t["display_name"] if t else f"#{r['teacher_id']}"
            line = f"  · #{r['id']} {teacher_name} {r['amount']} 元 {status_lab}"
            if r["status"] == "rejected" and r.get("reject_reason"):
                line += f"\n    驳回：{r['reject_reason'][:30]}"
            lines.append(line)
    else:
        lines.append("")
        lines.append("（暂无报销申请）")
    lines.append("")
    lines.append("💡 提交评价时若满足积分门槛 + 老师价位 > 0，可勾选申请报销。")

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=user_reimburse_menu_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=user_reimburse_menu_kb())
    await callback.answer()


def _parse_list_page(data: str) -> Optional[int]:
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "user" or parts[1] != "reimburse" or parts[2] != "list":
        return None
    if len(parts) == 3:
        return 0
    try:
        return max(0, int(parts[3]))
    except ValueError:
        return None


@router.callback_query(F.data.startswith("user:reimburse:list"))
async def cb_user_reimburse_list(callback: types.CallbackQuery):
    """[📋 报销明细] 分页"""
    page = _parse_list_page(callback.data or "")
    if page is None:
        await callback.answer("参数错误", show_alert=True)
        return
    user_id = callback.from_user.id
    total = await count_user_reimbursements(user_id)
    total_pages = max(1, (total + REIMBURSE_PAGE_SIZE - 1) // REIMBURSE_PAGE_SIZE)
    if page >= total_pages:
        page = total_pages - 1
    offset = page * REIMBURSE_PAGE_SIZE
    rows = await list_user_reimbursements_paged(user_id, REIMBURSE_PAGE_SIZE, offset)

    if not rows:
        text = "📋 报销明细\n\n（暂无记录）"
    else:
        lines = [f"📋 报销明细（共 {total} 笔，第 {page + 1}/{total_pages} 页）", "━━━━━━━━━━━━━━━"]
        for idx, r in enumerate(rows, start=offset + 1):
            status_lab = _STATUS_LABEL.get(r["status"], r["status"])
            teacher_name = "?"
            if r.get("teacher_id"):
                t = await get_teacher(r["teacher_id"])
                teacher_name = t["display_name"] if t else f"#{r['teacher_id']}"
            lines.append(
                f"{idx}. #{r['id']} {teacher_name}  {r['amount']} 元  {status_lab}"
            )
            lines.append(f"   {r.get('created_at', '')}")
            if r["status"] == "rejected" and r.get("reject_reason"):
                lines.append(f"   驳回原因：{r['reject_reason']}")
        text = "\n".join(lines)

    try:
        await callback.message.edit_text(
            text, reply_markup=user_reimburse_pagination_kb(page, total_pages),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=user_reimburse_pagination_kb(page, total_pages),
        )
    await callback.answer()

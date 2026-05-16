"""用户「我的积分」渲染（Phase P.2）

纯函数渲染：
- format_points_summary_page: 积分总览（余额 / 累计获得 / 累计消耗）
- format_points_detail_block: 明细列表每条
- fetch_teacher_names_for_txs: 反查 review_approved 类型的老师名

按 [POINTS-FEATURE-DRAFT.md §2.2] 格式。
"""
from __future__ import annotations

from typing import Optional


# 明细分页每页条数（spec §2.2）
POINTS_DETAIL_PAGE_SIZE: int = 20


def format_points_summary_page(summary: dict) -> str:
    """积分总览页正文（spec §2.2 格式）

    summary: {total, earned, spent, tx_count}
    0 数据时仍渲染（all zeros + 友好提示）。
    """
    total = int(summary.get("total", 0) or 0)
    earned = int(summary.get("earned", 0) or 0)
    spent = int(summary.get("spent", 0) or 0)
    tx_count = int(summary.get("tx_count", 0) or 0)

    lines = [
        "💰 我的积分",
        "",
        f"当前余额：{total} 分",
        "",
        f"📈 累计获得：{earned} 分（{tx_count} 次报告通过）",
        f"📉 累计消耗：{spent} 分",
    ]
    if tx_count == 0:
        lines.append("")
        lines.append("ℹ️ 暂无积分记录。提交并通过审核的报告会自动加分。")
    return "\n".join(lines)


def _format_time(created_at: Optional[str]) -> str:
    """时间截取前 16 字符（YYYY-MM-DD HH:MM）"""
    if not created_at:
        return "?"
    s = str(created_at).strip()
    return s[:16] if len(s) >= 16 else s


def _format_delta(delta: int) -> str:
    """delta 显示：+5 / +0 / -3"""
    if delta is None:
        return "?"
    d = int(delta)
    if d > 0:
        return f"+{d}"
    return str(d)  # 负数自带 "-"，0 显示 "0"


def format_points_detail_line(
    idx: int,
    tx: dict,
    teachers_map: dict[int, str],
    review_teacher_map: dict[int, int],
) -> str:
    """渲染单行明细（spec §2.2）

    Args:
        idx: 1-based 序号
        tx: point_transactions 一行
        teachers_map: {teacher_id: display_name}
        review_teacher_map: {review_id: teacher_id} 用于 reason=review_approved 反查

    格式：
        1. +5  审核通过：丁小夏（包夜）  2026-05-16 14:23
    """
    delta_str = _format_delta(tx.get("delta") or 0)
    reason = tx.get("reason") or "?"
    note = tx.get("note") or ""
    time_str = _format_time(tx.get("created_at"))

    if reason == "review_approved":
        rid = tx.get("related_id")
        teacher_name = ""
        if rid is not None:
            tid = review_teacher_map.get(int(rid))
            if tid is not None:
                teacher_name = teachers_map.get(int(tid), "")
        title = "审核通过"
        if teacher_name:
            title = f"审核通过：{teacher_name}"
        if note:
            title = f"{title}（{note}）"
        body = title
    elif reason == "admin_grant":
        body = f"管理员加分：{note}" if note else "管理员加分"
    elif reason == "admin_revoke":
        body = f"管理员扣分：{note}" if note else "管理员扣分"
    elif reason == "lottery_entry":
        body = f"抽奖参与扣分：{note}" if note else "抽奖参与扣分"
    elif reason == "lottery_refund":
        body = f"抽奖取消退款：{note}" if note else "抽奖取消退款"
    else:
        body = f"{reason}：{note}" if note else reason

    return f"{idx}. {delta_str:<4}{body}  {time_str}"


def format_points_detail_block(
    txs: list[dict],
    teachers_map: dict[int, str],
    review_teacher_map: dict[int, int],
    *,
    start_idx: int = 1,
) -> str:
    """渲染明细块（多行）

    start_idx：起始序号（分页用，page=2 时 start_idx=21）。
    txs 为空时返回空字符串。
    """
    if not txs:
        return ""
    lines: list[str] = []
    for i, tx in enumerate(txs):
        lines.append(format_points_detail_line(
            start_idx + i, tx, teachers_map, review_teacher_map,
        ))
    return "\n".join(lines)


async def fetch_teacher_names_for_txs(
    txs: list[dict],
) -> tuple[dict[int, str], dict[int, int]]:
    """批量反查 review_approved 类型 tx 的老师名

    Returns: (teachers_map, review_teacher_map)
        teachers_map: {teacher_id: display_name}
        review_teacher_map: {review_id: teacher_id}
    """
    review_ids = [
        int(tx["related_id"])
        for tx in txs
        if tx.get("reason") == "review_approved" and tx.get("related_id") is not None
    ]
    if not review_ids:
        return {}, {}

    from bot.database import get_teacher_review, get_teachers_by_ids
    review_teacher_map: dict[int, int] = {}
    for rid in set(review_ids):
        rev = await get_teacher_review(rid)
        if rev and rev.get("teacher_id") is not None:
            review_teacher_map[rid] = int(rev["teacher_id"])
    if not review_teacher_map:
        return {}, {}
    teacher_ids = list(set(review_teacher_map.values()))
    teachers = await get_teachers_by_ids(teacher_ids)
    teachers_map = {tid: t.get("display_name", f"#{tid}") for tid, t in teachers.items()}
    return teachers_map, review_teacher_map

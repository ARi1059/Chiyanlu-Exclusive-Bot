"""私聊详情页评价区块渲染（Phase 9.6）

按 spec §5 在详情页底部追加：
- 统计块（review_count / 三级 % / 6 维 + 综合 avg）
- 最近 N 条评价（半匿名签名 + 评级 + 综合 + 总结 + 日期）

格式（详情页版，与频道档案帖 §6.1 格式不同）：
    📊 35 条车评，综合评分 9.21
    好评 100% | 人照 9.08 | 服务 9.07
    中评 0.0% | 颜值 9.27 | 态度 9.63
    差评 0.0% | 身材 8.94 | 环境 9.15

    最近评价：
    ────────────────────
    小* · 👍 好评 · 🎯 8.6
    📝 非常推荐，下次还会再约
    — 2026-05-16
    ...
    ────────────────────

纯函数 + DB 异步取数。
"""
from __future__ import annotations

from typing import Optional

from bot.database import (
    REVIEW_RATINGS,
    get_users_first_names,
)


# 详情页"最近评价"显示条数（spec §5）
RECENT_REVIEWS_COUNT: int = 3
# 分页"全部评价"每页条数（spec §5："分页 10 条/页"）
REVIEWS_PAGE_SIZE: int = 10


def anonymize_signer(first_name: Optional[str]) -> str:
    """半匿名签名（spec §5）

    规则：
        - first_name 为非空字符串 → 取首字 + "*"（如 "小红" → "小*"，"Alice" → "A*"）
        - None / 空字符串 → fallback "匿*"
    """
    if not first_name:
        return "匿*"
    name = str(first_name).strip()
    if not name:
        return "匿*"
    return f"{name[0]}*"


def format_review_stats_block(stats: Optional[dict]) -> str:
    """详情页统计块（4 行，spec §5 格式）

    stats 为 None 或 review_count == 0 → 返回 ""（详情页省略整段）。
    """
    if not stats:
        return ""
    rc = stats.get("review_count", 0) or 0
    if rc == 0:
        return ""

    pos = stats.get("positive_count", 0) or 0
    neu = stats.get("neutral_count", 0) or 0
    neg = stats.get("negative_count", 0) or 0
    pos_pct = pos / rc * 100
    neu_pct = neu / rc * 100
    neg_pct = neg / rc * 100

    def _fmt_avg(key: str) -> str:
        v = stats.get(key, 0) or 0
        return f"{float(v):.2f}"

    lines = [
        f"📊 {rc} 条车评，综合评分 {_fmt_avg('avg_overall')}",
        f"好评 {pos_pct:>5.1f}% | 人照 {_fmt_avg('avg_humanphoto')} | 服务 {_fmt_avg('avg_service')}",
        f"中评 {neu_pct:>5.1f}% | 颜值 {_fmt_avg('avg_appearance')} | 态度 {_fmt_avg('avg_attitude')}",
        f"差评 {neg_pct:>5.1f}% | 身材 {_fmt_avg('avg_body')} | 环境 {_fmt_avg('avg_environment')}",
    ]
    return "\n".join(lines)


_RATING_META: dict[str, dict] = {r["key"]: r for r in REVIEW_RATINGS}


def _format_score_compact(value) -> str:
    """评分紧凑显示：整数 '9'，否则 '8.6'"""
    if value is None:
        return "?"
    f = float(value)
    return str(int(f)) if f == int(f) else f"{f:.1f}"


def _format_date(created_at: Optional[str]) -> str:
    """created_at 仅取日期部分（'2026-05-16 12:34:56' → '2026-05-16'）"""
    if not created_at:
        return "?"
    s = str(created_at).strip()
    if len(s) >= 10:
        return s[:10]
    return s


def format_recent_reviews_block(
    reviews: list[dict],
    signer_names: dict[int, Optional[str]],
) -> str:
    """渲染最近 N 条评价（spec §5 格式）

    每条:
        {签名} · {emoji} {label} · 🎯 {overall}
        📝 {summary}           （summary=None 时显示 "（无总结）"）
        — {YYYY-MM-DD}

    多条之间空行分隔，整段用 "─" 分割线包裹。
    """
    if not reviews:
        return ""
    sep = "─" * 20
    parts: list[str] = ["最近评价：", sep]
    for i, rev in enumerate(reviews):
        sig = anonymize_signer(signer_names.get(rev["user_id"]))
        rating_meta = _RATING_META.get(
            rev.get("rating"),
            {"emoji": "❓", "label": rev.get("rating", "?")},
        )
        overall = _format_score_compact(rev.get("overall_score"))
        summary = rev.get("summary") or "（无总结）"
        date = _format_date(rev.get("created_at"))
        parts.append(
            f"{sig} · {rating_meta['emoji']} {rating_meta['label']} · 🎯 {overall}"
        )
        parts.append(f"📝 {summary}")
        parts.append(f"— {date}")
        if i + 1 < len(reviews):
            parts.append("")
    parts.append(sep)
    return "\n".join(parts)


async def fetch_signer_names(reviews: list[dict]) -> dict[int, Optional[str]]:
    """批量从 users 表取评价者 first_name"""
    uids = list({int(r["user_id"]) for r in reviews if r.get("user_id") is not None})
    if not uids:
        return {}
    return await get_users_first_names(uids)

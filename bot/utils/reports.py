"""日报 / 周报文本构建器（Phase 6.3）

调用方：bot/scheduler/tasks.py 的 send_daily_report / send_weekly_report
       以及 bot/handlers/report_settings.py 的"立即测试发送"

所有函数:
- 内部不抛异常（任何错误都退化为 "暂无数据"）
- 文本长度兜底截断到 ≤ 4000 字符,避免超过 Telegram 4096 上限
"""

import logging
from typing import Iterable

from bot.database import get_report_stats

logger = logging.getLogger(__name__)


_TG_TEXT_MAX = 4000  # 留点余量


def _fmt_top_teachers(rows: Iterable[dict] | None, limit: int = 10) -> str:
    """🔥 top_teachers 渲染：N. {display_name}｜{score}"""
    if not rows:
        return "暂无数据"
    lines = []
    for i, r in enumerate(list(rows)[:limit], 1):
        name = (r.get("display_name") or "未知").strip()
        score = int(r.get("score") or 0)
        lines.append(f"{i}. {name}｜{score}")
    return "\n".join(lines) if lines else "暂无数据"


def _fmt_top_keywords(rows: Iterable[dict] | None, limit: int = 10) -> str:
    """🔎 top_search_keywords 渲染：顿号分隔"""
    if not rows:
        return "暂无数据"
    names: list[str] = []
    for r in list(rows)[:limit]:
        if isinstance(r, dict):
            kw = r.get("keyword") or r.get("tag") or ""
        else:
            kw = str(r)
        kw = str(kw or "").strip()
        if kw:
            names.append(kw)
    return "、".join(names) if names else "暂无数据"


def _fmt_top_tags(rows: Iterable[dict] | None, limit: int = 10) -> str:
    """🏷 top_user_tags 渲染：顿号分隔 tag 字段"""
    if not rows:
        return "暂无数据"
    names: list[str] = []
    for r in list(rows)[:limit]:
        if isinstance(r, dict):
            tag = r.get("tag") or ""
        else:
            tag = str(r)
        tag = str(tag or "").strip()
        if tag:
            names.append(tag)
    return "、".join(names) if names else "暂无数据"


def _fmt_top_sources(rows: Iterable[dict] | None, limit: int = 10) -> str:
    """📈 top_sources 渲染：N. {source_type}:{source_id}｜{user_count}"""
    if not rows:
        return "暂无数据"
    lines = []
    for i, r in enumerate(list(rows)[:limit], 1):
        stype = str(r.get("source_type") or "").strip() or "unknown"
        sid = str(r.get("source_id") or "").strip() or "-"
        cnt = int(r.get("user_count") or 0)
        lines.append(f"{i}. {stype}:{sid}｜{cnt}")
    return "\n".join(lines) if lines else "暂无数据"


def _truncate(text: str) -> str:
    """Telegram 4096 字符上限的兜底截断"""
    if len(text) > _TG_TEXT_MAX:
        return text[:_TG_TEXT_MAX - 10] + "\n…（已截断）"
    return text


async def build_daily_report_text(date_str: str) -> str:
    """构建日报文本（Phase 6.3 §四）"""
    try:
        stats = await get_report_stats(date_str, date_str)
    except Exception as e:
        logger.warning("get_report_stats 失败 (daily): %s", e)
        stats = {}

    text = (
        "📊 痴颜录日报\n"
        f"日期：{date_str}\n\n"
        "👥 用户\n"
        f"新增用户：{stats.get('new_users', 0)}\n"
        f"活跃用户：{stats.get('active_users', 0)}\n\n"
        "🔍 行为\n"
        f"搜索次数：{stats.get('search_count', 0)}\n"
        f"老师详情浏览：{stats.get('teacher_view_count', 0)}\n"
        f"新增收藏：{stats.get('favorite_add_count', 0)}\n\n"
        "📅 开课\n"
        f"今日签到老师：{stats.get('today_checkin_count', 0)}\n\n"
        "🔥 热门老师\n"
        f"{_fmt_top_teachers(stats.get('top_teachers'))}\n\n"
        "🔎 热门搜索\n"
        f"{_fmt_top_keywords(stats.get('top_search_keywords'))}\n\n"
        "🏷 热门画像\n"
        f"{_fmt_top_tags(stats.get('top_user_tags'))}\n\n"
        "📈 渠道 TOP\n"
        f"{_fmt_top_sources(stats.get('top_sources'))}"
    )
    return _truncate(text)


async def build_weekly_report_text(start_date: str, end_date: str) -> str:
    """构建周报文本（Phase 6.3 §四）"""
    try:
        stats = await get_report_stats(start_date, end_date)
    except Exception as e:
        logger.warning("get_report_stats 失败 (weekly): %s", e)
        stats = {}

    text = (
        "📊 痴颜录周报\n"
        f"周期：{start_date} ~ {end_date}\n\n"
        "👥 用户增长\n"
        f"新增用户：{stats.get('new_users', 0)}\n"
        f"活跃用户：{stats.get('active_users', 0)}\n\n"
        "🔍 用户行为\n"
        f"搜索次数：{stats.get('search_count', 0)}\n"
        f"老师详情浏览：{stats.get('teacher_view_count', 0)}\n"
        f"新增收藏：{stats.get('favorite_add_count', 0)}\n\n"
        "📅 开课\n"
        f"签到记录：{stats.get('today_checkin_count', 0)}\n\n"
        "🔥 老师排行\n"
        f"{_fmt_top_teachers(stats.get('top_teachers'))}\n\n"
        "🔎 热门搜索\n"
        f"{_fmt_top_keywords(stats.get('top_search_keywords'))}\n\n"
        "🏷 用户画像趋势\n"
        f"{_fmt_top_tags(stats.get('top_user_tags'))}\n\n"
        "📈 渠道排行\n"
        f"{_fmt_top_sources(stats.get('top_sources'))}"
    )
    return _truncate(text)

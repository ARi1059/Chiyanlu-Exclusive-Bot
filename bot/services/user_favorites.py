"""用户「⭐ 我的收藏」增强版聚合查询 + 渲染。

提供：
    - FavoriteTeacherItem：dataclass，单条收藏摘要
    - FavoriteTeachersStats：dataclass，列表 + 计数 + 模式 + 时间戳
    - get_user_favorites(user_id, mode, limit)：JOIN teachers / LEFT JOIN checkins
      的只读聚合，复用现有 favorites 表（无新表、无迁移）
    - render_user_favorites(stats)：纯渲染函数，便于测试

设计原则：
    - 全程只读：不写表，不修改收藏 / 取消收藏 / 老师详情 / 签到 / 通知流程
    - 复用现有 callback：[查看详情] 走 teacher:view:<id>
      取消收藏在 keyboard 层使用 user:favorites:rm:<id>（handler 复用既有
      remove_favorite DB 函数；详见 handlers/user_panel.py 注释）
    - 时间格式化复用 recent_views.format_viewed_at_relative，避免重复实现
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import aiosqlite
from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import get_db

# 复用 recent_views 中已经写好的时间格式化（无修改）
from bot.services.recent_views import format_viewed_at_relative

logger = logging.getLogger(__name__)


MODE_ALL = "all"
MODE_TODAY = "today"
_VALID_MODES: frozenset[str] = frozenset({MODE_ALL, MODE_TODAY})


@dataclass
class FavoriteTeacherItem:
    """单条收藏摘要。"""

    teacher_id: int
    display_name: str
    favorited_at: Optional[str]
    is_checked_in_today: Optional[bool] = None


@dataclass
class FavoriteTeachersStats:
    """收藏列表聚合数据。

    Optional 计数语义：
        - None → 渲染显示 "N/A"
        - 已知值 → 正常显示
    """

    total_count: Optional[int] = None
    checked_in_today_count: Optional[int] = None
    not_checked_in_today_count: Optional[int] = None
    items: list[FavoriteTeacherItem] = field(default_factory=list)
    mode: str = MODE_ALL
    generated_at: Optional[datetime] = None


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


def _today_local_str() -> str:
    return _now_local().strftime("%Y-%m-%d")


def _normalize_mode(mode: str) -> str:
    if mode in _VALID_MODES:
        return mode
    return MODE_ALL


async def get_user_favorites(
    user_id: int,
    mode: str = MODE_ALL,
    limit: int = 10,
) -> FavoriteTeachersStats:
    """读取用户收藏列表 + 当日签到聚合。

    流程：
      1. 用一条 SQL 拿所有收藏（含 is_checked_in_today 计算）
      2. 计算总数 / 今日可约 / 今日未签 三个计数
      3. mode='today' 时只保留 is_checked_in_today=True 的条目
      4. 截断到 limit；保留计数为原始全量值

    停用 / 删除老师通过 INNER JOIN + is_active=1 自然过滤。
    """
    mode = _normalize_mode(mode)
    stats = FavoriteTeachersStats(mode=mode, generated_at=_now_local())
    today = _today_local_str()

    db = await get_db()
    try:
        try:
            cur = await db.execute(
                """
                SELECT
                    f.teacher_id   AS teacher_id,
                    t.display_name AS display_name,
                    f.created_at   AS favorited_at,
                    CASE WHEN EXISTS (
                        SELECT 1 FROM checkins c
                        WHERE c.teacher_id = f.teacher_id
                          AND c.checkin_date = ?
                    ) THEN 1 ELSE 0 END AS is_checked_in_today
                FROM favorites f
                INNER JOIN teachers t ON f.teacher_id = t.user_id
                WHERE f.user_id = ? AND t.is_active = 1
                ORDER BY f.created_at DESC
                """,
                (today, int(user_id)),
            )
            rows = await cur.fetchall()
        except Exception as e:
            logger.warning("get_user_favorites 查询失败 user=%s: %s",
                           user_id, e)
            # 失败时计数置 None（渲染 N/A），items 为空
            return stats

        all_items: list[FavoriteTeacherItem] = []
        for row in rows:
            try:
                all_items.append(FavoriteTeacherItem(
                    teacher_id=int(row["teacher_id"]),
                    display_name=row["display_name"] or "(未知老师)",
                    favorited_at=row["favorited_at"],
                    is_checked_in_today=bool(row["is_checked_in_today"]),
                ))
            except Exception as e:
                logger.warning("favorites row 解析失败: %s", e)

        stats.total_count = len(all_items)
        stats.checked_in_today_count = sum(
            1 for it in all_items if it.is_checked_in_today
        )
        stats.not_checked_in_today_count = (
            stats.total_count - stats.checked_in_today_count
        )

        if mode == MODE_TODAY:
            filtered = [it for it in all_items if it.is_checked_in_today]
        else:
            filtered = all_items

        # 防御性 limit
        try:
            n = int(limit)
        except (TypeError, ValueError):
            n = 10
        if n < 0:
            n = 0
        stats.items = filtered[:n]
    finally:
        await db.close()

    return stats


def _fmt(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def _fmt_status(is_checked_in: Optional[bool]) -> str:
    if is_checked_in is None:
        return "N/A"
    return "今日可约" if is_checked_in else "今日未签到"


# 空列表占位文案（spec UI）
EMPTY_TEXT = (
    "⭐ 我的收藏\n\n"
    "你还没有收藏老师。\n"
    "可以先从热门推荐、条件搜索或最近看过中选择喜欢的老师收藏。"
)


def render_user_favorites(stats: FavoriteTeachersStats) -> str:
    """把 FavoriteTeachersStats 渲染为面板文本。

    纯函数：仅依赖入参。
    - total_count == 0  且 None → 显示 EMPTY_TEXT
    - mode='today' 且无可约老师 → 显示提示而非空占位
    """
    # 完全无收藏：直接占位
    if stats.total_count is None or stats.total_count == 0:
        return EMPTY_TEXT

    lines: list[str] = ["⭐ 我的收藏", ""]
    lines.append(f"今日可约：{_fmt(stats.checked_in_today_count)} 位")
    lines.append(f"今日未签到：{_fmt(stats.not_checked_in_today_count)} 位")
    lines.append(f"总收藏：{_fmt(stats.total_count)} 位")
    lines.append("")

    if stats.mode == MODE_TODAY:
        lines.append("视图：只看今日可约")
        lines.append("")

    if not stats.items:
        # 有收藏，但当前 mode 下无可显示条目（例如 today 模式无人签到）
        if stats.mode == MODE_TODAY:
            lines.append("你的收藏老师今日均未签到。")
            lines.append("可点击下方 [查看全部] 看完整收藏列表。")
        else:
            lines.append("当前列表为空。")
    else:
        for i, item in enumerate(stats.items, start=1):
            if i > 1:
                lines.append("")
            lines.append(f"{i}. {item.display_name or 'N/A'}")
            lines.append(f"状态：{_fmt_status(item.is_checked_in_today)}")
            lines.append(
                f"收藏时间：{format_viewed_at_relative(item.favorited_at, now_local=stats.generated_at)}"
            )

    if stats.generated_at is not None:
        try:
            ts_str = stats.generated_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append("")
            lines.append(f"更新时间：{ts_str}")
        except Exception:
            pass

    return "\n".join(lines)

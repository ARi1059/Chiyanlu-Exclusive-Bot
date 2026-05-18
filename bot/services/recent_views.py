"""用户「👀 最近看过」增强版聚合查询 + 渲染。

提供：
    - RecentTeacherViewItem：dataclass，单条最近浏览摘要
    - get_recent_teacher_views(user_id, limit)：JOIN teachers / favorites / checkins
      的只读聚合，复用现有 user_teacher_views 表（无新表、无迁移）
    - render_recent_views(items, ...)：纯渲染函数，便于测试
    - format_viewed_at_relative(...)：相对时间格式化（今天/昨天/YYYY-MM-DD HH:mm）

设计原则：
    - 全程只读：不写表，不修改详情页 / 收藏 / 签到 / 通知逻辑
    - 复用现有 callback：[查看详情] 走 teacher:view:<id>；[收藏切换] 走
      teacher:toggle_fav:<id>；返回主菜单走 user:main
    - 时间口径：viewed_at 是 SQLite CURRENT_TIMESTAMP（UTC, 'YYYY-MM-DD HH:MM:SS'），
      渲染时按 config.timezone 转本地后再计算 今天/昨天
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Optional

import aiosqlite
from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import get_db

logger = logging.getLogger(__name__)


@dataclass
class RecentTeacherViewItem:
    """单条最近浏览摘要。"""

    teacher_id: int
    display_name: str
    viewed_at: Optional[str]          # 原始 UTC 字符串
    is_favorited: Optional[bool] = None
    is_checked_in_today: Optional[bool] = None


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


def _today_local_str() -> str:
    return _now_local().strftime("%Y-%m-%d")


def _parse_utc_string(s: str) -> Optional[datetime]:
    """把 SQLite CURRENT_TIMESTAMP 字符串解析为 UTC-aware datetime。

    支持几种常见形式：'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DDTHH:MM:SS' /
    带微秒。失败返回 None。
    """
    if not s:
        return None
    candidate = s.strip()
    if not candidate:
        return None
    # 容错统一：把 'T' 换 ' '，去末尾 'Z' / '+00:00'
    normalized = candidate.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1]
    # 优先尝试 isoformat-friendly 解析
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            dt = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def format_viewed_at_relative(
    viewed_at: Optional[str],
    *,
    now_local: Optional[datetime] = None,
) -> str:
    """把 UTC 时间字符串渲染为相对时间。

    规则：
        - None / 空 / 解析失败 → 'N/A'
        - 今天 → '今天 HH:mm'
        - 昨天 → '昨天 HH:mm'
        - 其它 → 'YYYY-MM-DD HH:mm'

    `now_local` 参数允许测试注入固定时间，避免依赖系统时钟。
    """
    parsed = _parse_utc_string(viewed_at) if viewed_at else None
    if parsed is None:
        return "N/A"

    tz = pytz_timezone(config.timezone)
    local_dt = parsed.astimezone(tz)
    ref_now = now_local if now_local is not None else _now_local()
    # 容错：ref_now naive → 假定为 local tz
    if ref_now.tzinfo is None:
        ref_now = tz.localize(ref_now)

    today = ref_now.date()
    delta_days = (today - local_dt.date()).days
    hm = local_dt.strftime("%H:%M")
    if delta_days == 0:
        return f"今天 {hm}"
    if delta_days == 1:
        return f"昨天 {hm}"
    return local_dt.strftime("%Y-%m-%d %H:%M")


async def get_recent_teacher_views(
    user_id: int, limit: int = 10,
) -> list[RecentTeacherViewItem]:
    """读取用户最近浏览的启用老师列表。

    单条 SQL：
      - INNER JOIN teachers WHERE is_active=1（停用 / 删除老师过滤掉，
        与现有 list_recent_teacher_views 行为一致）
      - LEFT JOIN favorites 判断收藏状态
      - 子查询计算今日是否签到（DATE 与本地时区按现有 admin / dashboard 口径一致）
      - 按 viewed_at DESC，PRIMARY KEY (user_id, teacher_id) 保证去重
    """
    today = _today_local_str()
    items: list[RecentTeacherViewItem] = []

    db = await get_db()
    try:
        try:
            cur = await db.execute(
                """
                SELECT
                    v.teacher_id   AS teacher_id,
                    t.display_name AS display_name,
                    v.viewed_at    AS viewed_at,
                    CASE WHEN f.user_id IS NULL THEN 0 ELSE 1 END AS is_favorited,
                    CASE WHEN EXISTS (
                        SELECT 1 FROM checkins c
                        WHERE c.teacher_id = v.teacher_id
                          AND c.checkin_date = ?
                    ) THEN 1 ELSE 0 END AS is_checked_in_today
                FROM user_teacher_views v
                INNER JOIN teachers t ON v.teacher_id = t.user_id
                LEFT JOIN favorites f
                    ON f.user_id = v.user_id AND f.teacher_id = v.teacher_id
                WHERE v.user_id = ? AND t.is_active = 1
                ORDER BY v.viewed_at DESC
                LIMIT ?
                """,
                (today, int(user_id), int(limit)),
            )
            rows = await cur.fetchall()
        except Exception as e:
            logger.warning("get_recent_teacher_views 查询失败 user=%s: %s",
                           user_id, e)
            return []
        for row in rows:
            try:
                items.append(RecentTeacherViewItem(
                    teacher_id=int(row["teacher_id"]),
                    display_name=row["display_name"] or "(未知老师)",
                    viewed_at=row["viewed_at"],
                    is_favorited=bool(row["is_favorited"]),
                    is_checked_in_today=bool(row["is_checked_in_today"]),
                ))
            except Exception as e:
                logger.warning("recent_views row 解析失败: %s", e)
    finally:
        await db.close()
    return items


def _fmt_status(is_checked_in: Optional[bool]) -> str:
    if is_checked_in is None:
        return "N/A"
    return "今日可约" if is_checked_in else "今日未签到"


def _fmt_favorite(is_favorited: Optional[bool]) -> str:
    if is_favorited is None:
        return "N/A"
    return "已收藏" if is_favorited else "未收藏"


# 空列表占位文案（spec UI 文案 + 引导）
EMPTY_TEXT = (
    "👀 最近看过\n\n"
    "你还没有浏览过老师。\n"
    "可以从热门推荐、条件搜索或群关键词开始查看。"
)


def render_recent_views(
    items: list[RecentTeacherViewItem],
    *,
    generated_at: Optional[datetime] = None,
    now_local: Optional[datetime] = None,
) -> str:
    """把最近浏览列表渲染为面板文本。

    纯函数：仅依赖入参。空列表时返回 EMPTY_TEXT。
    """
    if not items:
        return EMPTY_TEXT

    lines: list[str] = [
        f"👀 最近看过（{len(items)} 位）",
        "",
    ]
    for i, item in enumerate(items, start=1):
        if i > 1:
            lines.append("")
        lines.append(f"{i}. {item.display_name or 'N/A'}")
        lines.append(f"最近查看：{format_viewed_at_relative(item.viewed_at, now_local=now_local)}")
        lines.append(f"状态：{_fmt_status(item.is_checked_in_today)}")
        lines.append(f"收藏：{_fmt_favorite(item.is_favorited)}")

    ts = generated_at if generated_at is not None else now_local
    if ts is not None:
        try:
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            lines.append("")
            lines.append(f"更新时间：{ts_str}")
        except Exception:
            pass

    return "\n".join(lines)

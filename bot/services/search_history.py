"""用户「📜 搜索历史」增强版聚合查询 + 渲染。

提供：
    - SearchHistoryItem：dataclass，单条搜索摘要（query / result_count / searched_at / source）
    - get_user_search_history_detailed(user_id, limit)：从 user_events 读富数据，
      复用现有 event_type='search' + payload JSON 约定（无新表、无迁移）
    - render_search_history(items, ...)：纯渲染，便于测试

设计原则：
    - 全程只读：不写 user_events，不修改搜索算法 / 群关键词 / 条件筛选
    - 不纳入 group_search 事件类型（按 spec 本阶段排除）
    - 与现有 database.get_user_search_history 共存：旧函数仍返回 list[str]（被
      cb_search_history_pick 通过 FSM 调用），本服务返回结构化条目供渲染
    - 时间格式化复用 recent_views.format_viewed_at_relative，避免重复实现
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import get_db

# 复用 recent_views 中已经测试过的相对时间格式化
from bot.services.recent_views import format_viewed_at_relative

logger = logging.getLogger(__name__)


@dataclass
class SearchHistoryItem:
    """单条搜索历史摘要。

    字段语义：
        - query：原始关键词（已通过 payload.raw 优先 / tokens 拼接 fallback 提取）
        - result_count：当时的搜索结果数；payload 缺失或非 int 时为 None → 渲染 N/A
        - searched_at：user_events.created_at（SQLite UTC TEXT）
        - source：第一阶段固定 "private"（event_type='search'）；本字段为未来扩展预留，
                  但不会在文本中暴露给用户
    """

    query: str
    result_count: Optional[int]
    searched_at: Optional[str]
    source: str = "private"


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


def _parse_result_count(payload: dict) -> Optional[int]:
    raw = payload.get("result_count")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _extract_query(payload: dict) -> Optional[str]:
    """与 database.get_user_search_history 行为一致：优先 raw，其次 tokens 拼接。"""
    raw = payload.get("raw")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    tokens = payload.get("tokens")
    if isinstance(tokens, list):
        parts = [str(t).strip() for t in tokens if t and str(t).strip()]
        if parts:
            return " ".join(parts)
    return None


async def get_user_search_history_detailed(
    user_id: int, limit: int = 10,
) -> list[SearchHistoryItem]:
    """读取该用户最近搜索条目（含结果数 + 时间）。

    流程与 database.get_user_search_history 行为对齐（去重 + over-fetch），
    但返回 SearchHistoryItem 而非裸字符串。

    异常 / 表缺失 → 返回 []。
    """
    if limit <= 0:
        return []

    rows = []
    try:
        db = await get_db()
        try:
            cur = await db.execute(
                """SELECT payload, created_at FROM user_events
                   WHERE user_id = ? AND event_type = 'search'
                     AND payload IS NOT NULL
                   ORDER BY id DESC
                   LIMIT ?""",
                (int(user_id), int(limit) * 5),  # 与旧函数同样 over-fetch
            )
            rows = await cur.fetchall()
        finally:
            await db.close()
    except Exception as e:
        logger.warning("get_user_search_history_detailed 查询失败 user=%s: %s",
                       user_id, e)
        return []

    seen_lower: set[str] = set()
    items: list[SearchHistoryItem] = []
    for r in rows:
        payload_str = r["payload"]
        if not payload_str:
            continue
        try:
            data = json.loads(payload_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue

        query = _extract_query(data)
        if not query:
            continue

        key = query.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)

        items.append(SearchHistoryItem(
            query=query,
            result_count=_parse_result_count(data),
            searched_at=r["created_at"],
            source="private",
        ))
        if len(items) >= limit:
            break

    return items


# 空列表占位文案（spec UI）
EMPTY_TEXT = (
    "📜 搜索历史\n\n"
    "你还没有搜索记录。\n"
    "可以先使用条件筛选或直接输入关键词搜索。"
)


def _fmt_count(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def render_search_history(
    items: list[SearchHistoryItem],
    *,
    generated_at: Optional[datetime] = None,
    now_local: Optional[datetime] = None,
) -> str:
    """渲染搜索历史面板文本。

    纯函数：仅依赖入参，便于 pytest 直接断言。
    """
    if not items:
        return EMPTY_TEXT

    lines: list[str] = [
        f"📜 搜索历史（{len(items)} 条）",
        "",
        "最近搜索：",
    ]
    ref_now = now_local if now_local is not None else generated_at
    for i, item in enumerate(items, start=1):
        if i > 1:
            lines.append("")
        lines.append(f"{i}. {item.query}")
        lines.append(f"结果：{_fmt_count(item.result_count)} 个")
        lines.append(
            f"时间：{format_viewed_at_relative(item.searched_at, now_local=ref_now)}"
        )

    lines.append("")
    lines.append("点击下方关键词可再次搜索。")

    if generated_at is not None:
        try:
            ts_str = generated_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append("")
            lines.append(f"更新时间：{ts_str}")
        except Exception:
            pass

    return "\n".join(lines)

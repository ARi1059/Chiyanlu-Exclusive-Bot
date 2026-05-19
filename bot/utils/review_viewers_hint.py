"""审核详情页"近期查看者"提示文案 helper（UX-7.4）。

用于在 admin_review.py / rreview_admin.py 的 review 详情页顶部渲染：
    ⚠️ 管理员 #123 1 分钟前查看过此条

避免多管理员并发进入同一条审核。Caller 应预查
`bot.database.list_recent_target_viewers(...)` 后传入。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _parse_utc(ts: str) -> Optional[datetime]:
    """解析 SQLite CURRENT_TIMESTAMP 格式 'YYYY-MM-DD HH:MM:SS'（UTC）。"""
    if not ts:
        return None
    s = ts.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _relative_zh(seconds: int) -> str:
    """秒数 → 中文相对时间（"刚刚 / X 秒前 / X 分钟前 / X 小时前 / X 天前"）。"""
    if seconds < 5:
        return "刚刚"
    if seconds < 60:
        return f"{seconds} 秒前"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时前"
    days = hours // 24
    return f"{days} 天前"


def format_recent_viewers_hint(
    viewers: list[dict],
    *,
    now: Optional[datetime] = None,
    max_show: int = 3,
) -> Optional[str]:
    """构造"⚠️ 管理员 #X 几分钟前查看过此条"提示行（UX-7.4）。

    Args:
        viewers: list[dict]，每条含 admin_id (int) 和 created_at (UTC 字符串)；
                 通常来自 bot.database.list_recent_target_viewers()。
        now: 用于测试注入"当前时间"；缺省取当前 UTC。
        max_show: 同一行最多展示 N 个管理员；超过部分用 "等 N 人" 收尾。

    Returns:
        提示字符串（不含尾部换行）；viewers 为空时返回 None。
    """
    if not viewers:
        return None
    cur = now or datetime.now(timezone.utc)
    parts: list[str] = []
    for v in viewers[:max_show]:
        admin_id = int(v.get("admin_id") or 0)
        if admin_id == 0:
            continue
        viewed = _parse_utc(str(v.get("created_at") or ""))
        if viewed is None:
            rel = "近期"
        else:
            delta = (cur - viewed).total_seconds()
            rel = _relative_zh(max(0, int(delta)))
        parts.append(f"管理员 #{admin_id} {rel}")
    if not parts:
        return None
    extra = ""
    if len(viewers) > max_show:
        extra = f" 等 {len(viewers)} 人"
    return "⚠️ " + " / ".join(parts) + extra + " 查看过此条"

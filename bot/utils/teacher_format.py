"""老师详情 / 群组卡片的共用格式化工具（Phase 8.1）

被以下模块复用：
    - bot/handlers/teacher_detail.py  → 私聊决策型详情（Phase 7.1）
    - bot/handlers/keyword.py         → 群组精准艺名命中卡片（Phase 8.1）

全部纯函数；DB 访问由调用方完成后把结果传进来。
"""

from __future__ import annotations

import json
from typing import Optional


# ============ 通用 ============


def parse_teacher_tags(teacher: dict) -> list[str]:
    """JSON-safe 解析 teacher.tags，返回非空字符串列表

    解析失败或非数组 → 空列表，不抛异常。
    """
    try:
        raw = teacher.get("tags") if isinstance(teacher, dict) else None
        if not raw:
            return []
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []
        return [str(t) for t in parsed if t]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def format_price_display(price: Optional[str]) -> str:
    """把存储价格转换为展示价格：'1000P' → '10P'，'900P' → '9P'

    规则：抽出数字部分，除以 100 后追加 'P'。无数字时原样返回；None/空 → ''。
    """
    if price is None:
        return ""
    s = str(price).strip()
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return s
    return f"{int(digits) // 100}P"


def build_today_label(t: dict) -> str:
    """今日开课列表按钮 label：'地区 艺名 价格'

    任一字段缺失时跳过该段；空白用空格连接。display_name 全空时兜底 '?'。
    """
    region = (t.get("region") or "").strip()
    name = (t.get("display_name") or "").strip()
    price = format_price_display(t.get("price"))
    parts = [p for p in (region, name, price) if p]
    return " ".join(parts) or name or "?"


def build_teacher_hot_text(
    teacher: dict,
    today_str: str,
    fav_count: int = 0,
) -> str:
    """热度文案优先级：近期推荐 > 近期热门 > 多人收藏 > 普通展示

    任何字段缺失 / 异常 → 安全退到"普通展示"。
    is_effective_featured 不存在时跳过该层判断。
    """
    try:
        from bot.database import is_effective_featured  # type: ignore
        if is_effective_featured(teacher, today_str):
            return "近期推荐"
    except Exception:
        pass
    try:
        if int(teacher.get("hot_score") or 0) >= 100:
            return "近期热门"
    except (ValueError, TypeError):
        pass
    try:
        fc = int(fav_count or 0)
    except (ValueError, TypeError):
        fc = 0
    if fc >= 5:
        return "多人收藏"
    return "普通展示"


def build_teacher_fit_text(
    teacher: dict,
    tags: list,
    *,
    short: bool = False,
) -> str:
    """适合人群文案（纯规则拼装，无 AI）

    short=False（私聊详情用）：
        "适合喜欢成熟气质、预算 1000P 左右、想找 天府一街 附近的用户。"

    short=True（群组卡片用）：
        "成熟气质 / 预算 1000P / 天府一街附近"

    全部维度缺失时：
        - 私聊：适合想快速了解并联系老师的用户。
        - 群组：想快速了解并联系老师的用户
    """
    long_parts: list[str] = []
    short_parts: list[str] = []
    tag_set = {str(t).strip() for t in tags if t and str(t).strip()}

    if "御姐" in tag_set:
        long_parts.append("喜欢成熟气质")
        short_parts.append("成熟气质")
    if "甜妹" in tag_set:
        long_parts.append("喜欢甜美亲和风格")
        short_parts.append("甜美亲和")
    if "高颜值" in tag_set or "颜值" in tag_set:
        long_parts.append("看重颜值表现")
        short_parts.append("看重颜值")

    price = ""
    if isinstance(teacher, dict):
        price = (teacher.get("price") or "").strip()
    if price:
        long_parts.append(f"预算在 {price} 左右")
        short_parts.append(f"预算 {price}")

    region = ""
    if isinstance(teacher, dict):
        region = (teacher.get("region") or "").strip()
    if region:
        long_parts.append(f"想找 {region} 附近")
        short_parts.append(f"{region}附近")

    if short:
        if not short_parts:
            return "想快速了解并联系老师的用户"
        return " / ".join(short_parts)

    if not long_parts:
        return "适合想快速了解并联系老师的用户。"
    return "适合" + "、".join(long_parts) + "的用户。"


# ============ 今日状态 ============


def derive_today_status_for_detail(
    is_signed_in_today: bool,
    daily_status_row: Optional[dict],
) -> str:
    """私聊详情页用：返回单行 today_status_text

    daily_status_row.status: available / full / unavailable / None
    （available_time / note 不再用于展示）
    """
    status_val = (daily_status_row or {}).get("status") if daily_status_row else None

    if not is_signed_in_today and status_val != "unavailable":
        return "今日暂未开课"
    if status_val == "unavailable":
        return "❌ 今日已取消"
    if status_val == "full":
        return "🈵 今日已满"
    return "✅ 今日可约"


def derive_today_status_for_group(
    is_signed_in_today: bool,
    daily_status_row: Optional[dict],
) -> str:
    """群组卡片用：单行短文案，四态

    - 未签到 → "今日暂未开课"
    - unavailable → "已取消"
    - full → "已满"
    - 其它（available / 已签到无 daily_status）→ "今日可约"
    """
    status_val = (daily_status_row or {}).get("status") if daily_status_row else None

    if not is_signed_in_today and status_val != "unavailable":
        return "今日暂未开课"
    if status_val == "unavailable":
        return "已取消"
    if status_val == "full":
        return "已满"
    return "今日可约"


# ============ 完整文本拼装 ============


def format_teacher_private_detail(
    teacher: dict,
    *,
    is_signed_in_today: bool,
    is_fav: bool,
    daily_status_row: Optional[dict] = None,
    fav_count: int = 0,
    today_str: str = "",
) -> str:
    """Phase 7.1 决策型私聊详情页文本（从 teacher_detail.py 抽出复用）"""
    tags = parse_teacher_tags(teacher)
    tags_text = " ｜ ".join(tags) if tags else "暂无标签"

    today_status_text = derive_today_status_for_detail(
        is_signed_in_today, daily_status_row,
    )
    hot_text = build_teacher_hot_text(teacher, today_str, fav_count)
    favorite_text = "已收藏" if is_fav else "未收藏"
    fit_text = build_teacher_fit_text(teacher, tags, short=False)
    price_text = format_price_display(teacher.get("price")) or "未设置"

    lines = [
        f"👤 {teacher['display_name']}",
        "",
        f"📍 地区：{teacher.get('region') or '未设置'}",
        f"💰 价格：{price_text}",
        f"📅 今日：{today_status_text}",
        f"🔥 热度：{hot_text}",
        f"⭐ 你的状态：{favorite_text}",
        "",
        "🏷 特点：",
        tags_text,
        "",
        "📌 适合：",
        fit_text,
    ]
    return "\n".join(lines)


def format_teacher_group_card(
    teacher: dict,
    *,
    is_signed_in_today: bool,
    daily_status_row: Optional[dict] = None,
    fav_count: int = 0,
    today_str: str = "",
) -> str:
    """Phase 8.1 群组精简卡片文本

    与私聊详情的差异：
        - 地区 / 价格 合并到一行
        - 今日状态合并 status + available_time 为一行
        - 无"⭐ 你的状态"（群组消息对所有人可见，不能个性化）
        - "适合"使用 short=True 短文案
    """
    tags = parse_teacher_tags(teacher)
    tags_text = "｜".join(tags) if tags else "暂无标签"

    today_line = derive_today_status_for_group(is_signed_in_today, daily_status_row)
    hot_text = build_teacher_hot_text(teacher, today_str, fav_count)
    fit_text = build_teacher_fit_text(teacher, tags, short=True)

    region = (teacher.get("region") or "").strip() or "?"
    price = format_price_display(teacher.get("price")) or "?"

    lines = [
        f"👤 {teacher.get('display_name') or '?'}",
        "",
        f"📍 {region}｜💰 {price}",
        f"📅 今日：{today_line}",
        f"🔥 热度：{hot_text}",
        "",
        f"🏷 {tags_text}",
        "",
        f"📌 适合：{fit_text}",
    ]
    return "\n".join(lines)

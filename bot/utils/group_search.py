"""群组组合搜索 + 群组快捷词工具（Phase 8.2）

包含：
    - 输入归一化 / token 拆分
    - 3 层群组冷却（group_total / group+keyword / group+user）
    - base64url 编解码（用于 /start q_<encoded> deep link）
    - 群组搜索结果短状态文案

全部纯函数或进程内状态；不依赖数据库。
"""

from __future__ import annotations

import base64
import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ============ token 拆分 ============


def split_query_tokens(raw: str) -> list[str]:
    """按 空白 / 中英文逗号 / 顿号 拆分群组输入

    去重保留首次出现顺序（key 用小写比较，但保留原始大小写）。
    与 user_search._split_tokens 同源逻辑。
    """
    if not raw:
        return []
    parts = re.split(r"[\s,，、]+", raw)
    seen_lower: set[str] = set()
    result: list[str] = []
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        key = p.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        result.append(p)
    return result


def normalize_group_query(raw: str) -> str:
    """归一化用于冷却 key：trim + 小写 + 多空白塌缩"""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip().lower())


# ============ 3 层群组冷却（进程内 dict，不入库） ============


# 单用户冷却：同一 (group_id, user_id) 15s 内最多触发一次
_user_in_group_last: dict[tuple[int, int], float] = {}
# 同关键词冷却：同一 (group_id, normalized_query) 30s 内最多回复一次
_keyword_in_group_last: dict[tuple[int, str], float] = {}
# 群组总冷却：同一 group_id 5s 内最多回复一次
_group_total_last: dict[int, float] = {}

USER_GROUP_COOLDOWN_SECONDS: int = 15
KEYWORD_GROUP_COOLDOWN_SECONDS: int = 30
GROUP_TOTAL_COOLDOWN_SECONDS: int = 5


def check_group_cooldown(
    group_id: int,
    user_id: int,
    normalized_query: str,
    *,
    skip_user_layer: bool = False,
) -> tuple[bool, str]:
    """检查 3 层冷却

    Args:
        group_id / user_id / normalized_query: 必填
        skip_user_layer: True → 跳过用户层（用于老师艺名精准命中，spec §九 提示）

    Returns:
        (allowed, reason)
            allowed=True: 没有任何一层在冷却，可以发送
            allowed=False: 至少一层冷却中，调用方应静默不回复
            reason: 仅 debug 用，标识被哪层挡住
    """
    now = time.time()

    # Layer 3 (cheapest): 群组总冷却
    last = _group_total_last.get(group_id, 0.0)
    if now - last < GROUP_TOTAL_COOLDOWN_SECONDS:
        return False, "group_total"

    # Layer 2: 同关键词冷却
    if normalized_query:
        key_kw = (group_id, normalized_query)
        last = _keyword_in_group_last.get(key_kw, 0.0)
        if now - last < KEYWORD_GROUP_COOLDOWN_SECONDS:
            return False, "same_keyword"

    # Layer 1: 单用户冷却（部分场景可跳过）
    if not skip_user_layer:
        key_user = (group_id, user_id)
        last = _user_in_group_last.get(key_user, 0.0)
        if now - last < USER_GROUP_COOLDOWN_SECONDS:
            return False, "user_per_group"

    return True, ""


def record_group_cooldown(
    group_id: int,
    user_id: int,
    normalized_query: str,
    *,
    skip_user_layer: bool = False,
) -> None:
    """记录本次回复时间，更新三层冷却时间戳

    skip_user_layer 含义与 check_group_cooldown 一致 —— 跳过的层不会被记录，
    保证下一次该用户仍可在 15s 内进行其他类型的查询。
    """
    now = time.time()
    _group_total_last[group_id] = now
    if normalized_query:
        _keyword_in_group_last[(group_id, normalized_query)] = now
    if not skip_user_layer:
        _user_in_group_last[(group_id, user_id)] = now


# ============ base64url 编解码（/start q_<encoded>） ============


# Telegram /start 参数官方限制 64 字节。预留 "q_" 前缀 2 字节 + 安全余量。
DEEP_LINK_QUERY_MAX_ENCODED_LEN: int = 60


def encode_query_for_deep_link(query: str) -> Optional[str]:
    """把搜索词 base64url-encode（去掉 padding）

    超长（编码后 > 60 字符）→ 返回 None，调用方应降级到 /start search。
    异常 → 返回 None。
    """
    if not query:
        return None
    try:
        raw = query.encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    except Exception as e:
        logger.debug("encode_query_for_deep_link 失败 q=%r: %s", query, e)
        return None
    if len(encoded) > DEEP_LINK_QUERY_MAX_ENCODED_LEN:
        return None
    return encoded


def decode_query_from_deep_link(encoded: str) -> Optional[str]:
    """base64url-decode；失败 / 空输入 / 非法字符 → None"""
    if not encoded:
        return None
    try:
        padding = "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(encoded + padding)
        result = raw.decode("utf-8")
        result = result.strip()
        return result or None
    except Exception as e:
        logger.debug("decode_query_from_deep_link 失败 e=%r: %s", encoded, e)
        return None


# ============ 群组搜索结果短状态文案 ============


def group_result_short_status(t: dict) -> str:
    """从一行老师 dict 派生群组结果列表用的短状态

    与 user_filter._short_status 同语义；放在这里方便 keyword.py 复用。
    """
    status = t.get("daily_status")
    if status == "unavailable":
        return "今日已取消"
    if status == "full":
        return "今日已满"
    if bool(t.get("signed_in_today")):
        avt = (t.get("daily_available_time") or "").strip()
        note = (t.get("daily_note") or "").strip()
        if avt == "全天":
            return "全天可约"
        if avt == "下午":
            return "下午可约"
        if avt == "晚上":
            return "晚上可约"
        if avt == "自定义" and note:
            return note
        return "今日可约"
    return "今日暂未开课"


def sort_group_search_results(
    teachers: list[dict],
    today_str: str,
) -> list[dict]:
    """Phase 8.2 §十 排序优先级：
        1. 今日可约（已签到且状态 != unavailable/full）
        2. 已签到 + full（次于"可约"，因为仍是今日活跃）
        3. 未签到 + 非取消
        4. 已取消
        然后按 featured / sort_weight / hot_score / fav_count / created_at
    """
    try:
        from bot.database import is_effective_featured  # type: ignore
    except ImportError:
        is_effective_featured = None  # type: ignore

    def _rank(t: dict) -> int:
        signed = bool(t.get("signed_in_today"))
        status = (t.get("daily_status") or "")
        if signed and status not in ("full", "unavailable"):
            return 0
        if signed and status == "full":
            return 1
        if not signed and status != "unavailable":
            return 2
        return 3

    def _featured(t: dict) -> int:
        if is_effective_featured is None:
            return 0
        try:
            return 1 if is_effective_featured(t, today_str) else 0
        except Exception:
            return 0

    def _int(t: dict, k: str) -> int:
        try:
            return int(t.get(k) or 0)
        except (ValueError, TypeError):
            return 0

    def key(t: dict):
        return (
            _rank(t),
            -_featured(t),
            -_int(t, "sort_weight"),
            -_int(t, "hot_score"),
            -_int(t, "fav_count"),
            str(t.get("created_at") or ""),
        )

    return sorted(teachers, key=key)


def render_group_search_result_text(
    teachers: list[dict],
    *,
    total_count: int,
    display_limit: int = 5,
) -> str:
    """渲染群组搜索结果文本（命中 ≥2 时）"""
    shown = teachers[:display_limit]
    n = len(shown)

    if total_count <= display_limit:
        header = f"🔎 找到 {total_count} 位相关老师"
        footer = "点击下方按钮查看更多。"
    else:
        header = f"🔎 找到 {total_count} 位相关老师，先展示前 {n} 位："
        footer = "结果较多，建议私聊查看更多。"

    lines = [header, ""]
    for i, t in enumerate(shown, start=1):
        name = t.get("display_name") or "?"
        region = (t.get("region") or "?").strip() or "?"
        price = (t.get("price") or "?").strip() or "?"
        status = group_result_short_status(t)
        lines.append(f"{i}. {name}｜{region}｜{price}｜{status}")
    lines.append("")
    lines.append(footer)
    return "\n".join(lines)

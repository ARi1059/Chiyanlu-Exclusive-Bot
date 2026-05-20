"""群组组合搜索 + 群组快捷词工具（Phase 8.2）

包含：
    - 输入归一化 / token 拆分
    - 3 层群组冷却（group_total / group+keyword / group+user）
    - base64url 编解码（用于 /start q_<encoded> deep link）
    - 群组搜索结果短状态文案
    - 分页 HTML 渲染（2026-05：群内必须完整 + 超链接，超长自动分页）

全部纯函数或进程内状态；不依赖数据库。
"""

from __future__ import annotations

import base64
import logging
import re
import time
from html import escape
from typing import Optional

from bot.utils.url import normalize_url

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

# UX-10.2：默认值（无 config 覆盖时使用，与历史值一致）
USER_GROUP_COOLDOWN_SECONDS: int = 15
KEYWORD_GROUP_COOLDOWN_SECONDS: int = 30
GROUP_TOTAL_COOLDOWN_SECONDS: int = 5

# config key 前缀（UX-10.2）；超管可在 KV config 表里写：
#   keyword.cooldown.user      （默认 15 秒）
#   keyword.cooldown.keyword   （默认 30 秒）
#   keyword.cooldown.group     （默认 5 秒）
_COOLDOWN_CONFIG_KEYS = {
    "user":    ("keyword.cooldown.user",    USER_GROUP_COOLDOWN_SECONDS),
    "keyword": ("keyword.cooldown.keyword", KEYWORD_GROUP_COOLDOWN_SECONDS),
    "group":   ("keyword.cooldown.group",   GROUP_TOTAL_COOLDOWN_SECONDS),
}


async def _read_cooldown_seconds(layer: str) -> int:
    """读取指定层的冷却秒数；config 缺失 / 非法 → 回退到默认值（UX-10.2）。"""
    config_key, default = _COOLDOWN_CONFIG_KEYS[layer]
    try:
        from bot.database import get_config
        raw = await get_config(config_key)
    except Exception:
        return default
    if raw is None or str(raw).strip() == "":
        return default
    try:
        n = int(str(raw).strip())
    except (ValueError, TypeError):
        return default
    # 防御：负数视为无效；超长（>3600 秒）也视为配置失误回退
    if n < 0 or n > 3600:
        return default
    return n


async def check_group_cooldown(
    group_id: int,
    user_id: int,
    normalized_query: str,
    *,
    skip_user_layer: bool = False,
) -> tuple[bool, str]:
    """检查 3 层冷却（UX-10.2：每层秒数从 config 读取，缺失回退默认）

    Args:
        group_id / user_id / normalized_query: 必填
        skip_user_layer: True → 跳过用户层（用于老师艺名精准命中，spec §九 提示）

    Returns:
        (allowed, reason)
            allowed=True: 没有任何一层在冷却，可以发送
            allowed=False: 至少一层冷却中，调用方应静默不回复
            reason: 仅 debug 用，标识被哪层挡住，caller 可附加到 silenced 埋点
    """
    now = time.time()

    # Layer 3 (cheapest): 群组总冷却
    group_cd = await _read_cooldown_seconds("group")
    last = _group_total_last.get(group_id, 0.0)
    if now - last < group_cd:
        return False, "group_total"

    # Layer 2: 同关键词冷却
    if normalized_query:
        kw_cd = await _read_cooldown_seconds("keyword")
        key_kw = (group_id, normalized_query)
        last = _keyword_in_group_last.get(key_kw, 0.0)
        if now - last < kw_cd:
            return False, "same_keyword"

    # Layer 1: 单用户冷却（部分场景可跳过）
    if not skip_user_layer:
        user_cd = await _read_cooldown_seconds("user")
        key_user = (group_id, user_id)
        last = _user_in_group_last.get(key_user, 0.0)
        if now - last < user_cd:
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
    """从一行老师 dict 派生群组结果列表用的短状态（四态）

    - unavailable → 今日已取消
    - full → 今日已满
    - 已签到 → 今日可约
    - 未签到 → 今日暂未开课
    """
    status = t.get("daily_status")
    if status == "unavailable":
        return "今日已取消"
    if status == "full":
        return "今日已满"
    if bool(t.get("signed_in_today")):
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


def _render_one_teacher_html(idx: int, teacher: dict) -> str:
    """渲染单老师为 HTML 一行：

        <a href="url">{idx}. {name}｜{region}｜{price}｜{status}</a>

    button_url 无效时退化为纯文本（去掉 <a>，保留同样视觉布局）。
    所有用户内容必走 html.escape（防 < > & 注入）。
    """
    name = teacher.get("display_name") or "?"
    region = (teacher.get("region") or "?").strip() or "?"
    price = (teacher.get("price") or "?").strip() or "?"
    status = group_result_short_status(teacher)
    inner = (
        f"{idx}. {escape(name)}｜{escape(region)}｜"
        f"{escape(price)}｜{escape(status)}"
    )
    url = normalize_url(teacher.get("button_url"))
    if url:
        return f'<a href="{escape(url, quote=True)}">{inner}</a>'
    return inner


def render_group_search_result_pages(
    teachers: list[dict],
    *,
    total_count: int,
    per_page: int = 25,
) -> list[str]:
    """把搜索命中分页为多段 HTML 文本，每位老师含可点击超链接。

    设计要点（2026-05：群内必须完整 + 不再截断）：
        - 不再硬截到前 5 位；遍历全部 teachers
        - 老师名整行做超链接（指向其 button_url），无 url 时降级为纯文本
        - 单页 per_page 条；total_count > per_page 时分多页
        - 单条消息 < Telegram 4096 字符上限（per_page=25 × 约 100 字节/行 ≈ 2.5KB，安全）
        - 每页头部带页码；最后一页结尾不再写"建议私聊"，由 caller 附按钮即可

    Returns:
        list[str]：至少 1 页；caller 用 ParseMode.HTML + disable_web_page_preview=True
        逐页 send_message。当列表为空时返回 []（caller 应跳过发送）。
    """
    if not teachers:
        return []
    per_page = max(1, int(per_page))
    total_pages = (len(teachers) + per_page - 1) // per_page
    pages: list[str] = []
    for page_no in range(total_pages):
        start = page_no * per_page
        end = start + per_page
        chunk = teachers[start:end]
        if total_pages == 1:
            header = f"🔎 找到 {total_count} 位相关老师"
        else:
            header = (
                f"🔎 找到 {total_count} 位相关老师"
                f"（第 {page_no + 1}/{total_pages} 页）"
            )
        lines = [header, ""]
        for offset, t in enumerate(chunk):
            idx = start + offset + 1
            lines.append(_render_one_teacher_html(idx, t))
        pages.append("\n".join(lines))
    return pages


def render_group_search_result_text(
    teachers: list[dict],
    *,
    total_count: int,
    display_limit: int = 5,
) -> str:
    """兼容旧调用：返回第一页 HTML 文本。

    新代码请直接用 render_group_search_result_pages，可获得完整分页 + 所有老师；
    保留本函数避免破坏既有测试 / 调用方。
    """
    pages = render_group_search_result_pages(
        teachers, total_count=total_count, per_page=max(1, int(display_limit)),
    )
    if not pages:
        return f"🔎 找到 {total_count} 位相关老师"
    return pages[0]

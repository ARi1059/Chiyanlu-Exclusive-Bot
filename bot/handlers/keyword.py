"""群组内关键词响应 + 群内快捷入口 + 群组组合搜索

匹配优先级（Phase 8.2 §三）：
    1. 精准匹配老师艺名 → Phase 8.1 精简详情卡片
    2. 群组快捷词       → 菜单 / 今日 / 热门 / 推荐 / 筛选（私聊跳转入口）
    3. 群组组合搜索     → 标签 / 地区 / 价格 组合，0/1/N 结果分别处理
    4. 无匹配           → 静默不回复（不发"未找到"，避免刷屏）

冷却（Phase 8.2 §九）：
    - 群组总冷却 5s
    - 同关键词冷却 30s
    - 单用户冷却 15s（老师精准命中跳过此层）
    任何一层在冷却中 → 静默
"""

import logging
from datetime import datetime

from aiogram import Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pytz import timezone

from bot.config import config
from bot.database import (
    count_teacher_favoriters,
    get_config,
    get_teacher_by_name,
    get_teacher_daily_status,
    is_checked_in,
    search_teachers_smart_and,
)
from bot.utils.group_search import (
    check_group_cooldown,
    encode_query_for_deep_link,
    normalize_group_query,
    record_group_cooldown,
    render_group_search_result_text,
    sort_group_search_results,
    split_query_tokens,
)
from bot.utils.teacher_format import format_teacher_group_card
from bot.utils.teacher_render import build_teacher_group_card_v2_kb

logger = logging.getLogger(__name__)

router = Router(name="keyword")

_tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(_tz).strftime("%Y-%m-%d")


# ============ 群组快捷词（Phase 8.2 §七，更新文案） ============


# 每条：banner / body / 3 个 (button_text, deep_link_target) 按钮
_QUICK_ENTRY_CONFIG: dict[str, dict] = {
    "菜单": {
        "banner": "📌 痴颜录 Bot 菜单",
        "body": "你可以点击下方进入私聊使用：",
        "buttons": [
            ("打开菜单", "menu"),
            ("今日开课", "today"),
            ("热门推荐", "hot"),
        ],
    },
    "今日": {
        "banner": "📚 今日开课入口",
        "body": "点击下方进入私聊查看今日开课老师。",
        "buttons": [
            ("打开今日开课", "today"),
            ("按条件筛选", "filter"),
            ("热门推荐", "hot"),
        ],
    },
    "热门": {
        "banner": "🔥 热门推荐入口",
        "body": "点击下方查看近期热门老师。",
        "buttons": [
            ("热门推荐", "hot"),
            ("帮我推荐", "recommend"),
            ("按条件筛选", "filter"),
        ],
    },
    "推荐": {
        "banner": "🎯 推荐入口",
        "body": "想让 Bot 根据你的浏览、搜索和收藏推荐老师，请进入私聊使用。",
        "buttons": [
            ("为我推荐", "recommend"),
            ("热门推荐", "hot"),
            ("按条件筛选", "filter"),
        ],
    },
    "筛选": {
        "banner": "🔎 条件筛选入口",
        "body": "可以按地区、价格、标签查找老师。",
        "buttons": [
            ("按条件筛选", "filter"),
            ("今日开课", "today"),
            ("热门推荐", "hot"),
        ],
    },
}


# ============ helpers ============


async def _get_response_group_ids() -> list[int]:
    """获取响应群组 ID 列表"""
    raw = await get_config("response_group_ids")
    if not raw:
        return []
    try:
        return [int(g.strip()) for g in raw.split(",") if g.strip()]
    except ValueError:
        return []


async def _safe_log_event(user_id: int, event_type: str, payload=None) -> None:
    """log_user_event 缺失 / 异常时静默跳过"""
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(user_id, event_type, payload)
    except Exception as e:
        logger.debug("log_user_event(%s) 失败: %s", event_type, e)


async def _get_bot_username(message: types.Message) -> str | None:
    """统一获取 bot username；失败返回 None（调用方应自行降级）"""
    try:
        me = await message.bot.get_me()
        return me.username
    except Exception as e:
        logger.warning("get_me 失败: %s", e)
        return None


def _build_deep_link_buttons(
    bot_username: str,
    buttons: list[tuple[str, str]],
    *,
    per_row: int = 3,
) -> InlineKeyboardMarkup:
    """把 [(label, target_suffix), ...] 渲染成 URL deep link 按钮组

    Telegram 群组场景必须用 URL 跳转（callback 在群组里也能用，但 URL 体验更明确）。
    per_row 默认 3 — 群组场景尽量单行减少视觉高度。
    """
    base = f"https://t.me/{bot_username}"
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, suffix in buttons:
        row.append(InlineKeyboardButton(
            text=label,
            url=f"{base}?start={suffix}",
        ))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============ 1. 精准艺名 → Phase 8.1 卡片 ============


async def _send_teacher_group_card_v2(
    message: types.Message,
    teacher: dict,
) -> None:
    """Phase 8.1：群组精准艺名命中 → 精简详情卡片"""
    today = _today_str()
    teacher_id = teacher["user_id"]

    try:
        daily = await get_teacher_daily_status(teacher_id, today)
    except Exception as e:
        logger.debug("get_teacher_daily_status 失败: %s", e)
        daily = None
    try:
        signed_in = await is_checked_in(teacher_id, today)
    except Exception as e:
        logger.debug("is_checked_in 失败: %s", e)
        signed_in = False
    try:
        fav_count = await count_teacher_favoriters(teacher_id)
    except Exception as e:
        logger.debug("count_teacher_favoriters 失败: %s", e)
        fav_count = 0

    text = format_teacher_group_card(
        teacher,
        is_signed_in_today=signed_in,
        daily_status_row=daily,
        fav_count=fav_count,
        today_str=today,
    )

    bot_username = await _get_bot_username(message)
    kb = build_teacher_group_card_v2_kb(teacher, bot_username)

    try:
        if teacher.get("photo_file_id"):
            await message.answer_photo(
                photo=teacher["photo_file_id"],
                caption=text,
                reply_markup=kb,
            )
        else:
            await message.answer(text, reply_markup=kb)
    except Exception as e:
        logger.warning("发送群组卡片失败，降级为文字: %s", e)
        try:
            await message.answer(text, reply_markup=kb)
        except Exception as e2:
            logger.warning("文字降级也失败: %s", e2)


# ============ 2. 群组快捷词（Phase 8.2 §七） ============


async def _send_quick_entry(
    message: types.Message,
    keyword: str,
) -> bool:
    """发送群组快捷词回复

    Returns:
        True  → 成功发送（调用方应记录冷却）
        False → 没发出（bot_username 缺失等异常；调用方不要记录冷却）
    """
    cfg = _QUICK_ENTRY_CONFIG.get(keyword)
    if not cfg:
        return False

    bot_username = await _get_bot_username(message)
    if not bot_username:
        return False

    body = f"{cfg['banner']}\n\n{cfg['body']}"
    kb = _build_deep_link_buttons(bot_username, cfg["buttons"], per_row=3)

    try:
        await message.reply(
            body,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning("发送群内快捷入口失败: %s", e)
        return False

    return True


# ============ 3. 群组组合搜索（Phase 8.2 §四-六） ============


async def _enrich_with_today_status(
    teachers: list[dict],
    today: str,
) -> list[dict]:
    """给搜索命中的老师补 signed_in_today / daily_status / fav_count

    每位老师 3 次小查询。典型 N<20 性能可接受。
    """
    enriched: list[dict] = []
    for t in teachers:
        tt = dict(t)
        try:
            tt["signed_in_today"] = 1 if await is_checked_in(t["user_id"], today) else 0
        except Exception:
            tt["signed_in_today"] = 0
        try:
            daily = await get_teacher_daily_status(t["user_id"], today)
        except Exception:
            daily = None
        if daily:
            tt["daily_status"] = daily.get("status")
            tt["daily_available_time"] = daily.get("available_time")
            tt["daily_note"] = daily.get("note")
        else:
            tt["daily_status"] = None
            tt["daily_available_time"] = None
            tt["daily_note"] = None
        try:
            tt["fav_count"] = await count_teacher_favoriters(t["user_id"])
        except Exception:
            tt["fav_count"] = 0
        enriched.append(tt)
    return enriched


def _build_combo_search_kb(
    bot_username: str,
    raw_query: str,
    total_count: int,
) -> InlineKeyboardMarkup:
    """组合搜索结果页底部按钮

    [查看全部结果] —— /start q_<base64url> 优先，超长 fallback 到 /start search
    [按条件筛选] —— /start filter
    [热门推荐]   —— 仅在结果 > 5 时显示
    """
    base = f"https://t.me/{bot_username}"

    encoded = encode_query_for_deep_link(raw_query)
    if encoded:
        all_results_url = f"{base}?start=q_{encoded}"
    else:
        all_results_url = f"{base}?start=search"

    row1: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="🔍 查看全部结果", url=all_results_url),
        InlineKeyboardButton(text="🔎 按条件筛选", url=f"{base}?start=filter"),
    ]
    rows: list[list[InlineKeyboardButton]] = [row1]
    if total_count > 5:
        rows.append([
            InlineKeyboardButton(text="🔥 热门推荐", url=f"{base}?start=hot"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _handle_combo_search(
    message: types.Message,
    raw_query: str,
    tokens: list[str],
) -> tuple[bool, int]:
    """执行群组组合搜索，按命中数量分支渲染

    Returns:
        (sent, matched_count):
            sent=True  → 已发送回复（调用方记录冷却 + 埋点）
            sent=False → 静默（0 命中 / 全 unrecognized / bot username 缺失）
            matched_count → 命中数量（用于埋点）
    """
    try:
        teachers, _unrec = await search_teachers_smart_and(tokens)
    except Exception as e:
        logger.warning("search_teachers_smart_and 失败 tokens=%r: %s", tokens, e)
        return False, 0

    matched_count = len(teachers)
    if matched_count == 0:
        return False, 0

    today = _today_str()

    # 单结果：直接复用 Phase 8.1 群组卡片
    if matched_count == 1:
        await _send_teacher_group_card_v2(message, teachers[0])
        return True, 1

    # ≥2：补 daily_status + 排序 + 渲染列表
    enriched = await _enrich_with_today_status(teachers, today)
    enriched = sort_group_search_results(enriched, today)

    bot_username = await _get_bot_username(message)
    if not bot_username:
        return False, matched_count

    text = render_group_search_result_text(
        enriched,
        total_count=matched_count,
        display_limit=5,
    )
    kb = _build_combo_search_kb(bot_username, raw_query, matched_count)

    try:
        await message.reply(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        logger.warning("发送群组搜索列表失败: %s", e)
        return False, matched_count

    return True, matched_count


# ============ 入口 ============


@router.message()
async def on_keyword_message(message: types.Message):
    """群组消息分发（Phase 8.2 §三 4 级优先级 + §九 3 层冷却）"""
    # 1. 仅处理响应群组的纯文本
    if message.chat.type not in ("group", "supergroup"):
        return
    if not message.text:
        return
    group_ids = await _get_response_group_ids()
    if not group_ids:
        return
    if message.chat.id not in group_ids:
        return
    keyword = message.text.strip()
    if not keyword:
        return

    group_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    normalized = normalize_group_query(keyword)

    # ============ 优先级 1：精准艺名命中 ============
    try:
        teacher = await get_teacher_by_name(keyword)
    except Exception as e:
        logger.warning("get_teacher_by_name 失败 kw=%r: %s", keyword, e)
        teacher = None

    if teacher:
        # spec §九：老师精准命中走"群组总+同关键词"冷却，跳过单用户冷却
        allowed, _ = check_group_cooldown(
            group_id, user_id, normalized,
            skip_user_layer=True,
        )
        if not allowed:
            return  # 静默
        await _send_teacher_group_card_v2(message, teacher)
        record_group_cooldown(
            group_id, user_id, normalized,
            skip_user_layer=True,
        )
        await _safe_log_event(
            user_id,
            "group_teacher_card_view",
            {
                "teacher_id": teacher["user_id"],
                "group_id": group_id,
                "keyword": keyword,
            },
        )
        return

    # ============ 优先级 2：群组快捷词 ============
    if keyword in _QUICK_ENTRY_CONFIG:
        allowed, _ = check_group_cooldown(group_id, user_id, normalized)
        if not allowed:
            return
        sent = await _send_quick_entry(message, keyword)
        if not sent:
            return
        record_group_cooldown(group_id, user_id, normalized)
        await _safe_log_event(
            user_id,
            "group_quick_entry",
            {
                "keyword": keyword,
                "target": _QUICK_ENTRY_CONFIG[keyword]["buttons"][0][1],
                "group_id": group_id,
            },
        )
        return

    # ============ 优先级 3：群组组合搜索 ============
    tokens = split_query_tokens(keyword)
    if not tokens:
        return

    # 先 cooldown 后再做较重的 DB 查询；命中后再消费 cooldown 配额
    allowed, _ = check_group_cooldown(group_id, user_id, normalized)
    if not allowed:
        return

    sent, matched_count = await _handle_combo_search(message, keyword, tokens)
    if not sent:
        return  # 0 命中 / 全 unrecognized / 渲染失败 → 静默（spec §五）

    record_group_cooldown(group_id, user_id, normalized)
    await _safe_log_event(
        user_id,
        "group_search",
        {
            "query": keyword,
            "tokens": tokens,
            "group_id": group_id,
            "matched_count": matched_count,
        },
    )

    # 优先级 4：以上均未命中 → 静默（无任何额外动作）

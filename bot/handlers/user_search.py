"""私聊搜索 FSM handler（v2 §2.4 F4 智能 AND 搜索 + Phase 2 详情页接入）

处理 SearchStates.waiting_query 状态下用户的文本输入:
    1. 艺名精确命中 → 直接展示该老师详情页（teacher_detail）
    2. 否则按空格 / 逗号拆分 → 智能 AND 搜索
       - 命中 1 位 → 详情页
       - 命中多位 → 列表（每个老师按钮 → teacher:view）
       - 命中 0 位 → 推荐关键词键盘（today / hot / 关键词）

仅响应私聊消息，避免群组内被误触发。状态在每次搜索后保持，用户可连续搜索；
通过 /cancel 或菜单按钮退出。

Phase 2 新增 callbacks:
    search:suggest:today       → 列出今日开课老师（点击进详情页）
    search:suggest:hot         → 列出热门老师（按收藏 TOP）
    search:suggest:<keyword>   → 以 <keyword> 作为查询重新执行搜索
"""

import logging
import re

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.database import (
    add_user_tag,
    get_checked_in_teachers,
    get_teacher_by_name,
    is_effective_featured,
    is_favorited,
    search_teachers_smart_and,
)
from bot.keyboards.user_kb import (
    search_cancel_kb,
    search_suggestion_kb,
    suggestion_result_back_kb,
    teacher_detail_list_kb,
    user_main_menu_kb,
)
from bot.states.user_states import SearchStates
from bot.handlers.teacher_detail import (
    _today_str,
    send_teacher_detail_message,
)

logger = logging.getLogger(__name__)

router = Router(name="user_search")


# 推荐关键词的默认集合（Phase 2 §四 要求 2）
DEFAULT_SUGGEST_KEYWORDS: list[str] = [
    "御姐", "甜妹", "新人", "高颜值", "天府一街", "金融城",
]


def _split_tokens(raw: str) -> list[str]:
    """按空格 / 中文逗号 / 英文逗号 / 顿号拆分用户输入

    去除空白，按小写去重（保留首次出现的原始大小写）。
    """
    parts = re.split(r"[\s,，、]+", raw)
    seen_lower: set[str] = set()
    result: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        key = p.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        result.append(p)
    return result


async def _resolve_suggestion_keywords() -> list[str]:
    """搜索失败推荐词来源
    选用：第一阶段如果实现了 get_top_search_keywords(limit=8) 则用真实数据，
    否则用 DEFAULT_SUGGEST_KEYWORDS。
    """
    try:
        from bot.database import get_top_search_keywords  # type: ignore
    except ImportError:
        return DEFAULT_SUGGEST_KEYWORDS

    try:
        result = await get_top_search_keywords(limit=8)
    except Exception as e:
        logger.debug("get_top_search_keywords 调用失败，回退默认词: %s", e)
        return DEFAULT_SUGGEST_KEYWORDS

    keywords: list[str] = []
    for item in result or []:
        if isinstance(item, str):
            keywords.append(item)
        elif isinstance(item, dict):
            kw = item.get("keyword") or item.get("query") or item.get("word")
            if kw:
                keywords.append(str(kw))
    return keywords or DEFAULT_SUGGEST_KEYWORDS


async def _send_no_result(message: types.Message, unrecognized: list[str]) -> None:
    """搜索 0 结果：推荐关键词键盘"""
    keywords = await _resolve_suggestion_keywords()
    hint = ""
    if unrecognized:
        hint = (
            "\n\n以下关键词未识别为标签/地区/价格，已忽略：\n"
            + " / ".join(unrecognized)
        )
    await message.answer(
        f"🔍 未找到匹配的老师{hint}\n\n可以试试这些关键词：",
        reply_markup=search_suggestion_kb(keywords),
    )


def _sort_search_results(teachers: list[dict], today_str: str) -> list[dict]:
    """对搜索命中的老师按 Phase 3 统一规则排序（Python 层，避免再查 DB）

    仅使用 teachers 表自带字段（不计算 fav_count / signed_in_today，
    搜索是即时操作，简化即可）：
        effective_featured DESC, sort_weight DESC, hot_score DESC, created_at ASC
    """
    def key(t: dict):
        eff = is_effective_featured(t, today_str)
        return (
            0 if eff else 1,
            -(t.get("sort_weight") or 0),
            -(t.get("hot_score") or 0),
            t.get("created_at") or "",
        )
    return sorted(teachers, key=key)


async def _send_list(message: types.Message, teachers: list[dict]) -> None:
    """搜索命中多位老师：列表按钮（每个 → teacher:view 详情页）

    Phase 3：按统一排序规则展示；有效推荐老师名称前加 🔥 标识。
    """
    today = _today_str()
    sorted_teachers = _sort_search_results(teachers, today)

    def _label(t: dict) -> str:
        prefix = "🔥 " if is_effective_featured(t, today) else ""
        return f"{prefix}{t['display_name']} · {t['region']} · {t['price']}"

    text = (
        f"🔍 找到 {len(sorted_teachers)} 位老师\n\n"
        "点击老师查看详情。"
    )
    kb = teacher_detail_list_kb(
        sorted_teachers,
        per_row=1,
        label_fn=_label,
    )
    await message.answer(text, reply_markup=kb)


async def _record_search_tags(user_id: int, tokens: list[str]) -> None:
    """Phase 6.1：把每个搜索 token 沉淀为用户画像标签 + 搜索型用户角色画像

    异常静默吞（标签写入不能阻断搜索结果展示）。
    """
    try:
        for tok in tokens:
            await add_user_tag(user_id, tok, score_delta=1, source="search")
        await add_user_tag(user_id, "搜索型用户", score_delta=1, source="search")
    except Exception:
        pass


async def _safe_log_search_event(
    user_id: int,
    raw_query: str,
    tokens: list[str],
    result_count: int,
) -> None:
    """Phase 7.3：把搜索事件落到 user_events（event_type='search'）

    供"搜索历史"复用。raw_query 保留原始输入用于回放；
    log_user_event 缺失 / 异常时静默跳过，不影响搜索主流程。
    """
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(
            user_id,
            "search",
            {
                "raw": raw_query,
                "tokens": tokens,
                "result_count": result_count,
            },
        )
    except Exception as e:
        logger.debug("log_user_event('search') 失败 user=%s: %s", user_id, e)


async def _execute_search(
    user_id: int,
    raw_query: str,
    target_message: types.Message,
) -> None:
    """共享的搜索执行逻辑

    用于：
    - FSM 收到用户文字时（on_search_query）
    - 推荐关键词按钮回调（cb_suggest_keyword）

    所有结果通过 target_message.answer 发送新消息。
    """
    raw = (raw_query or "").strip()
    if not raw:
        await target_message.answer(
            "请输入有效的关键词",
            reply_markup=search_cancel_kb(),
        )
        return

    # 1. 艺名精确匹配 → 详情页
    teacher = await get_teacher_by_name(raw)
    if teacher:
        # Phase 6.1：艺名搜索也记一个搜索型用户标签
        await _record_search_tags(user_id, [])
        # Phase 7.3：搜索事件落库（供搜索历史复用）
        await _safe_log_search_event(user_id, raw, [], 1)
        await send_teacher_detail_message(
            target_message, user_id, teacher, record_view=True,
        )
        return

    # 2. 组合搜索（智能 AND）
    tokens = _split_tokens(raw)
    if not tokens:
        await target_message.answer(
            "请输入有效的关键词",
            reply_markup=search_cancel_kb(),
        )
        return

    # Phase 6.1：搜索 token → 用户画像标签（仅私聊场景，已在调用方过滤）
    await _record_search_tags(user_id, tokens)

    teachers, unrecognized = await search_teachers_smart_and(tokens)

    # Phase 7.3：搜索事件落库（供搜索历史复用）
    await _safe_log_search_event(user_id, raw, tokens, len(teachers))

    if not teachers:
        await _send_no_result(target_message, unrecognized)
        return

    if len(teachers) == 1:
        await send_teacher_detail_message(
            target_message, user_id, teachers[0], record_view=True,
        )
    else:
        await _send_list(target_message, teachers)

    if unrecognized:
        await target_message.answer(
            "⚠️ 以下关键词未识别为标签/地区/价格，已忽略：\n"
            + " / ".join(unrecognized),
        )


# ============ FSM 状态下退出 / 输入处理 ============


@router.message(SearchStates.waiting_query, Command("cancel"))
async def cmd_cancel_search(message: types.Message, state: FSMContext):
    """搜索状态下 /cancel 退出，回到主菜单"""
    if message.chat.type != "private":
        return
    await state.clear()
    await message.answer("🔙 已退出搜索", reply_markup=user_main_menu_kb())


@router.message(SearchStates.waiting_query, F.text)
async def on_search_query(message: types.Message, state: FSMContext):
    """接收用户的搜索关键词

    状态保持不清除，用户可在收到结果后继续输入下一次查询。
    """
    if message.chat.type != "private":
        return

    user_id = message.from_user.id
    await _execute_search(user_id, message.text or "", message)

    # 状态保持，提示可继续
    await message.answer(
        "继续输入下一个关键词，或点击下方按钮退出。",
        reply_markup=search_cancel_kb(),
    )


# ============ 搜索失败推荐按钮 callbacks（Phase 2 §四） ============


@router.callback_query(F.data == "search:suggest:today")
async def cb_suggest_today(callback: types.CallbackQuery):
    """推荐：📚 今日开课老师"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    today = _today_str()
    teachers = await get_checked_in_teachers(today)
    if not teachers:
        await callback.message.edit_text(
            f"📚 今日开课老师 · {today}\n\n今日暂无老师开课。",
            reply_markup=suggestion_result_back_kb(),
        )
        await callback.answer()
        return

    text = (
        f"📚 今日开课老师 · {today}（{len(teachers)} 位）\n\n"
        "点击老师查看详情。"
    )
    kb = teacher_detail_list_kb(
        teachers,
        per_row=2,
        label_fn=lambda t: t.get("button_text") or t["display_name"],
        extra_back_buttons=[
            [
                types.InlineKeyboardButton(text="🔙 返回搜索", callback_data="user:search"),
                types.InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main"),
            ],
        ],
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "search:suggest:hot")
async def cb_suggest_hot(callback: types.CallbackQuery):
    """推荐：🔥 热门老师（按收藏数 TOP）

    依赖第一阶段（或本阶段补充）的 get_top_favorited_teachers helper。
    若未实现 / 无数据，则提示。
    """
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    try:
        from bot.database import get_top_favorited_teachers  # type: ignore
    except ImportError:
        await callback.message.edit_text(
            "🔥 热门老师\n\n热门老师功能暂未生成数据。",
            reply_markup=suggestion_result_back_kb(),
        )
        await callback.answer()
        return

    try:
        teachers = await get_top_favorited_teachers(limit=10)
    except Exception as e:
        logger.warning("get_top_favorited_teachers 调用失败: %s", e)
        teachers = []

    if not teachers:
        await callback.message.edit_text(
            "🔥 热门老师\n\n热门老师功能暂未生成数据。",
            reply_markup=suggestion_result_back_kb(),
        )
        await callback.answer()
        return

    text = (
        f"🔥 热门老师（按收藏数排序，TOP {len(teachers)}）\n\n"
        "点击老师查看详情。"
    )
    kb = teacher_detail_list_kb(
        teachers,
        per_row=1,
        label_fn=lambda t: (
            f"{t['display_name']} · {t['region']} · ⭐ {t.get('fav_count', 0)}"
        ),
        extra_back_buttons=[
            [
                types.InlineKeyboardButton(text="🔙 返回搜索", callback_data="user:search"),
                types.InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main"),
            ],
        ],
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("search:suggest:"))
async def cb_suggest_keyword(callback: types.CallbackQuery):
    """推荐关键词按钮：用该关键词执行一次搜索

    today / hot 由更具体的 == 路由优先匹配，到这里时一定是关键词。
    """
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    keyword = callback.data[len("search:suggest:"):]
    if not keyword or keyword in ("today", "hot"):
        # 兜底：不该到这里
        await callback.answer()
        return

    await callback.answer(f"🔍 {keyword}")
    await _execute_search(callback.from_user.id, keyword, callback.message)

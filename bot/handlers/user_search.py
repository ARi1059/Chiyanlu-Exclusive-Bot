"""私聊搜索 FSM handler（v2 §2.4 F4 智能 AND 搜索）

处理 SearchStates.waiting_query 状态下用户的文本输入:
    1. 艺名精确命中 → 返回老师卡片（独立路径，不进入组合搜索）
    2. 否则按空格 / 逗号拆分 → 智能 AND 搜索 → 卡片(1 位) / 列表(多位) / 兜底文案(0 位)

仅响应私聊消息，避免群组内被误触发。
状态在每次搜索后保持，用户可连续搜索；通过 /cancel 或菜单按钮退出。
"""

import re

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.database import (
    get_teacher_by_name,
    is_favorited,
    search_teachers_smart_and,
)
from bot.keyboards.user_kb import user_main_menu_kb, search_cancel_kb
from bot.states.user_states import SearchStates
from bot.utils.teacher_render import send_teacher_card, send_teacher_list

router = Router(name="user_search")


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


@router.message(SearchStates.waiting_query, Command("cancel"))
async def cmd_cancel_search(message: types.Message, state: FSMContext):
    """搜索状态下 /cancel 退出，回到主菜单"""
    if message.chat.type != "private":
        return
    await state.clear()
    await message.answer(
        "🔙 已退出搜索",
        reply_markup=user_main_menu_kb(),
    )


@router.message(SearchStates.waiting_query, F.text)
async def on_search_query(message: types.Message, state: FSMContext):
    """接收用户的搜索关键词

    状态保持不清除，用户可在收到结果后继续输入下一次查询。
    """
    if message.chat.type != "private":
        return

    raw = message.text.strip()
    if not raw:
        await message.reply("请输入有效的关键词", reply_markup=search_cancel_kb())
        return

    user_id = message.from_user.id

    # 1. 艺名精确匹配（独立路径，v2 §2.4.3）
    teacher = await get_teacher_by_name(raw)
    if teacher:
        fav_state = await is_favorited(user_id, teacher["user_id"])
        await send_teacher_card(message, teacher, is_group=False, is_favorited=fav_state)
        # 状态保持，提示可继续
        await message.answer(
            "继续输入下一个关键词，或点击下方按钮退出。",
            reply_markup=search_cancel_kb(),
        )
        return

    # 2. 组合搜索（智能 AND）
    tokens = _split_tokens(raw)
    if not tokens:
        await message.reply("请输入有效的关键词", reply_markup=search_cancel_kb())
        return

    teachers, unrecognized = await search_teachers_smart_and(tokens)

    if not teachers:
        hint = ""
        if unrecognized:
            hint = f"\n\n以下关键词未识别为标签/地区/价格，已忽略：\n{' / '.join(unrecognized)}"
        await message.answer(
            f"未找到匹配的老师{hint}\n\n试试其他关键词，或点击下方按钮退出。",
            reply_markup=search_cancel_kb(),
        )
        return

    # 命中：单人 → 卡片（带收藏状态），多人 → 列表（不带个体收藏按钮）
    if len(teachers) == 1:
        fav_state = await is_favorited(user_id, teachers[0]["user_id"])
        await send_teacher_card(
            message, teachers[0], is_group=False, is_favorited=fav_state
        )
    else:
        await send_teacher_list(message, teachers)

    # 如果有未识别 token，附加提示
    if unrecognized:
        await message.answer(
            f"⚠️ 以下关键词未识别为标签/地区/价格，已忽略：\n{' / '.join(unrecognized)}",
        )

    # 状态保持，提示可继续
    await message.answer(
        "继续输入下一个关键词，或点击下方按钮退出。",
        reply_markup=search_cancel_kb(),
    )

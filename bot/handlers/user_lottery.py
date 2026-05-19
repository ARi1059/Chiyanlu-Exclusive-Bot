"""用户「🎁 抽奖中心」入口（UX-6.1）。

callback 命名空间：
    user:lottery            抽奖中心二级菜单（含 3 tab 计数）
    user:lottery:active     Tab 1 进行中可参与（list_lotteries_by_status('active')）
    user:lottery:joined     Tab 2 我已参与（active/scheduled 状态的 entries）
    user:lottery:drawn      Tab 3 已开奖记录（drawn 状态的 entries，含中奖 ✅ / 未中 ⚪）

设计：
    - 纯只读：不动 entry / draw / publish 业务逻辑
    - 复用既有 DB 查询：list_lotteries_by_status / list_user_lottery_entries（新增）
    - 复用 UX-4.5 的 build_lottery_channel_url 构造频道帖跳转 URL
    - 不引入 schema 迁移；list_user_lottery_entries 仅 JOIN 既有表
"""
from __future__ import annotations

import logging

from aiogram import F, Router, types

from bot.database import (
    count_lotteries_by_status,
    count_user_lottery_entries,
    get_lottery_entry,
    list_lotteries_by_status,
    list_user_lottery_entries,
)
from bot.keyboards.user_kb import user_lottery_back_kb, user_lottery_menu_kb

logger = logging.getLogger(__name__)

router = Router(name="user_lottery")


_MAX_LIST_PER_TAB = 10


# ============ 二级菜单入口 ============


@router.callback_query(F.data == "user:lottery")
async def cb_user_lottery(callback: types.CallbackQuery):
    """[🎁 抽奖中心] 二级菜单（含 3 tab 计数）。"""
    user_id = callback.from_user.id

    # 3 个 tab 各自计数（容错：单项失败不阻塞主页渲染）
    try:
        active_count = await count_lotteries_by_status("active")
    except Exception as e:
        logger.warning("[UX-6.1] active count failed: %s", e)
        active_count = 0
    try:
        joined_count = await count_user_lottery_entries(
            user_id, lottery_statuses=["active", "scheduled"],
        )
    except Exception as e:
        logger.warning("[UX-6.1] joined count failed: %s", e)
        joined_count = 0
    try:
        drawn_count = await count_user_lottery_entries(
            user_id, lottery_statuses=["drawn"],
        )
    except Exception as e:
        logger.warning("[UX-6.1] drawn count failed: %s", e)
        drawn_count = 0

    lines = [
        "🎁 抽奖中心",
        "━━━━━━━━━━━━━━━",
        f"进行中可参与：{active_count} 场",
        f"我已参与：{joined_count} 场",
        f"已开奖记录：{drawn_count} 次",
        "━━━━━━━━━━━━━━━",
        "",
        "请选择查看：",
    ]
    text = "\n".join(lines)
    kb = user_lottery_menu_kb(
        active_count=active_count,
        joined_count=joined_count,
        drawn_count=drawn_count,
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


# ============ Tab 1：进行中可参与 ============


@router.callback_query(F.data == "user:lottery:active")
async def cb_user_lottery_active(callback: types.CallbackQuery):
    """Tab 1：进行中可参与的抽奖列表。"""
    user_id = callback.from_user.id
    try:
        lotteries = await list_lotteries_by_status(
            "active", limit=_MAX_LIST_PER_TAB,
        )
    except Exception as e:
        logger.warning("[UX-6.1] list_active failed: %s", e)
        lotteries = []

    if not lotteries:
        text = (
            "🎲 进行中可参与\n"
            "━━━━━━━━━━━━━━━\n"
            "（当前暂无可参与的抽奖）\n\n"
            "可关注主频道获取下一场活动通知。"
        )
        try:
            await callback.message.edit_text(text, reply_markup=user_lottery_back_kb())
        except Exception:
            await callback.message.answer(text, reply_markup=user_lottery_back_kb())
        await callback.answer()
        return

    lines = ["🎲 进行中可参与", "━━━━━━━━━━━━━━━"]
    for idx, lot in enumerate(lotteries, start=1):
        # 检查用户是否已参与
        try:
            entered = await get_lottery_entry(int(lot["id"]), user_id)
        except Exception:
            entered = None
        joined_tag = "✅ 已参与" if entered else "⏳ 未参与"
        cost = int(lot.get("entry_cost_points") or 0)
        cost_line = f" · 需 {cost} 积分" if cost > 0 else " · 免费"
        lines.append(
            f"{idx}. 「{lot.get('name', '?')}」{cost_line}\n"
            f"   开奖：{lot.get('draw_at', '?')} · {joined_tag}"
        )
    lines.append("")
    lines.append("💡 点击频道帖按钮参与（口令抽奖在私聊发送口令）。")

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=user_lottery_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=user_lottery_back_kb())
    await callback.answer()


# ============ Tab 2：我已参与 ============


@router.callback_query(F.data == "user:lottery:joined")
async def cb_user_lottery_joined(callback: types.CallbackQuery):
    """Tab 2：用户已参与 + lottery 仍在 active / scheduled 状态的抽奖列表。"""
    user_id = callback.from_user.id
    try:
        rows = await list_user_lottery_entries(
            user_id,
            lottery_statuses=["active", "scheduled"],
            limit=_MAX_LIST_PER_TAB,
        )
    except Exception as e:
        logger.warning("[UX-6.1] list_joined failed: %s", e)
        rows = []

    if not rows:
        text = (
            "📋 我已参与\n"
            "━━━━━━━━━━━━━━━\n"
            "（你还没有参与任何进行中的抽奖）\n\n"
            "去 [进行中可参与] 看看有什么活动吧。"
        )
        try:
            await callback.message.edit_text(text, reply_markup=user_lottery_back_kb())
        except Exception:
            await callback.message.answer(text, reply_markup=user_lottery_back_kb())
        await callback.answer()
        return

    lines = ["📋 我已参与（进行中）", "━━━━━━━━━━━━━━━"]
    for idx, r in enumerate(rows, start=1):
        status_zh = {
            "active":    "进行中",
            "scheduled": "未开始",
        }.get(r.get("lottery_status") or "", r.get("lottery_status") or "?")
        lines.append(
            f"{idx}. 「{r.get('lottery_name', '?')}」\n"
            f"   开奖：{r.get('draw_at', '?')} · 状态：{status_zh}"
        )
    lines.append("")
    lines.append("💡 抽奖会在开奖后私聊通知中奖者；未中奖一般无通知（运营可配置）。")

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=user_lottery_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=user_lottery_back_kb())
    await callback.answer()


# ============ Tab 3：已开奖记录 ============


@router.callback_query(F.data == "user:lottery:drawn")
async def cb_user_lottery_drawn(callback: types.CallbackQuery):
    """Tab 3：用户参与过 + lottery 已开奖（drawn）的记录，标注是否中奖。"""
    user_id = callback.from_user.id
    try:
        rows = await list_user_lottery_entries(
            user_id,
            lottery_statuses=["drawn"],
            limit=_MAX_LIST_PER_TAB,
        )
    except Exception as e:
        logger.warning("[UX-6.1] list_drawn failed: %s", e)
        rows = []

    if not rows:
        text = (
            "🏆 已开奖记录\n"
            "━━━━━━━━━━━━━━━\n"
            "（暂无已开奖的参与记录）"
        )
        try:
            await callback.message.edit_text(text, reply_markup=user_lottery_back_kb())
        except Exception:
            await callback.message.answer(text, reply_markup=user_lottery_back_kb())
        await callback.answer()
        return

    won_total = sum(1 for r in rows if int(r.get("won") or 0) == 1)
    lines = [
        "🏆 已开奖记录",
        f"中奖 {won_total} 次 / 共 {len(rows)} 次参与",
        "━━━━━━━━━━━━━━━",
    ]
    for idx, r in enumerate(rows, start=1):
        won_tag = "✅ 中奖" if int(r.get("won") or 0) == 1 else "⚪ 未中"
        lines.append(
            f"{idx}. 「{r.get('lottery_name', '?')}」 · {won_tag}\n"
            f"   开奖：{r.get('draw_at', '?')}"
        )
    lines.append("")
    lines.append("💡 中奖者已通过 bot 私聊通知；如有疑问可联系超管。")

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=user_lottery_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=user_lottery_back_kb())
    await callback.answer()

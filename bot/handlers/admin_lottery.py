"""超管「抽奖管理」工具（Phase L.1）

入口：主面板 [🎲 抽奖管理]（仅 is_super=True 可见）

callback 命名空间：admin:lottery:*
  - admin:lottery                    → 子菜单
  - admin:lottery:list               → 抽奖列表
  - admin:lottery:item:<id>          → 抽奖详情
  - admin:lottery:cancel:<id>        → 取消草稿二次确认
  - admin:lottery:cancel_ok:<id>     → 实际取消

  本 phase 仅 draft 状态可取消（active 取消留给 L.4）。
  创建 FSM 见 admin_lottery 创建模块（L.1.2）。
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    LOTTERY_STATUSES,
    cancel_lottery,
    count_lotteries_by_status,
    count_lottery_entries,
    get_lottery,
    is_super_admin,
    list_lotteries_by_status,
    log_admin_audit,
)
from bot.keyboards.admin_kb import (
    admin_lottery_cancel_confirm_kb,
    admin_lottery_detail_kb,
    admin_lottery_list_kb,
    admin_lottery_menu_kb,
)

logger = logging.getLogger(__name__)

router = Router(name="admin_lottery")


def _super_admin_required(func):
    """仅 super_admin 可访问；普通 admin / 用户 alert 拒绝"""
    async def wrapper(event, *args, **kwargs):
        if isinstance(event, types.CallbackQuery):
            uid = event.from_user.id
            denied = lambda: event.answer("此操作需超级管理员权限", show_alert=True)
        elif isinstance(event, types.Message):
            uid = event.from_user.id
            denied = lambda: event.reply("此操作需超级管理员权限")
        else:
            return
        if uid != config.super_admin_id and not await is_super_admin(uid):
            await denied()
            return
        return await func(event, *args, **kwargs)
    return wrapper


# ============ 子菜单 ============

@router.callback_query(F.data == "admin:lottery")
@_super_admin_required
async def cb_admin_lottery(callback: types.CallbackQuery, state: FSMContext):
    """[🎲 抽奖管理] 主菜单"""
    await state.clear()
    n = await count_lotteries_by_status()
    text = (
        "🎲 抽奖管理\n\n"
        "- ➕ 创建新抽奖：完整 10 步流程录入草稿\n"
        "- 📋 抽奖列表：按状态查看所有抽奖（草稿 / 已计划 / 进行中 / 已开奖 / 已取消）\n\n"
        f"当前共 {n} 条抽奖记录。"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_lottery_menu_kb(n))
    except Exception:
        await callback.message.answer(text, reply_markup=admin_lottery_menu_kb(n))
    await callback.answer()


# ============ 列表 ============

@router.callback_query(F.data == "admin:lottery:list")
@_super_admin_required
async def cb_admin_lottery_list(callback: types.CallbackQuery, state: FSMContext):
    """[📋 抽奖列表] 展示最近 30 条 + 按状态分组统计"""
    await state.clear()
    items = await list_lotteries_by_status(status=None, limit=30)
    if not items:
        text = "📋 抽奖列表（共 0 条）\n\n暂无抽奖记录。点 [➕ 创建新抽奖] 开始。"
        try:
            await callback.message.edit_text(text, reply_markup=admin_lottery_menu_kb(0))
        except Exception:
            pass
        await callback.answer()
        return

    # 状态分组统计
    counts: dict[str, int] = {}
    for it in items:
        s = it.get("status", "?")
        counts[s] = counts.get(s, 0) + 1
    summary_parts: list[str] = []
    label_map = {s["key"]: s["label"] for s in LOTTERY_STATUSES}
    for s in LOTTERY_STATUSES:
        c = counts.get(s["key"], 0)
        if c:
            summary_parts.append(f"{label_map[s['key']]} {c}")
    summary = "  ".join(summary_parts) if summary_parts else "—"

    text = (
        f"📋 抽奖列表（共 {len(items)} 条）\n\n"
        f"{summary}\n\n"
        "点击下方按钮查看详情。"
    )
    await callback.message.edit_text(text, reply_markup=admin_lottery_list_kb(items))
    await callback.answer()


# ============ 详情 ============

@router.callback_query(F.data.startswith("admin:lottery:item:"))
@_super_admin_required
async def cb_admin_lottery_item(callback: types.CallbackQuery, state: FSMContext):
    """抽奖详情页（只读）"""
    await state.clear()
    try:
        lid = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    lottery = await get_lottery(lid)
    if not lottery:
        await callback.answer("该抽奖不存在", show_alert=True)
        return

    text = await _render_lottery_detail(lottery)
    try:
        await callback.message.edit_text(text, reply_markup=admin_lottery_detail_kb(lottery))
    except Exception:
        await callback.message.answer(text, reply_markup=admin_lottery_detail_kb(lottery))
    await callback.answer()


async def _render_lottery_detail(lottery: dict) -> str:
    """渲染抽奖详情文字（spec §3.3 风格，含状态 / 时间 / 参与人数）"""
    label_map = {s["key"]: s["label"] for s in LOTTERY_STATUSES}
    status_label = label_map.get(lottery.get("status", ""), lottery.get("status", "?"))

    entry_method = lottery.get("entry_method") or "?"
    method_label = "🎲 按键抽奖" if entry_method == "button" else "🔑 口令抽奖"

    n_entries = await count_lottery_entries(lottery["id"])

    lines = [
        f"🎲 抽奖 #{lottery['id']}",
        "━━━━━━━━━━━━━━━",
        f"📌 状态：{status_label}",
        f"🏷 名称：{lottery.get('name', '?')}",
        f"📋 规则：{lottery.get('description', '?')}",
        f"🎁 奖品：{lottery.get('prize_description', '?')}",
        f"🏆 中奖人数：{lottery.get('prize_count', '?')}",
        f"🎯 参与方式：{method_label}",
    ]
    if entry_method == "code" and lottery.get("entry_code"):
        lines.append(f"🔑 口令：{lottery['entry_code']}")
    chats = lottery.get("required_chat_ids") or []
    lines.append(f"📡 必关频道/群组：{len(chats)} 项")
    if chats:
        for cid in chats[:5]:
            lines.append(f"  · {cid}")
        if len(chats) > 5:
            lines.append(f"  · …（共 {len(chats)} 项）")
    lines.append(f"⏰ 发布时间：{lottery.get('publish_at', '?')}")
    lines.append(f"⏰ 开奖时间：{lottery.get('draw_at', '?')}")
    if lottery.get("published_at"):
        lines.append(f"✅ 已发布：{lottery['published_at']}")
    if lottery.get("drawn_at"):
        lines.append(f"🏆 已开奖：{lottery['drawn_at']}")
    if lottery.get("cover_file_id"):
        lines.append("🖼 已上传封面图")
    lines.append(f"👥 已参与：{n_entries} 人")
    lines.append(f"📝 创建者：uid {lottery.get('created_by', '?')}")
    lines.append(f"⏱ 创建时间：{lottery.get('created_at', '?')}")
    lines.append("━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ============ 取消草稿（仅 draft 状态）============

@router.callback_query(F.data.startswith("admin:lottery:cancel:"))
@_super_admin_required
async def cb_admin_lottery_cancel(callback: types.CallbackQuery, state: FSMContext):
    """[❌ 取消草稿] 二次确认"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        lid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    lottery = await get_lottery(lid)
    if not lottery:
        await callback.answer("该抽奖不存在", show_alert=True)
        return
    if lottery.get("status") != "draft":
        await callback.answer(
            f"当前状态 {lottery.get('status')} 不可在本 phase 取消（active 取消见 L.4）",
            show_alert=True,
        )
        return
    await callback.message.edit_text(
        f"⚠️ 确认取消抽奖 #{lid}「{lottery.get('name', '')}」？\n\n"
        "取消后状态变为 cancelled，无法恢复（但记录保留）。",
        reply_markup=admin_lottery_cancel_confirm_kb(lid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:lottery:cancel_ok:"))
@_super_admin_required
async def cb_admin_lottery_cancel_ok(callback: types.CallbackQuery, state: FSMContext):
    """实际取消"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        lid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    ok = await cancel_lottery(lid)
    if not ok:
        await callback.answer("⚠️ 取消失败（可能已是终态）", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="lottery_cancel",
        target_type="lottery",
        target_id=str(lid),
        detail={},
    )
    await callback.answer(f"✅ 已取消 #{lid}")
    # 回到列表
    callback.data = "admin:lottery:list"
    await cb_admin_lottery_list(callback, state)

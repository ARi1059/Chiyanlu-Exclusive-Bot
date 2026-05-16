"""超管「积分管理」工具（Phase P.3）

入口：主面板 [💰 积分管理]（仅 is_super=True 可见）

callback 命名空间：admin:points:*
  - admin:points          → 子菜单
  - admin:points:query    → 进入查询 FSM
  - admin:points:grant    → 进入手动加扣分 FSM
  - admin:points:overview → 总览（TOP 10）

子菜单内每个动作可走单独子页 + 二次确认；所有动作 audit log。
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    count_user_point_transactions,
    find_user_by_username,
    get_user,
    get_user_points_summary,
    is_super_admin,
    list_user_point_transactions,
    log_admin_audit,
)
from bot.keyboards.admin_kb import (
    admin_points_back_kb,
    admin_points_cancel_kb,
    admin_points_menu_kb,
)
from bot.states.teacher_states import AdminPointsQueryStates
from bot.utils.user_points_render import (
    fetch_teacher_names_for_txs,
    format_points_detail_block,
)

logger = logging.getLogger(__name__)

router = Router(name="admin_points")


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


# ============ 子菜单入口 ============

@router.callback_query(F.data == "admin:points")
@_super_admin_required
async def cb_admin_points(callback: types.CallbackQuery, state: FSMContext):
    """[💰 积分管理] 主菜单"""
    await state.clear()
    text = (
        "💰 积分管理\n\n"
        "- 🔍 查询用户积分：输入 user_id 或 @username 查看明细\n"
        "- ➕ 手动加分：4 步流程（用户 → 数值 → 原因 → 确认）\n"
        "- 📊 积分总览：持币用户数 / 累计加分 / TOP 10"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_points_menu_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=admin_points_menu_kb())
    await callback.answer()


# ============ 查询用户积分 ============

@router.callback_query(F.data == "admin:points:query")
@_super_admin_required
async def cb_admin_points_query(callback: types.CallbackQuery, state: FSMContext):
    """[🔍 查询用户积分] 进入 FSM"""
    await state.set_state(AdminPointsQueryStates.waiting_input)
    await callback.message.edit_text(
        "🔍 查询用户积分\n\n"
        "请输入用户的 Telegram 数字 ID 或 @username。\n"
        "发 /cancel 取消（回积分管理）。",
        reply_markup=admin_points_cancel_kb(),
    )
    await callback.answer()


@router.message(F.text == "/cancel", AdminPointsQueryStates.waiting_input)
@_super_admin_required
async def cmd_cancel_query(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("已取消。", reply_markup=admin_points_menu_kb())


@router.message(AdminPointsQueryStates.waiting_input, F.text)
@_super_admin_required
async def on_query_input(message: types.Message, state: FSMContext):
    """收 user_id / @username → 查询 + 展示"""
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("已取消。", reply_markup=admin_points_menu_kb())
        return

    user_row = await _resolve_user(text)
    if user_row is None:
        await message.reply(
            "❌ 未找到该用户。请确认 user_id 或 @username 正确，或发 /cancel 取消。"
        )
        return

    await state.clear()
    user_id = int(user_row["user_id"])
    await log_admin_audit(
        admin_id=message.from_user.id,
        action="points_query",
        target_type="user",
        target_id=str(user_id),
        detail={"input": text},
    )
    body = await _render_user_points_view(user_row)
    await message.answer(body, reply_markup=admin_points_back_kb())


async def _resolve_user(input_text: str) -> Optional[dict]:
    """user_id 或 @username 解析 → users row（None 表示找不到）"""
    if not input_text:
        return None
    s = input_text.strip()
    if not s:
        return None
    # 数字 id
    if s.lstrip("-").isdigit():
        try:
            return await get_user(int(s))
        except ValueError:
            return None
    # @username
    return await find_user_by_username(s)


def _anon_uid(uid: int) -> str:
    s = str(uid)
    if len(s) <= 4:
        return "****"
    return "*" * (len(s) - 4) + s[-4:]


async def _render_user_points_view(user_row: dict) -> str:
    """渲染单个用户的积分明细页（含最近 10 条）"""
    user_id = int(user_row["user_id"])
    username = user_row.get("username")
    first_name = user_row.get("first_name") or ""
    summary = await get_user_points_summary(user_id)
    txs = await list_user_point_transactions(user_id, limit=10, offset=0)
    teachers_map, review_teacher_map = await fetch_teacher_names_for_txs(txs)
    detail_block = (
        format_points_detail_block(txs, teachers_map, review_teacher_map)
        if txs else "（暂无积分记录）"
    )

    name_line = first_name or "(无姓名)"
    if username:
        name_line = f"{name_line} (@{username})"
    name_line = f"{name_line} · uid {user_id}"

    total_count = await count_user_point_transactions(user_id)
    n_recent = len(txs)
    detail_title = (
        f"📋 最近 {n_recent} 条（共 {total_count} 条）"
        if total_count > n_recent else
        f"📋 全部 {total_count} 条"
    )

    return (
        f"💰 用户积分查询\n\n"
        f"👤 {name_line}\n\n"
        f"当前余额：{summary['total']} 分\n"
        f"📈 累计获得：{summary['earned']} 分（{summary['tx_count']} 次交易）\n"
        f"📉 累计消耗：{summary['spent']} 分\n\n"
        f"{detail_title}\n"
        f"{detail_block}"
    )

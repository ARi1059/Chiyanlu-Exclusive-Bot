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
    add_point_transaction,
    count_user_point_transactions,
    count_users_with_points,
    find_user_by_username,
    get_top_points_users,
    get_user,
    get_user_points_summary,
    get_user_total_points,
    is_super_admin,
    list_user_point_transactions,
    log_admin_audit,
    POINT_GRANT_REASON_OPTIONS,
    POINT_PACKAGE_OPTIONS,
    sum_total_points_earned,
)
from bot.keyboards.admin_kb import (
    admin_points_back_kb,
    admin_points_cancel_kb,
    admin_points_grant_confirm_kb,
    admin_points_grant_minus_kb,
    admin_points_grant_reason_kb,
    admin_points_grant_value_kb,
    admin_points_menu_kb,
)
from bot.states.teacher_states import (
    AdminPointsGrantStates,
    AdminPointsQueryStates,
)
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


# ============ 手动加扣分 4 步 FSM ============

# 加分预设额外项（spec §3.2：+10 / +20）
_EXTRA_GRANT_VALUES: dict[str, dict] = {
    "p10": {"delta": 10, "label": "+10"},
    "p20": {"delta": 20, "label": "+20"},
}


def _build_pkg_lookup() -> dict[str, dict]:
    """合并 POINT_PACKAGE_OPTIONS (P/PP/包时/包夜/包天/不加分) + _EXTRA"""
    m: dict[str, dict] = {}
    for o in POINT_PACKAGE_OPTIONS:
        m[o["key"]] = {"delta": int(o["delta"]), "label": o["label"]}
    m.update(_EXTRA_GRANT_VALUES)
    return m


_PKG_LOOKUP = _build_pkg_lookup()
_REASON_LOOKUP = {o["key"]: o for o in POINT_GRANT_REASON_OPTIONS}


@router.callback_query(F.data == "admin:points:grant")
@_super_admin_required
async def cb_admin_points_grant(callback: types.CallbackQuery, state: FSMContext):
    """[➕ 手动加分] Step 1 入口"""
    await state.set_state(AdminPointsGrantStates.waiting_target)
    await state.set_data({})
    await callback.message.edit_text(
        "➕ 手动加分（Step 1/4）\n\n"
        "请输入目标用户的 Telegram 数字 ID 或 @username。\n"
        "/cancel 取消。",
        reply_markup=admin_points_cancel_kb(),
    )
    await callback.answer()


@router.message(F.text == "/cancel", AdminPointsGrantStates())
@_super_admin_required
async def cmd_cancel_grant(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("已取消。", reply_markup=admin_points_menu_kb())


@router.callback_query(F.data == "admin:points:grant_cancel")
@_super_admin_required
async def cb_grant_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("已取消。", reply_markup=admin_points_menu_kb())
    await callback.answer()


@router.message(AdminPointsGrantStates.waiting_target, F.text)
@_super_admin_required
async def on_grant_target(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_grant(message, state)
    user_row = await _resolve_user(text)
    if user_row is None:
        await message.reply(
            "❌ 未找到该用户。请确认 user_id 或 @username 正确，或 /cancel 取消。"
        )
        return
    user_id = int(user_row["user_id"])
    current = await get_user_total_points(user_id)
    await state.update_data(
        target_user_id=user_id,
        target_username=user_row.get("username"),
        target_first_name=user_row.get("first_name") or "",
        current_total=current,
    )
    await state.set_state(AdminPointsGrantStates.waiting_delta)

    name_line = (user_row.get("first_name") or "(无姓名)")
    if user_row.get("username"):
        name_line = f"{name_line} (@{user_row['username']})"
    await message.answer(
        f"➕ 手动加分（Step 2/4）\n\n"
        f"目标：{name_line}\n"
        f"uid：{user_id}\n"
        f"当前余额：{current} 分\n\n"
        "请选择加分值：",
        reply_markup=admin_points_grant_value_kb(),
    )


# ---- Step 2：选数值 ----

@router.callback_query(F.data.startswith("admin:points:grant_v:"))
@_super_admin_required
async def cb_grant_value_preset(callback: types.CallbackQuery, state: FSMContext):
    """加分预设：+1/+3/+5/+8/+10/+20"""
    key = callback.data.split(":")[3]
    pkg = _PKG_LOOKUP.get(key)
    if not pkg:
        await callback.answer("未知套餐", show_alert=True)
        return
    await state.update_data(delta=int(pkg["delta"]), package_label=pkg["label"])
    await _enter_reason_step(callback, state)


@router.callback_query(F.data == "admin:points:grant_minus")
@_super_admin_required
async def cb_grant_value_minus_entry(callback: types.CallbackQuery, state: FSMContext):
    """[➖ 扣分] 入口 → 显示扣分子页"""
    await callback.message.edit_text(
        "➖ 扣分（Step 2b/4）\n\n请选择扣分值：",
        reply_markup=admin_points_grant_minus_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:points:grant_back")
@_super_admin_required
async def cb_grant_value_back(callback: types.CallbackQuery, state: FSMContext):
    """扣分子页 [🔙 返回加分] → 回 Step 2 加分页"""
    data = await state.get_data()
    name_line = data.get("target_first_name") or "(无姓名)"
    if data.get("target_username"):
        name_line = f"{name_line} (@{data['target_username']})"
    await callback.message.edit_text(
        f"➕ 手动加分（Step 2/4）\n\n"
        f"目标：{name_line}\n"
        f"uid：{data.get('target_user_id')}\n"
        f"当前余额：{data.get('current_total', 0)} 分\n\n"
        "请选择加分值：",
        reply_markup=admin_points_grant_value_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:points:grant_m:"))
@_super_admin_required
async def cb_grant_value_minus_preset(callback: types.CallbackQuery, state: FSMContext):
    """扣分预设：-1/-3/-5/-10"""
    try:
        n = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    delta = -abs(n)
    await state.update_data(delta=delta, package_label=f"{delta}")
    await _enter_reason_step(callback, state)


@router.callback_query(F.data == "admin:points:grant_custom")
@_super_admin_required
async def cb_grant_value_custom(callback: types.CallbackQuery, state: FSMContext):
    """[💬 自定义] → FSM 等数字 -100~100"""
    await state.set_state(AdminPointsGrantStates.waiting_custom_delta)
    await callback.message.edit_text(
        "💬 自定义加分值（Step 2c/4）\n\n"
        "请回复一个 -100 至 100 之间的整数（含 0）。\n"
        "/cancel 取消。",
        reply_markup=admin_points_cancel_kb(),
    )
    await callback.answer()


@router.message(AdminPointsGrantStates.waiting_custom_delta, F.text)
@_super_admin_required
async def on_custom_delta(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_grant(message, state)
    try:
        delta = int(text)
    except ValueError:
        await message.reply("❌ 请输入整数（-100~100），或 /cancel 取消。")
        return
    if delta < -100 or delta > 100:
        await message.reply(f"❌ 范围 -100~100，当前 {delta}。")
        return
    await state.update_data(delta=delta, package_label=f"自定义 {'+' if delta > 0 else ''}{delta}")
    # 回到 reason 步骤需 callback 触发；这里用 message 驱动
    data = await state.get_data()
    await state.set_state(AdminPointsGrantStates.waiting_reason)
    await message.answer(
        _format_reason_prompt(data, delta),
        reply_markup=admin_points_grant_reason_kb(),
    )


def _format_reason_prompt(data: dict, delta: int) -> str:
    name_line = data.get("target_first_name") or "(无姓名)"
    if data.get("target_username"):
        name_line = f"{name_line} (@{data['target_username']})"
    pkg_label = data.get("package_label") or f"{delta:+d}"
    return (
        f"➕ 手动加分（Step 3/4）\n\n"
        f"目标：{name_line}\n"
        f"加分值：{pkg_label}（{delta:+d} 分）\n\n"
        "请选择加分原因："
    )


async def _enter_reason_step(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    delta = int(data.get("delta", 0))
    await state.set_state(AdminPointsGrantStates.waiting_reason)
    await callback.message.edit_text(
        _format_reason_prompt(data, delta),
        reply_markup=admin_points_grant_reason_kb(),
    )
    await callback.answer()


# ---- Step 3：选原因 ----

@router.callback_query(F.data.startswith("admin:points:grant_r:"))
@_super_admin_required
async def cb_grant_reason_preset(callback: types.CallbackQuery, state: FSMContext):
    """选预设原因 → 进确认页"""
    key = callback.data.split(":")[3]
    reason_meta = _REASON_LOOKUP.get(key)
    if not reason_meta:
        await callback.answer("未知原因", show_alert=True)
        return
    await state.update_data(
        reason_key=key,
        reason_db=reason_meta["reason"],
        reason_note=reason_meta["note"],
    )
    await _enter_confirm_step(callback, state)


@router.callback_query(F.data == "admin:points:grant_rcustom")
@_super_admin_required
async def cb_grant_reason_custom(callback: types.CallbackQuery, state: FSMContext):
    """[💬 自定义原因] → FSM 等文本"""
    await state.set_state(AdminPointsGrantStates.waiting_custom_reason)
    await callback.message.edit_text(
        "💬 自定义原因（Step 3c/4）\n\n"
        "请回复一段文字（≤ 100 字）作为加扣分原因。\n"
        "/cancel 取消。",
        reply_markup=admin_points_cancel_kb(),
    )
    await callback.answer()


@router.message(AdminPointsGrantStates.waiting_custom_reason, F.text)
@_super_admin_required
async def on_custom_reason(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_grant(message, state)
    if not text:
        await message.reply("❌ 请输入非空原因，或 /cancel 取消。")
        return
    if len(text) > 100:
        await message.reply(f"❌ 原因过长（≤ 100 字），当前 {len(text)} 字。")
        return
    # 自定义原因：根据 delta 正负决定 reason db 值
    data = await state.get_data()
    delta = int(data.get("delta", 0))
    reason_db = "admin_grant" if delta >= 0 else "admin_revoke"
    await state.update_data(reason_key="custom", reason_db=reason_db, reason_note=text)
    # 渲染确认页（message 驱动）
    await state.set_state(AdminPointsGrantStates.waiting_confirm)
    await message.answer(
        _format_confirm_text(await state.get_data()),
        reply_markup=admin_points_grant_confirm_kb(),
    )


async def _enter_confirm_step(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminPointsGrantStates.waiting_confirm)
    await callback.message.edit_text(
        _format_confirm_text(await state.get_data()),
        reply_markup=admin_points_grant_confirm_kb(),
    )
    await callback.answer()


def _format_confirm_text(data: dict) -> str:
    """Step 4 确认页（spec §3.2）"""
    name_line = data.get("target_first_name") or "(无姓名)"
    if data.get("target_username"):
        name_line = f"{name_line} (@{data['target_username']})"
    delta = int(data.get("delta", 0))
    current = int(data.get("current_total", 0))
    new_total = current + delta
    pkg_label = data.get("package_label") or f"{delta:+d}"
    note = data.get("reason_note") or "-"
    return (
        f"➕ 手动加分确认（Step 4/4）\n\n"
        f"👤 目标：{name_line}\n"
        f"uid：{data.get('target_user_id')}\n\n"
        f"加分值：{pkg_label}（{delta:+d} 分）\n"
        f"原因：{note}\n\n"
        f"💰 余额变化：{current} → {new_total} 分\n\n"
        "确认后立即执行；可在 [📋 数据看板] 操作日志查到本次审计记录。"
    )


# ---- Step 4：确认提交 ----

@router.callback_query(F.data == "admin:points:grant_ok")
@_super_admin_required
async def cb_grant_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    target = data.get("target_user_id")
    delta = data.get("delta")
    reason_db = data.get("reason_db")
    note = data.get("reason_note")
    if target is None or delta is None or not reason_db:
        await callback.answer("状态丢失，请重新进入", show_alert=True)
        await state.clear()
        try:
            await callback.message.edit_text("已取消（状态丢失）。", reply_markup=admin_points_menu_kb())
        except Exception:
            pass
        return

    tx_id = await add_point_transaction(
        int(target), int(delta), reason_db,
        operator_id=callback.from_user.id,
        note=note,
    )
    if not tx_id:
        await callback.answer("写入失败，请检查", show_alert=True)
        return

    new_total = await get_user_total_points(int(target))
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="points_grant",
        target_type="user",
        target_id=str(target),
        detail={
            "delta": int(delta),
            "reason": reason_db,
            "note": note,
            "new_total": new_total,
            "tx_id": tx_id,
        },
    )
    await state.clear()
    await callback.message.edit_text(
        f"✅ 已 {'加' if int(delta) >= 0 else '扣'} {abs(int(delta))} 分\n\n"
        f"👤 uid {target}\n"
        f"💰 新余额：{new_total} 分\n"
        f"原因：{note}",
        reply_markup=admin_points_back_kb(),
    )
    await callback.answer(f"完成（{int(delta):+d}）")


# ============ 积分总览 TOP 10 ============

@router.callback_query(F.data == "admin:points:overview")
@_super_admin_required
async def cb_admin_points_overview(callback: types.CallbackQuery, state: FSMContext):
    """[📊 积分总览]：总用户数 / 总加分 / TOP 10（spec §3.2）"""
    await state.clear()
    total_users = await count_users_with_points()
    total_earned = await sum_total_points_earned()
    top_users = await get_top_points_users(limit=10)

    lines = [
        "📊 积分总览",
        "",
        f"💼 总用户数（持币）：{total_users}",
        f"💰 总加分（累计）：{total_earned} 分",
        "",
        f"🏆 TOP {len(top_users)} 用户：" if top_users else "🏆 TOP 用户：（暂无）",
    ]
    if top_users:
        for i, u in enumerate(top_users, start=1):
            uid = int(u["user_id"])
            name = (u.get("first_name") or "").strip()
            username = (u.get("username") or "").strip()
            pts = int(u.get("total_points") or 0)
            tag_parts = []
            if name:
                tag_parts.append(name)
            if username:
                tag_parts.append(f"@{username}")
            tag_parts.append(f"uid {uid}")
            tag = " · ".join(tag_parts)
            lines.append(f"{i}. {tag}    {pts} 分")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…(截断)"
    try:
        await callback.message.edit_text(text, reply_markup=admin_points_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=admin_points_back_kb())
    await callback.answer()

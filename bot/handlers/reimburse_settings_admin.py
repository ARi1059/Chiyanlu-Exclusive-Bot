"""报销规则配置 admin handler（2026-05 新增）。

提供两个超管专属配置入口：

  1. 🎚 报销门槛设置 (system:reimburse_min_points)
     调整 reimbursement_min_points config（0 = 不启用门槛）。

  2. 🔄 重置本月报销池 (system:reimburse_pool_reset)
     不动 reimbursements 表 / 不改历史状态；通过新增
     config key reimbursement_monthly_pool_reset_baselines 设置基线，
     让"本月已使用额度"从重置点后重新计算。

所有动作必须二次确认 + 写 admin_audit_logs；完整流程见
docs/POLICY-reimbursement.md §15。
"""
from __future__ import annotations

import functools
import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    REIMBURSE_MIN_POINTS_DEFAULT,
    REIMBURSE_MIN_POINTS_MAX,
    current_month_key,
    get_config,
    get_reimburse_pool_reset_baselines,
    get_reimbursement_min_points,
    get_reimbursement_monthly_pool_usage,
    is_super_admin,
    log_admin_audit,
    set_reimburse_pool_reset_baseline,
    set_reimbursement_min_points,
)
from bot.keyboards.admin_kb import (
    reimburse_min_points_cancel_kb,
    reimburse_min_points_confirm_kb,
    reimburse_min_points_menu_kb,
    reimburse_pool_reset_cancel_kb,
    reimburse_pool_reset_confirm_kb,
    reimburse_pool_reset_done_kb,
)
from bot.states.teacher_states import (
    ReimburseMinPointsStates,
    ReimbursePoolResetStates,
)

logger = logging.getLogger(__name__)

router = Router(name="reimburse_settings_admin")


def _super_admin_required(func):
    """仅超管可访问。"""
    @functools.wraps(func)
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


# ============================================================
# 1. 🎚 报销门槛设置
# ============================================================


@router.callback_query(F.data == "system:reimburse_min_points")
@_super_admin_required
async def cb_min_points_menu(callback: types.CallbackQuery, state: FSMContext):
    """🎚 报销门槛设置主面板：展示当前值 + 修改入口。"""
    await state.clear()
    current = await get_reimbursement_min_points()
    text = (
        "🎚 报销门槛设置\n\n"
        f"当前报销积分门槛：{current} 分\n\n"
        "说明：\n"
        "用户申请报销前，积分需达到该门槛。\n"
        "设置为 0 表示不启用积分门槛。\n"
        f"允许范围：0–{REIMBURSE_MIN_POINTS_MAX}。"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_min_points_menu_kb(),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_min_points_menu_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "system:reimburse_min_points:edit")
@_super_admin_required
async def cb_min_points_edit(callback: types.CallbackQuery, state: FSMContext):
    """点击「✏️ 修改门槛」→ 进入 FSM 等待输入。"""
    current = await get_reimbursement_min_points()
    await state.set_state(ReimburseMinPointsStates.waiting_value)
    await state.update_data(old_value=current)
    text = (
        f"✏️ 修改报销积分门槛\n\n"
        f"当前：{current} 分\n\n"
        f"请输入新门槛（整数，0–{REIMBURSE_MIN_POINTS_MAX}）。\n"
        "0 表示不启用积分门槛。"
    )
    await callback.message.edit_text(
        text, reply_markup=reimburse_min_points_cancel_kb(),
    )
    await callback.answer()


@router.message(ReimburseMinPointsStates.waiting_value)
@_super_admin_required
async def step_min_points_value(message: types.Message, state: FSMContext):
    """超管输入新门槛值 → 校验 → 进入确认页。"""
    text = (message.text or "").strip()
    try:
        v = int(text)
    except ValueError:
        await message.reply(
            "❌ 必须是整数。",
            reply_markup=reimburse_min_points_cancel_kb(),
        )
        return
    if v < 0:
        await message.reply(
            "❌ 不能为负数。",
            reply_markup=reimburse_min_points_cancel_kb(),
        )
        return
    if v > REIMBURSE_MIN_POINTS_MAX:
        await message.reply(
            f"❌ 不能超过上限 {REIMBURSE_MIN_POINTS_MAX}。",
            reply_markup=reimburse_min_points_cancel_kb(),
        )
        return
    await state.update_data(new_value=v)
    await state.set_state(ReimburseMinPointsStates.confirming)
    data = await state.get_data()
    confirm_text = (
        "确认修改报销积分门槛？\n\n"
        f"原门槛：{data.get('old_value')}\n"
        f"新门槛：{v}\n\n"
        + ("（设置为 0：不启用积分门槛）" if v == 0 else "")
    )
    await message.answer(
        confirm_text, reply_markup=reimburse_min_points_confirm_kb(),
    )


@router.callback_query(
    F.data == "system:reimburse_min_points:confirm",
    ReimburseMinPointsStates.confirming,
)
@_super_admin_required
async def cb_min_points_confirm(callback: types.CallbackQuery, state: FSMContext):
    """确认修改 → 写 config + audit log + 回主面板。"""
    data = await state.get_data()
    old_value = data.get("old_value")
    new_value = data.get("new_value")
    if new_value is None:
        await callback.answer("会话已过期，请重新进入", show_alert=True)
        await state.clear()
        return
    try:
        await set_reimbursement_min_points(int(new_value))
    except ValueError as e:
        await callback.answer(f"⚠️ 写入失败：{e}", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_min_points_set",
        target_type="config",
        target_id="reimbursement_min_points",
        detail={
            "old_value": int(old_value) if old_value is not None else None,
            "new_value": int(new_value),
        },
    )
    await state.clear()
    await callback.answer(f"✅ 已更新门槛为 {new_value} 分")
    # 回主面板
    await cb_min_points_menu(callback, state)


# ============================================================
# 2. 🔄 重置本月报销池
# ============================================================


def _format_pool_reset_preview(
    *,
    month_key: str,
    monthly_pool: int,
    raw_used: int,
    reset_baseline: int,
    effective_used: int,
) -> str:
    pool_str = "不限（0）" if monthly_pool == 0 else f"{monthly_pool} 元"
    remaining = "—" if monthly_pool == 0 else f"{monthly_pool - effective_used} 元"
    new_remaining = "—" if monthly_pool == 0 else f"{monthly_pool} 元"
    return (
        "🔄 重置本月报销池\n\n"
        f"当前月份：{month_key}\n"
        f"月度报销池：{pool_str}\n"
        f"当前原始已使用：{raw_used} 元\n"
        f"已重置基线（旧）：{reset_baseline} 元\n"
        f"当前有效已使用：{effective_used} 元\n"
        f"当前剩余额度：{remaining}\n\n"
        "重置后：\n"
        f"新基线：{raw_used} 元\n"
        f"有效已使用：0 元\n"
        f"剩余额度：{new_remaining}\n\n"
        "说明：\n"
        "该操作不会删除历史报销记录。\n"
        "该操作只重置本月报销池的额度计算基线。\n"
        "历史报销仍可在报销记录中查询。\n\n"
        "请输入重置原因（非空，≤ 200 字符），或点击取消。"
    )


@router.callback_query(F.data == "system:reimburse_pool_reset")
@_super_admin_required
async def cb_pool_reset_menu(callback: types.CallbackQuery, state: FSMContext):
    """🔄 重置本月报销池主入口：展示当前用量 + 提示输入原因。"""
    await state.clear()
    month_key = current_month_key()
    usage = await get_reimbursement_monthly_pool_usage(month_key)
    raw_pool = await get_config("reimbursement_monthly_pool")
    try:
        monthly_pool = int(raw_pool) if raw_pool else 0
    except (TypeError, ValueError):
        monthly_pool = 0

    await state.update_data(
        month_key=month_key,
        baseline_amount=usage["raw_used"],
        monthly_pool=monthly_pool,
        prev_effective_used=usage["effective_used"],
    )
    await state.set_state(ReimbursePoolResetStates.waiting_reason)

    text = _format_pool_reset_preview(
        month_key=month_key,
        monthly_pool=monthly_pool,
        raw_used=usage["raw_used"],
        reset_baseline=usage["reset_baseline"],
        effective_used=usage["effective_used"],
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_pool_reset_cancel_kb(),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_pool_reset_cancel_kb(),
        )
    await callback.answer()


@router.message(ReimbursePoolResetStates.waiting_reason)
@_super_admin_required
async def step_pool_reset_reason(message: types.Message, state: FSMContext):
    """超管输入原因 → 校验 → 进入最终确认页。"""
    reason = (message.text or "").strip()
    if not reason:
        await message.reply(
            "❌ 原因不能为空，请重新输入。",
            reply_markup=reimburse_pool_reset_cancel_kb(),
        )
        return
    if len(reason) > 200:
        await message.reply(
            "❌ 原因过长（≤ 200 字符），请重新输入。",
            reply_markup=reimburse_pool_reset_cancel_kb(),
        )
        return
    data = await state.get_data()
    await state.update_data(reason=reason)
    await state.set_state(ReimbursePoolResetStates.confirming)
    confirm_text = (
        "确认重置本月报销池？\n\n"
        f"月份：{data.get('month_key')}\n"
        f"本次 baseline：{data.get('baseline_amount')} 元\n"
        f"原因：{reason}"
    )
    await message.answer(
        confirm_text, reply_markup=reimburse_pool_reset_confirm_kb(),
    )


@router.callback_query(
    F.data == "system:reimburse_pool_reset:confirm",
    ReimbursePoolResetStates.confirming,
)
@_super_admin_required
async def cb_pool_reset_confirm(callback: types.CallbackQuery, state: FSMContext):
    """最终确认 → 写 config baseline + audit log + 成功提示。"""
    data = await state.get_data()
    month_key = data.get("month_key")
    baseline_amount = data.get("baseline_amount")
    reason = data.get("reason")
    prev_effective = data.get("prev_effective_used", 0)
    if month_key is None or baseline_amount is None or not reason:
        await callback.answer("会话已过期，请重新进入", show_alert=True)
        await state.clear()
        return
    try:
        entry = await set_reimburse_pool_reset_baseline(
            month_key=str(month_key),
            baseline_amount=int(baseline_amount),
            admin_id=callback.from_user.id,
            reason=str(reason),
        )
    except Exception as e:
        logger.exception("set_reimburse_pool_reset_baseline 失败: %s", e)
        await callback.answer(f"⚠️ 写入失败：{e}", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_pool_reset",
        target_type="config",
        target_id="reimbursement_monthly_pool_reset_baselines",
        detail={
            "month_key": str(month_key),
            "baseline_amount": int(baseline_amount),
            "prev_effective_used": int(prev_effective),
            "reason": str(reason),
            "reset_at": entry.get("reset_at"),
        },
    )
    await state.clear()
    text = (
        "✅ 本月报销池已重置\n\n"
        f"月份：{month_key}\n"
        f"重置前原始已使用：{baseline_amount} 元\n"
        f"重置前有效已使用：{prev_effective} 元\n"
        "重置后有效已使用：0 元\n"
        f"原因：{reason}"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_pool_reset_done_kb(),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_pool_reset_done_kb(),
        )
    await callback.answer("✅ 已重置")

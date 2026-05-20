"""报销规则配置 admin handler（2026-05 新增）。

提供两个超管专属配置入口：

  1. 🎚 报销门槛设置 (system:reimburse_min_points)
     调整 reimbursement_min_points config（0 = 不启用门槛）。

  2. 🔄 重置本月报销池 (system:reimburse_pool_reset)
     不动 reimbursements 表 / 不改历史状态；通过新增
     config key reimbursement_monthly_pool_reset_baselines 设置基线，
     让"本月已使用额度"从重置点后重新计算。

所有动作必须二次确认 + 写 admin_audit_logs；完整流程见
docs/POLICY.md (Part II) §15。
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
    REIMBURSE_PROMO_TEXT_DEFAULT,
    REIMBURSE_PROMO_TEXT_MAX_LEN,
    REIMBURSE_PROMO_URL_DEFAULT,
    REIMBURSE_PROMO_URL_MAX_LEN,
    REIMBURSE_WEEKLY_LIMIT_DEFAULT,
    REIMBURSE_WEEKLY_LIMIT_MAX,
    REIMBURSE_WEEKLY_LIMIT_MIN,
    current_month_key,
    get_config,
    get_reimburse_pool_reset_baselines,
    get_reimburse_promo_text,
    get_reimburse_promo_url,
    get_reimbursement_min_points,
    get_reimbursement_monthly_pool_usage,
    get_reimbursement_weekly_limit,
    is_super_admin,
    log_admin_audit,
    set_reimburse_pool_reset_baseline,
    set_reimburse_promo_text,
    set_reimburse_promo_url,
    set_reimbursement_min_points,
    set_reimbursement_weekly_limit,
)
from bot.keyboards.admin_kb import (
    reimburse_min_points_cancel_kb,
    reimburse_min_points_confirm_kb,
    reimburse_min_points_menu_kb,
    reimburse_pool_reset_cancel_kb,
    reimburse_pool_reset_confirm_kb,
    reimburse_pool_reset_done_kb,
    reimburse_promo_text_cancel_kb,
    reimburse_promo_text_confirm_kb,
    reimburse_promo_text_menu_kb,
    reimburse_promo_url_cancel_kb,
    reimburse_promo_url_confirm_kb,
    reimburse_promo_url_menu_kb,
    reimburse_weekly_limit_cancel_kb,
    reimburse_weekly_limit_confirm_kb,
    reimburse_weekly_limit_menu_kb,
)
from bot.states.teacher_states import (
    ReimburseMinPointsStates,
    ReimbursePoolResetStates,
    ReimbursePromoTextStates,
    ReimbursePromoUrlStates,
    ReimburseWeeklyLimitStates,
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
# 1b. 🗓 每周报销上限设置（2026-05 新增）
# ============================================================


@router.callback_query(F.data == "system:reimburse_weekly_limit")
@_super_admin_required
async def cb_weekly_limit_menu(callback: types.CallbackQuery, state: FSMContext):
    """🗓 每周报销上限主面板：展示当前值 + 修改入口。"""
    await state.clear()
    current = await get_reimbursement_weekly_limit()
    text = (
        "🗓 每周报销上限\n\n"
        f"当前每用户每周 approved 上限：{current} 次\n\n"
        "说明：\n"
        "每个用户每 ISO 周内最多可被批准 N 次报销。\n"
        f"允许范围：{REIMBURSE_WEEKLY_LIMIT_MIN}–{REIMBURSE_WEEKLY_LIMIT_MAX}"
        f"（默认 {REIMBURSE_WEEKLY_LIMIT_DEFAULT}）。\n"
        "如需对单个用户额外解锁本周配额，使用「reset voucher」。"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_weekly_limit_menu_kb(),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_weekly_limit_menu_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "system:reimburse_weekly_limit:edit")
@_super_admin_required
async def cb_weekly_limit_edit(callback: types.CallbackQuery, state: FSMContext):
    """点击「✏️ 修改每周上限」→ 进入 FSM 等待输入。"""
    current = await get_reimbursement_weekly_limit()
    await state.set_state(ReimburseWeeklyLimitStates.waiting_value)
    await state.update_data(old_value=current)
    text = (
        f"✏️ 修改每周报销上限\n\n"
        f"当前：{current} 次\n\n"
        f"请输入新上限（整数，{REIMBURSE_WEEKLY_LIMIT_MIN}–"
        f"{REIMBURSE_WEEKLY_LIMIT_MAX}）。"
    )
    await callback.message.edit_text(
        text, reply_markup=reimburse_weekly_limit_cancel_kb(),
    )
    await callback.answer()


@router.message(ReimburseWeeklyLimitStates.waiting_value)
@_super_admin_required
async def step_weekly_limit_value(message: types.Message, state: FSMContext):
    """超管输入新上限值 → 校验 → 进入确认页。"""
    text = (message.text or "").strip()
    try:
        v = int(text)
    except ValueError:
        await message.reply(
            "❌ 必须是整数。",
            reply_markup=reimburse_weekly_limit_cancel_kb(),
        )
        return
    if v < REIMBURSE_WEEKLY_LIMIT_MIN:
        await message.reply(
            f"❌ 不能小于 {REIMBURSE_WEEKLY_LIMIT_MIN}。",
            reply_markup=reimburse_weekly_limit_cancel_kb(),
        )
        return
    if v > REIMBURSE_WEEKLY_LIMIT_MAX:
        await message.reply(
            f"❌ 不能超过上限 {REIMBURSE_WEEKLY_LIMIT_MAX}。",
            reply_markup=reimburse_weekly_limit_cancel_kb(),
        )
        return
    await state.update_data(new_value=v)
    await state.set_state(ReimburseWeeklyLimitStates.confirming)
    data = await state.get_data()
    confirm_text = (
        "确认修改每周报销上限？\n\n"
        f"原上限：{data.get('old_value')} 次/周\n"
        f"新上限：{v} 次/周"
    )
    await message.answer(
        confirm_text, reply_markup=reimburse_weekly_limit_confirm_kb(),
    )


@router.callback_query(
    F.data == "system:reimburse_weekly_limit:confirm",
    ReimburseWeeklyLimitStates.confirming,
)
@_super_admin_required
async def cb_weekly_limit_confirm(callback: types.CallbackQuery, state: FSMContext):
    """确认修改 → 写 config + audit log + 回主面板。"""
    data = await state.get_data()
    old_value = data.get("old_value")
    new_value = data.get("new_value")
    if new_value is None:
        await callback.answer("会话已过期，请重新进入", show_alert=True)
        await state.clear()
        return
    try:
        await set_reimbursement_weekly_limit(int(new_value))
    except ValueError as e:
        await callback.answer(f"⚠️ 写入失败：{e}", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_weekly_limit_set",
        target_type="config",
        target_id="reimbursement_weekly_limit",
        detail={
            "old_value": int(old_value) if old_value is not None else None,
            "new_value": int(new_value),
        },
    )
    await state.clear()
    await callback.answer(f"✅ 已更新每周上限为 {new_value} 次")
    # 回主面板
    await cb_weekly_limit_menu(callback, state)


# ============================================================
# 1c. 📢 评价 footer 推广文本（2026-05 新增）
# ============================================================


def _fmt_promo_value(v: str) -> str:
    """空值显示为「（已禁用）」。"""
    return "（已禁用 → footer 不渲染）" if not v else repr(v)


@router.callback_query(F.data == "system:reimburse_promo_text")
@_super_admin_required
async def cb_promo_text_menu(callback: types.CallbackQuery, state: FSMContext):
    """📢 评价 footer 推广文本主面板。"""
    await state.clear()
    current = await get_reimburse_promo_text()
    text = (
        "📢 评价 footer 推广文本\n\n"
        f"当前：{_fmt_promo_value(current)}\n"
        f"默认：{REIMBURSE_PROMO_TEXT_DEFAULT!r}\n\n"
        "说明：\n"
        "评价通过后讨论群评论 + 老师私聊评论尾部 footer 第二行 HTML 链接的\n"
        "显示文字。任一（text 或 url）为空 → footer 整行不渲染。\n"
        f"长度限制：≤ {REIMBURSE_PROMO_TEXT_MAX_LEN} 字符。"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_promo_text_menu_kb(),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_promo_text_menu_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "system:reimburse_promo_text:edit")
@_super_admin_required
async def cb_promo_text_edit(callback: types.CallbackQuery, state: FSMContext):
    """进入 FSM 等待输入新文本。"""
    current = await get_reimburse_promo_text()
    await state.set_state(ReimbursePromoTextStates.waiting_value)
    await state.update_data(old_value=current)
    text = (
        f"✏️ 修改 footer 文本\n\n"
        f"当前：{_fmt_promo_value(current)}\n\n"
        f"请输入新文本（≤ {REIMBURSE_PROMO_TEXT_MAX_LEN} 字符）。"
    )
    await callback.message.edit_text(
        text, reply_markup=reimburse_promo_text_cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "system:reimburse_promo_text:clear")
@_super_admin_required
async def cb_promo_text_clear(callback: types.CallbackQuery, state: FSMContext):
    """清空 footer 文本（=禁用 footer）。直接进入确认页。"""
    current = await get_reimburse_promo_text()
    await state.set_state(ReimbursePromoTextStates.confirming)
    await state.update_data(old_value=current, new_value="")
    text = (
        "确认清空 footer 文本？\n\n"
        f"原文本：{_fmt_promo_value(current)}\n"
        "新文本：（清空 → footer 不渲染）"
    )
    await callback.message.edit_text(
        text, reply_markup=reimburse_promo_text_confirm_kb(),
    )
    await callback.answer()


@router.message(ReimbursePromoTextStates.waiting_value)
@_super_admin_required
async def step_promo_text_value(message: types.Message, state: FSMContext):
    """超管输入新文本 → 校验长度 → 进入确认页。"""
    v = (message.text or "")
    if len(v) > REIMBURSE_PROMO_TEXT_MAX_LEN:
        await message.reply(
            f"❌ 文本长度超过上限 {REIMBURSE_PROMO_TEXT_MAX_LEN}（当前 {len(v)}）。",
            reply_markup=reimburse_promo_text_cancel_kb(),
        )
        return
    await state.update_data(new_value=v)
    await state.set_state(ReimbursePromoTextStates.confirming)
    data = await state.get_data()
    confirm_text = (
        "确认修改 footer 文本？\n\n"
        f"原文本：{_fmt_promo_value(data.get('old_value') or '')}\n"
        f"新文本：{_fmt_promo_value(v)}"
    )
    await message.answer(
        confirm_text, reply_markup=reimburse_promo_text_confirm_kb(),
    )


@router.callback_query(
    F.data == "system:reimburse_promo_text:confirm",
    ReimbursePromoTextStates.confirming,
)
@_super_admin_required
async def cb_promo_text_confirm(callback: types.CallbackQuery, state: FSMContext):
    """确认修改 → 写 config + audit log。"""
    data = await state.get_data()
    old_value = data.get("old_value")
    new_value = data.get("new_value")
    if new_value is None:
        await callback.answer("会话已过期，请重新进入", show_alert=True)
        await state.clear()
        return
    try:
        await set_reimburse_promo_text(str(new_value))
    except ValueError as e:
        await callback.answer(f"⚠️ 写入失败：{e}", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_promo_text_set",
        target_type="config",
        target_id="reimbursement_promo_text",
        detail={
            "old_value": str(old_value or ""),
            "new_value": str(new_value),
        },
    )
    await state.clear()
    await callback.answer(
        "✅ 已更新文本" + ("（footer 已禁用）" if not new_value else "")
    )
    await cb_promo_text_menu(callback, state)


# ============================================================
# 1d. 🔗 评价 footer 推广 URL（2026-05 新增）
# ============================================================


@router.callback_query(F.data == "system:reimburse_promo_url")
@_super_admin_required
async def cb_promo_url_menu(callback: types.CallbackQuery, state: FSMContext):
    """🔗 评价 footer 推广 URL 主面板。"""
    await state.clear()
    current = await get_reimburse_promo_url()
    text = (
        "🔗 评价 footer 推广 URL\n\n"
        f"当前：{_fmt_promo_value(current)}\n"
        f"默认：{REIMBURSE_PROMO_URL_DEFAULT!r}\n\n"
        "说明：\n"
        "评价通过后讨论群评论 + 老师私聊评论尾部 footer 第二行 HTML 链接的\n"
        "目标 URL。任一（text 或 url）为空 → footer 整行不渲染。\n"
        "格式要求：http:// 或 https:// 开头。\n"
        f"长度限制：≤ {REIMBURSE_PROMO_URL_MAX_LEN} 字符。"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_promo_url_menu_kb(),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_promo_url_menu_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "system:reimburse_promo_url:edit")
@_super_admin_required
async def cb_promo_url_edit(callback: types.CallbackQuery, state: FSMContext):
    """进入 FSM 等待输入新 URL。"""
    current = await get_reimburse_promo_url()
    await state.set_state(ReimbursePromoUrlStates.waiting_value)
    await state.update_data(old_value=current)
    text = (
        f"✏️ 修改 footer URL\n\n"
        f"当前：{_fmt_promo_value(current)}\n\n"
        f"请输入新 URL（http(s)://，≤ {REIMBURSE_PROMO_URL_MAX_LEN} 字符）。"
    )
    await callback.message.edit_text(
        text, reply_markup=reimburse_promo_url_cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "system:reimburse_promo_url:clear")
@_super_admin_required
async def cb_promo_url_clear(callback: types.CallbackQuery, state: FSMContext):
    """清空 footer URL（=禁用 footer）。直接进入确认页。"""
    current = await get_reimburse_promo_url()
    await state.set_state(ReimbursePromoUrlStates.confirming)
    await state.update_data(old_value=current, new_value="")
    text = (
        "确认清空 footer URL？\n\n"
        f"原 URL：{_fmt_promo_value(current)}\n"
        "新 URL：（清空 → footer 不渲染）"
    )
    await callback.message.edit_text(
        text, reply_markup=reimburse_promo_url_confirm_kb(),
    )
    await callback.answer()


@router.message(ReimbursePromoUrlStates.waiting_value)
@_super_admin_required
async def step_promo_url_value(message: types.Message, state: FSMContext):
    """超管输入新 URL → 校验长度 + http(s):// 前缀 → 进入确认页。"""
    v = (message.text or "").strip()
    if len(v) > REIMBURSE_PROMO_URL_MAX_LEN:
        await message.reply(
            f"❌ URL 长度超过上限 {REIMBURSE_PROMO_URL_MAX_LEN}（当前 {len(v)}）。",
            reply_markup=reimburse_promo_url_cancel_kb(),
        )
        return
    if v and not (v.startswith("http://") or v.startswith("https://")):
        await message.reply(
            "❌ URL 必须以 http:// 或 https:// 开头。",
            reply_markup=reimburse_promo_url_cancel_kb(),
        )
        return
    await state.update_data(new_value=v)
    await state.set_state(ReimbursePromoUrlStates.confirming)
    data = await state.get_data()
    confirm_text = (
        "确认修改 footer URL？\n\n"
        f"原 URL：{_fmt_promo_value(data.get('old_value') or '')}\n"
        f"新 URL：{_fmt_promo_value(v)}"
    )
    await message.answer(
        confirm_text, reply_markup=reimburse_promo_url_confirm_kb(),
    )


@router.callback_query(
    F.data == "system:reimburse_promo_url:confirm",
    ReimbursePromoUrlStates.confirming,
)
@_super_admin_required
async def cb_promo_url_confirm(callback: types.CallbackQuery, state: FSMContext):
    """确认修改 → 写 config + audit log。"""
    data = await state.get_data()
    old_value = data.get("old_value")
    new_value = data.get("new_value")
    if new_value is None:
        await callback.answer("会话已过期，请重新进入", show_alert=True)
        await state.clear()
        return
    try:
        await set_reimburse_promo_url(str(new_value))
    except ValueError as e:
        await callback.answer(f"⚠️ 写入失败：{e}", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_promo_url_set",
        target_type="config",
        target_id="reimbursement_promo_url",
        detail={
            "old_value": str(old_value or ""),
            "new_value": str(new_value),
        },
    )
    await state.clear()
    await callback.answer(
        "✅ 已更新 URL" + ("（footer 已禁用）" if not new_value else "")
    )
    await cb_promo_url_menu(callback, state)


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

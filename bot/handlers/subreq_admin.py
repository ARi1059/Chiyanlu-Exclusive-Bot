"""必关频道/群组 admin 子菜单（Phase 9.3）

入口：[⚙️ 系统设置] → [📋 必关频道/群组]
功能：列表 / 添加（3 步 FSM，含 precheck）/ 启停 / 删除（二次确认）
"""
from __future__ import annotations

import logging

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from bot.database import (
    add_required_subscription,
    list_required_subscriptions,
    get_required_subscription,
    toggle_required_subscription,
    remove_required_subscription,
    log_admin_audit,
)
from bot.keyboards.admin_kb import (
    subreq_menu_kb,
    subreq_list_kb,
    subreq_item_action_kb,
    subreq_remove_confirm_kb,
    subreq_cancel_kb,
    system_menu_kb,
)
from bot.states.teacher_states import SubReqAddStates
from bot.utils.permissions import admin_required
from bot.utils.required_channels import precheck_required_chat

logger = logging.getLogger(__name__)

router = Router(name="subreq_admin")


# ============ 列表 ============

@router.callback_query(F.data == "admin:subreq")
@admin_required
async def cb_subreq_list(callback: types.CallbackQuery, state: FSMContext):
    """[📋 必关频道/群组] 主页：列表 + 操作入口"""
    await state.clear()
    items = await list_required_subscriptions(active_only=False)
    if not items:
        text = (
            "📋 必关频道/群组（共 0 项）\n\n"
            '列表为空时视为"无门槛"，所有用户均可写评价。\n'
            "点 [➕ 添加] 录入第一项。"
        )
        await callback.message.edit_text(text, reply_markup=subreq_menu_kb())
    else:
        n_active = sum(1 for x in items if x.get("is_active"))
        text = (
            f"📋 必关频道/群组（共 {len(items)} 项，启用 {n_active} 项）\n\n"
            "点击某项进入详情，[➕ 添加] 录入新项。"
        )
        await callback.message.edit_text(text, reply_markup=subreq_list_kb(items))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:subreq:item:"))
@admin_required
async def cb_subreq_item(callback: types.CallbackQuery, state: FSMContext):
    """某项详情页"""
    await state.clear()
    try:
        item_id = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    item = await get_required_subscription(item_id)
    if not item:
        await callback.answer("该项不存在", show_alert=True)
        return
    status_str = "✅ 启用中" if item["is_active"] else "⛔ 已停用"
    text = (
        f"📋 必关项 #{item_id}\n\n"
        f"显示名：{item['display_name']}\n"
        f"类型：{item['chat_type']}\n"
        f"chat_id：{item['chat_id']}\n"
        f"邀请链接：{item['invite_link']}\n"
        f"状态：{status_str}\n"
        f"排序：{item.get('sort_order') or 0}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=subreq_item_action_kb(item_id, bool(item["is_active"])),
    )
    await callback.answer()


# ============ 启停 ============

@router.callback_query(F.data.startswith("admin:subreq:toggle:"))
@admin_required
async def cb_subreq_toggle(callback: types.CallbackQuery, state: FSMContext):
    try:
        item_id = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    new_val = await toggle_required_subscription(item_id)
    if new_val is None:
        await callback.answer("该项不存在", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="subreq_toggle",
        target_type="required_subscription",
        target_id=str(item_id),
        detail={"is_active": new_val},
    )
    await callback.answer("已启用" if new_val else "已停用")
    # 刷新详情页
    callback.data = f"admin:subreq:item:{item_id}"
    await cb_subreq_item(callback, state)


# ============ 删除（二次确认）============

@router.callback_query(F.data.startswith("admin:subreq:remove:"))
@admin_required
async def cb_subreq_remove_ask(callback: types.CallbackQuery, state: FSMContext):
    """删除前的二次确认页"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        item_id = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    item = await get_required_subscription(item_id)
    if not item:
        await callback.answer("该项不存在", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ 确认删除必关项 #{item_id}「{item['display_name']}」？\n\n"
        "删除后该项不再用于写评价前的关注校验（已存在的评价不受影响）。",
        reply_markup=subreq_remove_confirm_kb(item_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:subreq:remove_confirm:"))
@admin_required
async def cb_subreq_remove_confirm(callback: types.CallbackQuery, state: FSMContext):
    try:
        item_id = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    ok = await remove_required_subscription(item_id)
    if ok:
        await log_admin_audit(
            admin_id=callback.from_user.id,
            action="subreq_remove",
            target_type="required_subscription",
            target_id=str(item_id),
            detail={},
        )
        await callback.answer("✅ 已删除")
    else:
        await callback.answer("⚠️ 删除失败或已不存在", show_alert=True)
    # 回列表
    callback.data = "admin:subreq"
    await cb_subreq_list(callback, state)


# ============ 添加（3 步 FSM） ============

@router.callback_query(F.data == "admin:subreq:add")
@admin_required
async def cb_subreq_add_start(callback: types.CallbackQuery, state: FSMContext):
    """[➕ 添加] 进入 Step 1：等待 chat_id"""
    await state.set_state(SubReqAddStates.waiting_chat_id)
    await state.set_data({})
    await callback.message.edit_text(
        "➕ 添加必关频道/群组 (Step 1/3)\n\n"
        "请输入目标 Chat ID（频道/群组数字 ID，通常为负数）。\n"
        "bot 必须已加入该频道/群组才能配置成功。\n\n"
        "任意时刻发 /cancel 中止。",
        reply_markup=subreq_cancel_kb(),
    )
    await callback.answer()


@router.message(SubReqAddStates.waiting_chat_id)
@admin_required
async def step_subreq_chat_id(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("❌ 已取消。", reply_markup=subreq_menu_kb())
        return
    try:
        chat_id = int(text)
    except ValueError:
        await message.reply("❌ 请输入数字 chat_id（可负）。")
        return
    # 预校验：bot 必须已在场，能查 member
    await message.answer("⏳ 正在校验 bot 是否在该 chat...")
    ok, reason, info = await precheck_required_chat(message.bot, chat_id)
    if not ok:
        await message.reply(
            f"❌ 校验失败：{reason}\n\n请确认 chat_id 正确且 bot 已加入，"
            "然后重新输入；或发 /cancel 取消。"
        )
        return
    await state.update_data(
        chat_id=chat_id,
        chat_type=info["type"],
        chat_title=info["title"],
    )
    await state.set_state(SubReqAddStates.waiting_display_name)
    await message.answer(
        f"✅ 校验通过：{info['type']} · {info['title']}\n\n"
        f"➕ 添加必关频道/群组 (Step 2/3)\n\n"
        '请输入"显示名"（在用户拒绝消息里展示，例：痴颜录公示频道）。',
        reply_markup=subreq_cancel_kb(),
    )


@router.message(SubReqAddStates.waiting_display_name)
@admin_required
async def step_subreq_display_name(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("❌ 已取消。", reply_markup=subreq_menu_kb())
        return
    if not text or len(text) > 60:
        await message.reply("❌ 显示名不能为空，长度 ≤ 60。")
        return
    await state.update_data(display_name=text)
    await state.set_state(SubReqAddStates.waiting_invite_link)
    await message.answer(
        f"➕ 添加必关频道/群组 (Step 3/3)\n\n"
        "请输入邀请链接（https://t.me/... 或 https://t.me/+xxxxx）。\n"
        "用户被拒绝时点击此链接加入。",
        reply_markup=subreq_cancel_kb(),
    )


@router.message(SubReqAddStates.waiting_invite_link)
@admin_required
async def step_subreq_invite_link(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("❌ 已取消。", reply_markup=subreq_menu_kb())
        return
    if not (text.startswith("https://t.me/") or text.startswith("http://t.me/")):
        await message.reply("❌ 请输入有效的 t.me 邀请链接。")
        return
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if chat_id is None:
        await state.clear()
        await message.answer("⚠️ 状态丢失，请重新进入。", reply_markup=subreq_menu_kb())
        return
    item_id = await add_required_subscription(
        chat_id=int(chat_id),
        chat_type=str(data.get("chat_type") or "unknown"),
        display_name=str(data.get("display_name") or chat_id),
        invite_link=text,
    )
    await state.clear()
    if item_id is None:
        await message.answer(
            f"⚠️ 添加失败（chat_id {chat_id} 可能已存在）。",
            reply_markup=subreq_menu_kb(),
        )
        return
    await log_admin_audit(
        admin_id=message.from_user.id,
        action="subreq_add",
        target_type="required_subscription",
        target_id=str(item_id),
        detail={
            "chat_id": int(chat_id),
            "chat_type": str(data.get("chat_type")),
            "display_name": str(data.get("display_name")),
        },
    )
    await message.answer(
        f"✅ 已添加必关项 #{item_id}「{data.get('display_name')}」。",
        reply_markup=subreq_menu_kb(),
    )

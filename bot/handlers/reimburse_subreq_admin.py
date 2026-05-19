"""报销专用必关频道 / 群组配置 admin 子菜单。

入口：[⚙️ 系统设置] → [💰 报销必关设置]
功能：列表 / 添加（3 步 FSM + 二次确认）/ 删除（二次确认）

设计：
    - 与全局 subreq_admin.py 完全独立——使用独立 callback 命名空间
      system:reimburse_subreq:* 和独立 FSM 状态类 ReimburseSubReqAddStates
    - 数据存于 config 表 key=reimbursement_required_chats（不新增表）
    - 全部入口仅超管可见可操作（@super_admin_required）
    - 所有写操作（添加 / 删除）写入 admin_audit_logs
    - 与全局 required_subscriptions 表互不影响
"""
from __future__ import annotations

import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from bot.database import (
    add_reimburse_required_chat,
    get_reimburse_required_chats,
    log_admin_audit,
    remove_reimburse_required_chat,
)
from bot.keyboards.admin_kb import (
    reimburse_subreq_add_confirm_kb,
    reimburse_subreq_cancel_kb,
    reimburse_subreq_menu_kb,
    reimburse_subreq_remove_confirm_kb,
)
from bot.states.teacher_states import ReimburseSubReqAddStates
from bot.utils.permissions import super_admin_required
from bot.utils.required_channels import precheck_required_chat

logger = logging.getLogger(__name__)

router = Router(name="reimburse_subreq_admin")


# ============ 主菜单：列表 + 入口 ============


@router.callback_query(F.data == "system:reimburse_subreq")
@super_admin_required
async def cb_reimburse_subreq_menu(
    callback: types.CallbackQuery, state: FSMContext,
):
    """💰 报销必关设置主页：列出现有配置 + 添加 / 删除入口。"""
    await state.clear()
    chats = await get_reimburse_required_chats()
    if not chats:
        text = (
            "💰 报销必关设置\n\n"
            "这里配置「申请报销前必须关注 / 加入」的频道或群组。\n"
            "该配置仅影响报销流程，**不影响**全局必关订阅。\n\n"
            "当前已配置：\n（空）\n\n"
            "点 [➕ 添加频道 / 群组] 录入第一项；为空时报销流程不强制订阅检查。"
        )
    else:
        lines = ["💰 报销必关设置", "", "这里配置「申请报销前必须关注 / 加入」的频道或群组。",
                 "该配置仅影响报销流程，**不影响**全局必关订阅。", "", "当前已配置："]
        for idx, c in enumerate(chats, start=1):
            mark = "✅" if c.get("enabled", True) else "⛔"
            lines.append(
                f"{idx}. {mark} {c.get('display_name') or '(未命名)'} "
                f"({c.get('chat_type') or '?'} / {c['chat_id']})"
            )
        lines.append("")
        lines.append(f"共 {len(chats)} 项；可点对应行删除。")
        text = "\n".join(lines)
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_subreq_menu_kb(chats),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_subreq_menu_kb(chats),
        )
    await callback.answer()


# ============ 删除：列表点击 → 二次确认 → 真删除 ============


@router.callback_query(F.data.startswith("system:reimburse_subreq:delete:"))
@super_admin_required
async def cb_reimburse_subreq_delete_ask(
    callback: types.CallbackQuery, state: FSMContext,
):
    """点击列表删除项 → 二次确认页。"""
    await state.clear()
    try:
        idx = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    chats = await get_reimburse_required_chats()
    if idx < 0 or idx >= len(chats):
        await callback.answer("该项不存在", show_alert=True)
        return
    item = chats[idx]
    text = (
        "⚠️ 确认删除该报销必关配置？\n\n"
        f"显示名：{item.get('display_name') or '(未命名)'}\n"
        f"chat_id：{item['chat_id']}\n"
        f"类型：{item.get('chat_type') or '?'}\n\n"
        "注意：这只会移除报销流程的必关要求，不会影响全局必关订阅。"
    )
    await callback.message.edit_text(
        text, reply_markup=reimburse_subreq_remove_confirm_kb(idx),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("system:reimburse_subreq:confirm_delete:"))
@super_admin_required
async def cb_reimburse_subreq_delete_confirm(
    callback: types.CallbackQuery, state: FSMContext,
):
    """二次确认 → 真删除 + audit log。"""
    await state.clear()
    try:
        idx = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    chats = await get_reimburse_required_chats()
    if idx < 0 or idx >= len(chats):
        await callback.answer("该项不存在", show_alert=True)
        return
    item = chats[idx]
    chat_id = item["chat_id"]
    ok = await remove_reimburse_required_chat(chat_id)
    if ok:
        await log_admin_audit(
            admin_id=callback.from_user.id,
            action="reimburse_subreq_remove",
            target_type="reimbursement_required_chat",
            target_id=str(chat_id),
            detail={
                "chat_id": chat_id,
                "display_name": item.get("display_name") or "",
                "chat_type": item.get("chat_type") or "",
            },
        )
        await callback.answer(f"✅ 已删除 {item.get('display_name') or chat_id}")
    else:
        await callback.answer("⚠️ 该项已不存在", show_alert=True)
    # 回到主菜单
    await cb_reimburse_subreq_menu(
        callback.model_copy(update={"data": "system:reimburse_subreq"}),
        state,
    )


# ============ 添加：3 步 FSM + 确认 ============


@router.callback_query(F.data == "system:reimburse_subreq:add")
@super_admin_required
async def cb_reimburse_subreq_add_start(
    callback: types.CallbackQuery, state: FSMContext,
):
    """Step 1：要求输入 chat_id。"""
    await state.clear()
    await state.set_state(ReimburseSubReqAddStates.waiting_chat_id)
    text = (
        "➕ 添加报销必关频道 / 群组\n\n"
        "请输入频道 / 群组的 Telegram chat_id（整数）。\n\n"
        "示例：-1001234567890\n\n"
        "Bot 必须能访问该 chat（建议设为管理员）。\n"
        "发 /cancel 退出。"
    )
    await callback.message.edit_text(text, reply_markup=reimburse_subreq_cancel_kb())
    await callback.answer()


@router.message(ReimburseSubReqAddStates.waiting_chat_id)
@super_admin_required
async def step_reimburse_subreq_chat_id(
    message: types.Message, state: FSMContext,
):
    """Step 1 输入：校验 chat_id + precheck bot 是否在场。"""
    text = (message.text or "").strip()
    try:
        chat_id = int(text)
    except ValueError:
        await message.reply(
            "❌ chat_id 必须是整数（频道 / 大群以 -100 开头）",
            reply_markup=reimburse_subreq_cancel_kb(),
        )
        return
    # 校验：是否已存在
    existing = await get_reimburse_required_chats()
    if any(c["chat_id"] == chat_id for c in existing):
        await message.reply(
            f"⚠️ chat_id {chat_id} 已在配置中，跳过。请用列表点击删除项再重新添加。",
            reply_markup=reimburse_subreq_cancel_kb(),
        )
        return
    # precheck：bot 能否访问
    ok, reason, info = await precheck_required_chat(message.bot, chat_id)
    if not ok:
        await message.reply(
            f"❌ Bot 无法访问该 chat：{reason}\n请确认 chat_id 正确且 Bot 已被加入。",
            reply_markup=reimburse_subreq_cancel_kb(),
        )
        return
    chat_type = (info or {}).get("type") or ""
    title = (info or {}).get("title") or str(chat_id)
    await state.update_data(
        chat_id=chat_id, chat_type=chat_type, display_name_default=title,
    )
    await state.set_state(ReimburseSubReqAddStates.waiting_display_name)
    await message.answer(
        f"✅ 已校验 chat_id={chat_id}（{chat_type} / {title}）\n\n"
        "Step 2：请输入用于展示的名称（≤ 60 字符）。\n"
        f"直接发 `{title}` 可使用 Bot 拿到的默认名。\n"
        "发 /cancel 退出。",
        reply_markup=reimburse_subreq_cancel_kb(),
    )


@router.message(ReimburseSubReqAddStates.waiting_display_name)
@super_admin_required
async def step_reimburse_subreq_display_name(
    message: types.Message, state: FSMContext,
):
    """Step 2 输入：display_name。"""
    name = (message.text or "").strip()
    if not name:
        await message.reply(
            "❌ 名称不能为空", reply_markup=reimburse_subreq_cancel_kb(),
        )
        return
    if len(name) > 60:
        await message.reply(
            "❌ 名称太长（≤ 60 字符）", reply_markup=reimburse_subreq_cancel_kb(),
        )
        return
    await state.update_data(display_name=name)
    await state.set_state(ReimburseSubReqAddStates.waiting_invite_link)
    await message.answer(
        "Step 3：请输入邀请链接（用户拦截页会显示「📢 加入」按钮跳转）。\n"
        "必须以 https://t.me/ 或 http://t.me/ 开头。\n"
        "发 /cancel 退出。",
        reply_markup=reimburse_subreq_cancel_kb(),
    )


@router.message(ReimburseSubReqAddStates.waiting_invite_link)
@super_admin_required
async def step_reimburse_subreq_invite_link(
    message: types.Message, state: FSMContext,
):
    """Step 3 输入：invite_link → 进入确认页。"""
    link = (message.text or "").strip()
    if not (link.startswith("https://t.me/") or link.startswith("http://t.me/")):
        await message.reply(
            "❌ 邀请链接必须以 https://t.me/ 或 http://t.me/ 开头",
            reply_markup=reimburse_subreq_cancel_kb(),
        )
        return
    await state.update_data(invite_link=link)
    data = await state.get_data()
    text = (
        "确认添加报销必关频道 / 群组？\n\n"
        f"显示名：{data['display_name']}\n"
        f"chat_id：{data['chat_id']}\n"
        f"类型：{data.get('chat_type') or '?'}\n"
        f"邀请链接：{link}"
    )
    await message.answer(text, reply_markup=reimburse_subreq_add_confirm_kb())


@router.callback_query(F.data == "system:reimburse_subreq:add_confirm")
@super_admin_required
async def cb_reimburse_subreq_add_confirm(
    callback: types.CallbackQuery, state: FSMContext,
):
    """确认页 → 写入 config + audit log + 回主菜单。"""
    data = await state.get_data()
    chat_id = data.get("chat_id")
    chat_type = data.get("chat_type") or ""
    display_name = data.get("display_name") or ""
    invite_link = data.get("invite_link") or ""
    if not chat_id or not display_name or not invite_link:
        await callback.answer("⚠️ 缺少必要字段，请重新添加", show_alert=True)
        await state.clear()
        await cb_reimburse_subreq_menu(callback, state)
        return
    ok = await add_reimburse_required_chat(
        chat_id=chat_id,
        chat_type=chat_type,
        display_name=display_name,
        invite_link=invite_link,
    )
    if ok:
        await log_admin_audit(
            admin_id=callback.from_user.id,
            action="reimburse_subreq_add",
            target_type="reimbursement_required_chat",
            target_id=str(chat_id),
            detail={
                "chat_id": chat_id,
                "chat_type": chat_type,
                "display_name": display_name,
                "invite_link": invite_link,
            },
        )
        await callback.answer(f"✅ 已添加 {display_name}")
    else:
        await callback.answer(
            f"⚠️ chat_id {chat_id} 已存在", show_alert=True,
        )
    await state.clear()
    await cb_reimburse_subreq_menu(
        callback.model_copy(update={"data": "system:reimburse_subreq"}),
        state,
    )

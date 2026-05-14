"""发布模板管理 handler（Phase 6.2）

Callbacks:
    admin:publish_templates                     模板管理主页
    admin:publish_templates:list                模板列表
    admin:publish_templates:create              新建模板（FSM 两步）
    admin:publish_templates:edit_default        编辑默认模板正文（FSM 一步）
    admin:publish_templates:set_default         设置默认模板（FSM 输入 ID）

FSM (PublishTemplateStates):
    waiting_create_name        新建：第 1 步等模板名称
    waiting_create_text        新建：第 2 步等模板正文（state.data 含 name）
    waiting_edit_text          编辑默认：等新正文（state.data 含 template_id）
    waiting_set_default_id     设置默认：等模板 ID

所有 FSM 支持 /cancel。降级兼容：log_admin_audit 不存在或失败时静默跳过。
"""

import logging

from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from bot.database import (
    create_publish_template,
    get_default_publish_template,
    get_publish_template,
    list_publish_templates,
    set_default_publish_template,
    update_publish_template,
)
from bot.keyboards.admin_kb import (
    publish_templates_cancel_kb,
    publish_templates_list_back_kb,
    publish_templates_menu_kb,
)
from bot.states.teacher_states import PublishTemplateStates
from bot.utils.permissions import admin_required

logger = logging.getLogger(__name__)

router = Router(name="publish_templates")


# 模板变量说明（用于新建/编辑提示）
_VARIABLE_HINT = (
    "可用变量：\n"
    "  {date}              发布日期 (YYYY-MM-DD)\n"
    "  {count}             实际展示的老师数\n"
    "  {grouped_teachers}  按时间段分组的老师文本\n"
    "  {city}              城市名（从 config.city 读取，未设置为空）\n"
    "  {weekday}           中文星期 (周一~周日)"
)


async def _safe_log_admin_audit(
    admin_id: int,
    action: str,
    **kwargs,
) -> None:
    """log_admin_audit 不存在或失败时静默跳过（Phase 1 兼容降级）"""
    try:
        from bot.database import log_admin_audit  # type: ignore
    except ImportError:
        return
    try:
        await log_admin_audit(admin_id=admin_id, action=action, **kwargs)
    except Exception as e:
        logger.debug("log_admin_audit 失败 (action=%s): %s", action, e)


# ============ 主菜单 ============


async def _render_main(target: types.Message | types.CallbackQuery) -> None:
    """渲染模板管理主页"""
    default_tpl = await get_default_publish_template()
    default_name = default_tpl["name"] if default_tpl else "（未设置）"
    text = (
        "📝 发布模板管理\n\n"
        f"当前默认模板：{default_name}"
    )
    kb = publish_templates_menu_kb()
    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin:publish_templates")
@admin_required
async def cb_publish_templates(callback: types.CallbackQuery, state: FSMContext):
    """📝 发布模板管理主页（兼作 FSM 取消的目标）"""
    await state.clear()
    await _render_main(callback)
    await callback.answer()


# ============ /cancel 退出 FSM ============


@router.message(
    Command("cancel"),
    StateFilter(
        PublishTemplateStates.waiting_create_name,
        PublishTemplateStates.waiting_create_text,
        PublishTemplateStates.waiting_edit_text,
        PublishTemplateStates.waiting_set_default_id,
    ),
)
@admin_required
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("已取消")
    await _render_main(message)


# ============ 模板列表 ============


@router.callback_query(F.data == "admin:publish_templates:list")
@admin_required
async def cb_list(callback: types.CallbackQuery, state: FSMContext):
    """📋 模板列表（只显示 active）"""
    await state.clear()
    rows = await list_publish_templates(active_only=True)
    if not rows:
        text = "📋 模板列表\n\n（暂无 active 模板）"
    else:
        lines = [f"📋 模板列表（{len(rows)} 项）", ""]
        for idx, r in enumerate(rows, 1):
            tag = "｜当前默认" if r.get("is_default") else ""
            lines.append(f"{idx}. {r['name']}｜ID {r['id']}{tag}")
        text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=publish_templates_list_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=publish_templates_list_back_kb())
    await callback.answer()


# ============ 新建模板（FSM 两步） ============


@router.callback_query(F.data == "admin:publish_templates:create")
@admin_required
async def cb_create_entry(callback: types.CallbackQuery, state: FSMContext):
    """➕ 新建模板 - 第 1 步：输入名称"""
    await state.set_state(PublishTemplateStates.waiting_create_name)
    text = (
        "➕ 新建模板（1/2）\n\n"
        "请输入模板名称（不能为空，建议简短）：\n"
        "例如：默认模板 / 周末模板 / 节日特别模板\n\n"
        "/cancel 退出"
    )
    try:
        await callback.message.edit_text(text, reply_markup=publish_templates_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=publish_templates_cancel_kb())
    await callback.answer()


@router.message(PublishTemplateStates.waiting_create_name)
@admin_required
async def on_create_name(message: types.Message, state: FSMContext):
    """新建模板 - 第 1 步：收到名称，进入第 2 步等正文"""
    name = (message.text or "").strip()
    if not name:
        await message.reply(
            "❌ 模板名称不能为空，请重新输入或 /cancel",
            reply_markup=publish_templates_cancel_kb(),
        )
        return

    await state.update_data(name=name)
    await state.set_state(PublishTemplateStates.waiting_create_text)
    await message.answer(
        f"➕ 新建模板（2/2）\n\n"
        f"模板名称：{name}\n\n"
        "请输入模板正文（不能为空）。\n\n"
        f"{_VARIABLE_HINT}\n\n"
        "/cancel 退出",
        reply_markup=publish_templates_cancel_kb(),
    )


@router.message(PublishTemplateStates.waiting_create_text)
@admin_required
async def on_create_text(message: types.Message, state: FSMContext):
    """新建模板 - 第 2 步：收到正文，写库"""
    body = (message.text or "").strip()
    if not body:
        await message.reply(
            "❌ 模板正文不能为空，请重新输入或 /cancel",
            reply_markup=publish_templates_cancel_kb(),
        )
        return

    data = await state.get_data()
    name = data.get("name", "").strip()
    if not name:
        await state.clear()
        await message.answer("⚠️ 会话已失效，请重新进入新建流程")
        await _render_main(message)
        return

    new_id = await create_publish_template(name=name, template_text=body, is_default=0)
    await state.clear()

    if new_id is None:
        await message.answer("⚠️ 创建失败，请稍后重试")
        await _render_main(message)
        return

    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="publish_template_create",
        target_type="publish_template",
        target_id=new_id,
        detail={"name": name, "length": len(body)},
    )

    await message.answer(
        f"✅ 已创建模板：{name}（ID {new_id}）\n"
        "如需设为默认，请在「✅ 设置默认模板」中操作。"
    )
    await _render_main(message)


# ============ 编辑默认模板 ============


@router.callback_query(F.data == "admin:publish_templates:edit_default")
@admin_required
async def cb_edit_default_entry(callback: types.CallbackQuery, state: FSMContext):
    """✏️ 编辑默认模板 - 展示当前正文，等新正文"""
    default_tpl = await get_default_publish_template()
    if not default_tpl:
        await callback.answer(
            "⚠️ 当前没有默认模板，请先「➕ 新建模板」并设为默认",
            show_alert=True,
        )
        return

    await state.set_state(PublishTemplateStates.waiting_edit_text)
    await state.update_data(template_id=default_tpl["id"])

    text = (
        f"✏️ 编辑默认模板：{default_tpl['name']}（ID {default_tpl['id']}）\n\n"
        "当前正文：\n"
        f"```\n{default_tpl['template_text']}\n```\n\n"
        "请输入新正文（不能为空，发送后立即生效）：\n\n"
        f"{_VARIABLE_HINT}\n\n"
        "/cancel 退出"
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=publish_templates_cancel_kb(),
            parse_mode="Markdown",
        )
    except Exception:
        # parse_mode 失败兜底
        await callback.message.answer(
            text.replace("```\n", "").replace("\n```", ""),
            reply_markup=publish_templates_cancel_kb(),
        )
    await callback.answer()


@router.message(PublishTemplateStates.waiting_edit_text)
@admin_required
async def on_edit_text(message: types.Message, state: FSMContext):
    """编辑默认模板 - 收到新正文，写库"""
    body = (message.text or "").strip()
    if not body:
        await message.reply(
            "❌ 模板正文不能为空，请重新输入或 /cancel",
            reply_markup=publish_templates_cancel_kb(),
        )
        return

    data = await state.get_data()
    template_id = data.get("template_id")
    if not template_id:
        await state.clear()
        await message.answer("⚠️ 会话已失效，请重新进入编辑流程")
        await _render_main(message)
        return

    ok = await update_publish_template(template_id, template_text=body)
    await state.clear()

    if not ok:
        await message.answer("⚠️ 更新失败（模板可能已被删除），请重试")
        await _render_main(message)
        return

    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="publish_template_update",
        target_type="publish_template",
        target_id=template_id,
        detail={"length": len(body)},
    )

    await message.answer(f"✅ 默认模板正文已更新（ID {template_id}）")
    await _render_main(message)


# ============ 设置默认模板 ============


@router.callback_query(F.data == "admin:publish_templates:set_default")
@admin_required
async def cb_set_default_entry(callback: types.CallbackQuery, state: FSMContext):
    """✅ 设置默认模板 - 展示候选列表 + 等 ID"""
    rows = await list_publish_templates(active_only=True)
    await state.set_state(PublishTemplateStates.waiting_set_default_id)

    lines = ["✅ 设置默认模板\n", "active 模板列表："]
    if not rows:
        lines.append("（暂无 active 模板）")
    else:
        for r in rows:
            mark = "｜★ 默认" if r.get("is_default") else ""
            lines.append(f"- ID {r['id']}：{r['name']}{mark}")
    lines.append("\n请输入要设为默认的模板 ID（纯数字）。\n/cancel 退出")

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=publish_templates_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=publish_templates_cancel_kb())
    await callback.answer()


@router.message(PublishTemplateStates.waiting_set_default_id)
@admin_required
async def on_set_default_id(message: types.Message, state: FSMContext):
    """收到模板 ID，设为默认"""
    text_in = (message.text or "").strip()
    if not text_in.isdigit():
        await message.reply(
            "❌ 请输入纯数字 ID，或 /cancel",
            reply_markup=publish_templates_cancel_kb(),
        )
        return

    tid = int(text_in)
    tpl = await get_publish_template(tid)
    if not tpl:
        await message.reply(
            f"❌ 模板 ID {tid} 不存在，请重试或 /cancel",
            reply_markup=publish_templates_cancel_kb(),
        )
        return
    if not tpl.get("is_active"):
        await message.reply(
            f"❌ 模板 ID {tid} 未启用（is_active=0），请选其他",
            reply_markup=publish_templates_cancel_kb(),
        )
        return

    ok = await set_default_publish_template(tid)
    await state.clear()

    if not ok:
        await message.answer("⚠️ 设置失败，请稍后重试")
        await _render_main(message)
        return

    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="publish_template_set_default",
        target_type="publish_template",
        target_id=tid,
        detail={"name": tpl.get("name")},
    )

    await message.answer(f"✅ 已将「{tpl.get('name')}」（ID {tid}）设为默认模板")
    await _render_main(message)

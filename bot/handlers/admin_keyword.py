"""群组快捷词管理 handler（UX-9.1）

Callbacks:
    admin:keywords                      关键词列表主页
    admin:keywords:add                  新增 - 进入 FSM 输 trigger
    admin:keywords:view:<id>            查看单条详情（其实复用 edit 面板）
    admin:keywords:edit:<id>            编辑面板
    admin:keywords:set_trigger:<id>     编辑 trigger
    admin:keywords:set_banner:<id>      编辑 banner
    admin:keywords:set_body:<id>        编辑 body
    admin:keywords:set_buttons:<id>     编辑 buttons（JSON）
    admin:keywords:toggle:<id>          切换 enabled
    admin:keywords:delete:<id>          删除二次确认
    admin:keywords:delete_yes:<id>      确认删除

FSM (QuickEntryKeywordStates):
    waiting_add_trigger / banner / body / buttons   新增 4 步
    waiting_edit_value                              编辑单字段

降级兼容：log_admin_audit / DB 异常时静默跳过；表缺失时主面板会显示提示。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from bot.database import (
    create_quick_entry_keyword,
    delete_quick_entry_keyword,
    get_quick_entry_keyword,
    list_quick_entry_keywords,
    toggle_quick_entry_enabled,
    update_quick_entry_keyword,
)
from bot.keyboards.admin_kb import (
    admin_keyword_cancel_input_kb,
    admin_keyword_confirm_delete_kb,
    admin_keyword_edit_kb,
    admin_keyword_list_kb,
)
from bot.states.teacher_states import QuickEntryKeywordStates
from bot.utils.permissions import admin_required

logger = logging.getLogger(__name__)

router = Router(name="admin_keyword")


# ============ helpers ============


async def _safe_log_admin_audit(admin_id: int, action: str, **kwargs) -> None:
    """log_admin_audit 缺失 / 异常时静默跳过。"""
    try:
        from bot.database import log_admin_audit  # type: ignore
    except ImportError:
        return
    try:
        await log_admin_audit(admin_id=admin_id, action=action, **kwargs)
    except Exception as e:
        logger.debug("log_admin_audit %s 失败: %s", action, e)


def _kid_from_callback(callback: types.CallbackQuery) -> Optional[int]:
    """从 admin:keywords:<verb>:<id> 类 callback 末尾解析 id。"""
    try:
        return int((callback.data or "").rsplit(":", 1)[-1])
    except (ValueError, TypeError):
        return None


def _render_one_line(it: dict) -> str:
    """单条关键词在列表里的简要文案。"""
    flag = "✅" if int(it.get("enabled") or 0) else "⏸"
    seeded = "（默认）" if int(it.get("seeded") or 0) else ""
    return (
        f"{flag} <code>{it.get('trigger') or '?'}</code>{seeded}  "
        f"命中 {int(it.get('hit_count') or 0)} 次"
    )


def _render_detail(it: dict) -> str:
    """编辑面板上方的详情块。"""
    buttons = it.get("buttons") or []
    if buttons:
        btn_lines = "\n".join(
            f"  • {b[0]} → start={b[1]}"
            for b in buttons
            if isinstance(b, (list, tuple)) and len(b) >= 2
        )
    else:
        btn_lines = "  （空）"
    return (
        f"🗝 关键词详情\n\n"
        f"触发词：<code>{it.get('trigger') or '?'}</code>\n"
        f"启用：{'✅' if int(it.get('enabled') or 0) else '⏸'}\n"
        f"命中次数：{int(it.get('hit_count') or 0)}\n"
        f"是否默认：{'是' if int(it.get('seeded') or 0) else '否'}\n\n"
        f"标题：\n{it.get('banner') or '（空）'}\n\n"
        f"正文：\n{it.get('body') or '（空）'}\n\n"
        f"按钮：\n{btn_lines}"
    )


async def _render_list(target: types.Message | types.CallbackQuery) -> None:
    """渲染关键词列表主页。"""
    items = await list_quick_entry_keywords()
    if not items:
        text = (
            "🗝 群组快捷词管理\n\n"
            "暂无关键词。\n"
            "如果迁移未执行，handler 会自动回退到历史硬编码默认值（菜单/今日/热门/推荐/筛选）。\n"
            "点击下方 [➕ 新增关键词] 创建第一条。"
        )
    else:
        lines = [f"🗝 群组快捷词管理（共 {len(items)} 条）", ""]
        for it in items:
            lines.append(_render_one_line(it))
        text = "\n".join(lines)
    kb = admin_keyword_list_kb(items)
    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await target.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


async def _render_edit(callback: types.CallbackQuery, kid: int) -> None:
    """渲染单条编辑面板。"""
    it = await get_quick_entry_keyword(kid)
    if not it:
        await callback.answer("关键词不存在或已删除", show_alert=True)
        await _render_list(callback)
        return
    try:
        await callback.message.edit_text(
            _render_detail(it),
            reply_markup=admin_keyword_edit_kb(kid),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            _render_detail(it),
            reply_markup=admin_keyword_edit_kb(kid),
            parse_mode="HTML",
        )


# ============ 主入口 ============


@router.callback_query(F.data == "admin:keywords")
@admin_required
async def cb_keywords(callback: types.CallbackQuery, state: FSMContext):
    """🗝 关键词管理主页（兼作 FSM 取消的目标）。"""
    await state.clear()
    await _render_list(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:keywords:view:"))
@admin_required
async def cb_keywords_view(callback: types.CallbackQuery, state: FSMContext):
    """点击某条标题 → 看详情（复用 edit 面板，权限相同）。"""
    await state.clear()
    kid = _kid_from_callback(callback)
    if kid is None:
        await callback.answer("参数错误", show_alert=True)
        return
    await _render_edit(callback, kid)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:keywords:edit:"))
@admin_required
async def cb_keywords_edit(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    kid = _kid_from_callback(callback)
    if kid is None:
        await callback.answer("参数错误", show_alert=True)
        return
    await _render_edit(callback, kid)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:keywords:toggle:"))
@admin_required
async def cb_keywords_toggle(callback: types.CallbackQuery, state: FSMContext):
    """切换 enabled。"""
    kid = _kid_from_callback(callback)
    if kid is None:
        await callback.answer("参数错误", show_alert=True)
        return
    new_state = await toggle_quick_entry_enabled(kid)
    if new_state is None:
        await callback.answer("关键词不存在", show_alert=True)
    else:
        await callback.answer("已启用" if new_state else "已停用")
    await _safe_log_admin_audit(
        admin_id=callback.from_user.id,
        action="quick_entry_toggle",
        payload={"kid": kid, "enabled": bool(new_state)},
    )
    # 切换后留在编辑面板，让管理员看到状态变化
    if new_state is None:
        await _render_list(callback)
    else:
        await _render_edit(callback, kid)


@router.callback_query(F.data.startswith("admin:keywords:delete:"))
@admin_required
async def cb_keywords_delete(callback: types.CallbackQuery, state: FSMContext):
    """删除前二次确认。"""
    kid = _kid_from_callback(callback)
    if kid is None:
        await callback.answer("参数错误", show_alert=True)
        return
    it = await get_quick_entry_keyword(kid)
    if not it:
        await callback.answer("关键词不存在或已删除", show_alert=True)
        await _render_list(callback)
        return
    text = (
        f"⚠️ 确认删除关键词「<code>{it.get('trigger')}</code>」？\n"
        f"该操作不可撤销，删除后群内此关键词将"
        f"{'回退到硬编码默认' if int(it.get('seeded') or 0) else '彻底失效'}。"
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=admin_keyword_confirm_delete_kb(kid),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=admin_keyword_confirm_delete_kb(kid),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:keywords:delete_yes:"))
@admin_required
async def cb_keywords_delete_yes(callback: types.CallbackQuery, state: FSMContext):
    """确认删除：物理删行。"""
    kid = _kid_from_callback(callback)
    if kid is None:
        await callback.answer("参数错误", show_alert=True)
        return
    ok = await delete_quick_entry_keyword(kid)
    await _safe_log_admin_audit(
        admin_id=callback.from_user.id,
        action="quick_entry_delete",
        payload={"kid": kid, "ok": ok},
    )
    await callback.answer("✅ 已删除" if ok else "删除失败")
    await _render_list(callback)


# ============ 新增 FSM ============


@router.callback_query(F.data == "admin:keywords:add")
@admin_required
async def cb_keywords_add(callback: types.CallbackQuery, state: FSMContext):
    """新增 - 第 1 步：等触发词。"""
    await state.clear()
    await state.update_data(mode="add")
    await state.set_state(QuickEntryKeywordStates.waiting_add_trigger)
    try:
        await callback.message.edit_text(
            "➕ 新增关键词（1/4）\n\n请输入触发词（不区分大小写，必须唯一）：\n"
            "示例：菜单、今日开课、热门",
            reply_markup=admin_keyword_cancel_input_kb(),
        )
    except Exception:
        await callback.message.answer(
            "➕ 新增关键词（1/4）\n\n请输入触发词：",
            reply_markup=admin_keyword_cancel_input_kb(),
        )
    await callback.answer()


@router.message(StateFilter(QuickEntryKeywordStates.waiting_add_trigger), F.text)
async def on_add_trigger(message: types.Message, state: FSMContext):
    trigger = (message.text or "").strip()
    if not trigger or len(trigger) > 50:
        await message.answer(
            "触发词长度需 1-50；请重新输入或点 [⬅️ 取消输入] 返回。",
            reply_markup=admin_keyword_cancel_input_kb(),
        )
        return
    await state.update_data(trigger=trigger)
    await state.set_state(QuickEntryKeywordStates.waiting_add_banner)
    await message.answer(
        f"已记录触发词「<code>{trigger}</code>」\n\n"
        f"➕ 新增关键词（2/4）\n请输入标题（banner）：",
        reply_markup=admin_keyword_cancel_input_kb(),
        parse_mode="HTML",
    )


@router.message(StateFilter(QuickEntryKeywordStates.waiting_add_banner), F.text)
async def on_add_banner(message: types.Message, state: FSMContext):
    banner = (message.text or "").strip()
    if not banner or len(banner) > 200:
        await message.answer(
            "标题长度需 1-200；请重新输入或点 [⬅️ 取消输入] 返回。",
            reply_markup=admin_keyword_cancel_input_kb(),
        )
        return
    await state.update_data(banner=banner)
    await state.set_state(QuickEntryKeywordStates.waiting_add_body)
    await message.answer(
        f"➕ 新增关键词（3/4）\n请输入正文（body，可包含换行）：",
        reply_markup=admin_keyword_cancel_input_kb(),
    )


@router.message(StateFilter(QuickEntryKeywordStates.waiting_add_body), F.text)
async def on_add_body(message: types.Message, state: FSMContext):
    body = (message.text or "").strip()
    if not body or len(body) > 1000:
        await message.answer(
            "正文长度需 1-1000；请重新输入或点 [⬅️ 取消输入] 返回。",
            reply_markup=admin_keyword_cancel_input_kb(),
        )
        return
    await state.update_data(body=body)
    await state.set_state(QuickEntryKeywordStates.waiting_add_buttons)
    await message.answer(
        "➕ 新增关键词（4/4）\n"
        "请输入按钮 JSON 数组（最多 6 个，[[label, start_target], ...]）；\n"
        "示例：<code>[[\"打开菜单\", \"menu\"], [\"热门推荐\", \"hot\"]]</code>\n\n"
        "若无按钮，发送 <code>[]</code>。",
        reply_markup=admin_keyword_cancel_input_kb(),
        parse_mode="HTML",
    )


def _parse_buttons_json(raw: str) -> Optional[list]:
    """安全解析按钮 JSON；返回 None 表示无效。"""
    try:
        arr = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(arr, list) or len(arr) > 6:
        return None
    cleaned: list = []
    for row in arr:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            return None
        label, target = row
        if not isinstance(label, str) or not isinstance(target, str):
            return None
        if not label.strip() or not target.strip():
            return None
        cleaned.append([label.strip(), target.strip()])
    return cleaned


@router.message(StateFilter(QuickEntryKeywordStates.waiting_add_buttons), F.text)
async def on_add_buttons(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    buttons = _parse_buttons_json(raw)
    if buttons is None:
        await message.answer(
            "按钮 JSON 解析失败；必须是 <code>[[label, target], ...]</code> 数组，"
            "最多 6 项。请重新输入或点 [⬅️ 取消输入] 返回。",
            reply_markup=admin_keyword_cancel_input_kb(),
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    trigger = data.get("trigger") or ""
    banner = data.get("banner") or ""
    body = data.get("body") or ""
    kid = await create_quick_entry_keyword(
        trigger=trigger, banner=banner, body=body, buttons=buttons, enabled=True,
    )
    await state.clear()
    if kid is None:
        await message.answer(
            f"⚠️ 触发词「<code>{trigger}</code>」已存在或写入失败，请用其他词或返回列表查看。",
            parse_mode="HTML",
        )
        await _render_list(message)
        return
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="quick_entry_create",
        payload={"kid": kid, "trigger": trigger},
    )
    await message.answer(
        f"✅ 已新增关键词「<code>{trigger}</code>」",
        parse_mode="HTML",
    )
    await _render_list(message)


# ============ 编辑单字段 FSM ============


_FIELD_TO_PROMPT = {
    "trigger": ("触发词", 50),
    "banner":  ("标题", 200),
    "body":    ("正文", 1000),
    "buttons": ("按钮 JSON 数组（同新增格式）", 2000),
}


@router.callback_query(F.data.startswith("admin:keywords:set_"))
@admin_required
async def cb_keywords_set_field(callback: types.CallbackQuery, state: FSMContext):
    """admin:keywords:set_<field>:<id> 进入 FSM 编辑单字段。"""
    parts = (callback.data or "").split(":")
    # parts == ["admin", "keywords", "set_<field>", "<id>"]
    if len(parts) < 4:
        await callback.answer("参数错误", show_alert=True)
        return
    field = parts[2].replace("set_", "")
    if field not in _FIELD_TO_PROMPT:
        await callback.answer("未知字段", show_alert=True)
        return
    try:
        kid = int(parts[3])
    except (ValueError, TypeError):
        await callback.answer("参数错误", show_alert=True)
        return
    label, _ = _FIELD_TO_PROMPT[field]
    await state.clear()
    await state.update_data(mode="edit", kid=kid, field=field)
    await state.set_state(QuickEntryKeywordStates.waiting_edit_value)
    try:
        await callback.message.edit_text(
            f"✏️ 编辑「{label}」\n\n请输入新值；点 [⬅️ 取消输入] 返回列表。",
            reply_markup=admin_keyword_cancel_input_kb(),
        )
    except Exception:
        await callback.message.answer(
            f"✏️ 编辑「{label}」\n\n请输入新值。",
            reply_markup=admin_keyword_cancel_input_kb(),
        )
    await callback.answer()


@router.message(StateFilter(QuickEntryKeywordStates.waiting_edit_value), F.text)
async def on_edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    kid = int(data.get("kid") or 0)
    field = data.get("field") or ""
    if kid <= 0 or field not in _FIELD_TO_PROMPT:
        await state.clear()
        await message.answer("状态丢失，请重新进入编辑面板。")
        await _render_list(message)
        return
    raw = (message.text or "").strip()
    label, max_len = _FIELD_TO_PROMPT[field]
    if field == "buttons":
        buttons = _parse_buttons_json(raw)
        if buttons is None:
            await message.answer(
                "按钮 JSON 解析失败，请重新输入。",
                reply_markup=admin_keyword_cancel_input_kb(),
            )
            return
        ok = await update_quick_entry_keyword(kid, buttons=buttons)
    else:
        if not raw or len(raw) > max_len:
            await message.answer(
                f"{label} 长度需 1-{max_len}，请重新输入。",
                reply_markup=admin_keyword_cancel_input_kb(),
            )
            return
        kwargs = {field: raw}
        ok = await update_quick_entry_keyword(kid, **kwargs)
    await state.clear()
    if not ok:
        await message.answer(
            f"⚠️ 更新失败（{label}）；触发词冲突或行不存在。",
        )
        await _render_list(message)
        return
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="quick_entry_update",
        payload={"kid": kid, "field": field},
    )
    await message.answer(f"✅ 已更新「{label}」")
    # 跳回详情页
    it = await get_quick_entry_keyword(kid)
    if it:
        await message.answer(
            _render_detail(it),
            reply_markup=admin_keyword_edit_kb(kid),
            parse_mode="HTML",
        )
    else:
        await _render_list(message)


# ============ /cancel ============


@router.message(
    Command("cancel"),
    StateFilter(
        QuickEntryKeywordStates.waiting_add_trigger,
        QuickEntryKeywordStates.waiting_add_banner,
        QuickEntryKeywordStates.waiting_add_body,
        QuickEntryKeywordStates.waiting_add_buttons,
        QuickEntryKeywordStates.waiting_edit_value,
    ),
)
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("已取消。")
    await _render_list(message)

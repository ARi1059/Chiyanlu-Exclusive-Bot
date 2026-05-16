"""Phase 9.1：老师档案完整录入 FSM + 子菜单入口

Commit 2 范围：
- [📋 老师档案管理] 子菜单（tprofile:menu）
- [➕ 完整档案录入] 15 步 FSM（含 photos 多图 + 确认）
- [✏️ 编辑] / [🖼 相册] / [👁 预览] 按钮先做占位（Commit 3/4 补全）

callback 命名空间统一前缀 tprofile:* ，与旧 teacher:* 不冲突。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from bot.database import (
    add_teacher,
    get_teacher,
    set_teacher_photos,
    parse_basic_info,
)
from bot.keyboards.admin_kb import (
    teacher_menu_kb,
    teacher_profile_menu_kb,
    teacher_profile_cancel_kb,
    teacher_profile_skip_cancel_kb,
    teacher_profile_photos_done_kb,
    teacher_profile_confirm_kb,
)
from bot.states.teacher_states import TeacherProfileAddStates
from bot.utils.permissions import admin_required
from bot.utils.url import normalize_url

router = Router(name="teacher_profile")


# 总步数（用于"Step X/15"提示）
_TOTAL_STEPS = 15


# ============ 子菜单入口 ============

@router.callback_query(F.data == "tprofile:menu")
@admin_required
async def cb_profile_menu(callback: types.CallbackQuery, state: FSMContext):
    """[📋 老师档案管理] 主面板"""
    await state.clear()
    await callback.message.edit_text(
        "📋 老师档案管理\n\n"
        "管理老师的完整档案（用于 Phase 9.2 频道发布）。\n"
        "- ➕ 完整档案录入：从零新建一位老师\n"
        "- ✏️ 编辑：修改已有老师的某个字段\n"
        "- 🖼 相册：管理老师的照片相册（最多 10 张）\n"
        "- 👁 预览：查看档案 caption 渲染效果",
        reply_markup=teacher_profile_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "tprofile:cancel")
@admin_required
async def cb_profile_cancel(callback: types.CallbackQuery, state: FSMContext):
    """取消任意子流程，回到 [📋 老师档案管理]"""
    await state.clear()
    await callback.message.edit_text(
        "📋 老师档案管理",
        reply_markup=teacher_profile_menu_kb(),
    )
    await callback.answer("已取消")


# ============ 完整档案录入 FSM ============

@router.callback_query(F.data == "tprofile:add")
@admin_required
async def cb_profile_add_start(callback: types.CallbackQuery, state: FSMContext):
    """[➕ 完整档案录入] 入口 → 进入 Step 1（user_id）"""
    await state.set_state(TeacherProfileAddStates.waiting_user_id)
    await state.set_data({"photos": []})
    await callback.message.edit_text(
        f"[Step 1/{_TOTAL_STEPS}] 老师 Telegram 数字 ID\n\n"
        "请输入老师的 Telegram user_id（纯数字）。\n"
        "任意一步发 /cancel 中止。",
        reply_markup=teacher_profile_cancel_kb(),
    )
    await callback.answer()


@router.message(TeacherProfileAddStates.waiting_user_id)
@admin_required
async def step_user_id(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text.isdigit():
        await message.reply("❌ 请输入纯数字 user_id。")
        return
    user_id = int(text)
    existing = await get_teacher(user_id)
    if existing:
        status = "启用中" if existing["is_active"] else "已停用"
        await message.reply(
            f"⚠️ 该 ID 已存在老师：{existing['display_name']}（{status}）\n"
            "如需编辑请用 [✏️ 编辑老师档案]；或换一个 user_id。"
        )
        return
    await state.update_data(user_id=user_id)
    await state.set_state(TeacherProfileAddStates.waiting_username)
    await message.answer(
        f"[Step 2/{_TOTAL_STEPS}] Telegram 用户名\n\n"
        "请输入老师的 Telegram username（不带 @，例如 chixiaoxia）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_username)
@admin_required
async def step_username(message: types.Message, state: FSMContext):
    text = (message.text or "").strip().lstrip("@")
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text or not re.fullmatch(r"[A-Za-z0-9_]{4,32}", text):
        await message.reply("❌ username 需 4-32 个字母/数字/下划线，不带 @。")
        return
    await state.update_data(username=text)
    await state.set_state(TeacherProfileAddStates.waiting_display_name)
    await message.answer(
        f"[Step 3/{_TOTAL_STEPS}] 老师艺名\n\n"
        "请输入老师的艺名（如：丁小夏）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_display_name)
@admin_required
async def step_display_name(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text or len(text) > 40:
        await message.reply("❌ 艺名不能为空，长度 ≤ 40。")
        return
    await state.update_data(display_name=text)
    await state.set_state(TeacherProfileAddStates.waiting_basic_info)
    await message.answer(
        f"[Step 4/{_TOTAL_STEPS}] 基本信息\n\n"
        "请用一行回复：年龄 身高(cm) 体重(kg) 罩杯，空格分隔。\n"
        "例如：25 172 90 B\n"
        "范围：年龄 15-60 / 身高 140-200 / 体重 35-120。",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_basic_info)
@admin_required
async def step_basic_info(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    info = parse_basic_info(text)
    if info is None:
        await message.reply(
            "❌ 格式不对或数值越界。请重发，例如：25 172 90 B\n"
            "年龄 15-60 / 身高 140-200 / 体重 35-120 / 罩杯 1-3 个字母。"
        )
        return
    await state.update_data(**info)
    await state.set_state(TeacherProfileAddStates.waiting_description)
    await message.answer(
        f"[Step 5/{_TOTAL_STEPS}] 描述（可跳过）\n\n"
        "请输入对老师的简短描述，或点击 [⏭️ 跳过]。",
        reply_markup=teacher_profile_skip_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_description)
@admin_required
async def step_description(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if text == "跳过":
        text = ""
    await state.update_data(description=(text or None))
    await _enter_service_content(message, state)


@router.message(TeacherProfileAddStates.waiting_service_content)
@admin_required
async def step_service_content(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if text == "跳过":
        text = ""
    await state.update_data(service_content=(text or None))
    await _enter_price_detail(message, state)


@router.message(TeacherProfileAddStates.waiting_price_detail)
@admin_required
async def step_price_detail(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text:
        await message.reply("❌ 价格详述不能为空。")
        return
    await state.update_data(price_detail=text)
    await state.set_state(TeacherProfileAddStates.waiting_taboos)
    await message.answer(
        f"[Step 8/{_TOTAL_STEPS}] 禁忌（可跳过）\n\n"
        "请输入老师的禁忌项（如不接受的服务），或点击 [⏭️ 跳过]。",
        reply_markup=teacher_profile_skip_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_taboos)
@admin_required
async def step_taboos(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if text == "跳过":
        text = ""
    await state.update_data(taboos=(text or None))
    await _enter_contact_telegram(message, state)


@router.message(TeacherProfileAddStates.waiting_contact_telegram)
@admin_required
async def step_contact_telegram(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    # 必须以 @ 开头
    if not text.startswith("@") or not re.fullmatch(r"@[A-Za-z0-9_]{4,32}", text):
        await message.reply(
            "❌ 联系电报必须以 @ 开头，4-32 个字母/数字/下划线，例如：@chixiaoxia"
        )
        return
    await state.update_data(contact_telegram=text)
    await state.set_state(TeacherProfileAddStates.waiting_region)
    await message.answer(
        f"[Step 10/{_TOTAL_STEPS}] 地区\n\n请输入老师所在地区（如：天府一街）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_region)
@admin_required
async def step_region(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text:
        await message.reply("❌ 地区不能为空。")
        return
    await state.update_data(region=text)
    await state.set_state(TeacherProfileAddStates.waiting_price)
    await message.answer(
        f'[Step 11/{_TOTAL_STEPS}] 价格（排序用）\n\n'
        "请输入老师的价格短标签（用于列表排序与展示，如：3000P）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_price)
@admin_required
async def step_price(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text:
        await message.reply("❌ 价格不能为空。")
        return
    await state.update_data(price=text)
    await state.set_state(TeacherProfileAddStates.waiting_tags)
    await message.answer(
        f"[Step 12/{_TOTAL_STEPS}] 标签\n\n"
        "用空格或逗号分隔多个标签（如：御姐 高颜值 服务好）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_tags)
@admin_required
async def step_tags(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    tags = [t.strip().lstrip("#") for t in re.split(r"[,，\s]+", text) if t.strip()]
    if not tags:
        await message.reply("❌ 至少输入一个标签。")
        return
    await state.update_data(tags=tags)
    await state.set_state(TeacherProfileAddStates.waiting_button_url)
    await message.answer(
        f"[Step 13/{_TOTAL_STEPS}] 跳转链接\n\n"
        "请输入老师卡片按钮的跳转链接（http://、https:// 或 tg://）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_button_url)
@admin_required
async def step_button_url(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    url = normalize_url(text)
    if not url:
        await message.reply(
            "❌ 请输入有效 URL（http://、https:// 或 tg:// 开头，且不含空格）。"
        )
        return
    await state.update_data(button_url=url)
    await state.set_state(TeacherProfileAddStates.waiting_button_text)
    await message.answer(
        f"[Step 14/{_TOTAL_STEPS}] 按钮文字（可跳过）\n\n"
        "请输入卡片按钮上显示的文字（默认用艺名）。",
        reply_markup=teacher_profile_skip_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_button_text)
@admin_required
async def step_button_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if text == "跳过":
        text = ""
    await state.update_data(button_text=(text or None))
    await _enter_photos(message, state)


@router.message(TeacherProfileAddStates.waiting_photos, F.photo)
@admin_required
async def step_photos_recv(message: types.Message, state: FSMContext):
    """收图：累加到 photos 列表（上限 10 张）"""
    data = await state.get_data()
    photos: list = list(data.get("photos") or [])
    if len(photos) >= 10:
        await message.reply('⚠️ 已达 10 张上限，请发 "完成" 或撤销最后一张。')
        return
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(photos=photos)
    await message.reply(
        f"✅ 已收到，当前 {len(photos)}/10。\n"
        "继续发送更多照片，或点击 [✅ 完成上传]。"
    )


@router.message(TeacherProfileAddStates.waiting_photos)
@admin_required
async def step_photos_text(message: types.Message, state: FSMContext):
    """非图片消息：识别"完成" / /cancel / 其他文字"""
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if text in {"完成", "done", "Done", "DONE"}:
        return await _enter_confirm(message, state)
    await message.reply(
        "ℹ️ 请发送图片，或点击 [✅ 完成上传] / [❌ 取消]。"
    )


# ============ 可跳过字段的"⏭️ 跳过"按钮 ============

@router.callback_query(F.data == "tprofile:skip")
@admin_required
async def cb_profile_skip(callback: types.CallbackQuery, state: FSMContext):
    cur = await state.get_state()
    if cur == TeacherProfileAddStates.waiting_description.state:
        await state.update_data(description=None)
        await _enter_service_content(callback.message, state, via_edit=True)
    elif cur == TeacherProfileAddStates.waiting_service_content.state:
        await state.update_data(service_content=None)
        await _enter_price_detail(callback.message, state, via_edit=True)
    elif cur == TeacherProfileAddStates.waiting_taboos.state:
        await state.update_data(taboos=None)
        await _enter_contact_telegram(callback.message, state, via_edit=True)
    elif cur == TeacherProfileAddStates.waiting_button_text.state:
        await state.update_data(button_text=None)
        await _enter_photos(callback.message, state, via_edit=True)
    else:
        await callback.answer("当前步骤不支持跳过", show_alert=True)
        return
    await callback.answer("已跳过")


# ============ 照片步骤的按钮 ============

@router.callback_query(F.data == "tprofile:photos_done")
@admin_required
async def cb_photos_done(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != TeacherProfileAddStates.waiting_photos.state:
        await callback.answer()
        return
    data = await state.get_data()
    photos = data.get("photos") or []
    if len(photos) < 1:
        await callback.answer("至少上传 1 张照片", show_alert=True)
        return
    await _enter_confirm(callback.message, state, via_edit=False)
    await callback.answer()


@router.callback_query(F.data == "tprofile:photos_undo")
@admin_required
async def cb_photos_undo(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != TeacherProfileAddStates.waiting_photos.state:
        await callback.answer()
        return
    data = await state.get_data()
    photos = list(data.get("photos") or [])
    if not photos:
        await callback.answer("当前没有照片可撤销", show_alert=True)
        return
    photos.pop()
    await state.update_data(photos=photos)
    await callback.answer(f"已撤销，当前 {len(photos)}/10")


# ============ 确认页 ============

@router.callback_query(F.data == "tprofile:save", TeacherProfileAddStates.waiting_confirm)
@admin_required
async def cb_profile_save(callback: types.CallbackQuery, state: FSMContext):
    """[✅ 保存到 DB] → 入库 + 写相册"""
    data = await state.get_data()
    photos: list = list(data.get("photos") or [])
    if not photos:
        await callback.answer("缺少照片，无法保存", show_alert=True)
        return

    teacher_data = {
        "user_id":     data["user_id"],
        "username":    data["username"],
        "display_name": data["display_name"],
        "region":      data["region"],
        "price":       data["price"],
        "tags":        json.dumps(data["tags"], ensure_ascii=False),
        "photo_file_id": photos[0],  # 旧字段兼容（set_teacher_photos 也会写）
        "button_url":  data["button_url"],
        "button_text": data.get("button_text") or data["display_name"],
    }
    ok = await add_teacher(teacher_data)
    if not ok:
        await callback.message.edit_text(
            f"⚠️ 保存失败：user_id={data['user_id']} 可能已存在。",
            reply_markup=teacher_profile_menu_kb(),
        )
        await state.clear()
        await callback.answer()
        return

    # 写 Phase 9.1 新字段（白名单逐项更新）
    from bot.database import update_teacher_profile_field
    optional_fields = [
        "age", "height_cm", "weight_kg", "bra_size",
        "description", "service_content", "price_detail", "taboos",
        "contact_telegram",
    ]
    for f in optional_fields:
        v = data.get(f)
        if v is None:
            continue
        await update_teacher_profile_field(data["user_id"], f, v)

    # 写相册（同步更新旧 photo_file_id 为第一张）
    await set_teacher_photos(data["user_id"], photos)

    await state.clear()
    await callback.message.edit_text(
        f"✅ 老师档案「{data['display_name']}」保存成功。\n"
        f"📸 相册 {len(photos)} 张已入库。",
        reply_markup=teacher_profile_menu_kb(),
    )
    await callback.answer("已保存")


# ============ /cancel 文本退出（任意 FSM 步骤）============

@router.message(F.text == "/cancel", TeacherProfileAddStates())
@admin_required
async def cmd_cancel_in_profile_fsm(message: types.Message, state: FSMContext):
    await _do_cancel(message, state)


# ============ Commit 3/4 占位（避免按钮无反应）============

@router.callback_query(F.data.in_({"tprofile:edit", "tprofile:album", "tprofile:preview"}))
@admin_required
async def cb_not_yet(callback: types.CallbackQuery):
    await callback.answer("将在 Phase 9.1.3 / 9.1.4 启用", show_alert=True)


# ============ 内部转移辅助 ============

async def _enter_service_content(
    msg: types.Message, state: FSMContext, *, via_edit: bool = False
):
    await state.set_state(TeacherProfileAddStates.waiting_service_content)
    text = (
        f"[Step 6/{_TOTAL_STEPS}] 服务内容（可跳过）\n\n"
        "请输入老师的服务范围（如：包夜 ¥3000），或点击 [⏭️ 跳过]。"
    )
    await _show(msg, text, teacher_profile_skip_cancel_kb(), via_edit)


async def _enter_price_detail(
    msg: types.Message, state: FSMContext, *, via_edit: bool = False
):
    await state.set_state(TeacherProfileAddStates.waiting_price_detail)
    text = (
        f"[Step 7/{_TOTAL_STEPS}] 价格详述\n\n"
        "请输入价格详情（如：包夜 3000 ¥；半天 1500 ¥）。"
    )
    await _show(msg, text, teacher_profile_cancel_kb(), via_edit)


async def _enter_contact_telegram(
    msg: types.Message, state: FSMContext, *, via_edit: bool = False
):
    await state.set_state(TeacherProfileAddStates.waiting_contact_telegram)
    text = (
        f"[Step 9/{_TOTAL_STEPS}] 联系电报\n\n"
        "请输入老师的电报联系账号，必须以 @ 开头（例如 @chixiaoxia）。"
    )
    await _show(msg, text, teacher_profile_cancel_kb(), via_edit)


async def _enter_photos(
    msg: types.Message, state: FSMContext, *, via_edit: bool = False
):
    await state.set_state(TeacherProfileAddStates.waiting_photos)
    data = await state.get_data()
    n = len(data.get("photos") or [])
    text = (
        f"[Step 15/{_TOTAL_STEPS}] 上传照片相册\n\n"
        "请发送 1-10 张图片，每发一张回复进度。\n"
        "全部发送完后点击 [✅ 完成上传]。\n"
        f"当前已上传：{n}/10"
    )
    await _show(msg, text, teacher_profile_photos_done_kb(), via_edit)


async def _enter_confirm(
    msg: types.Message, state: FSMContext, *, via_edit: bool = False
):
    await state.set_state(TeacherProfileAddStates.waiting_confirm)
    data = await state.get_data()
    text = _render_confirm_text(data)
    await _show(msg, text, teacher_profile_confirm_kb(), via_edit)


def _render_confirm_text(d: dict) -> str:
    tags = d.get("tags") or []
    photos = d.get("photos") or []
    lines = [
        "📋 档案预览（确认前最后一步）",
        "━━━━━━━━━━━━━━━",
        f"👤 {d.get('display_name', '?')}",
        f"🆔 {d.get('user_id', '?')} (@{d.get('username', '?')})",
        f"📋 {d.get('age', '?')} 岁 · {d.get('height_cm', '?')}cm · "
        f"{d.get('weight_kg', '?')}kg · 胸 {d.get('bra_size', '?')}",
    ]
    if d.get("description"):
        lines.append(f"📋 描述：{d['description']}")
    if d.get("service_content"):
        lines.append(f"📋 服务：{d['service_content']}")
    lines.append(f"💰 价格详述：{d.get('price_detail', '?')}")
    if d.get("taboos"):
        lines.append(f"🚫 禁忌：{d['taboos']}")
    lines.append(f"☎ 联系电报：{d.get('contact_telegram', '?')}")
    lines.append(f"📍 地区：{d.get('region', '?')}")
    lines.append(f"💰 价格(排序)：{d.get('price', '?')}")
    lines.append(f"🏷 标签：{' | '.join(tags) if tags else '-'}")
    lines.append(f"🔗 跳转链接：{d.get('button_url', '?')}")
    lines.append(f"🔠 按钮文字：{d.get('button_text') or d.get('display_name', '?')}")
    lines.append(f"📸 已上传 {len(photos)} 张照片")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("确认无误后点击 [✅ 保存到 DB]。")
    return "\n".join(lines)


async def _show(
    msg: types.Message, text: str, kb, via_edit: bool
):
    """统一显示文本（callback 改 edit_text，message 用 answer）"""
    if via_edit:
        try:
            await msg.edit_text(text, reply_markup=kb)
            return
        except Exception:
            # 不能 edit（例如包含媒体）时回退
            pass
    await msg.answer(text, reply_markup=kb)


async def _do_cancel(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "❌ 已取消档案录入。",
        reply_markup=teacher_menu_kb(),
    )

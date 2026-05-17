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
    teacher_profile_select_kb,
    teacher_profile_edit_field_kb,
    teacher_profile_album_menu_kb,
    teacher_profile_album_remove_kb,
    teacher_profile_album_collect_kb,
)
from bot.states.teacher_states import (
    TeacherProfileAddStates,
    TeacherProfileEditStates,
    TeacherProfileAlbumStates,
)
from bot.utils.permissions import admin_required
from bot.utils.url import normalize_url

router = Router(name="teacher_profile")


# 总步数（v2 2026-05-17：精简到 9 步主路径）
_TOTAL_STEPS = 9

# Step 5 自动写死禁忌
DEFAULT_TABOOS: str = "桩机 粗大长 口嗨 变态 后花园 醉酒 无套 暴力 嗑药"


def _extract_largest_price(text: str) -> Optional[str]:
    """从「价格描述」抽出所有形如 '\\d+P' 的数字，取最大值作为价格（排序用）

    返回 'NP' 字符串；找不到任何 P 数字时返 None。
    """
    if not text:
        return None
    matches = re.findall(r"(\d+)\s*[Pp](?![a-zA-Z])", text)
    if not matches:
        return None
    try:
        nums = [int(m) for m in matches]
    except (TypeError, ValueError):
        return None
    return f"{max(nums)}P"


def _compute_description_from_price(price: Optional[str]) -> str:
    """按 raw price 抽数字 // 100 = displayed 价位档自动生成描述

    - displayed ≤ 8  → 报销 100 元 → "出击加分 1分 报销金额 100元"
    - displayed == 9 → 报销 150 元 → "出击加分 1分 报销金额 150元"
    - displayed ≥ 10 → 报销 200 元 → "出击加分 1分 报销金额 200元"
    - 解析失败 / 无数字 → ""（保留空字符串，不影响保存）
    """
    if not price:
        return ""
    digits = "".join(c for c in str(price) if c.isdigit())
    if not digits:
        return ""
    n = int(digits) // 100
    if n <= 8:
        amount = 100
    elif n == 9:
        amount = 150
    else:
        amount = 200
    return f"出击加分 1分 报销金额 {amount}元"


def _extract_from_forward(message: types.Message) -> Optional[dict]:
    """从转发消息抽取老师身份：user_id / username / @contact_telegram

    成功 → {"user_id", "username", "contact_telegram"}（username/contact 可能为 None）
    失败（forward_from 缺失 / 被隐藏）→ None
    """
    src = getattr(message, "forward_from", None)
    if src is None:
        # 老 API fallback：forward_origin（pydantic v2 / aiogram 3.x）
        origin = getattr(message, "forward_origin", None)
        if origin is not None and getattr(origin, "type", "") == "user":
            src = getattr(origin, "sender_user", None)
    if src is None:
        return None
    uid = getattr(src, "id", None)
    if uid is None:
        return None
    uname = getattr(src, "username", None)
    contact = f"@{uname}" if uname else None
    return {
        "user_id": int(uid),
        "username": uname,
        "contact_telegram": contact,
    }


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
    """[➕ 完整档案录入] 入口 → Step 1 转发老师消息"""
    await state.set_state(TeacherProfileAddStates.waiting_forward)
    await state.set_data({"photos": []})
    await callback.message.edit_text(
        f"[Step 1/{_TOTAL_STEPS}] 转发老师消息\n\n"
        "请直接转发一条老师本人发出的消息。\n"
        "bot 会自动抓取 user_id / username / @contact_telegram 三项信息。\n\n"
        "⚠️ 若老师 Telegram 隐私设置了「转发消息 → 没有人」，bot 收不到\n"
        "→ 会自动跳到手动录入 3 个字段。\n\n"
        "任意一步发 /cancel 中止。",
        reply_markup=teacher_profile_cancel_kb(),
    )
    await callback.answer()


# --- Step 1 主：转发消息（自动抓 user_id + username + contact） ---

@router.message(TeacherProfileAddStates.waiting_forward)
@admin_required
async def step_forward(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    info = _extract_from_forward(message)
    if info is None:
        await state.set_state(TeacherProfileAddStates.waiting_manual_user_id)
        await message.reply(
            "⚠️ 未获取到老师信息（可能老师隐藏了转发来源）。请手动录入：\n\n"
            f"[Step 1a/{_TOTAL_STEPS}] 老师 Telegram 数字 ID",
            reply_markup=teacher_profile_cancel_kb(),
        )
        return
    existing = await get_teacher(info["user_id"])
    if existing:
        status = "启用中" if existing["is_active"] else "已停用"
        await message.reply(
            f"⚠️ user_id={info['user_id']} 已存在老师："
            f"{existing['display_name']}（{status}）\n"
            "请转发其他老师的消息，或 /cancel。"
        )
        return
    uname = info.get("username")
    if uname and not re.fullmatch(r"[A-Za-z0-9_]{4,32}", uname):
        uname = None
    contact = f"@{uname}" if uname else None
    if not contact:
        # 有 user_id 但无 username → 手动补
        await state.update_data(user_id=info["user_id"])
        await state.set_state(TeacherProfileAddStates.waiting_manual_username)
        await message.reply(
            f"✅ 已抓取 user_id={info['user_id']}\n"
            "⚠️ 老师无 username，无法自动构造 @contact_telegram\n\n"
            f"[Step 1b/{_TOTAL_STEPS}] 请输入 username（不带 @）",
            reply_markup=teacher_profile_cancel_kb(),
        )
        return
    await state.update_data(
        user_id=info["user_id"], username=uname, contact_telegram=contact,
    )
    await message.reply(
        f"✅ 自动抓取：\n"
        f"  user_id = {info['user_id']}\n"
        f"  username = {uname}\n"
        f"  contact = {contact}"
    )
    await _enter_display_name(message, state)


# --- Step 1 备用：手动 3 子步 ---

@router.message(TeacherProfileAddStates.waiting_manual_user_id)
@admin_required
async def step_manual_user_id(message: types.Message, state: FSMContext):
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
            f"⚠️ 该 ID 已存在：{existing['display_name']}（{status}）"
        )
        return
    await state.update_data(user_id=user_id)
    await state.set_state(TeacherProfileAddStates.waiting_manual_username)
    await message.answer(
        f"[Step 1b/{_TOTAL_STEPS}] Telegram username（不带 @；4-32 字母/数字/下划线）",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_manual_username)
@admin_required
async def step_manual_username(message: types.Message, state: FSMContext):
    text = (message.text or "").strip().lstrip("@")
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text or not re.fullmatch(r"[A-Za-z0-9_]{4,32}", text):
        await message.reply("❌ username 需 4-32 字母/数字/下划线。")
        return
    await state.update_data(username=text)
    await state.set_state(TeacherProfileAddStates.waiting_manual_contact)
    await message.answer(
        f"[Step 1c/{_TOTAL_STEPS}] 联系电报（必须 @ 开头，如 @chixiaoxia）",
        reply_markup=teacher_profile_cancel_kb(),
    )


@router.message(TeacherProfileAddStates.waiting_manual_contact)
@admin_required
async def step_manual_contact(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text.startswith("@") or not re.fullmatch(r"@[A-Za-z0-9_]{4,32}", text):
        await message.reply(
            "❌ 联系电报必须 @ 开头，4-32 字母/数字/下划线（如 @chixiaoxia）。"
        )
        return
    await state.update_data(contact_telegram=text)
    await _enter_display_name(message, state)


# --- Step 2 艺名 ---

async def _enter_display_name(msg, state: FSMContext):
    await state.set_state(TeacherProfileAddStates.waiting_display_name)
    await msg.answer(
        f"[Step 2/{_TOTAL_STEPS}] 艺名\n\n请输入老师的艺名（如：丁小夏）。",
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
        f"[Step 3/{_TOTAL_STEPS}] 基本信息\n\n"
        "请用一行回复：年龄 身高(cm) 体重(kg) 罩杯，空格分隔。\n"
        "例如：25 172 90 B\n"
        "范围：年龄 15-60 / 身高 140-200 / 体重 35-120。",
        reply_markup=teacher_profile_cancel_kb(),
    )


# --- Step 3 基本信息 ---

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
            "年龄 15-60 / 身高 140-200 / 体重 35-120 / 罩杯 1-3 字母。"
        )
        return
    await state.update_data(**info)
    await state.set_state(TeacherProfileAddStates.waiting_region)
    await message.answer(
        f"[Step 4/{_TOTAL_STEPS}] 地区\n\n请输入老师所在地区（如：金融城 · 成都）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


# --- Step 4 地区 ---

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
    await state.set_state(TeacherProfileAddStates.waiting_price_detail)
    await message.answer(
        f"[Step 5/{_TOTAL_STEPS}] 价格描述\n\n"
        "请输入价格详情（如：包夜 800P 半天 500P）。\n"
        "bot 会自动派生：\n"
        "  - 价格（排序用）= 最大数字+P\n"
        "  - 描述 = 按价位档生成「出击加分 / 报销金额」\n"
        "  - 禁忌 = 默认硬编码",
        reply_markup=teacher_profile_cancel_kb(),
    )


# --- Step 5 价格描述（自动派生 price + description + taboos） ---

@router.message(TeacherProfileAddStates.waiting_price_detail)
@admin_required
async def step_price_detail(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if not text:
        await message.reply("❌ 价格描述不能为空。")
        return
    price = _extract_largest_price(text)
    if not price:
        await message.reply(
            "❌ 价格描述里找不到「数字+P」格式（如 800P）。\n"
            "请补上至少一个数字+P，例如：包夜 800P 半天 500P"
        )
        return
    description = _compute_description_from_price(price)
    await state.update_data(
        price_detail=text,
        price=price,
        description=description,
        taboos=DEFAULT_TABOOS,
    )
    await message.reply(
        f"✅ 自动派生：\n"
        f"  价格 = {price}\n"
        f"  描述 = {description}\n"
        f"  禁忌 = {DEFAULT_TABOOS}"
    )
    await state.set_state(TeacherProfileAddStates.waiting_service_content)
    await message.answer(
        f"[Step 6/{_TOTAL_STEPS}] 服务内容（可跳过）\n\n"
        "请输入老师的服务范围（如：包夜 ¥3000 含 X 项），或点击 [⏭️ 跳过]。",
        reply_markup=teacher_profile_skip_cancel_kb(),
    )


# --- Step 6 服务内容（可跳过） ---

@router.message(TeacherProfileAddStates.waiting_service_content)
@admin_required
async def step_service_content(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await _do_cancel(message, state)
    if text == "跳过":
        text = ""
    await state.update_data(service_content=(text or None))
    await state.set_state(TeacherProfileAddStates.waiting_tags)
    await message.answer(
        f"[Step 7/{_TOTAL_STEPS}] 标签\n\n"
        "用空格或逗号分隔多个标签（如：御姐 高颜值 服务好）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


# --- Step 7 标签 ---

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
        f"[Step 8/{_TOTAL_STEPS}] 跳转链接\n\n"
        "请输入老师卡片按钮的跳转链接（http://、https:// 或 tg://）。",
        reply_markup=teacher_profile_cancel_kb(),
    )


# --- Step 8 跳转链接（直接进相册，button_text 在 save 时自动生成 = "地区 艺名"） ---

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
    await _enter_photos(message, state)


# --- Step 9 上传相册（支持媒体组聚合 reply） ---

# 媒体组 reply debounce：chat_id → asyncio.Task；同 group 600ms 内只 reply 一次
import asyncio as _asyncio
_PHOTO_GROUP_REPLY_TASKS: dict[int, "_asyncio.Task"] = {}


@router.message(TeacherProfileAddStates.waiting_photos, F.photo)
@admin_required
async def step_photos_recv(message: types.Message, state: FSMContext):
    """收图：累加到 photos 列表（上限 10 张）

    单张照片 → 立即 reply 进度
    媒体组（多张连发）→ 600ms debounce 后 reply 一次，避免刷屏
    """
    data = await state.get_data()
    photos: list = list(data.get("photos") or [])
    if len(photos) >= 10:
        await message.reply('⚠️ 已达 10 张上限，请发 "完成" 或撤销最后一张。')
        return
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(photos=photos)

    chat_id = message.chat.id
    if message.media_group_id is None:
        await message.reply(
            f"✅ 已收到，当前 {len(photos)}/10。\n"
            "继续发送更多照片，或点击 [✅ 完成上传]。"
        )
        return

    # 媒体组：取消旧 debounce task，重新起一个
    old = _PHOTO_GROUP_REPLY_TASKS.get(chat_id)
    if old and not old.done():
        old.cancel()
    bot_ref = message.bot

    async def _debounced_reply():
        try:
            await _asyncio.sleep(0.6)
            d = await state.get_data()
            n = len(d.get("photos") or [])
            await bot_ref.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ 已接收媒体组，当前 {n}/10。\n"
                    "继续发送更多照片，或点击 [✅ 完成上传]。"
                ),
            )
        except _asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            _PHOTO_GROUP_REPLY_TASKS.pop(chat_id, None)

    _PHOTO_GROUP_REPLY_TASKS[chat_id] = _asyncio.create_task(_debounced_reply())


@router.message(TeacherProfileAddStates.waiting_photos)
@admin_required
async def step_photos_text(message: types.Message, state: FSMContext):
    """非图片：识别"完成" / /cancel / 其他文字"""
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
    """v2：仅 service_content 一步可跳"""
    cur = await state.get_state()
    if cur == TeacherProfileAddStates.waiting_service_content.state:
        await state.update_data(service_content=None)
        await state.set_state(TeacherProfileAddStates.waiting_tags)
        text = (
            f"[Step 7/{_TOTAL_STEPS}] 标签\n\n"
            "用空格或逗号分隔多个标签（如：御姐 高颜值 服务好）。"
        )
        try:
            await callback.message.edit_text(text, reply_markup=teacher_profile_cancel_kb())
        except Exception:
            await callback.message.answer(text, reply_markup=teacher_profile_cancel_kb())
        await callback.answer("已跳过")
    else:
        await callback.answer("当前步骤不支持跳过", show_alert=True)


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
    """[✅ 保存到 DB] → 入库 + 写相册（button_text 自动 = '地区 艺名'）"""
    data = await state.get_data()
    photos: list = list(data.get("photos") or [])
    if not photos:
        await callback.answer("缺少照片，无法保存", show_alert=True)
        return

    region = data.get("region", "")
    display_name = data.get("display_name", "")
    auto_button_text = f"{region} {display_name}".strip() or display_name

    teacher_data = {
        "user_id":     data["user_id"],
        "username":    data["username"],
        "display_name": display_name,
        "region":      region,
        "price":       data["price"],
        "tags":        json.dumps(data["tags"], ensure_ascii=False),
        "photo_file_id": photos[0],
        "button_url":  data["button_url"],
        "button_text": auto_button_text,
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


# ============ 老数据一键同步（2026-05-17）============
#
# 把所有已存在老师的 3 个字段强制刷成新规则：
#   - description = 按 price 档位 (出击加分 1分 报销金额 100/150/200元)
#   - taboos = DEFAULT_TABOOS（写死字符串）
#   - button_text = "地区 艺名"
# admin 之前手动改过的会被覆盖。两步确认 + 详细统计 + audit。


def _compute_legacy_sync_target(t: dict) -> dict:
    """对一个老师计算 3 个新字段值（不写 DB）

    返回 {description, taboos, button_text}；其中 description 在老师 price
    无数字时为 ""（此时跳过更新），button_text 缺地区时退化为 display_name。
    """
    desc = _compute_description_from_price(t.get("price"))
    taboos = DEFAULT_TABOOS
    region = (t.get("region") or "").strip()
    name = (t.get("display_name") or "").strip()
    bt = f"{region} {name}".strip() or name
    return {"description": desc, "taboos": taboos, "button_text": bt}


async def _scan_legacy_sync_diff() -> dict:
    """扫描所有老师，统计将变更的字段数（不写 DB），用于预览页"""
    from bot.database import get_all_teachers
    teachers = await get_all_teachers(active_only=False)
    stats = {
        "total": len(teachers),
        "diff_description": 0,
        "diff_taboos": 0,
        "diff_button_text": 0,
        "diff_any": 0,
    }
    for t in teachers:
        target = _compute_legacy_sync_target(t)
        any_diff = False
        if target["description"] and (t.get("description") or "") != target["description"]:
            stats["diff_description"] += 1
            any_diff = True
        if (t.get("taboos") or "") != target["taboos"]:
            stats["diff_taboos"] += 1
            any_diff = True
        if (t.get("button_text") or "") != target["button_text"]:
            stats["diff_button_text"] += 1
            any_diff = True
        if any_diff:
            stats["diff_any"] += 1
    return stats


async def _run_legacy_sync(bot=None) -> dict:
    """实际执行：遍历所有老师，把不一致的字段写入 DB；可选刷新频道帖 caption

    Args:
        bot: 传入 Bot 实例 → 对已发布且字段有变更的老师调
             update_teacher_post_caption(force=True) 同步频道帖。
             None → 仅同步 DB，不动频道。

    返回 dict 含 DB 统计 + 频道刷新统计。
    """
    import asyncio
    from bot.database import (
        get_all_teachers,
        get_teacher_channel_post,
        update_teacher,
        update_teacher_profile_field,
    )
    teachers = await get_all_teachers(active_only=False)
    stats = {
        "total": len(teachers),
        "diff_description": 0,
        "diff_taboos": 0,
        "diff_button_text": 0,
        "updated": 0,
        "caption_refreshed": 0,
        "caption_failed": 0,
        "caption_skipped_unpublished": 0,
    }
    refresh_fn = None
    if bot is not None:
        try:
            from bot.utils.teacher_channel_publish import update_teacher_post_caption
            refresh_fn = update_teacher_post_caption
        except Exception:
            refresh_fn = None

    for t in teachers:
        target = _compute_legacy_sync_target(t)
        uid = int(t["user_id"])
        any_diff = False
        if target["description"] and (t.get("description") or "") != target["description"]:
            ok = await update_teacher_profile_field(uid, "description", target["description"])
            if ok:
                stats["diff_description"] += 1
                any_diff = True
        if (t.get("taboos") or "") != target["taboos"]:
            ok = await update_teacher_profile_field(uid, "taboos", target["taboos"])
            if ok:
                stats["diff_taboos"] += 1
                any_diff = True
        if (t.get("button_text") or "") != target["button_text"]:
            ok = await update_teacher(uid, "button_text", target["button_text"])
            if ok:
                stats["diff_button_text"] += 1
                any_diff = True
        if any_diff:
            stats["updated"] += 1
            # 同步频道帖 caption（仅对已发布的老师 + bot 已传入）
            if refresh_fn is not None:
                post = await get_teacher_channel_post(uid)
                if post is None:
                    stats["caption_skipped_unpublished"] += 1
                else:
                    try:
                        refreshed = await refresh_fn(bot, uid, force=True)
                        if refreshed:
                            stats["caption_refreshed"] += 1
                        else:
                            stats["caption_failed"] += 1
                    except Exception:
                        stats["caption_failed"] += 1
                    # Telegram edit_message 限流：每老师间 sleep 0.5s 友好处理
                    await asyncio.sleep(0.5)
    return stats


@router.callback_query(F.data == "tprofile:sync_legacy")
@admin_required
async def cb_sync_legacy_preview(callback: types.CallbackQuery, state: FSMContext):
    """[🔄 老数据一键同步] 预览页（不写 DB，仅扫描差异）"""
    from bot.keyboards.admin_kb import tprofile_sync_legacy_confirm_kb
    await state.clear()
    stats = await _scan_legacy_sync_diff()
    text = (
        "🔄 老数据一键同步（预览）\n"
        "━━━━━━━━━━━━━━━\n"
        f"📊 共 {stats['total']} 位老师（含停用），其中 {stats['diff_any']} 位有字段需更新\n\n"
        "将按新规则刷新以下 3 个字段：\n"
        f"  📋 描述需更新：{stats['diff_description']} 位\n"
        "       规则：按 price 档位（≤800P→100元 / 900P→150元 / ≥1000P→200元）\n"
        f"  🚫 禁忌需更新：{stats['diff_taboos']} 位\n"
        f"       规则：写死 \"{DEFAULT_TABOOS}\"\n"
        f"  🔠 按钮文字需更新：{stats['diff_button_text']} 位\n"
        "       规则：「地区 艺名」\n"
        "━━━━━━━━━━━━━━━\n"
        "⚠️ 已经手动改过这些字段的老师会被覆盖。\n"
        "📣 同时会同步刷新所有已发布老师的频道帖 caption。\n"
        f"⏱ 频道刷新每位间隔 0.5 秒避免限流；预计耗时约 {max(1, stats['diff_any']) // 2} 秒。"
    )
    try:
        await callback.message.edit_text(text, reply_markup=tprofile_sync_legacy_confirm_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=tprofile_sync_legacy_confirm_kb())
    await callback.answer()


@router.callback_query(F.data == "tprofile:sync_legacy_ok")
@admin_required
async def cb_sync_legacy_execute(callback: types.CallbackQuery, state: FSMContext):
    """实际执行同步 — DB 同步 + 已发布老师的频道 caption 同步刷新

    频道 caption 刷新走 update_teacher_post_caption(force=True)；每老师间
    sleep 0.5s 友好 Telegram 限流。当老师较多时可能需要数十秒。
    """
    from bot.database import log_admin_audit
    # 提前给一个 alert，因为可能要等几十秒
    await callback.answer("⏳ 正在同步 DB + 频道帖，请稍候...", show_alert=False)
    try:
        await callback.message.edit_text(
            "⏳ 同步进行中...\n\n"
            "正在逐位更新 DB 并刷新已发布老师的频道 caption。\n"
            "（每老师间隔 0.5 秒以避免 Telegram 限流；老师数较多时请耐心等待）",
        )
    except Exception:
        pass

    stats = await _run_legacy_sync(bot=callback.bot)

    try:
        await log_admin_audit(
            admin_id=callback.from_user.id,
            action="teacher_sync_legacy",
            target_type="teachers",
            target_id="",
            detail=stats,
        )
    except Exception:
        pass

    text = (
        "✅ 老数据同步完成\n"
        "━━━━━━━━━━━━━━━\n"
        f"📊 共 {stats['total']} 位老师，{stats['updated']} 位 DB 实际更新\n\n"
        "DB 写入统计：\n"
        f"  📋 描述：{stats['diff_description']} 位\n"
        f"  🚫 禁忌：{stats['diff_taboos']} 位\n"
        f"  🔠 按钮文字：{stats['diff_button_text']} 位\n\n"
        "频道帖 caption 同步：\n"
        f"  📣 已刷新：{stats['caption_refreshed']} 位\n"
        f"  ⚪ 未发布（跳过）：{stats['caption_skipped_unpublished']} 位\n"
        f"  ⚠️ 刷新失败：{stats['caption_failed']} 位\n"
        "━━━━━━━━━━━━━━━\n"
    )
    if stats["caption_failed"] > 0:
        text += "ℹ️ 失败的多半是频道帖已被删除 / bot 权限丢失；可用 [🔄 重发档案帖] 单独重发。"
    else:
        text += "🎉 全部同步成功！"
    try:
        await callback.message.edit_text(text, reply_markup=teacher_profile_menu_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=teacher_profile_menu_kb())


# ============ /cancel 文本退出（任意 FSM 步骤）============

@router.message(F.text == "/cancel", TeacherProfileAddStates())
@admin_required
async def cmd_cancel_in_profile_fsm(message: types.Message, state: FSMContext):
    await _do_cancel(message, state)


# ============ 编辑老师档案 FSM ============

# 老师选择列表分页大小（edit / album / preview 共用）
_TPROFILE_LIST_PAGE_SIZE = 20

# action → (中文标题, FSM 状态)
_TPROFILE_LIST_ACTION_MAP: dict = {
    "edit":    ("✏️ 选择要编辑档案的老师", TeacherProfileEditStates.waiting_target_teacher),
    "album":   ("🖼 选择要管理相册的老师", TeacherProfileAlbumStates.waiting_target_teacher),
    "preview": ("👁 选择要预览档案 caption 的老师", None),  # preview 不进 FSM
}


async def _render_teacher_list_page(
    callback: types.CallbackQuery,
    state: FSMContext,
    action: str,
    page: int,
) -> None:
    """统一渲染老师选择列表（含分页）

    action ∈ {'edit','album','preview'}；page 从 0 起。
    handler 负责：取 teachers / 排序 / 分页切片 / 设 FSM 状态 / 渲染 + 答 callback。
    """
    from bot.database import get_all_teachers
    teachers = await get_all_teachers(active_only=False)
    if not teachers:
        await callback.answer("当前没有老师", show_alert=True)
        return

    title, target_state = _TPROFILE_LIST_ACTION_MAP.get(action, ("选择老师", None))

    teachers = sorted(teachers, key=lambda t: t.get("created_at", ""), reverse=True)
    total = len(teachers)
    page_size = _TPROFILE_LIST_PAGE_SIZE
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    offset = page * page_size
    chunk = teachers[offset:offset + page_size]

    # 设/清 FSM 状态
    if target_state is not None:
        await state.set_state(target_state)
    elif action == "preview":
        await state.clear()

    text = (
        f"{title}\n"
        f"（按创建时间倒序，共 {total} 位 · 第 {page + 1}/{total_pages} 页）"
    )
    kb = teacher_profile_select_kb(
        chunk, action=action, page=page, total_pages=total_pages,
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("tprofile:list:"))
@admin_required
async def cb_profile_list_paginate(callback: types.CallbackQuery, state: FSMContext):
    """老师选择列表分页：tprofile:list:{action}:{page}"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    action = parts[2]
    if action not in _TPROFILE_LIST_ACTION_MAP:
        await callback.answer("未知 action", show_alert=True)
        return
    try:
        page = max(0, int(parts[3]))
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    await _render_teacher_list_page(callback, state, action, page)


@router.callback_query(F.data == "tprofile:edit")
@admin_required
async def cb_profile_edit_start(callback: types.CallbackQuery, state: FSMContext):
    """[✏️ 编辑老师档案] 入口：从第 1 页开始"""
    await _render_teacher_list_page(callback, state, "edit", 0)


@router.callback_query(F.data.startswith("tprofile:select:edit:"))
@admin_required
async def cb_profile_edit_pick(callback: types.CallbackQuery, state: FSMContext):
    """选定老师 → 显示当前档案 + 字段编辑面板"""
    try:
        target = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.database import get_teacher_full_profile, is_teacher_profile_complete
    profile = await get_teacher_full_profile(target)
    if not profile:
        await callback.answer("老师不存在", show_alert=True)
        return
    await state.set_state(TeacherProfileEditStates.waiting_field_choice)
    await state.set_data({"target_user_id": target})

    ok, missing = await is_teacher_profile_complete(target)
    status = (
        "✅ 必填齐备" if ok
        else "⚠️ 缺：" + ", ".join(missing[:8]) + ("…" if len(missing) > 8 else "")
    )
    text = (
        f"✏️ 编辑老师档案：{profile['display_name']}\n"
        f"{status}\n\n"
        f"当前字段一览：\n"
        f"📋 基本信息：{profile.get('age') or '-'} 岁 · "
        f"{profile.get('height_cm') or '-'}cm · "
        f"{profile.get('weight_kg') or '-'}kg · 胸 {profile.get('bra_size') or '-'}\n"
        f"☎ 联系电报：{profile.get('contact_telegram') or '-'}\n"
        f"💰 价格详述：{profile.get('price_detail') or '-'}\n"
        f"📍 地区：{profile.get('region') or '-'}\n"
        f"💰 价格(排序)：{profile.get('price') or '-'}\n"
        f"🏷 标签：{' | '.join(profile.get('tags') or []) or '-'}\n"
        f"🔗 链接：{profile.get('button_url') or '-'}\n"
        f"🔠 按钮文字：{profile.get('button_text') or '-'}\n\n"
        "选择要修改的字段："
    )
    await callback.message.edit_text(text, reply_markup=teacher_profile_edit_field_kb(target))
    await callback.answer()


_EDIT_FIELD_PROMPTS: dict = {
    "display_name":     ("艺名", "输入新的艺名（≤ 40 字）。", "text"),
    "basic_info":       ("基本信息", "请用一行回复：年龄 身高 体重 罩杯，空格分隔。例如：25 172 90 B", "basic"),
    "description":      ("描述", '输入新的描述，或回复"清空"将其置空。', "optional"),
    "service_content":  ("服务内容", '输入新的服务范围，或回复"清空"。', "optional"),
    "price_detail":     ("价格详述", "输入新的价格详述（必填，不可为空）。", "text"),
    "taboos":           ("禁忌", '输入新的禁忌项，或回复"清空"。', "optional"),
    "contact_telegram": ("联系电报", "输入新的电报联系账号，必须以 @ 开头。", "contact"),
    "region":           ("地区", "输入新的地区（如：天府一街）。", "text"),
    "price":            ("价格(排序)", "输入新的价格短标签（如：3000P）。", "text"),
    "tags":             ("标签", "用空格或逗号分隔多个标签。", "tags"),
    "button_url":       ("跳转链接", "输入新的 URL（http/https/tg）。", "url"),
    "button_text":      ("按钮文字", '输入新的按钮文字，或回复"清空"使用默认（艺名）。', "optional"),
}


@router.callback_query(F.data.startswith("tprofile:editfield:"))
@admin_required
async def cb_profile_editfield_pick(callback: types.CallbackQuery, state: FSMContext):
    """点击某字段 → 提示输入新值"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        target = int(parts[2])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    field = parts[3]
    if field not in _EDIT_FIELD_PROMPTS:
        await callback.answer("未知字段", show_alert=True)
        return
    label, prompt, _kind = _EDIT_FIELD_PROMPTS[field]
    await state.set_state(TeacherProfileEditStates.waiting_field_value)
    await state.set_data({"target_user_id": target, "field_key": field})
    await callback.message.edit_text(
        f"✏️ 修改 {label}\n\n{prompt}\n\n任意时刻发 /cancel 中止。",
        reply_markup=teacher_profile_cancel_kb(),
    )
    await callback.answer()


@router.message(TeacherProfileEditStates.waiting_field_value)
@admin_required
async def on_profile_edit_value(message: types.Message, state: FSMContext):
    """接收新值，校验后入库"""
    from bot.database import update_teacher_profile_field
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("❌ 已取消修改。", reply_markup=teacher_profile_menu_kb())
        return
    data = await state.get_data()
    target = data.get("target_user_id")
    field = data.get("field_key")
    if not target or not field:
        await state.clear()
        await message.answer("状态丢失，请重新进入。", reply_markup=teacher_profile_menu_kb())
        return

    _label, _prompt, kind = _EDIT_FIELD_PROMPTS[field]

    # 类型分支
    if kind == "basic":
        info = parse_basic_info(text)
        if info is None:
            await message.reply(
                "❌ 格式不对或越界，例如：25 172 90 B（15-60 / 140-200 / 35-120）。"
            )
            return
        # 4 个字段分别 update
        for k, v in info.items():
            await update_teacher_profile_field(target, k, v)
        await _finish_edit(message, state, "基本信息", target)
        return

    if kind == "url":
        url = normalize_url(text)
        if not url:
            await message.reply("❌ URL 无效（http/https/tg，且不含空格）。")
            return
        ok = await update_teacher_profile_field(target, field, url)
        await _finish_edit(message, state, field, target, success=ok)
        return

    if kind == "contact":
        if not text.startswith("@") or not re.fullmatch(r"@[A-Za-z0-9_]{4,32}", text):
            await message.reply("❌ 联系电报必须 @ 开头，4-32 个字母/数字/下划线。")
            return
        ok = await update_teacher_profile_field(target, field, text)
        await _finish_edit(message, state, field, target, success=ok)
        return

    if kind == "tags":
        tags = [t.strip().lstrip("#") for t in re.split(r"[,，\s]+", text) if t.strip()]
        if not tags:
            await message.reply("❌ 至少输入一个标签。")
            return
        ok = await update_teacher_profile_field(target, "tags", tags)
        await _finish_edit(message, state, "tags", target, success=ok)
        return

    if kind == "optional":
        # "清空" → 写 NULL
        new_val = None if text in {"清空", "/clear"} else text
        ok = await update_teacher_profile_field(target, field, new_val)
        await _finish_edit(message, state, field, target, success=ok)
        return

    # kind == "text"：必填，不能为空
    if not text:
        await message.reply("❌ 该字段必填，不能为空。")
        return
    if field == "display_name" and len(text) > 40:
        await message.reply("❌ 艺名长度需 ≤ 40 字。")
        return
    ok = await update_teacher_profile_field(target, field, text)
    await _finish_edit(message, state, field, target, success=ok)


async def _finish_edit(
    message: types.Message,
    state: FSMContext,
    field_or_label: str,
    target_user_id: int,
    *,
    success: bool = True,
):
    await state.clear()
    if success:
        await message.answer(f"✅ 已更新「{field_or_label}」。")
    else:
        await message.answer("⚠️ 更新失败（字段或值不被接受）。")
    # 重新展示该老师的字段面板，便于继续修改
    from bot.database import get_teacher_full_profile, is_teacher_profile_complete
    profile = await get_teacher_full_profile(target_user_id)
    if not profile:
        await message.answer("📋 老师档案管理", reply_markup=teacher_profile_menu_kb())
        return

    # Phase 9.2：若该老师已发布到频道，字段更新后自动 edit_message_caption
    # （60s debounce 在 update_teacher_post_caption 内部处理，silent skip 未发布）
    if success:
        try:
            from bot.utils.teacher_channel_publish import update_teacher_post_caption
            edited = await update_teacher_post_caption(message.bot, target_user_id)
            if edited:
                await message.answer("📡 已同步频道 caption。")
        except Exception as e:
            # 不打断 admin 流程；失败仅记日志
            import logging as _lg
            _lg.getLogger(__name__).warning(
                "auto edit caption 失败 teacher=%s: %s", target_user_id, e,
            )

    ok, missing = await is_teacher_profile_complete(target_user_id)
    status = "✅ 必填齐备" if ok else f"⚠️ 仍缺 {len(missing)} 项"
    await state.set_state(TeacherProfileEditStates.waiting_field_choice)
    await state.set_data({"target_user_id": target_user_id})
    await message.answer(
        f"✏️ 继续编辑：{profile['display_name']}（{status}）",
        reply_markup=teacher_profile_edit_field_kb(target_user_id),
    )


# ============ 相册管理 ============

@router.callback_query(F.data == "tprofile:album")
@admin_required
async def cb_album_start(callback: types.CallbackQuery, state: FSMContext):
    """[🖼 管理照片相册] 入口：从第 1 页开始"""
    await _render_teacher_list_page(callback, state, "album", 0)


@router.callback_query(F.data.startswith("tprofile:select:album:"))
@admin_required
async def cb_album_pick(callback: types.CallbackQuery, state: FSMContext):
    """选定老师 → 显示当前相册数 + 操作按钮"""
    try:
        target = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    await _show_album_menu(callback.message, state, target, via_edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("tprofile:album_back:"))
@admin_required
async def cb_album_back(callback: types.CallbackQuery, state: FSMContext):
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    await _show_album_menu(callback.message, state, target, via_edit=True)
    await callback.answer()


async def _show_album_menu(
    msg: types.Message, state: FSMContext, target: int, *, via_edit: bool
):
    from bot.database import get_teacher_full_profile
    profile = await get_teacher_full_profile(target)
    if not profile:
        await msg.answer("老师不存在。", reply_markup=teacher_profile_menu_kb())
        return
    await state.set_state(TeacherProfileAlbumStates.waiting_album_action)
    await state.set_data({"target_user_id": target})
    n = len(profile["photo_album"])
    text = (
        f"🖼 相册管理：{profile['display_name']}\n\n"
        f"当前相册：{n}/10 张\n\n"
        f"➕ 添加照片：发送图片，点 [✅ 完成] 入库\n"
        f"❌ 删除照片：选择 index 1-{n}\n"
        f"🔄 整体替换：丢弃当前所有照片，重新上传"
    )
    await _show(msg, text, teacher_profile_album_menu_kb(target), via_edit)


@router.callback_query(F.data.startswith("tprofile:album_add:"))
@admin_required
async def cb_album_add(callback: types.CallbackQuery, state: FSMContext):
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.database import count_teacher_photos
    cur = await count_teacher_photos(target)
    if cur >= 10:
        await callback.answer("已达 10 张上限，请先删除或整体替换", show_alert=True)
        return
    await state.set_state(TeacherProfileAlbumStates.waiting_add_photos)
    await state.set_data({"target_user_id": target, "buffer": []})
    await callback.message.edit_text(
        f"➕ 添加照片：依次发送图片，最多再添加 {10 - cur} 张。\n"
        f"发送完后点 [✅ 完成]。",
        reply_markup=teacher_profile_album_collect_kb(target),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tprofile:album_replace:"))
@admin_required
async def cb_album_replace(callback: types.CallbackQuery, state: FSMContext):
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    await state.set_state(TeacherProfileAlbumStates.waiting_replace_photos)
    await state.set_data({"target_user_id": target, "buffer": []})
    await callback.message.edit_text(
        "🔄 整体替换：依次发送 1-10 张图片，完成后点 [✅ 完成]。\n"
        "⚠️ 此操作会丢弃当前所有照片。",
        reply_markup=teacher_profile_album_collect_kb(target),
    )
    await callback.answer()


@router.message(TeacherProfileAlbumStates.waiting_add_photos, F.photo)
@admin_required
async def on_album_add_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target = data.get("target_user_id")
    buf: list = list(data.get("buffer") or [])
    from bot.database import count_teacher_photos
    cur = await count_teacher_photos(target)
    if cur + len(buf) >= 10:
        await message.reply("⚠️ 已达 10 张上限，请点 [✅ 完成]。")
        return
    buf.append(message.photo[-1].file_id)
    await state.update_data(buffer=buf)
    await message.reply(f"✅ 已收到，本次将追加 {len(buf)} 张（合计 {cur + len(buf)}/10）。")


@router.message(TeacherProfileAlbumStates.waiting_replace_photos, F.photo)
@admin_required
async def on_album_replace_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    buf: list = list(data.get("buffer") or [])
    if len(buf) >= 10:
        await message.reply("⚠️ 已收满 10 张，请点 [✅ 完成]。")
        return
    buf.append(message.photo[-1].file_id)
    await state.update_data(buffer=buf)
    await message.reply(f"✅ 已收到，当前 {len(buf)}/10。")


@router.message(TeacherProfileAlbumStates.waiting_add_photos)
@router.message(TeacherProfileAlbumStates.waiting_replace_photos)
@admin_required
async def on_album_collect_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("❌ 已取消相册操作。", reply_markup=teacher_profile_menu_kb())
        return
    await message.reply("ℹ️ 请发送图片，或点 [✅ 完成] / [❌ 取消]。")


@router.callback_query(F.data.startswith("tprofile:album_collect_done:"))
@admin_required
async def cb_album_collect_done(callback: types.CallbackQuery, state: FSMContext):
    """收图阶段点 [✅ 完成]：执行 add 或 replace"""
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    cur_state = await state.get_state()
    data = await state.get_data()
    if data.get("target_user_id") != target:
        await callback.answer("状态不匹配", show_alert=True)
        return
    buf: list = list(data.get("buffer") or [])

    from bot.database import get_teacher_photos
    if cur_state == TeacherProfileAlbumStates.waiting_add_photos.state:
        if not buf:
            await callback.answer("还没有收到照片", show_alert=True)
            return
        existing = await get_teacher_photos(target)
        new_album = (existing + buf)[:10]
        await set_teacher_photos(target, new_album)
        await callback.answer(f"已追加 {len(buf)} 张")
    elif cur_state == TeacherProfileAlbumStates.waiting_replace_photos.state:
        if not buf:
            await callback.answer("至少需要 1 张照片才能替换", show_alert=True)
            return
        await set_teacher_photos(target, buf)
        await callback.answer(f"已替换为 {len(buf)} 张")
    else:
        await callback.answer()
        return

    await _show_album_menu(callback.message, state, target, via_edit=True)


@router.callback_query(F.data.startswith("tprofile:album_remove:"))
@admin_required
async def cb_album_remove(callback: types.CallbackQuery, state: FSMContext):
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.database import get_teacher_photos, get_teacher_full_profile
    photos = await get_teacher_photos(target)
    if not photos:
        await callback.answer("当前相册为空", show_alert=True)
        return
    profile = await get_teacher_full_profile(target)
    name = profile["display_name"] if profile else str(target)
    await state.set_state(TeacherProfileAlbumStates.waiting_remove_index)
    await state.set_data({"target_user_id": target})
    await callback.message.edit_text(
        f"❌ 删除 {name} 的照片\n\n当前共 {len(photos)} 张，点击下方数字选择要删除的照片（1-{len(photos)}）。",
        reply_markup=teacher_profile_album_remove_kb(target, len(photos)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tprofile:album_remove_idx:"))
@admin_required
async def cb_album_remove_idx(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        target = int(parts[2])
        idx = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.database import remove_teacher_photo
    ok = await remove_teacher_photo(target, idx)
    if ok:
        await callback.answer(f"已删除第 {idx} 张")
    else:
        await callback.answer("删除失败（index 越界或操作错误）", show_alert=True)
    await _show_album_menu(callback.message, state, target, via_edit=True)


# ============ 预览 caption ============

@router.callback_query(F.data == "tprofile:preview")
@admin_required
async def cb_preview_start(callback: types.CallbackQuery, state: FSMContext):
    """[👁 预览档案 caption] 入口：从第 1 页开始"""
    await _render_teacher_list_page(callback, state, "preview", 0)


_FIELD_LABEL_CN: dict = {
    "display_name":     "艺名",
    "age":              "年龄",
    "height_cm":        "身高",
    "weight_kg":        "体重",
    "bra_size":         "罩杯",
    "price_detail":     "价格详述",
    "contact_telegram": "联系电报",
    "region":           "地区",
    "price":            "价格(排序)",
    "tags":             "标签",
    "button_url":       "跳转链接",
    "photo_album":      "照片相册（≥1 张）",
}


@router.callback_query(F.data.startswith("tprofile:select:preview:"))
@admin_required
async def cb_preview_show(callback: types.CallbackQuery):
    """渲染 caption + 显示发布动作按钮（Phase 9.2）"""
    try:
        target = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.database import (
        get_teacher_full_profile, is_teacher_profile_complete,
        get_teacher_channel_post,
    )
    from bot.utils.teacher_profile_render import render_teacher_channel_caption
    from bot.utils.teacher_channel_publish import _load_brand_settings
    from bot.keyboards.admin_kb import teacher_profile_publish_action_kb

    profile = await get_teacher_full_profile(target)
    if not profile:
        await callback.answer("老师不存在", show_alert=True)
        return

    ok, missing = await is_teacher_profile_complete(target)
    post = await get_teacher_channel_post(target)
    is_published = post is not None
    brand = await _load_brand_settings(callback.bot)

    # 渲染时把 channel_posts 行作为 stats 传入（首发前 post 为 None → 占位符）
    try:
        caption = render_teacher_channel_caption(profile, stats=post, **brand)
        caption_block = (
            "─── 档案 caption 预览 ───\n"
            f"{caption}\n"
            "───────────────────"
        )
    except ValueError as e:
        caption_block = (
            "─── 档案 caption 预览 ───\n"
            f"⚠️ 无法渲染：{e}\n"
            "请先补全必填字段后再预览。\n"
            "───────────────────"
        )

    if is_published:
        status_line = (
            f"✅ 已发布到频道（chat_id={post['channel_chat_id']}, "
            f"msg_id={post['channel_msg_id']}，共 {len(post['media_group_msg_ids'])} 张）"
        )
    elif ok:
        status_line = "✅ 必填齐备，可点 [📤 发布档案帖到频道]"
    else:
        labels = [_FIELD_LABEL_CN.get(f, f) for f in missing]
        status_line = (
            "⚠️ 仍缺以下必填字段（先补全才能发频道）：\n"
            "  · " + "\n  · ".join(labels)
        )

    text = f"{caption_block}\n\n{status_line}"
    if len(text) > 4000:
        text = text[:3990] + "\n…(截断)"

    await callback.message.edit_text(
        text,
        reply_markup=teacher_profile_publish_action_kb(
            target, is_published=is_published, can_publish=ok,
        ),
    )
    await callback.answer()


# ============ 频道发布动作（Phase 9.2）============

async def _back_to_preview(callback: types.CallbackQuery, target: int):
    """复用 cb_preview_show 的渲染逻辑回到预览页

    CallbackQuery 是 pydantic v2 frozen 模型，必须 model_copy 创建新实例。
    """
    await cb_preview_show(
        callback.model_copy(update={"data": f"tprofile:select:preview:{target}"})
    )


@router.callback_query(F.data.startswith("tprofile:publish:"))
@admin_required
async def cb_publish_post(callback: types.CallbackQuery):
    """[📤 发布档案帖到频道]"""
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.utils.teacher_channel_publish import publish_teacher_post, PublishError
    from bot.database import log_admin_audit
    try:
        result = await publish_teacher_post(callback.bot, target)
    except PublishError as err:
        await callback.answer(f"❌ {err}", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="teacher_publish_to_channel",
        target_type="teacher",
        target_id=str(target),
        detail={"chat_id": result["chat_id"], "msg_id": result["channel_msg_id"],
                "media_count": result["media_count"]},
    )
    await callback.answer(f"✅ 已发布到频道（{result['media_count']} 张）")
    await _back_to_preview(callback, target)


@router.callback_query(F.data.startswith("tprofile:sync:"))
@admin_required
async def cb_sync_caption(callback: types.CallbackQuery):
    """[🔄 同步 caption]（绕过 debounce 显式 edit）"""
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.utils.teacher_channel_publish import (
        update_teacher_post_caption, PublishError,
    )
    from bot.database import log_admin_audit
    try:
        edited = await update_teacher_post_caption(
            callback.bot, target, force=True,
        )
    except PublishError as err:
        await callback.answer(f"❌ {err}", show_alert=True)
        return
    if edited:
        await log_admin_audit(
            admin_id=callback.from_user.id,
            action="teacher_channel_caption_update",
            target_type="teacher",
            target_id=str(target),
            detail={"trigger": "manual_sync"},
        )
        await callback.answer("✅ 已同步 caption")
    else:
        await callback.answer("ℹ️ 已是最新（无变化）")
    await _back_to_preview(callback, target)


@router.callback_query(F.data.startswith("tprofile:repost:"))
@admin_required
async def cb_repost_confirm_ask(callback: types.CallbackQuery):
    """[🔄 重发档案帖] 二次确认"""
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.keyboards.admin_kb import teacher_profile_repost_confirm_kb
    await callback.message.edit_text(
        "🔄 重发档案帖\n\n"
        "此操作会先删除当前频道里的媒体组（每张照片单独 delete_message），\n"
        "然后用现有相册重新 send_media_group 一次。\n"
        "⚠️ 删旧消息时部分失败不阻塞（Telegram 48h 限制等），但请确认频道仍可正常发图。",
        reply_markup=teacher_profile_repost_confirm_kb(target),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tprofile:repost_confirm:"))
@admin_required
async def cb_repost_execute(callback: types.CallbackQuery):
    """[⚠️ 确认重发]"""
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.utils.teacher_channel_publish import repost_teacher_post, PublishError
    from bot.database import log_admin_audit
    try:
        result = await repost_teacher_post(callback.bot, target)
    except PublishError as err:
        await callback.answer(f"❌ {err}", show_alert=True)
        await _back_to_preview(callback, target)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="teacher_channel_repost",
        target_type="teacher",
        target_id=str(target),
        detail={"chat_id": result["chat_id"], "msg_id": result["channel_msg_id"],
                "media_count": result["media_count"]},
    )
    await callback.answer(f"✅ 已重发（{result['media_count']} 张）")
    await _back_to_preview(callback, target)


@router.callback_query(F.data.startswith("tprofile:unpublish:"))
@admin_required
async def cb_unpublish_confirm_ask(callback: types.CallbackQuery):
    """[❌ 删除频道帖] 二次确认"""
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.keyboards.admin_kb import teacher_profile_unpublish_confirm_kb
    await callback.message.edit_text(
        "❌ 删除频道档案帖\n\n"
        "此操作会从频道删除该老师所有媒体组消息，并清除 teacher_channel_posts 记录。\n"
        "⚠️ 老师本身和数据库其他记录不会被删除；如需重新发布，回到预览页点 [📤 发布]。",
        reply_markup=teacher_profile_unpublish_confirm_kb(target),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tprofile:unpublish_confirm:"))
@admin_required
async def cb_unpublish_execute(callback: types.CallbackQuery):
    """[⚠️ 确认删除]"""
    try:
        target = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.utils.teacher_channel_publish import delete_teacher_post, PublishError
    from bot.database import log_admin_audit
    try:
        ok = await delete_teacher_post(callback.bot, target)
    except PublishError as err:
        await callback.answer(f"❌ {err}", show_alert=True)
        await _back_to_preview(callback, target)
        return
    if ok:
        await log_admin_audit(
            admin_id=callback.from_user.id,
            action="teacher_channel_post_delete",
            target_type="teacher",
            target_id=str(target),
            detail={},
        )
        await callback.answer("✅ 已删除频道帖")
    else:
        await callback.answer("⚠️ DB 行已不存在", show_alert=True)
    await _back_to_preview(callback, target)


# ============ /cancel 文本退出（编辑 / 相册 FSM）============

@router.message(F.text == "/cancel", TeacherProfileEditStates())
@router.message(F.text == "/cancel", TeacherProfileAlbumStates())
@admin_required
async def cmd_cancel_in_edit_album(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ 已取消。", reply_markup=teacher_profile_menu_kb())


# ============ 内部转移辅助 ============

async def _enter_photos(
    msg: types.Message, state: FSMContext, *, via_edit: bool = False
):
    """Step 9：上传相册（支持媒体组）"""
    await state.set_state(TeacherProfileAddStates.waiting_photos)
    data = await state.get_data()
    n = len(data.get("photos") or [])
    text = (
        f"[Step 9/{_TOTAL_STEPS}] 上传照片相册\n\n"
        "请发送 1-10 张图片（支持 Telegram 媒体组多选一次性发送）。\n"
        "全部发完后点击 [✅ 完成上传]。\n"
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
    """档案预览（v2 9 步精简版）

    自动派生字段以「(自动)」标注：
        🆔 / @username / ☎ 联系电报 → 来自转发或手动 3 步
        📋 描述 / 💰 价格(排序) / 🚫 禁忌 → 来自 Step 5 价格描述
        🔠 按钮文字 → 保存时自动 = "地区 艺名"
    """
    tags = d.get("tags") or []
    photos = d.get("photos") or []
    region = d.get("region", "")
    display_name = d.get("display_name", "?")
    auto_button_text = f"{region} {display_name}".strip() or display_name
    lines = [
        "📋 档案预览（确认前最后一步）",
        "━━━━━━━━━━━━━━━",
        f"👤 {display_name}",
        f"🆔 {d.get('user_id', '?')} (@{d.get('username', '?')}) (自动)",
        f"📋 {d.get('age', '?')} 岁 · {d.get('height_cm', '?')}cm · "
        f"{d.get('weight_kg', '?')}kg · 胸 {d.get('bra_size', '?')}",
        f"📍 地区：{region or '?'}",
        f"💰 价格描述：{d.get('price_detail', '?')}",
        f"💰 价格(排序)：{d.get('price', '?')} (自动)",
        f"📋 描述：{d.get('description', '?')} (自动)",
        f"🚫 禁忌：{d.get('taboos', '?')} (自动)",
    ]
    if d.get("service_content"):
        lines.append(f"📋 服务：{d['service_content']}")
    else:
        lines.append("📋 服务：(跳过)")
    lines.append(f"☎ 联系电报：{d.get('contact_telegram', '?')} (自动)")
    lines.append(f"🏷 标签：{' | '.join(tags) if tags else '-'}")
    lines.append(f"🔗 跳转链接：{d.get('button_url', '?')}")
    lines.append(f"🔠 按钮文字：{auto_button_text} (自动 = 地区 艺名)")
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

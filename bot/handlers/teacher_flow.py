import json
import time
from aiogram import Router, types, F, BaseMiddleware
from aiogram.fsm.context import FSMContext
from typing import Callable, Dict, Any, Awaitable

from bot.database import (
    add_teacher,
    update_teacher,
    remove_teacher,
    enable_teacher,
    get_teacher,
    get_all_teachers,
)
from bot.keyboards.admin_kb import (
    main_menu_kb,
    teacher_menu_kb,
    cancel_kb,
    skip_cancel_kb,
    confirm_cancel_kb,
    delete_confirm_kb,
    enable_confirm_kb,
    teacher_enable_list_kb,
    teacher_list_kb,
    edit_field_kb,
)
from bot.states.teacher_states import AddTeacherStates, EditTeacherStates
from bot.utils.permissions import admin_required

router = Router(name="teacher_flow")

# FSM 超时时间（秒）
FSM_TIMEOUT = 300  # 5 分钟


class FSMTimeoutMiddleware(BaseMiddleware):
    """FSM 超时中间件：5 分钟无操作自动取消状态"""

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        state: FSMContext = data.get("state")
        if state:
            current_state = await state.get_state()
            if current_state:
                state_data = await state.get_data()
                last_active = state_data.get("_last_active", 0)
                now = time.time()

                if last_active and (now - last_active) > FSM_TIMEOUT:
                    await state.clear()
                    # 通知用户超时
                    if isinstance(event, types.Message):
                        await event.answer("⏰ 操作超时，已自动取消。请重新开始。")
                    elif isinstance(event, types.CallbackQuery):
                        await event.answer("⏰ 操作超时，已自动取消", show_alert=True)
                    return

                # 更新最后活跃时间
                await state.update_data(_last_active=now)

        return await handler(event, data)


# 注册中间件
router.message.middleware(FSMTimeoutMiddleware())
router.callback_query.middleware(FSMTimeoutMiddleware())


# ============ 添加老师引导流程 ============


@router.callback_query(F.data == "teacher:add")
@admin_required
async def cb_teacher_add(callback: types.CallbackQuery, state: FSMContext):
    """开始添加老师流程"""
    await state.set_state(AddTeacherStates.waiting_user_id)
    await state.set_data({"step": 1})
    await callback.message.edit_text(
        "步骤 1/8：\n📝 请输入老师的 Telegram 数字 ID：",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AddTeacherStates.waiting_user_id)
@admin_required
async def on_teacher_user_id(message: types.Message, state: FSMContext):
    """步骤1: 接收老师 user_id"""
    text = message.text.strip()
    if not text.isdigit():
        await message.reply("❌ 请输入有效的数字 ID")
        return

    user_id = int(text)
    existing_teacher = await get_teacher(user_id)
    if existing_teacher:
        status = "启用中" if existing_teacher["is_active"] else "已停用"
        await message.reply(
            f"⚠️ 该老师 ID 已存在：{existing_teacher['display_name']}（{status}）\n"
            "请重新输入其他 Telegram 数字 ID，或点击「取消」。"
        )
        return

    await state.update_data(user_id=user_id)
    await state.set_state(AddTeacherStates.waiting_username)
    await message.answer(
        "步骤 2/8：\n📝 请输入老师的 Telegram 用户名（不含@）：",
        reply_markup=cancel_kb(),
    )


@router.message(AddTeacherStates.waiting_username)
@admin_required
async def on_teacher_username(message: types.Message, state: FSMContext):
    """步骤2: 接收用户名"""
    username = message.text.strip().lstrip("@")
    if not username:
        await message.reply("❌ 用户名不能为空")
        return

    await state.update_data(username=username)
    await state.set_state(AddTeacherStates.waiting_display_name)
    await message.answer(
        "步骤 3/8：\n📝 请输入老师的艺名：",
        reply_markup=cancel_kb(),
    )


@router.message(AddTeacherStates.waiting_display_name)
@admin_required
async def on_teacher_display_name(message: types.Message, state: FSMContext):
    """步骤3: 接收艺名"""
    display_name = message.text.strip()
    if not display_name:
        await message.reply("❌ 艺名不能为空")
        return

    await state.update_data(display_name=display_name)
    await state.set_state(AddTeacherStates.waiting_region)
    await message.answer(
        "步骤 4/8：\n📍 请输入老师的地区：",
        reply_markup=cancel_kb(),
    )


@router.message(AddTeacherStates.waiting_region)
@admin_required
async def on_teacher_region(message: types.Message, state: FSMContext):
    """步骤4: 接收地区"""
    region = message.text.strip()
    if not region:
        await message.reply("❌ 地区不能为空")
        return

    await state.update_data(region=region)
    await state.set_state(AddTeacherStates.waiting_price)
    await message.answer(
        '步骤 5/8：\n💰 请输入老师的价格信息（如 "1000P"）：',
        reply_markup=cancel_kb(),
    )


@router.message(AddTeacherStates.waiting_price)
@admin_required
async def on_teacher_price(message: types.Message, state: FSMContext):
    """步骤5: 接收价格"""
    price = message.text.strip()
    if not price:
        await message.reply("❌ 价格不能为空")
        return

    await state.update_data(price=price)
    await state.set_state(AddTeacherStates.waiting_tags)
    await message.answer(
        "步骤 6/8：\n🏷️ 请输入老师的标签（用空格或逗号分隔）：\n"
        "例如：颜值 身材 服务好",
        reply_markup=cancel_kb(),
    )


@router.message(AddTeacherStates.waiting_tags)
@admin_required
async def on_teacher_tags(message: types.Message, state: FSMContext):
    """步骤6: 接收标签"""
    text = message.text.strip()
    if not text:
        await message.reply("❌ 标签不能为空")
        return

    # 支持空格或逗号分隔
    import re
    tags = [t.strip() for t in re.split(r"[,，\s]+", text) if t.strip()]
    if not tags:
        await message.reply("❌ 请至少输入一个标签")
        return

    await state.update_data(tags=tags)
    await state.set_state(AddTeacherStates.waiting_photo)
    await message.answer(
        "步骤 7/8：\n🖼️ 请发送老师的展示图片（头像/宣传图）：",
        reply_markup=skip_cancel_kb(),
    )


@router.message(AddTeacherStates.waiting_photo, F.photo)
@admin_required
async def on_teacher_photo(message: types.Message, state: FSMContext):
    """步骤7: 接收图片"""
    # 取最大尺寸的图片
    photo = message.photo[-1]
    await state.update_data(photo_file_id=photo.file_id)
    await state.set_state(AddTeacherStates.waiting_button_url)
    await message.answer(
        "步骤 8/8：\n🔗 请输入老师的按钮跳转链接（URL）：",
        reply_markup=cancel_kb(),
    )


@router.message(AddTeacherStates.waiting_photo)
@admin_required
async def on_teacher_photo_invalid(message: types.Message, state: FSMContext):
    """步骤7: 非图片消息提示"""
    await message.reply("❌ 请发送图片，或点击「跳过」")


@router.callback_query(F.data == "action:skip")
async def cb_skip_photo(callback: types.CallbackQuery, state: FSMContext):
    """跳过图片步骤"""
    current_state = await state.get_state()
    if current_state == AddTeacherStates.waiting_photo:
        await state.update_data(photo_file_id=None)
        await state.set_state(AddTeacherStates.waiting_button_url)
        await callback.message.edit_text(
            "步骤 8/8：\n🔗 请输入老师的按钮跳转链接（URL）：",
        )
    await callback.answer()


@router.message(AddTeacherStates.waiting_button_url)
@admin_required
async def on_teacher_button_url(message: types.Message, state: FSMContext):
    """步骤8: 接收按钮链接"""
    url = message.text.strip()
    if not url.startswith(("http://", "https://", "tg://")):
        await message.reply("❌ 请输入有效的 URL（以 http://、https:// 或 tg:// 开头）")
        return

    await state.update_data(button_url=url)
    await state.set_state(AddTeacherStates.confirm)

    # 展示确认信息
    data = await state.get_data()
    tags_str = " | ".join(data["tags"])
    photo_status = "已上传" if data.get("photo_file_id") else "无"

    text = (
        "✅ 确认信息：\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 {data['display_name']}\n"
        f"🆔 {data['user_id']} (@{data['username']})\n"
        f"📍 {data['region']}\n"
        f"💰 {data['price']}\n"
        f"🏷️ {tags_str}\n"
        f"🖼️ {photo_status}\n"
        f"🔗 {data['button_url']}\n"
        "━━━━━━━━━━━━━━━"
    )
    await message.answer(text, reply_markup=confirm_cancel_kb())


@router.callback_query(F.data == "action:confirm")
async def cb_confirm_add_teacher(callback: types.CallbackQuery, state: FSMContext):
    """确认保存老师"""
    current_state = await state.get_state()
    if current_state != AddTeacherStates.confirm:
        await callback.answer()
        return

    data = await state.get_data()
    teacher_data = {
        "user_id": data["user_id"],
        "username": data["username"],
        "display_name": data["display_name"],
        "region": data["region"],
        "price": data["price"],
        "tags": json.dumps(data["tags"], ensure_ascii=False),
        "photo_file_id": data.get("photo_file_id"),
        "button_url": data["button_url"],
        "button_text": data["display_name"],
    }

    success = await add_teacher(teacher_data)
    if success:
        await callback.message.edit_text(
            f"✅ 老师「{data['display_name']}」添加成功！"
        )
    else:
        await callback.message.edit_text(
            f"⚠️ 添加失败，该 ID ({data['user_id']}) 可能已存在"
        )

    await state.clear()
    await callback.message.answer("👩‍🏫 老师管理", reply_markup=teacher_menu_kb())
    await callback.answer()


# ============ 编辑老师流程 ============


@router.callback_query(F.data == "teacher:edit")
@admin_required
async def cb_teacher_edit(callback: types.CallbackQuery, state: FSMContext):
    """编辑老师 - 展示老师列表供选择"""
    teachers = await get_all_teachers(active_only=False)
    if not teachers:
        await callback.answer("当前没有老师", show_alert=True)
        return
    await state.set_state(EditTeacherStates.select_teacher)
    await callback.message.edit_text(
        "✏️ 选择要编辑的老师：",
        reply_markup=teacher_list_kb(teachers),
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("teacher:select:"),
    EditTeacherStates.select_teacher,
)
@admin_required
async def cb_teacher_selected_for_edit(callback: types.CallbackQuery, state: FSMContext):
    """选择老师后展示字段编辑面板"""
    teacher_id = int(callback.data.split(":")[2])
    teacher = await get_teacher(teacher_id)
    if not teacher:
        await callback.answer("老师不存在", show_alert=True)
        return

    await state.set_state(EditTeacherStates.select_field)
    await state.update_data(edit_teacher_id=teacher_id)

    tags = json.loads(teacher["tags"]) if teacher["tags"] else []
    tags_str = " | ".join(tags)
    photo_status = "已上传" if teacher["photo_file_id"] else "无"

    text = (
        f"✏️ 编辑 {teacher['display_name']}\n\n"
        "当前信息：\n"
        f"🆔 {teacher['user_id']} (@{teacher['username']})\n"
        f"📍 {teacher['region']}\n"
        f"💰 {teacher['price']}\n"
        f"🏷️ {tags_str}\n"
        f"🖼️ {photo_status}\n"
        f"🔗 {teacher['button_url']}\n\n"
        "选择要修改的字段："
    )
    await callback.message.edit_text(text, reply_markup=edit_field_kb(teacher_id))
    await callback.answer()


@router.callback_query(F.data.startswith("edit:"))
@admin_required
async def cb_edit_field_selected(callback: types.CallbackQuery, state: FSMContext):
    """选择要编辑的字段"""
    parts = callback.data.split(":")
    teacher_id = int(parts[1])
    field = parts[2]

    field_names = {
        "display_name": "艺名",
        "region": "地区",
        "price": "价格",
        "tags": "标签（用空格或逗号分隔）",
        "photo_file_id": "图片",
        "button_url": "链接",
    }

    await state.set_state(EditTeacherStates.waiting_new_value)
    await state.update_data(edit_teacher_id=teacher_id, edit_field=field)

    if field == "photo_file_id":
        await callback.message.edit_text("🖼️ 请发送新的图片：")
    else:
        await callback.message.edit_text(
            f"📝 请输入新的{field_names.get(field, field)}："
        )
    await callback.answer()


@router.message(EditTeacherStates.waiting_new_value, F.photo)
@admin_required
async def on_edit_photo(message: types.Message, state: FSMContext):
    """编辑老师 - 接收新图片"""
    data = await state.get_data()
    if data.get("edit_field") != "photo_file_id":
        return

    photo = message.photo[-1]
    teacher_id = data["edit_teacher_id"]
    await update_teacher(teacher_id, "photo_file_id", photo.file_id)
    await message.answer("✅ 图片已更新")
    await state.clear()
    await message.answer("👩‍🏫 老师管理", reply_markup=teacher_menu_kb())


@router.message(EditTeacherStates.waiting_new_value)
@admin_required
async def on_edit_value(message: types.Message, state: FSMContext):
    """编辑老师 - 接收新文本值"""
    data = await state.get_data()
    field = data.get("edit_field")
    teacher_id = data["edit_teacher_id"]
    text = message.text.strip()

    if not text:
        await message.reply("❌ 值不能为空")
        return

    if field == "tags":
        import re
        tags = [t.strip() for t in re.split(r"[,，\s]+", text) if t.strip()]
        value = json.dumps(tags, ensure_ascii=False)
    elif field == "button_url":
        if not text.startswith(("http://", "https://", "tg://")):
            await message.reply("❌ 请输入有效的 URL（以 http://、https:// 或 tg:// 开头）")
            return
        value = text
    else:
        value = text

    success = await update_teacher(teacher_id, field, value)
    if success:
        await message.answer(f"✅ 已更新")
    else:
        await message.answer("⚠️ 更新失败")

    await state.clear()
    await message.answer("👩‍🏫 老师管理", reply_markup=teacher_menu_kb())


# ============ 停用老师 ============


@router.callback_query(F.data == "teacher:delete")
@admin_required
async def cb_teacher_delete(callback: types.CallbackQuery, state: FSMContext):
    """停用老师 - 展示列表"""
    await state.clear()
    teachers = await get_all_teachers(active_only=False)
    if not teachers:
        await callback.answer("当前没有老师", show_alert=True)
        return
    await callback.message.edit_text(
        "❌ 选择要停用的老师：",
        reply_markup=teacher_list_kb(teachers),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("teacher:select:"))
@admin_required
async def cb_teacher_selected_for_delete(callback: types.CallbackQuery, state: FSMContext):
    """选择老师后展示停用确认"""
    current_state = await state.get_state()
    # 如果不在编辑状态，则为停用操作
    if current_state and current_state.startswith("EditTeacher"):
        return

    teacher_id = int(callback.data.split(":")[2])
    teacher = await get_teacher(teacher_id)
    if not teacher:
        await callback.answer("老师不存在", show_alert=True)
        return

    await callback.message.edit_text(
        f"⚠️ 确认停用老师「{teacher['display_name']}」？\n\n"
        "停用后该老师不会出现在签到发布和关键词查询中，历史签到记录会保留。",
        reply_markup=delete_confirm_kb(teacher_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("teacher:confirm_delete:"))
@admin_required
async def cb_teacher_confirm_delete(callback: types.CallbackQuery):
    """确认停用老师"""
    teacher_id = int(callback.data.split(":")[2])
    teacher = await get_teacher(teacher_id)
    success = await remove_teacher(teacher_id)

    if success:
        name = teacher["display_name"] if teacher else str(teacher_id)
        await callback.message.edit_text(f"✅ 老师「{name}」已停用")
    else:
        await callback.message.edit_text("⚠️ 停用失败")

    await callback.message.answer("👩‍🏫 老师管理", reply_markup=teacher_menu_kb())
    await callback.answer()


# ============ 启用老师 ============


@router.callback_query(F.data == "teacher:enable")
@admin_required
async def cb_teacher_enable(callback: types.CallbackQuery, state: FSMContext):
    """启用老师 - 展示已停用老师列表"""
    await state.clear()
    teachers = await get_all_teachers(active_only=False)
    inactive_teachers = [t for t in teachers if not t["is_active"]]
    if not inactive_teachers:
        await callback.answer("当前没有已停用的老师", show_alert=True)
        return
    await callback.message.edit_text(
        "✅ 选择要重新启用的老师：",
        reply_markup=teacher_enable_list_kb(inactive_teachers),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("teacher:enable_select:"))
@admin_required
async def cb_teacher_selected_for_enable(callback: types.CallbackQuery):
    """选择老师后展示启用确认"""
    teacher_id = int(callback.data.split(":")[2])
    teacher = await get_teacher(teacher_id)
    if not teacher:
        await callback.answer("老师不存在", show_alert=True)
        return
    if teacher["is_active"]:
        await callback.answer("该老师已经是启用状态", show_alert=True)
        return

    await callback.message.edit_text(
        f"确认重新启用老师「{teacher['display_name']}」？\n\n"
        "启用后该老师可正常签到，并会出现在发布和关键词查询中。",
        reply_markup=enable_confirm_kb(teacher_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("teacher:confirm_enable:"))
@admin_required
async def cb_teacher_confirm_enable(callback: types.CallbackQuery):
    """确认启用老师"""
    teacher_id = int(callback.data.split(":")[2])
    teacher = await get_teacher(teacher_id)
    success = await enable_teacher(teacher_id)

    if success:
        name = teacher["display_name"] if teacher else str(teacher_id)
        await callback.message.edit_text(f"✅ 老师「{name}」已启用")
    else:
        await callback.message.edit_text("⚠️ 启用失败")

    await callback.message.answer("👩‍🏫 老师管理", reply_markup=teacher_menu_kb())
    await callback.answer()


# ============ 老师列表 ============


@router.callback_query(F.data == "teacher:list")
@admin_required
async def cb_teacher_list(callback: types.CallbackQuery):
    """展示老师列表"""
    teachers = await get_all_teachers(active_only=False)
    if not teachers:
        await callback.message.edit_text(
            "📋 当前没有老师",
            reply_markup=teacher_menu_kb(),
        )
        await callback.answer()
        return

    lines = [f"📋 老师列表（共 {len(teachers)} 位）：\n"]
    for t in teachers:
        status = "✅" if t["is_active"] else "❌"
        tags = json.loads(t["tags"]) if t["tags"] else []
        tags_str = " | ".join(tags[:3])
        lines.append(
            f"{status} {t['display_name']} (@{t['username']})\n"
            f"   📍{t['region']} 💰{t['price']} 🏷️{tags_str}"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=teacher_menu_kb(),
    )
    await callback.answer()

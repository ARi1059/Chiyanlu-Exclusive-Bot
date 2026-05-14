"""老师自助管理 handler（v2 §2.3 F3）

入口:
    - start_router 识别老师角色后展示 teacher_main_menu_kb（在私聊里）
    - 这里处理:
        · teacher_self:menu       回到老师主菜单
        · teacher_self:profile    展示当前资料 + 字段选择面板
        · teacher_self:edit:<f>   选定字段进入 FSM 等待新值
        · teacher_self:locked:<f> 锁定字段点击提示
        · teacher_self:checkin    用按钮触发签到（v2 §2.5.5 决策 16，与"发文字签到"并存）
    - FSM message handler:接收新值，立即生效（图片例外）+ 创建 edit_request + 通知管理员

字段例外（v2 §2.3.3a）:
    · 文字字段（5 个）:UPDATE teachers 立即生效 + INSERT edit_request
    · 图片字段（photo_file_id）:不动 teachers + INSERT edit_request
      展示位继续用旧图，审核通过后才切换
"""

import json
import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from pytz import timezone

from bot.config import config
from bot.database import (
    checkin_teacher,
    create_edit_request,
    get_all_admins,
    get_config,
    get_teacher,
    is_checked_in,
    update_teacher,
)
from bot.keyboards.teacher_self_kb import (
    FIELD_LABELS,
    teacher_back_to_profile_kb,
    teacher_edit_cancel_kb,
    teacher_main_menu_kb,
    teacher_profile_kb,
    time_picker_kb,
)
from bot.states.teacher_self_states import TeacherEditStates

logger = logging.getLogger(__name__)

router = Router(name="teacher_self")

tz = timezone(config.timezone)

# 老师可自助改的字段白名单（必须和 database.TEACHER_EDITABLE_FIELDS 一致）
EDITABLE_FIELDS: set[str] = {
    "display_name",
    "region",
    "price",
    "tags",
    "photo_file_id",
    "button_text",
}


# ========================================================
# 渲染辅助
# ========================================================

def _format_teacher_profile_text(teacher: dict) -> str:
    """构造资料展示文本"""
    try:
        tags = json.loads(teacher["tags"]) if teacher["tags"] else []
    except (json.JSONDecodeError, TypeError):
        tags = []
    tags_str = " | ".join(tags) if tags else "（空）"
    status = "" if teacher["is_active"] else "  ⚠️ 已停用"

    return (
        f"✏️ 你的资料{status}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 ID: {teacher['user_id']}\n"
        f"📛 用户名: @{teacher['username']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📝 艺名: {teacher['display_name']}\n"
        f"📍 地区: {teacher['region']}\n"
        f"💰 价格: {teacher['price']}\n"
        f"🏷️ 标签: {tags_str}\n"
        f"🖼️ 图片: {'已上传' if teacher['photo_file_id'] else '（空）'}\n"
        f"🔠 按钮文本: {teacher['button_text'] or '（默认用艺名）'}\n"
        f"🔗 链接: {teacher['button_url']}（不可自助修改）\n"
        f"━━━━━━━━━━━━━━━\n"
        f"点击下方按钮修改对应字段，修改后管理员将审核。"
    )


def _format_field_prompt(field_name: str, current_value: str | None) -> str:
    """构造"等待输入新值"的提示文本"""
    label = FIELD_LABELS.get(field_name, field_name)
    current = "（空）" if current_value is None or current_value == "" else current_value

    if field_name == "photo_file_id":
        return (
            f"🖼️ 修改图片\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前: {'已上传' if current_value else '（空）'}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"请发送新的图片（直接发图）。\n\n"
            f"⚠️ 图片修改采用「审核通过后生效」策略：\n"
            f"在管理员审核期间，展示位仍使用旧图。\n\n"
            f"发送 /cancel 取消修改。"
        )
    if field_name == "tags":
        return (
            f"🏷️ 修改标签\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前: {current}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"请输入新标签，用空格或逗号分隔。\n"
            f"例如：御姐 颜值 服务好\n\n"
            f"修改后立即生效，管理员会审核（如不通过会回滚）。\n"
            f"发送 /cancel 取消修改。"
        )
    return (
        f"修改{label}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"当前: {current}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"请输入新{label}。\n\n"
        f"修改后立即生效，管理员会审核（如不通过会回滚）。\n"
        f"发送 /cancel 取消修改。"
    )


def _parse_tags(text: str) -> str:
    """把用户输入的标签字符串转成 JSON 数组字符串

    支持空格/中文逗号/英文逗号/顿号分隔；去空 + 去重保序。
    """
    import re
    parts = re.split(r"[\s,，、]+", text)
    seen: list[str] = []
    seen_set: set[str] = set()
    for p in parts:
        p = p.strip()
        if not p:
            continue
        key = p.lower()
        if key in seen_set:
            continue
        seen_set.add(key)
        seen.append(p)
    return json.dumps(seen, ensure_ascii=False)


async def _notify_admins(
    bot,
    teacher: dict,
    field_name: str,
    old_value: str | None,
    new_value: str,
    request_id: int,
):
    """老师修改一次 → 推一条私聊给所有管理员（v2 §4 待定项决策）

    包含字段、原值、新值，以及"前往审核"的 deep-link 按钮。
    限速容错：失败仅记日志。
    """
    label = FIELD_LABELS.get(field_name, field_name)

    # 图片字段的 old/new 是 file_id，不展示原始字符串（无意义且长）
    if field_name == "photo_file_id":
        old_repr = "已上传" if old_value else "（空）"
        new_repr = "新图（待审核）"
    else:
        old_repr = old_value if old_value else "（空）"
        new_repr = new_value if new_value else "（空）"

    note = ""
    if field_name == "photo_file_id":
        note = "\n\n⚠️ 图片字段：审核通过后才会切换到新图，旧图继续展示。"

    text = (
        f"📝 老师修改通知\n"
        f"━━━━━━━━━━━━━━━\n"
        f"老师: {teacher['display_name']} (ID: {teacher['user_id']})\n"
        f"字段: {label}\n"
        f"原值: {old_repr}\n"
        f"新值: {new_repr}\n"
        f"请求 ID: {request_id}{note}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"在管理面板「📝 待审核」中处理。"
    )

    admins = await get_all_admins()
    super_id = config.super_admin_id
    # 推送给所有管理员（含超管，去重）
    target_ids = {a["user_id"] for a in admins}
    target_ids.add(super_id)

    for admin_id in target_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception as e:
            logger.warning("通知管理员 %s 失败: %s", admin_id, e)


# ========================================================
# 老师主菜单 callbacks
# ========================================================

@router.callback_query(F.data == "teacher_self:menu")
async def cb_teacher_menu(callback: types.CallbackQuery, state: FSMContext):
    """回到老师主菜单"""
    if not _is_teacher_chat(callback):
        await callback.answer()
        return
    await state.clear()
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return
    status = "" if teacher["is_active"] else "（账号已停用）"
    await callback.message.edit_text(
        f"👤 你好，{teacher['display_name']}{status}\n\n"
        "你的私聊功能：",
        reply_markup=teacher_main_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "teacher_self:profile")
async def cb_profile(callback: types.CallbackQuery, state: FSMContext):
    """展示当前资料 + 字段编辑面板"""
    if not _is_teacher_chat(callback):
        await callback.answer()
        return
    await state.clear()
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return
    await callback.message.edit_text(
        _format_teacher_profile_text(teacher),
        reply_markup=teacher_profile_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "teacher_self:locked:button_url")
async def cb_locked_button_url(callback: types.CallbackQuery):
    """点击锁定字段（链接）→ 提示由管理员管理"""
    await callback.answer(
        "🔗 链接由管理员管理，无法自助修改\n"
        "如需调整，请联系管理员",
        show_alert=True,
    )


# ========================================================
# 字段编辑入口 + FSM
# ========================================================

@router.callback_query(F.data.startswith("teacher_self:edit:"))
async def cb_edit_field(callback: types.CallbackQuery, state: FSMContext):
    """选定字段，进入 FSM 等待新值"""
    if not _is_teacher_chat(callback):
        await callback.answer()
        return

    field_name = callback.data[len("teacher_self:edit:"):]
    if field_name not in EDITABLE_FIELDS:
        await callback.answer("⚠️ 无效字段", show_alert=True)
        return

    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return

    current_value = teacher.get(field_name)
    await state.set_state(TeacherEditStates.waiting_new_value)
    await state.set_data({"field_name": field_name})

    await callback.message.edit_text(
        _format_field_prompt(field_name, current_value),
        reply_markup=teacher_edit_cancel_kb(),
    )
    await callback.answer()


@router.message(TeacherEditStates.waiting_new_value, Command("cancel"))
async def cmd_cancel_edit(message: types.Message, state: FSMContext):
    """老师在编辑 FSM 状态下发 /cancel 退出"""
    if message.chat.type != "private":
        return
    await state.clear()
    await message.answer(
        "已取消修改",
        reply_markup=teacher_main_menu_kb(),
    )


@router.message(TeacherEditStates.waiting_new_value)
async def on_edit_value(message: types.Message, state: FSMContext):
    """接收老师输入的新值，执行立即生效（图片例外）+ 创建 edit_request + 通知管理员

    校验:
        - 私聊场景
        - 当前是老师
        - 字段在白名单内（双重校验）
        - 图片字段：要求 message.photo 非空
        - 文字字段：要求 message.text 非空
    """
    if message.chat.type != "private":
        return

    user_id = message.from_user.id
    teacher = await get_teacher(user_id)
    if not teacher:
        await state.clear()
        await message.reply("⚠️ 你不在老师名单内")
        return

    data = await state.get_data()
    field_name: str = data.get("field_name", "")
    if field_name not in EDITABLE_FIELDS:
        await state.clear()
        await message.reply("⚠️ 异常：未知字段，请重新进入编辑")
        return

    old_value = teacher.get(field_name)

    # 图片字段（v2 §2.3.3a 例外，延后生效）
    if field_name == "photo_file_id":
        if not message.photo:
            await message.reply(
                "请发送图片（直接发图，不是文字），或 /cancel 取消"
            )
            return
        # 取最高分辨率的 file_id
        new_value = message.photo[-1].file_id

        # ⚠️ 不动 teachers（延后生效）
        request_id = await create_edit_request(
            teacher_id=user_id,
            field_name="photo_file_id",
            old_value=old_value,
            new_value=new_value,
        )
        if request_id is None:
            await state.clear()
            await message.reply("⚠️ 创建审核请求失败（字段不在白名单）")
            return

        await _notify_admins(
            message.bot, teacher, "photo_file_id", old_value, new_value, request_id
        )

        await state.clear()
        await message.answer(
            "🖼️ 图片已提交审核\n"
            "━━━━━━━━━━━━━━━\n"
            "审核通过后立即生效；\n"
            "在此期间，展示位仍使用旧图。\n"
            "━━━━━━━━━━━━━━━",
            reply_markup=teacher_back_to_profile_kb(),
        )
        return

    # 文字字段（5 个），立即生效
    if not message.text:
        await message.reply("请输入文字内容，或 /cancel 取消")
        return

    raw = message.text.strip()
    if not raw:
        await message.reply("内容不能为空，请重新输入")
        return

    # tags 需要特殊编码为 JSON 字符串
    if field_name == "tags":
        new_value = _parse_tags(raw)
        if new_value == "[]":
            await message.reply("至少输入一个有效标签，或 /cancel 取消")
            return
    else:
        new_value = raw

    # 内容相同直接拒绝（避免无意义的审核请求）
    if old_value == new_value:
        await message.reply("新值与旧值相同，不需要修改")
        return

    # 立即生效：UPDATE teachers
    ok = await update_teacher(user_id, field_name, new_value)
    if not ok:
        await state.clear()
        await message.reply("⚠️ 修改失败，请稍后重试")
        return

    # 创建 edit_request
    request_id = await create_edit_request(
        teacher_id=user_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
    )
    if request_id is None:
        # 兜底（白名单已校验，理论不会到这里）
        logger.error(
            "create_edit_request 返回 None: teacher=%s field=%s",
            user_id, field_name,
        )

    # 通知所有管理员
    if request_id is not None:
        await _notify_admins(
            message.bot, teacher, field_name, old_value, new_value, request_id
        )

    label = FIELD_LABELS.get(field_name, field_name)
    await state.clear()
    await message.answer(
        f"✅ {label}修改已生效\n"
        "━━━━━━━━━━━━━━━\n"
        "管理员会审核此次修改，如不通过将自动回滚。",
        reply_markup=teacher_back_to_profile_kb(),
    )


# ========================================================
# 签到按钮（v2 §2.5.5 决策 16，与 v1 文字"签到"并存）
# ========================================================

@router.callback_query(F.data == "teacher_self:checkin")
async def cb_button_checkin(callback: types.CallbackQuery, state: FSMContext):
    """按钮触发签到（行为同 v1 teacher_checkin.on_checkin）"""
    if not _is_teacher_chat(callback):
        await callback.answer()
        return
    await state.clear()
    user_id = callback.from_user.id

    teacher = await get_teacher(user_id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return
    if not teacher["is_active"]:
        await callback.answer("⚠️ 你的账号已被停用", show_alert=True)
        return

    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    # 签到截止时间窗口（同 v1）
    publish_time = await get_config("publish_time") or config.publish_time
    hour, minute = map(int, publish_time.split(":"))
    if now.hour > hour or (now.hour == hour and now.minute >= minute):
        await callback.answer(
            f"⏰ 今日签到已截止（{publish_time}）\n请明天再来",
            show_alert=True,
        )
        return

    if await is_checked_in(user_id, today_str):
        await callback.answer("✅ 今日已签到，无需重复操作", show_alert=True)
        return

    ok = await checkin_teacher(user_id, today_str)
    if not ok:
        await callback.answer("⚠️ 签到失败，请稍后重试", show_alert=True)
        return

    await callback.answer(
        f"✅ 签到成功 - {today_str} {now.strftime('%H:%M')}",
        show_alert=True,
    )
    # Phase 5：签到后提示设置今日可约时间（发新消息，不动当前老师主菜单）
    await callback.message.answer(
        "✅ 签到成功！请选择今日可约时间：",
        reply_markup=time_picker_kb(),
    )


# ========================================================
# 工具
# ========================================================

def _is_teacher_chat(callback: types.CallbackQuery) -> bool:
    """只在私聊里响应；群组里收到也视为无效（应不会发生）"""
    return bool(
        callback.message
        and callback.message.chat
        and callback.message.chat.type == "private"
    )

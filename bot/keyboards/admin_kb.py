from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============ 主菜单 ============

def main_menu_kb() -> InlineKeyboardMarkup:
    """管理员主菜单面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👩‍🏫 老师管理", callback_data="menu:teacher"),
            InlineKeyboardButton(text="👥 管理员管理", callback_data="menu:admin"),
        ],
        [
            InlineKeyboardButton(text="📢 频道设置", callback_data="menu:channel"),
            InlineKeyboardButton(text="⚙️ 系统设置", callback_data="menu:system"),
        ],
    ])


# ============ 老师管理子面板 ============

def teacher_menu_kb() -> InlineKeyboardMarkup:
    """老师管理子面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 添加老师", callback_data="teacher:add")],
        [InlineKeyboardButton(text="✏️ 编辑老师", callback_data="teacher:edit")],
        [
            InlineKeyboardButton(text="停用老师", callback_data="teacher:delete"),
            InlineKeyboardButton(text="启用老师", callback_data="teacher:enable"),
        ],
        [InlineKeyboardButton(text="📋 老师列表", callback_data="teacher:list")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


# ============ 管理员管理子面板 ============

def admin_menu_kb() -> InlineKeyboardMarkup:
    """管理员管理子面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 添加管理员", callback_data="admin:add")],
        [InlineKeyboardButton(text="➖ 移除管理员", callback_data="admin:remove")],
        [InlineKeyboardButton(text="📋 管理员列表", callback_data="admin:list")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


# ============ 频道设置子面板 ============

def channel_menu_kb() -> InlineKeyboardMarkup:
    """频道设置子面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 设置发布目标", callback_data="channel:set_publish")],
        [InlineKeyboardButton(text="💬 设置响应群组", callback_data="channel:set_response")],
        [InlineKeyboardButton(text="📋 查看当前设置", callback_data="channel:view")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


# ============ 系统设置子面板 ============

def system_menu_kb() -> InlineKeyboardMarkup:
    """系统设置子面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="系统状态检查", callback_data="system:status")],
        [
            InlineKeyboardButton(text="发布预览", callback_data="publish:preview"),
            InlineKeyboardButton(text="手动发布", callback_data="publish:manual"),
        ],
        [InlineKeyboardButton(text="今日签到统计", callback_data="checkin:stats")],
        [
            InlineKeyboardButton(text="测试签到发布", callback_data="test:checkin_publish"),
            InlineKeyboardButton(text="🧪 测试收藏通知", callback_data="test:fav_notification"),
        ],
        [
            InlineKeyboardButton(text="签到提醒时间", callback_data="system:reminder_time"),
            InlineKeyboardButton(text="签到提醒开关", callback_data="system:reminder_toggle"),
        ],
        [InlineKeyboardButton(text="⏰ 修改发布时间", callback_data="system:publish_time")],
        [InlineKeyboardButton(text="⏳ 修改冷却时间", callback_data="system:cooldown")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


# ============ 通用按钮 ============

def cancel_kb() -> InlineKeyboardMarkup:
    """取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ 取消", callback_data="action:cancel")],
    ])


def skip_cancel_kb() -> InlineKeyboardMarkup:
    """跳过+取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏭️ 跳过", callback_data="action:skip"),
            InlineKeyboardButton(text="❌ 取消", callback_data="action:cancel"),
        ],
    ])


def confirm_cancel_kb() -> InlineKeyboardMarkup:
    """确认+取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ 确认保存", callback_data="action:confirm"),
            InlineKeyboardButton(text="❌ 取消", callback_data="action:cancel"),
        ],
    ])


def delete_confirm_kb(teacher_id: int) -> InlineKeyboardMarkup:
    """停用确认按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认停用", callback_data=f"teacher:confirm_delete:{teacher_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data="teacher:delete"),
        ],
    ])


def enable_confirm_kb(teacher_id: int) -> InlineKeyboardMarkup:
    """启用确认按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="确认启用", callback_data=f"teacher:confirm_enable:{teacher_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data="teacher:enable"),
        ],
    ])


def teacher_enable_list_kb(teachers: list[dict]) -> InlineKeyboardMarkup:
    """停用老师列表按钮（用于启用）"""
    keyboard = []
    for t in teachers:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{t['display_name']} (@{t['username']})",
                callback_data=f"teacher:enable_select:{t['user_id']}",
            )
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 返回", callback_data="menu:teacher")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def teacher_list_kb(teachers: list[dict]) -> InlineKeyboardMarkup:
    """老师列表按钮（用于选择）"""
    keyboard = []
    for t in teachers:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{t['display_name']} (@{t['username']})",
                callback_data=f"teacher:select:{t['user_id']}",
            )
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 返回", callback_data="menu:teacher")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def edit_field_kb(teacher_id: int) -> InlineKeyboardMarkup:
    """编辑老师字段选择面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 艺名", callback_data=f"edit:{teacher_id}:display_name"),
            InlineKeyboardButton(text="📍 地区", callback_data=f"edit:{teacher_id}:region"),
        ],
        [
            InlineKeyboardButton(text="💰 价格", callback_data=f"edit:{teacher_id}:price"),
            InlineKeyboardButton(text="🏷️ 标签", callback_data=f"edit:{teacher_id}:tags"),
        ],
        [
            InlineKeyboardButton(text="🖼️ 图片", callback_data=f"edit:{teacher_id}:photo_file_id"),
            InlineKeyboardButton(text="🔗 链接", callback_data=f"edit:{teacher_id}:button_url"),
        ],
        [InlineKeyboardButton(text="🔙 返回", callback_data="menu:teacher")],
    ])


def admin_remove_kb(admins: list[dict]) -> InlineKeyboardMarkup:
    """管理员移除列表"""
    keyboard = []
    for a in admins:
        if a["is_super"]:
            continue
        name = f"@{a['username']}" if a["username"] else str(a["user_id"])
        keyboard.append([
            InlineKeyboardButton(text=f"➖ {name}", callback_data=f"admin:confirm_remove:{a['user_id']}")
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 返回", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

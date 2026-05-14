from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============ 主菜单 ============

def main_menu_kb(pending_count: int = 0) -> InlineKeyboardMarkup:
    """管理员主菜单面板

    Args:
        pending_count: 待审核数量；> 0 时在"待审核"按钮文本上显示徽标
    """
    review_label = (
        f"📝 待审核 ({pending_count})" if pending_count > 0 else "📝 待审核"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👩‍🏫 老师管理", callback_data="menu:teacher"),
            InlineKeyboardButton(text="👥 管理员管理", callback_data="menu:admin"),
        ],
        [
            InlineKeyboardButton(text="📢 频道设置", callback_data="menu:channel"),
            InlineKeyboardButton(text="⚙️ 系统设置", callback_data="menu:system"),
        ],
        [
            InlineKeyboardButton(text="📊 数据看板", callback_data="dashboard:enter"),
            InlineKeyboardButton(text=review_label, callback_data="review:enter"),
        ],
        [InlineKeyboardButton(text="🔥 热门推荐", callback_data="admin:hot_manage")],
        [
            InlineKeyboardButton(text="🔗 推广链接", callback_data="admin:promo_links"),
            InlineKeyboardButton(text="📈 渠道统计", callback_data="admin:source_stats"),
        ],
    ])


# ============ 推广链接 / 渠道统计（Phase 4） ============


def promo_links_menu_kb() -> InlineKeyboardMarkup:
    """推广链接生成器主面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📺 频道来源", callback_data="admin:promo:channel")],
        [InlineKeyboardButton(text="👥 群组来源", callback_data="admin:promo:group")],
        [InlineKeyboardButton(text="👤 老师来源", callback_data="admin:promo:teacher")],
        [InlineKeyboardButton(text="🎯 活动来源", callback_data="admin:promo:campaign")],
        [InlineKeyboardButton(text="🎟️ 邀请来源", callback_data="admin:promo:invite")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def promo_cancel_kb() -> InlineKeyboardMarkup:
    """推广链接 FSM 输入页的取消按钮（回 promo 主菜单）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:promo_links")],
    ])


def source_stats_menu_kb() -> InlineKeyboardMarkup:
    """渠道统计主面板：按类型查看 + 查用户来源 + 返回"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📺 频道", callback_data="admin:source_stats:channel"),
            InlineKeyboardButton(text="👥 群组", callback_data="admin:source_stats:group"),
            InlineKeyboardButton(text="👤 老师", callback_data="admin:source_stats:teacher"),
        ],
        [
            InlineKeyboardButton(text="🎯 活动", callback_data="admin:source_stats:campaign"),
            InlineKeyboardButton(text="🎟️ 邀请", callback_data="admin:source_stats:invite"),
        ],
        [InlineKeyboardButton(text="🔍 查用户来源", callback_data="admin:user_source")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def source_stats_back_kb() -> InlineKeyboardMarkup:
    """渠道统计分类页的返回按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 返回渠道统计", callback_data="admin:source_stats"),
            InlineKeyboardButton(text="🏠 主菜单", callback_data="menu:main"),
        ],
    ])


def source_lookup_cancel_kb() -> InlineKeyboardMarkup:
    """用户来源查询 FSM 取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:source_stats")],
    ])


# ============ 热门推荐管理（Phase 3） ============


def hot_manage_menu_kb() -> InlineKeyboardMarkup:
    """热门推荐管理子面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 添加推荐", callback_data="admin:hot:add")],
        [InlineKeyboardButton(text="✏️ 修改权重", callback_data="admin:hot:weight")],
        [InlineKeyboardButton(text="❌ 取消推荐", callback_data="admin:hot:remove")],
        [InlineKeyboardButton(text="🔄 重算热度", callback_data="admin:hot:recalc")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def hot_manage_cancel_kb() -> InlineKeyboardMarkup:
    """热门推荐管理流程内的取消按钮（返回 hot manage 主页）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:hot_manage")],
    ])


# ============ 数据看板（Phase 1） ============


def dashboard_menu_kb() -> InlineKeyboardMarkup:
    """看板主视图：刷新 / 操作日志 / 返回主菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 刷新", callback_data="dashboard:enter"),
            InlineKeyboardButton(text="📜 操作日志", callback_data="dashboard:audit"),
        ],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def dashboard_audit_back_kb() -> InlineKeyboardMarkup:
    """操作日志页：返回看板 / 主菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 返回看板", callback_data="dashboard:enter"),
            InlineKeyboardButton(text="🏠 主菜单", callback_data="menu:main"),
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


# ============ 审核中心（F3） ============

def review_action_kb(
    request_id: int,
    *,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    """单条审核请求的操作面板:通过 / 驳回 / 上下条 / 返回主菜单"""
    nav: list[InlineKeyboardButton] = []
    if has_prev:
        nav.append(
            InlineKeyboardButton(text="⬅️ 上一条", callback_data=f"review:nav:prev:{request_id}")
        )
    if has_next:
        nav.append(
            InlineKeyboardButton(text="➡️ 下一条", callback_data=f"review:nav:next:{request_id}")
        )

    rows = [
        [
            InlineKeyboardButton(text="✅ 通过", callback_data=f"review:approve:{request_id}"),
            InlineKeyboardButton(text="❌ 驳回", callback_data=f"review:reject:{request_id}"),
        ],
    ]
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_reject_choice_kb(request_id: int) -> InlineKeyboardMarkup:
    """点"驳回"后:是否填写原因"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 填写原因", callback_data=f"review:reject_reason:{request_id}"),
            InlineKeyboardButton(text="⏭️ 跳过原因", callback_data=f"review:reject_skip:{request_id}"),
        ],
        [InlineKeyboardButton(text="🔙 取消", callback_data=f"review:show:{request_id}")],
    ])


def review_empty_kb() -> InlineKeyboardMarkup:
    """审核队列为空时的返回按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])

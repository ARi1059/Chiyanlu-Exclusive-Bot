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
        [
            InlineKeyboardButton(text="📅 今日状态", callback_data="admin:today_status"),
            InlineKeyboardButton(text="🏷 用户画像", callback_data="admin:user_tags"),
        ],
        [
            InlineKeyboardButton(text="📝 发布模板", callback_data="admin:publish_templates"),
            InlineKeyboardButton(text="📨 报表设置", callback_data="admin:report_settings"),
        ],
    ])


# ============ 报表设置（Phase 6.3） ============


def report_settings_cancel_kb() -> InlineKeyboardMarkup:
    """报表设置 FSM 输入页的取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:report_settings")],
    ])


# ============ 管理员今日状态总览（Phase 5） ============


def admin_today_status_kb() -> InlineKeyboardMarkup:
    """管理员今日开课状态总览页"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 刷新", callback_data="admin:today_status"),
            InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main"),
        ],
    ])


# ============ 用户画像看板（Phase 6.1） ============


def user_tags_menu_kb() -> InlineKeyboardMarkup:
    """用户画像看板主面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 查询标签用户", callback_data="admin:user_tags:query")],
        [
            InlineKeyboardButton(text="🔄 刷新", callback_data="admin:user_tags"),
            InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main"),
        ],
    ])


def user_tags_query_cancel_kb() -> InlineKeyboardMarkup:
    """查询标签用户 FSM 取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:user_tags")],
    ])


def user_tags_query_result_kb() -> InlineKeyboardMarkup:
    """标签用户查询结果页：再查 / 返回看板 / 返回主菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 再查一个", callback_data="admin:user_tags:query"),
            InlineKeyboardButton(text="🔙 返回看板", callback_data="admin:user_tags"),
        ],
        [InlineKeyboardButton(text="🏠 主菜单", callback_data="menu:main")],
    ])


# ============ 发布模板管理（Phase 6.2） ============


def publish_templates_menu_kb() -> InlineKeyboardMarkup:
    """发布模板管理主面板"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 模板列表", callback_data="admin:publish_templates:list")],
        [InlineKeyboardButton(text="➕ 新建模板", callback_data="admin:publish_templates:create")],
        [InlineKeyboardButton(text="✏️ 编辑默认模板", callback_data="admin:publish_templates:edit_default")],
        [InlineKeyboardButton(text="✅ 设置默认模板", callback_data="admin:publish_templates:set_default")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def publish_templates_cancel_kb() -> InlineKeyboardMarkup:
    """模板管理 FSM 输入页的取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:publish_templates")],
    ])


def publish_templates_list_back_kb() -> InlineKeyboardMarkup:
    """模板列表页的返回按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 返回模板管理", callback_data="admin:publish_templates"),
            InlineKeyboardButton(text="🏠 主菜单", callback_data="menu:main"),
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
    """老师管理子面板

    Phase 9.1：新增 [📋 老师档案管理] 入口，进入完整档案的录入/编辑/相册/预览。
    旧 [➕ 添加老师] / [✏️ 编辑老师]（简版录入）保留，向后兼容。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 添加老师 (简版)", callback_data="teacher:add")],
        [InlineKeyboardButton(text="✏️ 编辑老师 (简版)", callback_data="teacher:edit")],
        [InlineKeyboardButton(text="📋 老师档案管理", callback_data="tprofile:menu")],
        [
            InlineKeyboardButton(text="停用老师", callback_data="teacher:delete"),
            InlineKeyboardButton(text="启用老师", callback_data="teacher:enable"),
        ],
        [InlineKeyboardButton(text="📋 老师列表", callback_data="teacher:list")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


# ============ 老师档案管理（Phase 9.1） ============

def teacher_profile_menu_kb() -> InlineKeyboardMarkup:
    """[📋 老师档案管理] 子菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 完整档案录入", callback_data="tprofile:add")],
        [InlineKeyboardButton(text="✏️ 编辑老师档案", callback_data="tprofile:edit")],
        [InlineKeyboardButton(text="🖼 管理照片相册", callback_data="tprofile:album")],
        [InlineKeyboardButton(text="👁 预览档案 caption", callback_data="tprofile:preview")],
        [InlineKeyboardButton(text="🔙 返回老师管理", callback_data="menu:teacher")],
    ])


def teacher_profile_cancel_kb() -> InlineKeyboardMarkup:
    """档案录入 FSM 各步的取消按钮（返回档案管理主面板）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ 取消", callback_data="tprofile:cancel")],
    ])


def teacher_profile_skip_cancel_kb() -> InlineKeyboardMarkup:
    """可选字段步骤的 [跳过] + [取消] 按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏭️ 跳过", callback_data="tprofile:skip"),
            InlineKeyboardButton(text="❌ 取消", callback_data="tprofile:cancel"),
        ],
    ])


def teacher_profile_photos_done_kb() -> InlineKeyboardMarkup:
    """照片上传步：完成 / 撤销最后一张 / 取消"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ 完成上传", callback_data="tprofile:photos_done"),
            InlineKeyboardButton(text="↩️ 撤销最后一张", callback_data="tprofile:photos_undo"),
        ],
        [InlineKeyboardButton(text="❌ 取消", callback_data="tprofile:cancel")],
    ])


def teacher_profile_confirm_kb() -> InlineKeyboardMarkup:
    """确认页：保存 / 取消（修改某项的入口由 Commit 3 编辑流程承担）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ 保存到 DB", callback_data="tprofile:save"),
            InlineKeyboardButton(text="❌ 取消", callback_data="tprofile:cancel"),
        ],
    ])


def teacher_profile_select_kb(
    teachers: list[dict],
    *,
    action: str,
    per_row: int = 2,
) -> InlineKeyboardMarkup:
    """选择老师列表（用于编辑 / 相册 / 预览）

    action: "edit" / "album" / "preview"
        callback: tprofile:select:{action}:{user_id}
    """
    rows: list[list[InlineKeyboardButton]] = []
    cur: list[InlineKeyboardButton] = []
    for t in teachers[:30]:
        cur.append(InlineKeyboardButton(
            text=t["display_name"],
            callback_data=f"tprofile:select:{action}:{t['user_id']}",
        ))
        if len(cur) >= per_row:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append([InlineKeyboardButton(text="🔙 返回", callback_data="tprofile:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def teacher_profile_edit_field_kb(user_id: int) -> InlineKeyboardMarkup:
    """老师档案字段编辑面板（12 个字段）"""
    def btn(label: str, key: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=label,
            callback_data=f"tprofile:editfield:{user_id}:{key}",
        )
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("✏️ 艺名", "display_name"),       btn("✏️ 基本信息", "basic_info")],
        [btn("✏️ 描述", "description"),         btn("✏️ 服务", "service_content")],
        [btn("✏️ 价格详述", "price_detail"),    btn("✏️ 禁忌", "taboos")],
        [btn("✏️ 联系电报", "contact_telegram"), btn("✏️ 地区", "region")],
        [btn("✏️ 价格(排序)", "price"),         btn("✏️ 标签", "tags")],
        [btn("✏️ 跳转链接", "button_url"),      btn("✏️ 按钮文字", "button_text")],
        [InlineKeyboardButton(text="🔙 返回", callback_data="tprofile:edit")],
    ])


def teacher_profile_album_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    """相册管理主操作面板（已选定老师后）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ 添加照片", callback_data=f"tprofile:album_add:{user_id}"),
            InlineKeyboardButton(text="❌ 删除照片", callback_data=f"tprofile:album_remove:{user_id}"),
        ],
        [InlineKeyboardButton(text="🔄 整体替换", callback_data=f"tprofile:album_replace:{user_id}")],
        [InlineKeyboardButton(text="🔙 返回选老师", callback_data="tprofile:album")],
    ])


def teacher_profile_album_remove_kb(user_id: int, photo_count: int) -> InlineKeyboardMarkup:
    """选择要删除的照片 index（1-based）"""
    rows: list[list[InlineKeyboardButton]] = []
    cur: list[InlineKeyboardButton] = []
    for i in range(1, photo_count + 1):
        cur.append(InlineKeyboardButton(
            text=f"{i}",
            callback_data=f"tprofile:album_remove_idx:{user_id}:{i}",
        ))
        if len(cur) >= 5:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append([InlineKeyboardButton(text="🔙 取消", callback_data=f"tprofile:album_back:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def teacher_profile_album_collect_kb(user_id: int) -> InlineKeyboardMarkup:
    """相册新增 / 替换 收图过程中的"完成"按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ 完成", callback_data=f"tprofile:album_collect_done:{user_id}"),
            InlineKeyboardButton(text="❌ 取消", callback_data=f"tprofile:album_back:{user_id}"),
        ],
    ])


# ============ 老师档案：频道发布动作（Phase 9.2） ============

def teacher_profile_publish_action_kb(
    user_id: int,
    *,
    is_published: bool,
    can_publish: bool,
) -> InlineKeyboardMarkup:
    """预览页底部的发布操作按钮

    is_published: teacher_channel_posts 是否已有该老师的行
    can_publish: 必填齐备 + 相册 ≥ 1 张（影响首发按钮是否启用）
    """
    rows: list[list[InlineKeyboardButton]] = []
    if is_published:
        rows.append([
            InlineKeyboardButton(text="🔄 重发档案帖", callback_data=f"tprofile:repost:{user_id}"),
            InlineKeyboardButton(text="🔄 同步 caption", callback_data=f"tprofile:sync:{user_id}"),
        ])
        rows.append([
            InlineKeyboardButton(text="❌ 删除频道帖", callback_data=f"tprofile:unpublish:{user_id}"),
        ])
    elif can_publish:
        rows.append([
            InlineKeyboardButton(text="📤 发布档案帖到频道", callback_data=f"tprofile:publish:{user_id}"),
        ])
    rows.append([InlineKeyboardButton(text="🔙 返回档案管理", callback_data="tprofile:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def teacher_profile_repost_confirm_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认重发", callback_data=f"tprofile:repost_confirm:{user_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data=f"tprofile:select:preview:{user_id}"),
        ],
    ])


def teacher_profile_unpublish_confirm_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认删除", callback_data=f"tprofile:unpublish_confirm:{user_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data=f"tprofile:select:preview:{user_id}"),
        ],
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
    """频道设置子面板

    Phase 9.2：新增 [📦 设置档案频道]（archive_channel_id），与"发布目标"解耦。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 设置发布目标", callback_data="channel:set_publish")],
        [InlineKeyboardButton(text="📦 设置档案频道", callback_data="channel:set_archive")],
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
        [InlineKeyboardButton(text="📋 必关频道/群组", callback_data="admin:subreq")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


# ============ 必关频道/群组（Phase 9.3） ============

def subreq_menu_kb() -> InlineKeyboardMarkup:
    """[📋 必关频道/群组] 子菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 添加", callback_data="admin:subreq:add")],
        [InlineKeyboardButton(text="📋 列表", callback_data="admin:subreq")],
        [InlineKeyboardButton(text="🔙 返回系统设置", callback_data="menu:system")],
    ])


def subreq_list_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """必关项列表：每条一行"""
    rows: list[list[InlineKeyboardButton]] = []
    for it in items:
        mark = "✅" if it.get("is_active") else "⛔"
        text = f"{mark} {it['display_name']} ({it['chat_id']})"
        if len(text) > 60:
            text = text[:57] + "…"
        rows.append([InlineKeyboardButton(
            text=text,
            callback_data=f"admin:subreq:item:{it['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ 添加", callback_data="admin:subreq:add")])
    rows.append([InlineKeyboardButton(text="🔙 返回系统设置", callback_data="menu:system")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subreq_item_action_kb(item_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """单项操作面板"""
    toggle_label = "⛔ 停用" if is_active else "✅ 启用"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_label, callback_data=f"admin:subreq:toggle:{item_id}"),
            InlineKeyboardButton(text="❌ 删除", callback_data=f"admin:subreq:remove:{item_id}"),
        ],
        [InlineKeyboardButton(text="🔙 返回列表", callback_data="admin:subreq")],
    ])


def subreq_remove_confirm_kb(item_id: int) -> InlineKeyboardMarkup:
    """删除二次确认"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认删除", callback_data=f"admin:subreq:remove_confirm:{item_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data=f"admin:subreq:item:{item_id}"),
        ],
    ])


def subreq_cancel_kb() -> InlineKeyboardMarkup:
    """添加 FSM 取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ 取消", callback_data="admin:subreq")],
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

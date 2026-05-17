from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============ 主菜单 ============

def main_menu_kb(
    pending_count: int = 0,
    *,
    pending_review_count: int = 0,
    pending_reimburse_count: int = 0,
    queued_reimburse_count: int = 0,
    is_super: bool = False,
) -> InlineKeyboardMarkup:
    """管理员主菜单面板

    Args:
        pending_count: 老师改资料待审核数量
        pending_review_count: 用户评价待审核数量（Phase 9.4）
        pending_reimburse_count: 待审核报销数量
        queued_reimburse_count: 报销功能关闭期间静默录入名单的数量
        is_super: 是否超管；仅超管可见 [📝 报告审核 (M)] 行
    """
    review_label = (
        f"📝 待审核 ({pending_count})" if pending_count > 0 else "📝 待审核"
    )
    rows: list[list[InlineKeyboardButton]] = [
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
    ]
    if is_super:
        rreview_label = (
            f"📝 报告审核 ({pending_review_count})"
            if pending_review_count > 0 else "📝 报告审核"
        )
        rows.append([
            InlineKeyboardButton(text=rreview_label, callback_data="rreview:enter"),
            InlineKeyboardButton(text="💰 积分管理", callback_data="admin:points"),
        ])
        reimburse_label = (
            f"💰 报销审核 ({pending_reimburse_count})"
            if pending_reimburse_count > 0 else "💰 报销审核"
        )
        rows.append([
            InlineKeyboardButton(text="🎲 抽奖管理", callback_data="admin:lottery"),
            InlineKeyboardButton(text=reimburse_label, callback_data="reimburse:enter"),
        ])
        # 仅当存在静默录入条目时显示，避免冗余按钮
        if queued_reimburse_count > 0:
            rows.append([
                InlineKeyboardButton(
                    text=f"📋 报销名单 ({queued_reimburse_count})",
                    callback_data="reimburse:queued:0",
                ),
            ])
    rows.extend([
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
    return InlineKeyboardMarkup(inline_keyboard=rows)


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

    2026-05-17：移除简版录入入口；统一通过 [📋 老师档案管理] 进入完整档案流程。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
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
    page: int = 0,
    total_pages: int = 1,
    per_row: int = 2,
) -> InlineKeyboardMarkup:
    """选择老师列表（用于编辑 / 相册 / 预览），含分页

    action: "edit" / "album" / "preview"
        老师按钮 callback: tprofile:select:{action}:{user_id}
    分页按钮 callback: tprofile:list:{action}:{page}
    """
    rows: list[list[InlineKeyboardButton]] = []
    cur: list[InlineKeyboardButton] = []
    # teachers 已由 handler 切到当前页窗口；这里不再二次截断
    for t in teachers:
        cur.append(InlineKeyboardButton(
            text=t["display_name"],
            callback_data=f"tprofile:select:{action}:{t['user_id']}",
        ))
        if len(cur) >= per_row:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)

    # 多页时显示分页 nav
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text="⬅️ 上一页",
                callback_data=f"tprofile:list:{action}:{page - 1}",
            ))
        nav.append(InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data="noop:tprofile_page",
        ))
        if page + 1 < total_pages:
            nav.append(InlineKeyboardButton(
                text="➡️ 下一页",
                callback_data=f"tprofile:list:{action}:{page + 1}",
            ))
        rows.append(nav)

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
        [InlineKeyboardButton(text="👨‍💼 抽奖客服链接", callback_data="system:lottery_contact")],
        [
            InlineKeyboardButton(text="💰 报销池设置",   callback_data="system:reimburse_pool"),
            InlineKeyboardButton(text="🔘 报销功能开关", callback_data="system:reimburse_toggle"),
        ],
        [
            InlineKeyboardButton(text="🏷 档案品牌名",   callback_data="system:brand_name"),
            InlineKeyboardButton(text="📡 档案品牌频道", callback_data="system:brand_channels"),
        ],
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


# ============ 报告审核中心（Phase 9.4） ============

def rreview_action_kb(
    review_id: int,
    *,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    """单条报告审核详情页操作按钮（spec §4.2）"""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="✅ 通过", callback_data=f"rreview:approve:{review_id}"),
            InlineKeyboardButton(text="❌ 驳回", callback_data=f"rreview:reject:{review_id}"),
        ],
        [
            InlineKeyboardButton(text="🖼 重看约课截图", callback_data=f"rreview:photo:booking:{review_id}"),
            InlineKeyboardButton(text="✋ 重看手势照片", callback_data=f"rreview:photo:gesture:{review_id}"),
        ],
    ]
    nav: list[InlineKeyboardButton] = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="⬅️ 上一条", callback_data=f"rreview:nav:prev:{review_id}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="➡️ 下一条", callback_data=f"rreview:nav:next:{review_id}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 返回主面板", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rreview_reject_choice_kb(review_id: int) -> InlineKeyboardMarkup:
    """点 [❌ 驳回] 后的选项：4 预设 + 自定义 + 跳过 + 取消"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="证据不充分", callback_data=f"rreview:reject_preset:{review_id}:0")],
        [InlineKeyboardButton(text="内容违规", callback_data=f"rreview:reject_preset:{review_id}:1")],
        [InlineKeyboardButton(text="重复提交", callback_data=f"rreview:reject_preset:{review_id}:2")],
        [InlineKeyboardButton(text="评分明显不合理", callback_data=f"rreview:reject_preset:{review_id}:3")],
        [
            InlineKeyboardButton(text="📝 自定义原因", callback_data=f"rreview:reject_custom:{review_id}"),
            InlineKeyboardButton(text="⏭ 跳过原因", callback_data=f"rreview:reject_skip:{review_id}"),
        ],
        [InlineKeyboardButton(text="🔙 取消", callback_data=f"rreview:show:{review_id}")],
    ])


def rreview_empty_kb() -> InlineKeyboardMarkup:
    """报告审核队列为空"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回主面板", callback_data="menu:main")],
    ])


def rreview_push_action_kb() -> InlineKeyboardMarkup:
    """新评价推送给超管时附带的按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 前往审核", callback_data="rreview:enter")],
    ])


def admin_points_menu_kb() -> InlineKeyboardMarkup:
    """[💰 积分管理] 子菜单（spec §3.2）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 查询用户积分", callback_data="admin:points:query")],
        [InlineKeyboardButton(text="➕ 手动加分",     callback_data="admin:points:grant")],
        [InlineKeyboardButton(text="📊 积分总览",     callback_data="admin:points:overview")],
        [InlineKeyboardButton(text="🔙 返回主菜单",   callback_data="menu:main")],
    ])


def admin_points_cancel_kb() -> InlineKeyboardMarkup:
    """积分管理 FSM 通用取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:points")],
    ])


def admin_points_back_kb() -> InlineKeyboardMarkup:
    """查询结果页 / 总览页底部：返回积分管理"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 再查一个", callback_data="admin:points:query"),
            InlineKeyboardButton(text="🔙 返回积分管理", callback_data="admin:points"),
        ],
        [InlineKeyboardButton(text="🏠 主菜单", callback_data="menu:main")],
    ])


def admin_points_grant_value_kb() -> InlineKeyboardMarkup:
    """[➕ 手动加分] Step 2 加分值预设（spec §3.2）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+1 P/PP", callback_data="admin:points:grant_v:p"),
            InlineKeyboardButton(text="+3 包时", callback_data="admin:points:grant_v:hour"),
        ],
        [
            InlineKeyboardButton(text="+5 包夜", callback_data="admin:points:grant_v:night"),
            InlineKeyboardButton(text="+8 包天", callback_data="admin:points:grant_v:day"),
        ],
        [
            InlineKeyboardButton(text="+10", callback_data="admin:points:grant_v:p10"),
            InlineKeyboardButton(text="+20", callback_data="admin:points:grant_v:p20"),
        ],
        [
            InlineKeyboardButton(text="➖ 扣分", callback_data="admin:points:grant_minus"),
            InlineKeyboardButton(text="💬 自定义", callback_data="admin:points:grant_custom"),
        ],
        [InlineKeyboardButton(text="❌ 取消", callback_data="admin:points:grant_cancel")],
    ])


def admin_points_grant_minus_kb() -> InlineKeyboardMarkup:
    """[➖ 扣分] Step 2b 扣分预设"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="-1", callback_data="admin:points:grant_m:1"),
            InlineKeyboardButton(text="-3", callback_data="admin:points:grant_m:3"),
        ],
        [
            InlineKeyboardButton(text="-5", callback_data="admin:points:grant_m:5"),
            InlineKeyboardButton(text="-10", callback_data="admin:points:grant_m:10"),
        ],
        [InlineKeyboardButton(text="💬 自定义负数", callback_data="admin:points:grant_custom")],
        [
            InlineKeyboardButton(text="🔙 返回加分", callback_data="admin:points:grant_back"),
            InlineKeyboardButton(text="❌ 取消", callback_data="admin:points:grant_cancel"),
        ],
    ])


def admin_points_grant_reason_kb() -> InlineKeyboardMarkup:
    """Step 3 加分原因预设（spec §3.2）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 报告审核补加", callback_data="admin:points:grant_r:audit"),
            InlineKeyboardButton(text="🎁 活动奖励",     callback_data="admin:points:grant_r:event"),
        ],
        [
            InlineKeyboardButton(text="⚠️ 违规扣分", callback_data="admin:points:grant_r:violate"),
            InlineKeyboardButton(text="🛠 系统修正", callback_data="admin:points:grant_r:fix"),
        ],
        [InlineKeyboardButton(text="💬 自定义原因", callback_data="admin:points:grant_rcustom")],
        [InlineKeyboardButton(text="❌ 取消", callback_data="admin:points:grant_cancel")],
    ])


def admin_points_grant_confirm_kb() -> InlineKeyboardMarkup:
    """Step 4 确认页（spec §3.2）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ 确认", callback_data="admin:points:grant_ok"),
            InlineKeyboardButton(text="❌ 取消", callback_data="admin:points:grant_cancel"),
        ],
    ])


def rreview_approve_points_kb(review_id: int) -> InlineKeyboardMarkup:
    """Phase P.1：审核通过加分子页（spec §3.1）

    点 [✅ 通过] 后展示，超管根据材料选积分：
        [+1 P / PP]   [+3 包时]
        [+5 包夜]     [+8 包天]
        [+0 不加分]   [💬 自定义]
        [🔙 取消]

    callback：rreview:approve_p:<rid>:<key> 其中 key ∈ {p,hour,night,day,zero}
              rreview:approve_custom:<rid>
              rreview:show:<rid> 取消回审核详情页
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+1 P / PP", callback_data=f"rreview:approve_p:{review_id}:p"),
            InlineKeyboardButton(text="+3 包时",    callback_data=f"rreview:approve_p:{review_id}:hour"),
        ],
        [
            InlineKeyboardButton(text="+5 包夜",   callback_data=f"rreview:approve_p:{review_id}:night"),
            InlineKeyboardButton(text="+8 包天",   callback_data=f"rreview:approve_p:{review_id}:day"),
        ],
        [
            InlineKeyboardButton(text="+0 不加分", callback_data=f"rreview:approve_p:{review_id}:zero"),
            InlineKeyboardButton(text="💬 自定义", callback_data=f"rreview:approve_custom:{review_id}"),
        ],
        [InlineKeyboardButton(text="🔙 取消通过，返回审核", callback_data=f"rreview:show:{review_id}")],
    ])


# ============ 抽奖管理（Phase L.1） ============

def admin_lottery_menu_kb(pending_count: int = 0) -> InlineKeyboardMarkup:
    """[🎲 抽奖管理] 子菜单"""
    list_label = f"📋 抽奖列表 ({pending_count})" if pending_count else "📋 抽奖列表"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 创建新抽奖",   callback_data="admin:lottery:create")],
        [InlineKeyboardButton(text=list_label,       callback_data="admin:lottery:list")],
        [InlineKeyboardButton(text="👨‍💼 抽奖客服链接", callback_data="admin:lottery:contact")],
        [InlineKeyboardButton(text="🔙 返回主面板",   callback_data="menu:main")],
    ])


def admin_lottery_list_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """抽奖列表：每条按钮"""
    from bot.database import LOTTERY_STATUSES
    status_emoji = {s["key"]: s["emoji"] for s in LOTTERY_STATUSES}
    rows: list[list[InlineKeyboardButton]] = []
    for it in items[:30]:
        emoji = status_emoji.get(it.get("status", ""), "❓")
        name = it.get("name") or "(未命名)"
        if len(name) > 25:
            name = name[:24] + "…"
        rows.append([InlineKeyboardButton(
            text=f"{emoji} {name}",
            callback_data=f"admin:lottery:item:{it['id']}",
        )])
    rows.append([InlineKeyboardButton(text="🔙 返回抽奖管理", callback_data="admin:lottery")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_lottery_detail_kb(lottery: dict) -> InlineKeyboardMarkup:
    """抽奖详情页操作按钮

    draft     → [📤 立即发布] [❌ 取消草稿]
    scheduled → [❌ 取消计划]
    active    → [✏️ 编辑] [🔄 重发抽奖帖] [👥 查看参与] [❌ 取消抽奖]
    drawn / no_entries → [👥 查看参与]
    """
    rows: list[list[InlineKeyboardButton]] = []
    lid = lottery["id"]
    status = lottery.get("status")
    if status == "draft":
        rows.append([
            InlineKeyboardButton(text="📤 立即发布",  callback_data=f"admin:lottery:publish:{lid}"),
            InlineKeyboardButton(text="❌ 取消草稿", callback_data=f"admin:lottery:cancel:{lid}"),
        ])
    elif status == "scheduled":
        rows.append([
            InlineKeyboardButton(text="❌ 取消计划", callback_data=f"admin:lottery:cancel:{lid}"),
        ])
    elif status == "active":
        rows.append([
            InlineKeyboardButton(text="✏️ 编辑抽奖",   callback_data=f"admin:lottery:edit:{lid}"),
            InlineKeyboardButton(text="🔄 重发抽奖帖", callback_data=f"admin:lottery:repost:{lid}"),
        ])
        rows.append([
            InlineKeyboardButton(text="👥 查看参与", callback_data=f"admin:lottery:entries:{lid}"),
            InlineKeyboardButton(text="❌ 取消抽奖", callback_data=f"admin:lottery:cancel:{lid}"),
        ])
    elif status in ("drawn", "no_entries"):
        rows.append([
            InlineKeyboardButton(text="👥 查看参与", callback_data=f"admin:lottery:entries:{lid}"),
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 返回列表",     callback_data="admin:lottery:list"),
        InlineKeyboardButton(text="🏠 返回抽奖管理", callback_data="admin:lottery"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_lottery_entries_pagination_kb(
    lottery_id: int, page: int, total_pages: int,
) -> InlineKeyboardMarkup:
    """参与人员分页按钮（仿 9.6 / P.2）"""
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️ 上一页",
            callback_data=f"admin:lottery:entries:{lottery_id}:{page - 1}",
        ))
    nav.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{max(1, total_pages)}",
        callback_data="noop:lottery_entries_page",
    ))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(
            text="➡️ 下一页",
            callback_data=f"admin:lottery:entries:{lottery_id}:{page + 1}",
        ))
    return InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(text="🔙 返回详情", callback_data=f"admin:lottery:item:{lottery_id}")],
    ])


def admin_lottery_repost_confirm_kb(lottery_id: int) -> InlineKeyboardMarkup:
    """[🔄 重发抽奖帖] 二次确认"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认重发", callback_data=f"admin:lottery:repost_ok:{lottery_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data=f"admin:lottery:item:{lottery_id}"),
        ],
    ])


def lottery_contact_cancel_kb() -> InlineKeyboardMarkup:
    """客服链接 FSM 取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:lottery")],
    ])


def admin_lottery_edit_field_kb(lottery_id: int) -> InlineKeyboardMarkup:
    """active 抽奖编辑字段选择（Phase L.4.2）

    7 个可编辑字段：name / description / prize_description / prize_count /
                    entry_cost_points / required_chat_ids / draw_at
    （cover / entry_method / entry_code 不可改 — admin 重新建抽奖即可）
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏷 名称",   callback_data=f"admin:lottery:edit_field:{lottery_id}:name"),
            InlineKeyboardButton(text="📋 规则",   callback_data=f"admin:lottery:edit_field:{lottery_id}:description"),
        ],
        [
            InlineKeyboardButton(text="🎁 奖品描述", callback_data=f"admin:lottery:edit_field:{lottery_id}:prize_description"),
            InlineKeyboardButton(text="🏆 中奖人数", callback_data=f"admin:lottery:edit_field:{lottery_id}:prize_count"),
        ],
        [
            InlineKeyboardButton(text="💰 参与所需积分", callback_data=f"admin:lottery:edit_field:{lottery_id}:entry_cost_points"),
            InlineKeyboardButton(text="📡 必关频道",   callback_data=f"admin:lottery:edit_field:{lottery_id}:required_chat_ids"),
        ],
        [
            InlineKeyboardButton(text="⏰ 开奖时间", callback_data=f"admin:lottery:edit_field:{lottery_id}:draw_at"),
            InlineKeyboardButton(text="🔙 返回详情", callback_data=f"admin:lottery:item:{lottery_id}"),
        ],
    ])


def lottery_edit_cancel_kb(lottery_id: int) -> InlineKeyboardMarkup:
    """active 编辑 FSM 取消（回详情）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data=f"admin:lottery:item:{lottery_id}")],
    ])


def admin_lottery_publish_confirm_kb(lottery_id: int) -> InlineKeyboardMarkup:
    """[📤 立即发布] 二次确认"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认发布", callback_data=f"admin:lottery:publish_ok:{lottery_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data=f"admin:lottery:item:{lottery_id}"),
        ],
    ])


def admin_lottery_cancel_confirm_kb(
    lottery_id: int,
    *,
    show_refund_choice: bool = False,
) -> InlineKeyboardMarkup:
    """取消抽奖二次确认

    - show_refund_choice=False（默认；草稿/0 entries/cost=0）：单按钮 ⚠️ 确认取消
    - show_refund_choice=True（active 且 cost > 0 且 has entries）：
      两个按钮 [✅ 取消并退积分] / [⚠️ 取消但不退积分]
    """
    rows: list[list[InlineKeyboardButton]] = []
    if show_refund_choice:
        rows.append([
            InlineKeyboardButton(
                text="✅ 取消并退积分",
                callback_data=f"admin:lottery:cancel_ok_refund:{lottery_id}",
            ),
        ])
        rows.append([
            InlineKeyboardButton(
                text="⚠️ 取消但不退积分",
                callback_data=f"admin:lottery:cancel_ok_norefund:{lottery_id}",
            ),
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                text="⚠️ 确认取消",
                callback_data=f"admin:lottery:cancel_ok:{lottery_id}",
            ),
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 不取消", callback_data=f"admin:lottery:item:{lottery_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============ 抽奖创建 FSM 键盘（Phase L.1.2） ============

def lottery_create_cancel_kb() -> InlineKeyboardMarkup:
    """创建抽奖 FSM 通用取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ 取消", callback_data="admin:lottery:c_cancel")],
    ])


def lottery_create_skip_cancel_kb() -> InlineKeyboardMarkup:
    """Step 3 [⏭ 跳过封面] + 取消"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏭ 跳过封面", callback_data="admin:lottery:c_skip_cover"),
            InlineKeyboardButton(text="❌ 取消", callback_data="admin:lottery:c_cancel"),
        ],
    ])


def lottery_create_method_kb() -> InlineKeyboardMarkup:
    """Step 4：参与方式（按键 / 口令）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎲 按键抽奖", callback_data="admin:lottery:c_method:button"),
            InlineKeyboardButton(text="🔑 口令抽奖", callback_data="admin:lottery:c_method:code"),
        ],
        [InlineKeyboardButton(text="❌ 取消", callback_data="admin:lottery:c_cancel")],
    ])


def lottery_create_prize_count_kb() -> InlineKeyboardMarkup:
    """Step 5：中奖人数预设 + 自定义"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1",  callback_data="admin:lottery:c_count:1"),
            InlineKeyboardButton(text="3",  callback_data="admin:lottery:c_count:3"),
            InlineKeyboardButton(text="5",  callback_data="admin:lottery:c_count:5"),
        ],
        [
            InlineKeyboardButton(text="10", callback_data="admin:lottery:c_count:10"),
            InlineKeyboardButton(text="20", callback_data="admin:lottery:c_count:20"),
            InlineKeyboardButton(text="50", callback_data="admin:lottery:c_count:50"),
        ],
        [
            InlineKeyboardButton(text="💬 自定义", callback_data="admin:lottery:c_count_custom"),
            InlineKeyboardButton(text="❌ 取消", callback_data="admin:lottery:c_cancel"),
        ],
    ])


def lottery_create_required_kb(n_added: int) -> InlineKeyboardMarkup:
    """Step 7：必关频道子循环"""
    done_label = f"✅ 完成添加 ({n_added})" if n_added > 0 else "✅ 完成添加"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ 添加",  callback_data="admin:lottery:c_req_add"),
            InlineKeyboardButton(text=done_label, callback_data="admin:lottery:c_req_done"),
        ],
        [InlineKeyboardButton(text="❌ 取消", callback_data="admin:lottery:c_cancel")],
    ])


def lottery_create_publish_mode_kb() -> InlineKeyboardMarkup:
    """Step 8：发布模式"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚡ 立即发布", callback_data="admin:lottery:c_pub:immediate"),
            InlineKeyboardButton(text="⏰ 定时发布", callback_data="admin:lottery:c_pub:scheduled"),
        ],
        [InlineKeyboardButton(text="❌ 取消", callback_data="admin:lottery:c_cancel")],
    ])


def lottery_create_confirm_kb() -> InlineKeyboardMarkup:
    """Step 10：保存草稿 / 设置参与所需积分 / 取消"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 设置参与所需积分", callback_data="admin:lottery:c_set_cost")],
        [
            InlineKeyboardButton(text="✅ 保存草稿", callback_data="admin:lottery:c_save"),
            InlineKeyboardButton(text="❌ 取消", callback_data="admin:lottery:c_cancel"),
        ],
    ])


def lottery_create_cost_cancel_kb() -> InlineKeyboardMarkup:
    """设置参与积分 FSM 取消（回 Step 10 确认页）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:lottery:c_cost_back")],
    ])


# ============ 报销审核子系统 ============


def reimburse_action_kb(reimb_id: int, user_id: int) -> InlineKeyboardMarkup:
    """报销详情页操作按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ 通过",   callback_data=f"reimburse:approve:{reimb_id}"),
            InlineKeyboardButton(text="❌ 驳回",   callback_data=f"reimburse:reject:{reimb_id}"),
        ],
        [InlineKeyboardButton(text="🔄 重置该用户本周",
                              callback_data=f"reimburse:reset:{user_id}:{reimb_id}")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def reimburse_empty_kb() -> InlineKeyboardMarkup:
    """无待审核报销时显示"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def reimburse_reject_cancel_kb(reimb_id: int) -> InlineKeyboardMarkup:
    """驳回 FSM 取消（回详情）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data=f"reimburse:item:{reimb_id}")],
    ])


def reimburse_reset_confirm_kb(user_id: int, reimb_id: int) -> InlineKeyboardMarkup:
    """重置某用户本周配额的二次确认"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认重置",
                                 callback_data=f"reimburse:reset_ok:{user_id}:{reimb_id}"),
            InlineKeyboardButton(text="🔙 取消",
                                 callback_data=f"reimburse:item:{reimb_id}"),
        ],
    ])


def reimburse_pool_cancel_kb() -> InlineKeyboardMarkup:
    """报销池设置 FSM 取消"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="menu:system")],
    ])


def reimburse_queued_pagination_kb(
    page: int, total_pages: int,
) -> InlineKeyboardMarkup:
    """报销名单（queued）分页"""
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️ 上一页",
            callback_data=f"reimburse:queued:{page - 1}",
        ))
    nav.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{max(1, total_pages)}",
        callback_data="noop:reimburse_queued",
    ))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(
            text="➡️ 下一页",
            callback_data=f"reimburse:queued:{page + 1}",
        ))
    return InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def reimburse_queued_item_kb(reimb_id: int) -> InlineKeyboardMarkup:
    """名单单条详情 + 激活按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ 激活为待审核",
                                 callback_data=f"reimburse:activate:{reimb_id}"),
            InlineKeyboardButton(text="🔙 返回名单",
                                 callback_data="reimburse:queued:0"),
        ],
    ])

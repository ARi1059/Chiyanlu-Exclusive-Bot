from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.keyboards.common_kb import miniapp_entry_row

if TYPE_CHECKING:
    # 仅类型提示用，避免运行时循环依赖
    # Phase A0（2026-05-23）：移除 LotteryReconcileItem / LotteryStatusStats（抽奖功能下线）
    from bot.services.admin_overview import AdminOverviewStats
    from bot.services.reimbursement_pool import ReimbursementPoolStats


# ============ 主菜单 ============

def main_menu_kb(
    pending_count: int = 0,
    *,
    pending_review_count: int = 0,
    pending_reimburse_count: int = 0,
    queued_reimburse_count: int = 0,
    is_super: bool = False,
) -> InlineKeyboardMarkup:
    """管理员主菜单面板（2026-06 重排：去重 + 闭环）。

    布局（审核置顶=日常核心，带综合待办角标）：
        [🚀 打开小程序]
        [✅ 审核处理 (N)]
        [👩‍🏫 老师管理]   [📊 数据看板]
        [⚙️ 系统配置]     [💰 财务运营]（超管）
        [🛡 管理员设置]（超管）

    2026-06 重排要点：
        - 合并原「📈 数据分析(dashboard:enter)」+「📊 运营看板(admin:dashboard)」
          为单一「📊 数据看板」入口（dashboard:enter 降为其子视图）。
        - 「🎲 活动运营」改名「💰 财务运营」(admin:operations)，并入「报销配置」。
        - callback 命名空间一律不变；handler 不动。

    Args:
        pending_count: 老师改资料待审核数量
        pending_review_count: 用户评价待审核数量（仅超管计入角标）
        pending_reimburse_count: 待审核报销数量（仅超管计入角标）
        queued_reimburse_count: queued 报销名单数量（保留入参，角标不计）
        is_super: 是否超管
    """
    review_total = pending_count
    if is_super:
        review_total += pending_review_count + pending_reimburse_count
    review_tasks_label = (
        f"✅ 审核处理 ({review_total})" if review_total > 0 else "✅ 审核处理"
    )
    rows: list[list[InlineKeyboardButton]] = [
        miniapp_entry_row(),  # 🚀 打开小程序（§16.3：管理台也走 MiniApp，FSM 保留兜底）
        # 审核处理置顶（日常核心）
        [InlineKeyboardButton(text=review_tasks_label, callback_data="admin:review_tasks")],
        # 老师管理 + 数据看板（合并原 数据分析 + 运营看板）
        [
            InlineKeyboardButton(text="👩‍🏫 老师管理", callback_data="admin:teachers"),
            InlineKeyboardButton(text="📊 数据看板",   callback_data="admin:dashboard"),
        ],
    ]
    # 系统配置 + (超管) 财务运营
    config_row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="⚙️ 系统配置", callback_data="admin:settings"),
    ]
    if is_super:
        config_row.append(
            InlineKeyboardButton(text="💰 财务运营", callback_data="admin:operations"),
        )
    rows.append(config_row)
    # 管理员设置（仅超管）
    if is_super:
        rows.append([
            InlineKeyboardButton(text="🛡 管理员设置", callback_data="admin:admin_settings"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_admin_settings_kb() -> InlineKeyboardMarkup:
    """二级「🛡 管理员设置」面板：超管专用，管理员权限管理 + 返回后台。

    入口：
        - menu:admin       👥 管理员管理（添加 / 移除 / 列表）@super_admin_required

    2026-06：移除「📜 审计日志(dashboard:audit)」——已并入「📊 数据看板」作唯一入口。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 管理员管理", callback_data="menu:admin")],
        [InlineKeyboardButton(text="⬅️ 返回后台", callback_data="menu:main")],
    ])


def admin_teachers_kb() -> InlineKeyboardMarkup:
    """二级「👩‍🏫 老师管理」面板（Phase A0 后 2026-05-23）

    Phase A0：移除「📅 今日发布状态」入口（teacher_daily_status 表整体下线）。
    入口（全部 @admin_required，所有 admin 可见）：
        - menu:teacher          👥 老师档案与启停
        - admin:hot_manage      🔥 热门推荐
        - admin:user_tags       🏷 用户画像
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 老师列表与启停", callback_data="menu:teacher")],
        [InlineKeyboardButton(text="🔥 热门推荐",       callback_data="admin:hot_manage")],
        [InlineKeyboardButton(text="🏷 用户画像",       callback_data="admin:user_tags")],
        [InlineKeyboardButton(text="⬅️ 返回后台",       callback_data="menu:main")],
    ])


def admin_settings_kb(is_super: bool = False) -> InlineKeyboardMarkup:
    """二级「⚙️ 系统配置」面板（2026-06 重排）。

    入口（按 admin_required 权限可见）：
        - menu:channel             📣 频道 / 群组设置
        - menu:system              ⏰ 签到与发布设置（原「系统设置」改名，消同义混淆）
        - admin:subreq             📢 必关订阅（**唯一入口**，已从签到与发布设置去重）
        - admin:publish_templates  🧩 发布模板
        - admin:keywords           🗝 关键词管理
        - admin:report_settings    📅 日报 / 周报设置

    2026-06：「💰 报销配置」已移至「💰 财务运营(admin:operations)」与积分归一，
    本面板不再含报销配置入口（admin:reimburse_config handler 不变）。is_super 入参
    保留以兼容 handler 调用。
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📣 频道 / 群组设置", callback_data="menu:channel")],
        [InlineKeyboardButton(text="⏰ 签到与发布设置",  callback_data="menu:system")],
        [InlineKeyboardButton(text="📢 必关订阅",        callback_data="admin:subreq")],
        [InlineKeyboardButton(text="🧩 发布模板",        callback_data="admin:publish_templates")],
        [InlineKeyboardButton(text="🗝 关键词管理",      callback_data="admin:keywords")],
        [InlineKeyboardButton(text="📅 日报 / 周报设置", callback_data="admin:report_settings")],
        [InlineKeyboardButton(text="⬅️ 返回后台", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_reimburse_config_kb() -> InlineKeyboardMarkup:
    """二级「💰 报销配置」聚合面板（UX-6.2，仅超管可见）。

    2026-05 修订：在 5 项基础配置之上新增「🗓 每周报销上限」（callback
    system:reimburse_weekly_limit），原 POLICY §6.1 硬编码 1 次/周 已升级
    为 config 化（1-10 次范围，默认 1）。

    2026-05-20：评价 footer 文本 / 链接（system:reimburse_promo_text / _url）
    本质上是「评价文案」相关的全局配置，不属于报销功能本身；已迁回
    系统设置子面板（menu:system）统一管理，不在本聚合页重复出现。

    callback 命名空间继续复用 system:reimburse_*，所有原 handler 不动。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 完整规则一览（只读）", callback_data="admin:reimburse_rules")],
        [InlineKeyboardButton(text="🔛 报销功能开关", callback_data="system:reimburse_toggle")],
        [InlineKeyboardButton(text="💰 报销池设置",   callback_data="system:reimburse_pool")],
        [InlineKeyboardButton(text="🔄 重置本月报销池", callback_data="system:reimburse_pool_reset")],
        [InlineKeyboardButton(text="🎚 报销门槛设置", callback_data="system:reimburse_min_points")],
        [InlineKeyboardButton(text="🗓 每周报销上限", callback_data="system:reimburse_weekly_limit")],
        [InlineKeyboardButton(text="📋 报销必关设置", callback_data="system:reimburse_subreq")],
        [InlineKeyboardButton(text="⬅️ 返回财务运营", callback_data="admin:operations")],
    ])


def admin_reimburse_rules_kb() -> InlineKeyboardMarkup:
    """报销规则只读页 keyboard（Sprint 3 §5.2.1 / §5.2.3）。

    无任何编辑按钮（§5.3 禁止）；含「📢 复制公告草稿」基于当前规则生成
    可粘贴文本（§5.2.3）+ 刷新 + 返回报销配置。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📢 复制公告草稿",
                callback_data="admin:reimburse_announce",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔄 刷新",
                callback_data="admin:reimburse_rules:refresh",
            ),
            InlineKeyboardButton(
                text="⬅️ 返回报销配置",
                callback_data="admin:reimburse_config",
            ),
        ],
    ])


def admin_operations_kb() -> InlineKeyboardMarkup:
    """二级「💰 财务运营」面板（2026-06 改名「活动运营」→「财务运营」，钱相关归一）。

    入口（均超管，admin:operations 在主菜单仅对超管渲染）：
        - admin:points            💰 积分管理
        - admin:reimburse_config  💵 报销配置（从「系统配置」移来；含开关/池/门槛/每周上限/必关）
    注：报销审核(reimburse:enter)仍在「审核处理」；报销池状态在「数据看板」——审核/状态/配置分层。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 积分管理", callback_data="admin:points")],
        [InlineKeyboardButton(text="💵 报销配置", callback_data="admin:reimburse_config")],
        [InlineKeyboardButton(text="⬅️ 返回后台", callback_data="menu:main")],
    ])


def admin_review_tasks_kb(
    *,
    pending_edit_count: int = 0,
    pending_review_count: int = 0,
    pending_reimburse_count: int = 0,
    queued_reimburse_count: int = 0,
    is_super: bool = False,
) -> InlineKeyboardMarkup:
    """二级「✅ 审核处理」面板：聚合四个审核入口 + 返回后台

    入口分别对应：
        - review:enter           老师资料审核（teacher_edit_requests，所有管理员可见）
        - rreview:enter          评价审核（teacher_reviews，仅超管）
        - reimburse:enter        报销审核（reimbursements pending，仅超管）
        - reimburse:queued:0     报销名单（reimbursements queued，仅超管 + 有条目时）

    callback 含义未做任何变更，handler 仍由原模块处理（admin_review.py /
    rreview_admin.py / admin_reimburse.py）；本 keyboard 仅是聚合视图。

    每个按钮带 pending count badge（>0 时显示）。
    """
    def _badge(label_base: str, count: int) -> str:
        return f"{label_base} ({count})" if count > 0 else label_base

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text=_badge("👩‍🏫 老师资料审核", pending_edit_count),
            callback_data="review:enter",
        )],
    ]
    if is_super:
        rows.append([InlineKeyboardButton(
            text=_badge("📝 评价审核", pending_review_count),
            callback_data="rreview:enter",
        )])
        rows.append([InlineKeyboardButton(
            text=_badge("💰 报销审核", pending_reimburse_count),
            callback_data="reimburse:enter",
        )])
        if queued_reimburse_count > 0:
            rows.append([InlineKeyboardButton(
                text=f"📋 报销名单 ({queued_reimburse_count})",
                callback_data="reimburse:queued:0",
            )])
    rows.append([InlineKeyboardButton(text="⬅️ 返回后台", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# UX-2 第二项：审核完成后快捷动作 ============================================

_REVIEW_DONE_ENTRY = {
    # kind → 各自审核入口 callback（重新进入 = 看下一条待审，或显示空状态）
    "edit": "review:enter",          # 老师资料审核
    "review": "rreview:enter",       # 评价审核
    "reimburse": "reimburse:enter",  # 报销审核
}


def admin_review_done_next_kb(kind: str) -> InlineKeyboardMarkup:
    """审核完成后的快捷动作面板（UX-2 第二项）。

    在「老师资料 / 评价 / 报销」三类审核 approve / reject 成功后，紧跟 ack 消息
    给出两个快捷按钮：

        [➡️ 处理下一条] → 各自 entry callback（review:enter / rreview:enter /
                          reimburse:enter）：重新进入入口看下一条待审，或显示空状态
        [⬅️ 返回审核处理] → admin:review_tasks：回到审核处理二级页

    与既有「自动推下一条详情」流程互补：自动推送负责高频路径，本快捷按钮
    给「不想看下一条 / 错过推送 / 想换审核类型」的管理员一个明确出口。

    Args:
        kind: "edit" / "review" / "reimburse"，分别对应三类审核。

    Raises:
        ValueError: 传入非预期 kind。
    """
    try:
        entry = _REVIEW_DONE_ENTRY[kind]
    except KeyError as e:
        raise ValueError(
            f"admin_review_done_next_kb: 未知 kind={kind!r}，"
            f"期望 {sorted(_REVIEW_DONE_ENTRY)}"
        ) from e
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ 处理下一条", callback_data=entry)],
        [InlineKeyboardButton(text="⬅️ 返回审核处理", callback_data="admin:review_tasks")],
    ])


def admin_dashboard_kb(is_super: bool = False) -> InlineKeyboardMarkup:
    """二级「📊 数据看板」面板（2026-06 合并原 数据分析 + 运营看板为单一入口）。

    4 子视图：
        - dashboard:enter           📈 数据分析（活跃 / 搜索 / 收藏 / 7 日窗口）
        - admin:overview            📊 运营总览（今日签到 / 新用户 / 待审）
        - admin:reimbursement_pool  💰 报销池状态
        - dashboard:audit           📜 操作日志（审计，唯一入口）
    is_super 入参保留以兼容 handler 调用；本面板对所有 admin 展示同样 4 项。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📈 数据分析", callback_data="dashboard:enter"),
            InlineKeyboardButton(text="📊 运营总览", callback_data="admin:overview"),
        ],
        [
            InlineKeyboardButton(text="💰 报销池状态", callback_data="admin:reimbursement_pool"),
            InlineKeyboardButton(text="📜 操作日志",   callback_data="dashboard:audit"),
        ],
        [InlineKeyboardButton(text="⬅️ 返回后台", callback_data="menu:main")],
    ])


def admin_overview_kb(
    stats: Optional["AdminOverviewStats"] = None,
    *,
    is_super: bool = False,
) -> InlineKeyboardMarkup:
    """运营总览面板：（条件）快捷跳转 + 刷新 + 返回二级页 admin:dashboard。

    Phase A0（2026-05-23）：移除「🎲 抽奖管理」快捷入口（抽奖功能整体下线）。

    UX-2 第三项第一批：当 stats 传入时，按 pending count 与权限渲染快捷跳转：

        老师资料审核 (>0)        → review:enter         所有 admin 可见
        评价审核     (>0)        → rreview:enter        仅超管
        报销审核     (>0)        → reimburse:enter      仅超管
        报销名单     (queued>0)  → reimburse:queued:0   仅超管

    每个快捷按钮带 (N) 角标；count=0 时该按钮整体不显示。
    刷新 + 返回按钮始终保留。

    Args:
        stats: 运营总览统计；None 时不渲染任何快捷跳转（旧调用兼容）
        is_super: 是否超管；非超管不显示评价 / 报销 / 名单 入口
    """
    rows: list[list[InlineKeyboardButton]] = []

    if stats is not None:
        pending_edits = stats.pending_teacher_edits or 0
        if pending_edits > 0:
            rows.append([InlineKeyboardButton(
                text=f"👩‍🏫 老师资料审核 ({pending_edits})",
                callback_data="review:enter",
            )])
        if is_super:
            pending_review = stats.pending_reviews or 0
            if pending_review > 0:
                rows.append([InlineKeyboardButton(
                    text=f"📝 评价审核 ({pending_review})",
                    callback_data="rreview:enter",
                )])
            pending_reimb = stats.pending_reimbursements or 0
            if pending_reimb > 0:
                rows.append([InlineKeyboardButton(
                    text=f"💰 报销审核 ({pending_reimb})",
                    callback_data="reimburse:enter",
                )])
            queued = stats.queued_reimbursements or 0
            if queued > 0:
                rows.append([InlineKeyboardButton(
                    text=f"📋 报销名单 ({queued})",
                    callback_data="reimburse:queued:0",
                )])

    rows.append([
        InlineKeyboardButton(text="🔄 刷新", callback_data="admin:overview:refresh"),
        InlineKeyboardButton(text="⬅️ 返回运营看板", callback_data="admin:dashboard"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_reimbursement_pool_kb(
    stats: Optional["ReimbursementPoolStats"] = None,
    *,
    is_super: bool = False,
) -> InlineKeyboardMarkup:
    """报销池状态面板：（条件）快捷跳转 + 刷新 + 返回二级页 admin:dashboard。

    UX-2 第三项第二批：当 stats 传入且 is_super=True 时，按 count > 0 渲染
    快捷跳转：

        💰 报销审核 (pending_count)  → reimburse:enter        仅超管
        📋 报销名单 (queued_count)   → reimburse:queued:0     仅超管

    每个快捷按钮带 (N) 角标；count=0 / None 时整体不显示。
    刷新 / 返回按钮始终保留。

    Args:
        stats: 报销池统计；None 时不渲染任何快捷跳转（旧无参调用兼容）
        is_super: 是否超管；非超管不显示任何快捷跳转
    """
    rows: list[list[InlineKeyboardButton]] = []

    if stats is not None and is_super:
        pending = stats.pending_count or 0
        if pending > 0:
            rows.append([InlineKeyboardButton(
                text=f"💰 报销审核 ({pending})",
                callback_data="reimburse:enter",
            )])
        queued = stats.queued_count or 0
        if queued > 0:
            rows.append([InlineKeyboardButton(
                text=f"📋 报销名单 ({queued})",
                callback_data="reimburse:queued:0",
            )])

    rows.append([
        InlineKeyboardButton(text="🔄 刷新", callback_data="admin:reimbursement_pool:refresh"),
        InlineKeyboardButton(text="⬅️ 返回运营看板", callback_data="admin:dashboard"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Phase A0（2026-05-23）已下线：admin_lottery_status_kb（抽奖功能整体下线）


# ============ 报表设置（Phase 6.3） ============


def report_settings_cancel_kb() -> InlineKeyboardMarkup:
    """报表设置 FSM 输入页的取消按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:report_settings")],
    ])


# ============ 管理员今日状态总览（Phase 5） ============


# Phase A0（2026-05-23）已下线：admin_today_status_kb（老师今日状态功能整体下线）


# ============ 用户画像看板（Phase 6.1） ============


def user_tags_menu_kb() -> InlineKeyboardMarkup:
    """用户画像看板主面板

    返回按钮指向二级页 admin:teachers（👩‍🏫 老师管理），不再直接回 menu:main——
    UX-1 第四批返回路径优化（2026-05）。查询结果页（user_tags_query_result_kb）
    的「主菜单」快捷出口保持不变。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 查询标签用户", callback_data="admin:user_tags:query")],
        [
            InlineKeyboardButton(text="🔄 刷新", callback_data="admin:user_tags"),
            InlineKeyboardButton(text="⬅️ 返回老师管理", callback_data="admin:teachers"),
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
    """发布模板管理主面板

    返回按钮指向二级页 admin:settings（⚙️ 系统配置），不再直接回 menu:main——
    UX-1 第三批返回路径优化（2026-05）。深层子页（模板列表 / 详情等）
    的返回路径保持不变。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 模板列表", callback_data="admin:publish_templates:list")],
        [InlineKeyboardButton(text="➕ 新建模板", callback_data="admin:publish_templates:create")],
        [InlineKeyboardButton(text="✏️ 编辑默认模板", callback_data="admin:publish_templates:edit_default")],
        [InlineKeyboardButton(text="✅ 设置默认模板", callback_data="admin:publish_templates:set_default")],
        [InlineKeyboardButton(text="⬅️ 返回系统配置", callback_data="admin:settings")],
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


# ============ Phase 4 dead code 历史注释 ============
# 注：推广链接（promo_links_menu_kb / promo_cancel_kb）于 2026-05-20
# Sprint 7 §9.1 第 1 批 dead code 删除中清理；渠道统计（source_stats_menu_kb /
# source_stats_back_kb / source_lookup_cancel_kb）于 2026-05-20 Sprint 7 §9.1
# 第 2 批清理。原 admin:promo* / admin:source_stats* / admin:user_source 入口已于
# 2026-05-18 Phase 4 下线。bot/database.py 中的 4 个 source DB helper
# (count_total_source_users / get_top_sources_by_type / get_user_source_summary /
# get_source_stats) 已于 2026-05-20 Sprint 7 §9.1.4 第 3 批一并清理。


# ============ 热门推荐管理（Phase 3） ============


def hot_manage_menu_kb() -> InlineKeyboardMarkup:
    """热门推荐管理子面板

    返回按钮指向二级页 admin:teachers（👩‍🏫 老师管理），不再直接回 menu:main——
    UX-1 第四批返回路径优化（2026-05）。FSM 取消（hot_manage_cancel_kb）
    指向 admin:hot_manage，保持不变。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 添加推荐", callback_data="admin:hot:add")],
        [InlineKeyboardButton(text="✏️ 修改权重", callback_data="admin:hot:weight")],
        [InlineKeyboardButton(text="❌ 取消推荐", callback_data="admin:hot:remove")],
        [InlineKeyboardButton(text="🔄 重算热度", callback_data="admin:hot:recalc")],
        [InlineKeyboardButton(text="⬅️ 返回老师管理", callback_data="admin:teachers")],
    ])


def hot_manage_cancel_kb() -> InlineKeyboardMarkup:
    """热门推荐管理流程内的取消按钮（返回 hot manage 主页）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="admin:hot_manage")],
    ])


# ============ 数据看板（Phase 1） ============


def dashboard_menu_kb() -> InlineKeyboardMarkup:
    """数据分析视图（dashboard:enter）：刷新 / 操作日志 / 返回数据看板（闭环）。

    2026-06：本视图降为「📊 数据看板」子项，返回从 menu:main 改指 admin:dashboard。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 刷新", callback_data="dashboard:enter"),
            InlineKeyboardButton(text="📜 操作日志", callback_data="dashboard:audit"),
        ],
        [InlineKeyboardButton(text="🔙 返回数据看板", callback_data="admin:dashboard")],
    ])


def teacher_profile_draft_restore_kb() -> InlineKeyboardMarkup:
    """tprofile:add 入口检测到草稿时的引导（UX-9.3）：恢复 / 丢弃重新开始。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ 恢复上次录入", callback_data="tprofile:draft_restore")],
        [InlineKeyboardButton(text="🗑 丢弃 → 重新开始", callback_data="tprofile:draft_discard")],
        [InlineKeyboardButton(text="🔙 返回老师档案管理", callback_data="tprofile:cancel")],
    ])


def teacher_profile_cancel_confirm_kb() -> InlineKeyboardMarkup:
    """tprofile:cancel 检测到 state 有数据时的二次确认（UX-9.3）：保存 / 不保存。

    刻意不放"继续录入"——既然用户已经点了取消，再回去会让 callback 状态错乱；
    用户如果后悔可以重新点 [➕ 完整档案录入]，若选了保存草稿则能恢复。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 保存草稿后退出", callback_data="tprofile:cancel_save")],
        [InlineKeyboardButton(text="🗑 不保存直接退出", callback_data="tprofile:cancel_nosave")],
    ])


def dashboard_audit_back_kb() -> InlineKeyboardMarkup:
    """操作日志页：返回看板 / 主菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 返回看板", callback_data="dashboard:enter"),
            InlineKeyboardButton(text="🏠 主菜单", callback_data="menu:main"),
        ],
    ])


def dashboard_audit_paginated_kb(
    *,
    page: int,
    total_pages: int,
    action_filter: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """操作日志分页 keyboard（UX-9.6）。

    布局：
        Row 1：[⬅️ 上一页] [📄 X/Y] [➡️ 下一页]
        Row 2：[🔍 筛选 action] / 当前 action 过滤中 → [🔁 显示全部]
        Row 3：[🔙 返回看板] [🏠 主菜单]

    Args:
        page:         当前页（0-based）
        total_pages:  总页数（>=1）
        action_filter: 当前 action 过滤；None 表示无过滤。
            非空时翻页/筛选按钮 callback 都携带该 action。

    callback 格式：
        - 无过滤：dashboard:audit:p:<n>
        - 有过滤：dashboard:audit:f:<action>:<n>
        - 进入筛选子菜单：dashboard:audit:filter
        - 显示全部（清除过滤）：dashboard:audit:all
    """
    def _page_cb(p: int) -> str:
        if action_filter:
            return f"dashboard:audit:f:{action_filter}:{p}"
        return f"dashboard:audit:p:{p}"

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️ 上一页", callback_data=_page_cb(page - 1),
        ))
    nav.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{max(1, total_pages)}",
        callback_data="noop:audit_page",
    ))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(
            text="➡️ 下一页", callback_data=_page_cb(page + 1),
        ))

    if action_filter:
        filter_row = [InlineKeyboardButton(
            text=f"🔁 显示全部（当前过滤 {action_filter}）",
            callback_data="dashboard:audit:all",
        )]
    else:
        filter_row = [InlineKeyboardButton(
            text="🔍 筛选 action", callback_data="dashboard:audit:filter",
        )]

    return InlineKeyboardMarkup(inline_keyboard=[
        nav,
        filter_row,
        [
            InlineKeyboardButton(text="🔙 返回看板", callback_data="dashboard:enter"),
            InlineKeyboardButton(text="🏠 主菜单", callback_data="menu:main"),
        ],
    ])


def dashboard_audit_filter_menu_kb(action_options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """操作日志筛选子菜单（UX-9.6）。

    Args:
        action_options: list[(action_key, display_label)]——caller 决定哪些 action
            出现在筛选选项里（建议按高频排序，控制在 8-10 个内避免按钮溢出）。

    callback 格式：dashboard:audit:f:<action>:0 直接进 page 0。
    """
    rows: list[list[InlineKeyboardButton]] = []
    # 每行 1 个按钮（避免文案太长溢出）
    for action_key, label in action_options:
        rows.append([InlineKeyboardButton(
            text=f"{label}",
            callback_data=f"dashboard:audit:f:{action_key}:0",
        )])
    rows.append([
        InlineKeyboardButton(text="🔙 返回日志", callback_data="dashboard:audit"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============ 老师管理子面板 ============

def teacher_menu_kb() -> InlineKeyboardMarkup:
    """老师管理子面板

    2026-05-17：移除简版录入入口；统一通过 [📋 老师档案管理] 进入完整档案流程。

    返回按钮指向二级页 admin:teachers（👩‍🏫 老师管理），不再直接回 menu:main——
    UX-1 第四批返回路径优化（2026-05）。深层子页（老师列表 / 老师档案管理 /
    启停列表等）的返回路径保持不变。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 老师档案管理", callback_data="tprofile:menu")],
        [
            InlineKeyboardButton(text="停用老师", callback_data="teacher:delete"),
            InlineKeyboardButton(text="启用老师", callback_data="teacher:enable"),
        ],
        [
            InlineKeyboardButton(text="🗑 删除老师", callback_data="teacher:purge"),
            InlineKeyboardButton(text="♻️ 恢复老师", callback_data="teacher:restore"),
        ],
        [InlineKeyboardButton(text="📋 老师列表", callback_data="teacher:list")],
        [InlineKeyboardButton(text="⬅️ 返回老师管理", callback_data="admin:teachers")],
    ])


# ============ 老师档案管理（Phase 9.1） ============

def teacher_profile_menu_kb() -> InlineKeyboardMarkup:
    """[📋 老师档案管理] 子菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 完整档案录入", callback_data="tprofile:add")],
        [InlineKeyboardButton(text="✏️ 编辑老师档案", callback_data="tprofile:edit")],
        [InlineKeyboardButton(text="🖼 管理照片相册", callback_data="tprofile:album")],
        [InlineKeyboardButton(text="👁 预览档案 caption", callback_data="tprofile:preview")],
        [InlineKeyboardButton(text="🔄 老数据一键同步", callback_data="tprofile:sync_legacy")],
        [InlineKeyboardButton(text="🔙 返回老师管理", callback_data="menu:teacher")],
    ])


def tprofile_sync_legacy_confirm_kb() -> InlineKeyboardMarkup:
    """老数据同步预览页的二次确认"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认同步",
                                 callback_data="tprofile:sync_legacy_ok"),
            InlineKeyboardButton(text="🔙 取消",
                                 callback_data="tprofile:menu"),
        ],
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
    """管理员管理子面板

    返回按钮指向二级页 admin:admin_settings（🛡 管理员设置），不再直接回 menu:main——
    UX-1 第五批返回路径优化（2026-05）。深层子页（admin_remove_kb 选择列表的
    返回按钮指向 menu:admin）的返回路径保持不变。

    注：dashboard:audit（审计日志）同时可从「📈 数据分析」进入，其返回路径
    本批暂不调整，单独评估。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 添加管理员", callback_data="admin:add")],
        [InlineKeyboardButton(text="➖ 移除管理员", callback_data="admin:remove")],
        [InlineKeyboardButton(text="📋 管理员列表", callback_data="admin:list")],
        [InlineKeyboardButton(text="⬅️ 返回管理员设置", callback_data="admin:admin_settings")],
    ])


# ============ 频道设置子面板 ============

def channel_menu_kb() -> InlineKeyboardMarkup:
    """频道设置子面板

    Phase 9.2：新增 [📦 设置档案频道]（archive_channel_id），与"发布目标"解耦。

    返回按钮指向二级页 admin:settings（⚙️ 系统配置），不再直接回 menu:main——
    UX-1 第三批返回路径优化（2026-05）。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 设置发布目标", callback_data="channel:set_publish")],
        [InlineKeyboardButton(text="📦 设置档案频道", callback_data="channel:set_archive")],
        [InlineKeyboardButton(text="💬 设置响应群组", callback_data="channel:set_response")],
        [InlineKeyboardButton(text="📋 查看当前设置", callback_data="channel:view")],
        [InlineKeyboardButton(text="⬅️ 返回系统配置", callback_data="admin:settings")],
    ])


# ============ 系统设置子面板 ============

def system_menu_kb() -> InlineKeyboardMarkup:
    """系统设置子面板

    返回按钮指向二级页 admin:settings（⚙️ 系统配置），不再直接回 menu:main——
    UX-1 第三批返回路径优化（2026-05）。深层子项（system:status / publish:* /
    system:reminder_* 等）的返回路径保持不变。

    2026-05-20：移除 5 个已被「💰 报销配置（admin:reimburse_config）」聚合页
    收纳的报销按钮（reimburse_pool / reimburse_toggle / reimburse_min_points /
    reimburse_pool_reset / reimburse_subreq），避免与聚合页入口功能重复；
    callback handler 本身保持不变，仅本面板不再展示入口。

    同时把评价 footer 文本 / 链接两个按钮（system:reimburse_promo_text /
    _url）从「报销配置」聚合页移回本系统设置面板——这两项本质是评价文案
    全局配置（不专属于报销），与本面板其他单项配置同类。
    """
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
        # 2026-06：移除重复的「📋 必关频道/群组(admin:subreq)」——必关订阅唯一入口在「系统配置」。
        # Phase A0（2026-05-23）已下线：[👨‍💼 抽奖客服链接] system:lottery_contact
        [InlineKeyboardButton(text="📢 评价 footer 文本", callback_data="system:reimburse_promo_text")],
        [InlineKeyboardButton(text="🔗 评价 footer 链接", callback_data="system:reimburse_promo_url")],
        [
            InlineKeyboardButton(text="🏷 档案品牌名",   callback_data="system:brand_name"),
            InlineKeyboardButton(text="📡 档案品牌频道", callback_data="system:brand_channels"),
        ],
        [InlineKeyboardButton(text="⬅️ 返回系统配置", callback_data="admin:settings")],
    ])


# ============ 必关频道/群组（Phase 9.3） ============

def subreq_menu_kb() -> InlineKeyboardMarkup:
    """[📋 必关频道/群组] 子菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 添加", callback_data="admin:subreq:add")],
        [InlineKeyboardButton(text="📋 列表", callback_data="admin:subreq")],
        [InlineKeyboardButton(text="🔙 返回系统配置", callback_data="admin:settings")],
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
    rows.append([InlineKeyboardButton(text="🔙 返回系统配置", callback_data="admin:settings")])
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


def teacher_purge_list_kb(teachers: list[dict]) -> InlineKeyboardMarkup:
    """删除老师列表（选择要软删除的老师）。

    专用 teacher:purge_select: 前缀，避免与 teacher:select:（停用/编辑双注册）冲突。
    """
    keyboard = []
    for t in teachers:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{t['display_name']} (@{t['username']})",
                callback_data=f"teacher:purge_select:{t['user_id']}",
            )
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 返回", callback_data="menu:teacher")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def teacher_restore_list_kb(teachers: list[dict]) -> InlineKeyboardMarkup:
    """已删除老师列表（选择要恢复的老师，仅超管）"""
    keyboard = []
    for t in teachers:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{t['display_name']} (@{t['username']})",
                callback_data=f"teacher:restore_select:{t['user_id']}",
            )
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 返回", callback_data="menu:teacher")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def purge_confirm_kb(teacher_id: int) -> InlineKeyboardMarkup:
    """删除老师二次确认"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ 确认删除", callback_data=f"teacher:confirm_purge:{teacher_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data="teacher:purge"),
        ],
    ])


def restore_confirm_kb(teacher_id: int) -> InlineKeyboardMarkup:
    """恢复老师二次确认"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="♻️ 确认恢复", callback_data=f"teacher:confirm_restore:{teacher_id}"),
            InlineKeyboardButton(text="🔙 取消", callback_data="teacher:restore"),
        ],
    ])


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
    # UX-4.6：先回审核处理（上下文），再保留旧的主菜单兜底
    rows.append([InlineKeyboardButton(text="🔙 返回审核处理", callback_data="admin:review_tasks")])
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
    """审核队列为空时的返回按钮（UX-4.6：先回审核处理，再保留主菜单兜底）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回审核处理", callback_data="admin:review_tasks")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def review_claim_conflict_kb(
    kind: str, target_id: int,
) -> InlineKeyboardMarkup:
    """审核冲突页 keyboard（UX-7.1）。

    展示给"另一管理员正在审核此条"的访问者，提供：
        - [🛡 强制接管 + 进入审核]   强制覆盖锁后渲染详情
        - [🔙 返回审核处理]          放弃

    Args:
        kind:    "edit_request"（老师资料）/ "teacher_review"（评价）/
                 "reimbursement"（报销）；决定 force_claim callback 命名空间。
        target_id: 对应资源 id。
    """
    if kind == "edit_request":
        force_cb = f"review:force_claim:{target_id}"
    elif kind == "teacher_review":
        force_cb = f"rreview:force_claim:{target_id}"
    elif kind == "reimbursement":
        force_cb = f"reimburse:force_claim:{target_id}"
    else:
        # 未知 kind：兜底回审核处理，不出现 force_claim 按钮
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 返回审核处理", callback_data="admin:review_tasks")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡 强制接管 + 进入审核", callback_data=force_cb)],
        [InlineKeyboardButton(text="🔙 返回审核处理", callback_data="admin:review_tasks")],
    ])


# ============ 报告审核中心（Phase 9.4） ============

def rreview_action_kb(
    review_id: int,
    *,
    has_prev: bool,
    has_next: bool,
    has_gesture: bool = True,
) -> InlineKeyboardMarkup:
    """单条报告审核详情页操作按钮（spec §4.2）

    has_gesture（2026-05-21）：False 时省略「✋ 重看手势照片」按钮——
    用户未参与报销路径的评价没有手势照，按钮点不动也不该出现。
    默认 True 兼容旧调用方；新调用应明确传入 review["gesture_photo_file_id"]
    的真值判断。
    """
    photo_row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="🖼 重看约课截图", callback_data=f"rreview:photo:booking:{review_id}"),
    ]
    if has_gesture:
        photo_row.append(
            InlineKeyboardButton(text="✋ 重看手势照片", callback_data=f"rreview:photo:gesture:{review_id}"),
        )
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="✅ 通过", callback_data=f"rreview:approve:{review_id}"),
            InlineKeyboardButton(text="❌ 驳回", callback_data=f"rreview:reject:{review_id}"),
        ],
        photo_row,
    ]
    nav: list[InlineKeyboardButton] = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="⬅️ 上一条", callback_data=f"rreview:nav:prev:{review_id}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="➡️ 下一条", callback_data=f"rreview:nav:next:{review_id}"))
    if nav:
        rows.append(nav)
    # UX-4.6：先回审核处理（上下文），再保留旧的主面板兜底
    rows.append([InlineKeyboardButton(text="🔙 返回审核处理", callback_data="admin:review_tasks")])
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
    """报告审核队列为空（UX-4.6：先回审核处理，再保留主面板兜底）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回审核处理", callback_data="admin:review_tasks")],
        [InlineKeyboardButton(text="🔙 返回主面板", callback_data="menu:main")],
    ])


def rreview_push_action_kb(bot_username: str | None = None) -> InlineKeyboardMarkup:
    """新评价推送给超管时附带的按钮。

    bot_username 给定时附「📲 打开小程序处理」(startapp=admin 直达管理台)；
    始终保留「📝 前往审核」(bot 内审核，向后兼容)。
    """
    from bot.keyboards.common_kb import miniapp_admin_url_button
    rows: list[list[InlineKeyboardButton]] = []
    mini = miniapp_admin_url_button(bot_username)
    if mini is not None:
        rows.append([mini])
    rows.append([InlineKeyboardButton(text="📝 前往审核", callback_data="rreview:enter")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_points_menu_kb() -> InlineKeyboardMarkup:
    """[💰 积分管理] 子菜单（spec §3.2）

    返回按钮指向二级页 admin:operations（🎲 活动运营），不再直接回 menu:main——
    UX-1 第二批返回路径优化（2026-05）。深层子页（admin_points_back_kb 等）
    的返回路径保持不变。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 积分规则一览（只读）", callback_data="admin:points_rules")],
        [InlineKeyboardButton(text="📊 积分对账（只读）",     callback_data="admin:points_reconcile")],
        [InlineKeyboardButton(text="🔍 查询用户积分", callback_data="admin:points:query")],
        [InlineKeyboardButton(text="➕ 手动加分",     callback_data="admin:points:grant")],
        [InlineKeyboardButton(text="📊 积分总览",     callback_data="admin:points:overview")],
        [InlineKeyboardButton(text="⬅️ 返回活动运营", callback_data="admin:operations")],
    ])


def admin_points_reconcile_overview_kb(anomaly_users: int = 0) -> InlineKeyboardMarkup:
    """积分对账概览 keyboard（Sprint 4 §6.2.3）。

    无任何修正按钮（§6.3 禁止）；anomaly_users > 0 时含「📋 异常用户列表」入口。
    """
    rows: list[list[InlineKeyboardButton]] = []
    if anomaly_users > 0:
        rows.append([
            InlineKeyboardButton(
                text=f"📋 异常用户列表 ({anomaly_users})",
                callback_data="admin:points_reconcile:anomaly:1",
            ),
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔄 刷新",
            callback_data="admin:points_reconcile:refresh",
        ),
        InlineKeyboardButton(
            text="⬅️ 返回积分管理",
            callback_data="admin:points",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_points_reconcile_anomaly_kb(
    page: int, total_pages: int,
) -> InlineKeyboardMarkup:
    """积分异常用户列表分页 keyboard（Sprint 4 §6.2.3）。

    无修正按钮（§6.3 禁止）；分页 + 返回对账概览。
    """
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            text="⬅️ 上一页",
            callback_data=f"admin:points_reconcile:anomaly:{page - 1}",
        ))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            text="下一页 ➡️",
            callback_data=f"admin:points_reconcile:anomaly:{page + 1}",
        ))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(
            text="🔄 刷新当前页",
            callback_data=f"admin:points_reconcile:anomaly:{page}",
        ),
        InlineKeyboardButton(
            text="⬅️ 返回对账概览",
            callback_data="admin:points_reconcile",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_points_rules_kb() -> InlineKeyboardMarkup:
    """积分规则只读页 keyboard（Sprint 4 §6.2.1）。

    无任何编辑按钮（§6.3 禁止）；仅刷新 + 返回积分管理。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔄 刷新",
                callback_data="admin:points_rules:refresh",
            ),
            InlineKeyboardButton(
                text="⬅️ 返回积分管理",
                callback_data="admin:points",
            ),
        ],
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


# Phase A0（2026-05-23）已下线：抽奖管理 keyboards（admin_lottery_*_kb / lottery_*_kb 共 18 个）
# 删除原因：见 docs/DELETED-FEATURES.md（抽奖功能整体下线）。


# ============ 报销审核子系统 ============


def reimburse_action_kb(reimb_id: int, user_id: int) -> InlineKeyboardMarkup:
    """报销详情页操作按钮（UX-4.6：先回审核处理，再保留主菜单兜底）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ 通过",   callback_data=f"reimburse:approve:{reimb_id}"),
            InlineKeyboardButton(text="❌ 驳回",   callback_data=f"reimburse:reject:{reimb_id}"),
        ],
        [InlineKeyboardButton(text="🔄 重置该用户本周",
                              callback_data=f"reimburse:reset:{user_id}:{reimb_id}")],
        [InlineKeyboardButton(text="🔙 返回审核处理", callback_data="admin:review_tasks")],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


def reimburse_empty_kb() -> InlineKeyboardMarkup:
    """无待审核报销时显示（UX-4.6：先回审核处理，再保留主菜单兜底）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回审核处理", callback_data="admin:review_tasks")],
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


# ============ 报销专用必关频道 / 群组（与全局 subreq 分离） ============


def reimburse_subreq_menu_kb(chats: list[dict]) -> InlineKeyboardMarkup:
    """报销专用必关设置主面板。

    布局：
        每项一行：[🗑 删除：{display_name}] → system:reimburse_subreq:delete:<idx>
        [➕ 添加频道 / 群组] → system:reimburse_subreq:add
        [🔄 刷新] → system:reimburse_subreq
        [⬅️ 返回系统设置] → menu:system

    chats 为空时只显示 add / 刷新 / 返回三个按钮。
    """
    rows: list[list[InlineKeyboardButton]] = []
    for idx, c in enumerate(chats):
        name = c.get("display_name") or str(c.get("chat_id"))
        text = f"🗑 删除：{name}"
        if len(text) > 60:
            text = text[:57] + "…"
        rows.append([InlineKeyboardButton(
            text=text,
            callback_data=f"system:reimburse_subreq:delete:{idx}",
        )])
    rows.append([InlineKeyboardButton(
        text="➕ 添加频道 / 群组",
        callback_data="system:reimburse_subreq:add",
    )])
    rows.append([
        InlineKeyboardButton(text="🔄 刷新", callback_data="system:reimburse_subreq"),
        InlineKeyboardButton(text="⬅️ 返回系统设置", callback_data="menu:system"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reimburse_subreq_remove_confirm_kb(idx: int) -> InlineKeyboardMarkup:
    """删除二次确认。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⚠️ 确认删除",
                callback_data=f"system:reimburse_subreq:confirm_delete:{idx}",
            ),
            InlineKeyboardButton(
                text="🔙 取消",
                callback_data="system:reimburse_subreq",
            ),
        ],
    ])


def reimburse_subreq_cancel_kb() -> InlineKeyboardMarkup:
    """添加 FSM 通用取消按钮。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ 取消",
            callback_data="system:reimburse_subreq",
        )],
    ])


def reimburse_subreq_add_confirm_kb() -> InlineKeyboardMarkup:
    """添加确认页：确认添加 / 取消。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ 确认添加",
                callback_data="system:reimburse_subreq:add_confirm",
            ),
            InlineKeyboardButton(
                text="❌ 取消",
                callback_data="system:reimburse_subreq",
            ),
        ],
    ])


# ============ 报销审核 + 支付宝口令发放（2026-05） ============


def reimburse_pending_super_notice_kb(bot_username: str | None = None) -> InlineKeyboardMarkup:
    """报告审核通过后通知超管的快捷按钮组。

    bot_username 给定时附「📲 打开小程序处理」(startapp=admin)；始终保留 bot 内入口。
    """
    from bot.keyboards.common_kb import miniapp_admin_url_button
    rows: list[list[InlineKeyboardButton]] = []
    mini = miniapp_admin_url_button(bot_username)
    if mini is not None:
        rows.append([mini])
    rows.append([
        InlineKeyboardButton(text="💰 去审核报销", callback_data="reimburse:enter"),
        InlineKeyboardButton(text="✅ 审核处理", callback_data="admin:review_tasks"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reimburse_payout_waiting_cancel_kb(reimb_id: int) -> InlineKeyboardMarkup:
    """waiting_token 期间的取消按钮（不修改报销状态，仅清理 FSM 回详情列表）。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ 取消",
            callback_data=f"reimburse:payout:cancel:{reimb_id}",
        )],
    ])


def reimburse_payout_confirm_kb(reimb_id: int) -> InlineKeyboardMarkup:
    """confirming 状态下的确认页：发送 / 重新输入 / 取消。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ 确认发送并完成",
            callback_data=f"reimburse:payout:confirm:{reimb_id}",
        )],
        [
            InlineKeyboardButton(
                text="🔁 重新输入",
                callback_data=f"reimburse:payout:retry:{reimb_id}",
            ),
            InlineKeyboardButton(
                text="❌ 取消",
                callback_data=f"reimburse:payout:cancel:{reimb_id}",
            ),
        ],
    ])


def reimburse_payout_done_kb() -> InlineKeyboardMarkup:
    """口令发送成功后的"处理下一条 / 返回审核处理"。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➡️ 处理下一条",
            callback_data="reimburse:enter",
        )],
        [InlineKeyboardButton(
            text="⬅️ 返回审核处理",
            callback_data="admin:review_tasks",
        )],
    ])


# ============ 报销门槛配置（2026-05 新增） ============


def reimburse_min_points_menu_kb() -> InlineKeyboardMarkup:
    """🎚 报销门槛设置主面板：修改 + 返回系统设置。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ 修改门槛",
            callback_data="system:reimburse_min_points:edit",
        )],
        [InlineKeyboardButton(
            text="⬅️ 返回系统设置",
            callback_data="menu:system",
        )],
    ])


def reimburse_min_points_cancel_kb() -> InlineKeyboardMarkup:
    """报销门槛 FSM 通用取消按钮（回主面板）。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ 取消",
            callback_data="system:reimburse_min_points",
        )],
    ])


def reimburse_min_points_confirm_kb() -> InlineKeyboardMarkup:
    """确认修改报销门槛：确认 / 取消。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ 确认修改",
                callback_data="system:reimburse_min_points:confirm",
            ),
            InlineKeyboardButton(
                text="❌ 取消",
                callback_data="system:reimburse_min_points",
            ),
        ],
    ])


# ============ 每周报销上限（2026-05 新增） ============


def reimburse_weekly_limit_menu_kb() -> InlineKeyboardMarkup:
    """🗓 每周报销上限主面板：修改 + 返回报销配置。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ 修改每周上限",
            callback_data="system:reimburse_weekly_limit:edit",
        )],
        [InlineKeyboardButton(
            text="⬅️ 返回报销配置",
            callback_data="admin:reimburse_config",
        )],
    ])


def reimburse_weekly_limit_cancel_kb() -> InlineKeyboardMarkup:
    """每周上限 FSM 通用取消按钮（回主面板）。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ 取消",
            callback_data="system:reimburse_weekly_limit",
        )],
    ])


def reimburse_weekly_limit_confirm_kb() -> InlineKeyboardMarkup:
    """确认修改每周上限：确认 / 取消。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ 确认修改",
                callback_data="system:reimburse_weekly_limit:confirm",
            ),
            InlineKeyboardButton(
                text="❌ 取消",
                callback_data="system:reimburse_weekly_limit",
            ),
        ],
    ])


# ============ 评价 footer 推广（2026-05 新增） ============


def reimburse_promo_text_menu_kb() -> InlineKeyboardMarkup:
    """📢 footer 文本主面板：修改 + 清空 + 返回系统设置。

    2026-05-20：入口已从「报销配置」聚合页迁回「系统设置」（menu:system），
    返回按钮一并改指 menu:system。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ 修改文本",
            callback_data="system:reimburse_promo_text:edit",
        )],
        [InlineKeyboardButton(
            text="🗑 清空（禁用 footer）",
            callback_data="system:reimburse_promo_text:clear",
        )],
        [InlineKeyboardButton(
            text="⬅️ 返回系统设置",
            callback_data="menu:system",
        )],
    ])


def reimburse_promo_text_cancel_kb() -> InlineKeyboardMarkup:
    """footer 文本 FSM 通用取消按钮（回主面板）。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ 取消",
            callback_data="system:reimburse_promo_text",
        )],
    ])


def reimburse_promo_text_confirm_kb() -> InlineKeyboardMarkup:
    """确认修改 footer 文本：确认 / 取消。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ 确认修改",
                callback_data="system:reimburse_promo_text:confirm",
            ),
            InlineKeyboardButton(
                text="❌ 取消",
                callback_data="system:reimburse_promo_text",
            ),
        ],
    ])


def reimburse_promo_url_menu_kb() -> InlineKeyboardMarkup:
    """🔗 footer 链接主面板：修改 + 清空 + 返回系统设置。

    2026-05-20：入口已从「报销配置」聚合页迁回「系统设置」（menu:system），
    返回按钮一并改指 menu:system。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ 修改链接",
            callback_data="system:reimburse_promo_url:edit",
        )],
        [InlineKeyboardButton(
            text="🗑 清空（禁用 footer）",
            callback_data="system:reimburse_promo_url:clear",
        )],
        [InlineKeyboardButton(
            text="⬅️ 返回系统设置",
            callback_data="menu:system",
        )],
    ])


def reimburse_promo_url_cancel_kb() -> InlineKeyboardMarkup:
    """footer 链接 FSM 通用取消按钮（回主面板）。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ 取消",
            callback_data="system:reimburse_promo_url",
        )],
    ])


def reimburse_promo_url_confirm_kb() -> InlineKeyboardMarkup:
    """确认修改 footer 链接：确认 / 取消。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ 确认修改",
                callback_data="system:reimburse_promo_url:confirm",
            ),
            InlineKeyboardButton(
                text="❌ 取消",
                callback_data="system:reimburse_promo_url",
            ),
        ],
    ])


# ============ 本月报销池重置（2026-05 新增） ============


def reimburse_pool_reset_cancel_kb() -> InlineKeyboardMarkup:
    """重置 FSM 通用取消按钮（回报销池设置）。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ 取消",
            callback_data="system:reimburse_pool_reset",
        )],
    ])


def reimburse_pool_reset_confirm_kb() -> InlineKeyboardMarkup:
    """确认重置本月报销池：确认 / 取消。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ 确认重置",
                callback_data="system:reimburse_pool_reset:confirm",
            ),
            InlineKeyboardButton(
                text="❌ 取消",
                callback_data="system:reimburse_pool_reset",
            ),
        ],
    ])


def reimburse_pool_reset_done_kb() -> InlineKeyboardMarkup:
    """重置成功后的快捷动作。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 返回报销池设置",
            callback_data="system:reimburse_pool",
        )],
        [InlineKeyboardButton(
            text="📊 查看报销池状态",
            callback_data="admin:reimbursement_pool",
        )],
        [InlineKeyboardButton(
            text="⬅️ 返回系统设置",
            callback_data="menu:system",
        )],
    ])


def reimburse_subreq_user_gate_kb(
    missing: list[dict],
    *,
    context: str = "submit",
) -> InlineKeyboardMarkup:
    """用户报销准入拦截页 keyboard。

    Args:
        missing: 用户尚未加入的必关项列表
        context: "submit" 或 "card"——表示触发自评价提交 FSM 还是评价卡片 FSM；
                 重新检查时通过此值回到正确的入口

    布局：
        若 missing 项有 invite_link，每项一行 [📢 加入：{display_name}] URL
        [✅ 我已加入，重新检查] → reimburse:subreq:recheck:<context>
        [⬅️ 返回] → reimburse:subreq:back:<context>
    """
    rows: list[list[InlineKeyboardButton]] = []
    for it in missing:
        link = (it.get("invite_link") or "").strip()
        if link.startswith("http://") or link.startswith("https://"):
            name = it.get("display_name") or "未命名频道"
            label = f"📢 加入：{name}"
            if len(label) > 60:
                label = label[:57] + "…"
            rows.append([InlineKeyboardButton(text=label, url=link)])
    rows.append([InlineKeyboardButton(
        text="✅ 我已加入，重新检查",
        callback_data=f"reimburse:subreq:recheck:{context}",
    )])
    rows.append([InlineKeyboardButton(
        text="⬅️ 返回",
        callback_data=f"reimburse:subreq:back:{context}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============ 群组快捷词管理（UX-9.1） ============


def admin_keyword_list_kb(
    items: list[dict],
) -> InlineKeyboardMarkup:
    """关键词列表面板：每条占两行（标题 + 编辑/启停/删除按钮组）。

    items: list[dict]，每行需含 id / trigger / enabled / hit_count。
    """
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(
        text="➕ 新增关键词", callback_data="admin:keywords:add",
    )])
    for it in items:
        kid = int(it["id"])
        enabled = int(it.get("enabled") or 0)
        trigger = it.get("trigger") or "?"
        hits = int(it.get("hit_count") or 0)
        flag = "✅" if enabled else "⏸"
        # 第 1 行：标签 + 命中次数（只读展示，点击进入编辑详情）
        rows.append([InlineKeyboardButton(
            text=f"{flag} {trigger}（命中 {hits}）",
            callback_data=f"admin:keywords:view:{kid}",
        )])
        # 第 2 行：编辑 + 启停 + 删除
        toggle_text = "⏸ 停用" if enabled else "▶️ 启用"
        rows.append([
            InlineKeyboardButton(
                text="✏️ 编辑", callback_data=f"admin:keywords:edit:{kid}",
            ),
            InlineKeyboardButton(
                text=toggle_text, callback_data=f"admin:keywords:toggle:{kid}",
            ),
            InlineKeyboardButton(
                text="🗑 删除", callback_data=f"admin:keywords:delete:{kid}",
            ),
        ])
    rows.append([InlineKeyboardButton(
        text="⬅️ 返回系统配置", callback_data="admin:settings",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_keyword_edit_kb(kid: int) -> InlineKeyboardMarkup:
    """单条关键词编辑面板：4 个字段 + 启停 + 返回列表。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🏷 修改触发词", callback_data=f"admin:keywords:set_trigger:{kid}",
            ),
            InlineKeyboardButton(
                text="🪧 修改标题", callback_data=f"admin:keywords:set_banner:{kid}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📝 修改正文", callback_data=f"admin:keywords:set_body:{kid}",
            ),
            InlineKeyboardButton(
                text="🔘 修改按钮", callback_data=f"admin:keywords:set_buttons:{kid}",
            ),
        ],
        [InlineKeyboardButton(
            text="🔁 切换启停", callback_data=f"admin:keywords:toggle:{kid}",
        )],
        [InlineKeyboardButton(
            text="⬅️ 返回列表", callback_data="admin:keywords",
        )],
    ])


def admin_keyword_confirm_delete_kb(kid: int) -> InlineKeyboardMarkup:
    """删除二次确认面板。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ 确认删除", callback_data=f"admin:keywords:delete_yes:{kid}",
            ),
            InlineKeyboardButton(
                text="⬅️ 取消", callback_data=f"admin:keywords:edit:{kid}",
            ),
        ],
    ])


def admin_keyword_cancel_input_kb() -> InlineKeyboardMarkup:
    """FSM 输入页的"取消"按钮，回到关键词列表。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⬅️ 取消输入", callback_data="admin:keywords",
        )],
    ])



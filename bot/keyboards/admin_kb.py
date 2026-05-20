from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

if TYPE_CHECKING:
    # 仅类型提示用，避免运行时循环依赖
    from bot.services.admin_overview import AdminOverviewStats
    from bot.services.lottery_reconcile import LotteryReconcileItem
    from bot.services.lottery_status import LotteryStatusStats
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
    """管理员主菜单面板

    Args:
        pending_count: 老师改资料待审核数量（review:enter 内容）
        pending_review_count: 用户评价待审核数量（rreview:enter 内容；仅超管）
        pending_reimburse_count: 待审核报销数量（reimburse:enter 内容；仅超管）
        queued_reimburse_count: queued 报销名单数量（reimburse:queued:0 内容；仅超管）
        is_super: 是否超管

    审核相关四个 callback（review:enter / rreview:enter / reimburse:enter /
    reimburse:queued:0）已统一收纳进 admin:review_tasks 二级页；本主菜单不
    再直接含这四个 callback。
    """
    # ✅ 审核处理 综合 badge：非超管只算 pending_count；超管再加 review + reimburse pending
    review_total = pending_count
    if is_super:
        review_total += pending_review_count + pending_reimburse_count
    review_tasks_label = (
        f"✅ 审核处理 ({review_total})" if review_total > 0 else "✅ 审核处理"
    )
    # Row 1：老师管理 + (仅超管) 管理员设置；非超管 Row 1 只有 老师管理 单按钮
    row1: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="👩‍🏫 老师管理", callback_data="admin:teachers"),
    ]
    if is_super:
        # menu:admin（@super_admin_required）已收纳进二级页 admin:admin_settings；
        # 同时把 dashboard:audit 也收入该页（审计日志）
        row1.append(
            InlineKeyboardButton(text="🛡 管理员设置", callback_data="admin:admin_settings"),
        )
    rows: list[list[InlineKeyboardButton]] = [
        row1,
        [
            # 📈 数据分析：旧 Phase 1 看板，user_events + 审计 + 7 日窗口分析
            InlineKeyboardButton(text="📈 数据分析", callback_data="dashboard:enter"),
            InlineKeyboardButton(text=review_tasks_label, callback_data="admin:review_tasks"),
        ],
    ]
    if is_super:
        # 积分管理 / 抽奖管理 已收纳进二级页 admin:operations；这里仅保留入口
        rows.append([
            InlineKeyboardButton(text="🎲 活动运营", callback_data="admin:operations"),
        ])
    rows.extend([
        # 热门推荐 / 今日状态 / 用户画像 已收纳进二级页 admin:teachers
        # 频道设置 / 系统设置 / 发布模板 / 报表设置 已收纳进二级页 admin:settings
        # 📊 运营看板：admin:dashboard 二级页，含运营总览 / 报销池状态 / 抽奖状态
        [
            InlineKeyboardButton(text="📊 运营看板", callback_data="admin:dashboard"),
            InlineKeyboardButton(text="⚙️ 系统配置", callback_data="admin:settings"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_admin_settings_kb() -> InlineKeyboardMarkup:
    """二级「🛡 管理员设置」面板：超管专用，聚合管理员权限相关入口 + 返回后台

    入口：
        - menu:admin       👥 管理员管理（既有子菜单，含 添加 / 移除 / 列表）
                           @super_admin_required
        - dashboard:audit  📜 审计日志（既有，admin_audit_logs 最近 20 条）
                           @admin_required（super 当然也是 admin，能正常访问）

    本 keyboard 仅在 cb_admin_admin_settings（@super_admin_required）中被渲染，
    所以普通管理员既看不到入口，也不会通过 callback 路径进入。

    callback 含义全部保持不变；handler 仍由原模块处理。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 管理员管理", callback_data="menu:admin")],
        [InlineKeyboardButton(text="📜 审计日志",  callback_data="dashboard:audit")],
        [InlineKeyboardButton(text="⬅️ 返回后台", callback_data="menu:main")],
    ])


def admin_teachers_kb() -> InlineKeyboardMarkup:
    """二级「👩‍🏫 老师管理」面板：聚合老师资料 / 状态 / 推荐 / 标签类入口 + 返回后台

    入口（全部 @admin_required，所有 admin 可见）：
        - menu:teacher          👥 老师档案与启停（既有子菜单，含 老师档案管理 /
                                启停 / 老师列表）
        - admin:hot_manage      🔥 热门推荐（handler 在 hot_teachers.py）
        - admin:today_status    📅 今日发布状态（handler 在 teacher_daily_status.py）
        - admin:user_tags       🏷 用户画像（handler 在 user_tags.py；当前项目仅
                                有用户画像，无独立的"老师标签"callback）

    callback 含义未做任何变更，handler 仍由原模块处理；本 keyboard 仅是
    聚合视图组合。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 老师列表与启停", callback_data="menu:teacher")],
        [InlineKeyboardButton(text="🔥 热门推荐",       callback_data="admin:hot_manage")],
        [InlineKeyboardButton(text="📅 今日发布状态",   callback_data="admin:today_status")],
        [InlineKeyboardButton(text="🏷 用户画像",       callback_data="admin:user_tags")],
        [InlineKeyboardButton(text="⬅️ 返回后台",       callback_data="menu:main")],
    ])


def admin_settings_kb(is_super: bool = False) -> InlineKeyboardMarkup:
    """二级「⚙️ 系统配置」面板：聚合配置类入口 + 返回后台

    入口（按 admin_required 权限可见）：
        - admin:subreq             📢 必关订阅（handler 在 subreq_admin.py）
        - admin:publish_templates  🧩 发布模板（handler 在 publish_templates.py）
        - menu:channel             📣 频道 / 群组设置（handler 在 admin_panel.py）
        - admin:report_settings    📅 日报 / 周报设置（handler 在 report_settings.py）
        - menu:system              ⚙️ 系统设置（含发布时间 / 冷却 / 提醒 / 品牌等深层项）

    超管专属：
        - system:reimburse_pool    💰 报销池设置 (@super_admin_required)
        - system:reimburse_toggle  🔛 报销功能开关 (@super_admin_required)

    callback 含义未做任何变更，handler 仍由原模块处理；本 keyboard 仅是
    聚合视图组合。UX-9.1：群组快捷词配置入口 admin:keywords（handler 在
    admin_keyword.py），消息匹配触发仍由 keyword.py 处理。
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📢 必关订阅",        callback_data="admin:subreq")],
        [InlineKeyboardButton(text="🧩 发布模板",        callback_data="admin:publish_templates")],
        [InlineKeyboardButton(text="🗝 关键词管理",      callback_data="admin:keywords")],
        [InlineKeyboardButton(text="📣 频道 / 群组设置", callback_data="menu:channel")],
        [InlineKeyboardButton(text="📅 日报 / 周报设置", callback_data="admin:report_settings")],
        [InlineKeyboardButton(text="⚙️ 系统设置",        callback_data="menu:system")],
    ]
    if is_super:
        # UX-6.2：旧两按钮一行排列 + 新增聚合入口（旧 callback 双跑期保留兼容）
        rows.append([
            InlineKeyboardButton(text="💰 报销池设置",   callback_data="system:reimburse_pool"),
            InlineKeyboardButton(text="🔛 报销功能开关", callback_data="system:reimburse_toggle"),
        ])
        rows.append([
            InlineKeyboardButton(text="💰 报销配置（聚合 5 项）", callback_data="admin:reimburse_config"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ 返回后台", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_reimburse_config_kb() -> InlineKeyboardMarkup:
    """二级「💰 报销配置」聚合面板（UX-6.2，仅超管可见）。

    把原来散在 admin:settings 主面板 + menu:system 子面板的 5 个报销配置入口
    收纳到一个聚合页：

        - 🔛 报销功能开关       system:reimburse_toggle
        - 💰 报销池设置         system:reimburse_pool
        - 🔄 重置本月报销池     system:reimburse_pool_reset
        - 🎚 报销门槛设置       system:reimburse_min_points
        - 📋 报销必关设置       system:reimburse_subreq

    callback 全部复用既有 system:reimburse_* 命名空间，所有 handler 不动；
    旧入口（admin:settings 主面板的两个 super-only 按钮 + menu:system 内的 5 项）
    保留至少一个 Sprint 双跑期不删除（PLAN §1.2）。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔛 报销功能开关", callback_data="system:reimburse_toggle")],
        [InlineKeyboardButton(text="💰 报销池设置",   callback_data="system:reimburse_pool")],
        [InlineKeyboardButton(text="🔄 重置本月报销池", callback_data="system:reimburse_pool_reset")],
        [InlineKeyboardButton(text="🎚 报销门槛设置", callback_data="system:reimburse_min_points")],
        [InlineKeyboardButton(text="📋 报销必关设置", callback_data="system:reimburse_subreq")],
        [InlineKeyboardButton(text="⬅️ 返回系统配置", callback_data="admin:settings")],
    ])


def admin_operations_kb() -> InlineKeyboardMarkup:
    """二级「🎲 活动运营」面板：聚合活动运营类入口 + 返回后台

    入口分别对应：
        - admin:lottery   抽奖管理（仅超管，handler 在 admin_lottery.py）
        - admin:points    积分管理（仅超管，handler 在 admin_points.py）

    报销池设置 / 报销功能开关在系统设置子菜单中（system:reimburse_pool /
    system:reimburse_toggle），不属于"主菜单一级入口"，不在此聚合。
    推广来源 / 渠道统计已于 Phase 4 下线（router 未注册），不重新启用。

    callback 含义未做任何变更，handler 仍由原模块处理；本 keyboard 仅是
    聚合视图组合。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 抽奖管理", callback_data="admin:lottery")],
        [InlineKeyboardButton(text="💰 积分管理", callback_data="admin:points")],
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
    """二级「📊 运营看板」面板：聚合三个只读看板入口 + 返回后台

    入口分别对应：
        - admin:overview            运营总览
        - admin:reimbursement_pool  报销池状态
        - admin:lottery_status      抽奖状态
        - admin:lottery_reconcile   📊 抽奖对账（仅超管，Sprint 2 §4.2.1）

    callback 含义未做任何变更，handler 仍由原 admin_panel.py 模块处理；
    本 keyboard 仅是聚合入口的视图组合。
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📊 运营总览",   callback_data="admin:overview")],
        [InlineKeyboardButton(text="💰 报销池状态", callback_data="admin:reimbursement_pool")],
        [InlineKeyboardButton(text="🎲 抽奖状态",   callback_data="admin:lottery_status")],
    ]
    if is_super:
        rows.append([
            InlineKeyboardButton(text="📊 抽奖对账", callback_data="admin:lottery_reconcile"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ 返回后台", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_overview_kb(
    stats: Optional["AdminOverviewStats"] = None,
    *,
    is_super: bool = False,
) -> InlineKeyboardMarkup:
    """运营总览面板：（条件）快捷跳转 + 刷新 + 返回二级页 admin:dashboard。

    UX-2 第三项第一批：当 stats 传入时，按 pending count 与权限渲染快捷跳转：

        老师资料审核 (>0)        → review:enter         所有 admin 可见
        评价审核     (>0)        → rreview:enter        仅超管
        报销审核     (>0)        → reimburse:enter      仅超管
        报销名单     (queued>0)  → reimburse:queued:0   仅超管
        抽奖管理     (active+scheduled>0) → admin:lottery  仅超管

    每个快捷按钮带 (N) 角标；count=0 时该按钮整体不显示。
    刷新 + 返回按钮始终保留。

    Args:
        stats: 运营总览统计；None 时不渲染任何快捷跳转（旧调用兼容）
        is_super: 是否超管；非超管不显示评价 / 报销 / 名单 / 抽奖入口
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
            active = stats.active_lotteries or 0
            scheduled = stats.scheduled_lotteries or 0
            lottery_total = active + scheduled
            if lottery_total > 0:
                rows.append([InlineKeyboardButton(
                    text=f"🎲 抽奖管理 ({lottery_total})",
                    callback_data="admin:lottery",
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


def admin_lottery_status_kb(
    stats: Optional["LotteryStatusStats"] = None,
    *,
    is_super: bool = False,
) -> InlineKeyboardMarkup:
    """抽奖状态面板：（条件）快捷跳转 + 刷新 + 返回二级页 admin:dashboard。

    UX-2 第三项第二批：当 stats 传入且 is_super=True 时，按 count > 0 渲染
    快捷跳转：

        🎲 抽奖管理 (active + scheduled)  → admin:lottery   仅超管

    口径：(active_count or 0) + (scheduled_count or 0)，与运营总览快捷
    跳转保持一致；总数 = 0 / None 时整体不显示。
    刷新 / 返回按钮始终保留。

    Args:
        stats: 抽奖状态统计；None 时不渲染任何快捷跳转（旧无参调用兼容）
        is_super: 是否超管；非超管不显示快捷跳转
    """
    rows: list[list[InlineKeyboardButton]] = []

    if stats is not None and is_super:
        active = stats.active_count or 0
        scheduled = stats.scheduled_count or 0
        total = active + scheduled
        if total > 0:
            rows.append([InlineKeyboardButton(
                text=f"🎲 抽奖管理 ({total})",
                callback_data="admin:lottery",
            )])

    rows.append([
        InlineKeyboardButton(text="🔄 刷新", callback_data="admin:lottery_status:refresh"),
        InlineKeyboardButton(text="⬅️ 返回运营看板", callback_data="admin:dashboard"),
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
    """管理员今日开课状态总览页

    返回按钮指向二级页 admin:teachers（👩‍🏫 老师管理），不再直接回 menu:main——
    UX-1 第四批返回路径优化（2026-05）。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 刷新", callback_data="admin:today_status"),
            InlineKeyboardButton(text="⬅️ 返回老师管理", callback_data="admin:teachers"),
        ],
    ])


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
    """看板主视图：刷新 / 操作日志 / 返回主菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 刷新", callback_data="dashboard:enter"),
            InlineKeyboardButton(text="📜 操作日志", callback_data="dashboard:audit"),
        ],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
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
        [InlineKeyboardButton(text="📋 必关频道/群组", callback_data="admin:subreq")],
        [InlineKeyboardButton(text="👨‍💼 抽奖客服链接", callback_data="system:lottery_contact")],
        [
            InlineKeyboardButton(text="💰 报销池设置",   callback_data="system:reimburse_pool"),
            InlineKeyboardButton(text="🔘 报销功能开关", callback_data="system:reimburse_toggle"),
        ],
        [
            InlineKeyboardButton(text="🎚 报销门槛设置", callback_data="system:reimburse_min_points"),
            InlineKeyboardButton(text="🔄 重置本月报销池", callback_data="system:reimburse_pool_reset"),
        ],
        [
            InlineKeyboardButton(text="💰 报销必关设置", callback_data="system:reimburse_subreq"),
        ],
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


def rreview_push_action_kb() -> InlineKeyboardMarkup:
    """新评价推送给超管时附带的按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 前往审核", callback_data="rreview:enter")],
    ])


def admin_points_menu_kb() -> InlineKeyboardMarkup:
    """[💰 积分管理] 子菜单（spec §3.2）

    返回按钮指向二级页 admin:operations（🎲 活动运营），不再直接回 menu:main——
    UX-1 第二批返回路径优化（2026-05）。深层子页（admin_points_back_kb 等）
    的返回路径保持不变。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 查询用户积分", callback_data="admin:points:query")],
        [InlineKeyboardButton(text="➕ 手动加分",     callback_data="admin:points:grant")],
        [InlineKeyboardButton(text="📊 积分总览",     callback_data="admin:points:overview")],
        [InlineKeyboardButton(text="⬅️ 返回活动运营", callback_data="admin:operations")],
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
    """[🎲 抽奖管理] 子菜单

    返回按钮指向二级页 admin:operations（🎲 活动运营），不再直接回 menu:main——
    UX-1 第二批返回路径优化（2026-05）。深层子页（list / detail / create FSM 等）
    的返回路径保持不变。
    """
    list_label = f"📋 抽奖列表 ({pending_count})" if pending_count else "📋 抽奖列表"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 创建新抽奖",   callback_data="admin:lottery:create")],
        [InlineKeyboardButton(text=list_label,       callback_data="admin:lottery:list")],
        [InlineKeyboardButton(text="👨‍💼 抽奖客服链接", callback_data="admin:lottery:contact")],
        [InlineKeyboardButton(text="⬅️ 返回活动运营", callback_data="admin:operations")],
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


def reimburse_pending_super_notice_kb() -> InlineKeyboardMarkup:
    """报告审核通过后通知超管的快捷按钮组。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 去审核报销", callback_data="reimburse:enter"),
            InlineKeyboardButton(text="✅ 审核处理", callback_data="admin:review_tasks"),
        ],
    ])


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


# ============ 抽奖对账（admin:lottery_reconcile） ============


def _reconcile_item_button_text(item: "LotteryReconcileItem") -> str:
    """单条对账活动按钮文案：#L 名称 + 平账/差异标记。

    Telegram callback_data 限 64 字节，按钮 text 不受同等限制，但仍控制长度
    （活动名截断到 ~20 字符）避免单行换行。
    """
    name = (item.name or "(未命名)")
    if len(name) > 20:
        name = name[:19] + "…"
    if item.diff == 0 and item.anomaly_users == 0:
        tag = "✅"
    else:
        tag = "⚠️"
    return f"{tag} #{item.id} {name}"


def admin_lottery_reconcile_kb(
    items: list["LotteryReconcileItem"],
) -> InlineKeyboardMarkup:
    """对账列表 keyboard：每个活动一行 → detail；末尾刷新 + 返回运营看板。

    Sprint 2 §4.2.1：仅超管入口；不放任何"修复"按钮。
    """
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append([
            InlineKeyboardButton(
                text=_reconcile_item_button_text(item),
                callback_data=f"admin:lottery_reconcile:item:{item.id}",
            ),
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔄 刷新", callback_data="admin:lottery_reconcile:refresh",
        ),
        InlineKeyboardButton(
            text="⬅️ 返回运营看板", callback_data="admin:dashboard",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_lottery_reconcile_detail_kb(
    item: "LotteryReconcileItem",
) -> InlineKeyboardMarkup:
    """单活动对账详情 keyboard：刷新 + 返回列表；异常用户列表（§4.2.2，
    仅当 anomaly_users > 0 时渲染）。

    Sprint 2 §4.2.2：详情页加「📋 异常用户列表 (N)」入口。
    不放任何"修复"按钮（§4.3 禁止）。
    """
    rows: list[list[InlineKeyboardButton]] = []
    if item.anomaly_users > 0:
        rows.append([
            InlineKeyboardButton(
                text=f"📋 异常用户列表 ({item.anomaly_users})",
                callback_data=f"admin:lottery_reconcile:anomaly:{item.id}:1",
            ),
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔄 刷新当前",
            callback_data=f"admin:lottery_reconcile:item:{item.id}:refresh",
        ),
        InlineKeyboardButton(
            text="⬅️ 返回对账列表",
            callback_data="admin:lottery_reconcile",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_lottery_reconcile_anomaly_kb(
    lid: int, page: int, total_pages: int,
) -> InlineKeyboardMarkup:
    """异常用户列表 keyboard：分页 + 返回详情。

    Sprint 2 §4.2.2：仅超管入口。无"修复 / 导出"按钮。
    """
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            text="⬅️ 上一页",
            callback_data=f"admin:lottery_reconcile:anomaly:{lid}:{page - 1}",
        ))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            text="下一页 ➡️",
            callback_data=f"admin:lottery_reconcile:anomaly:{lid}:{page + 1}",
        ))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(
            text="🔄 刷新当前页",
            callback_data=f"admin:lottery_reconcile:anomaly:{lid}:{page}",
        ),
        InlineKeyboardButton(
            text=f"⬅️ 返回 #{lid}",
            callback_data=f"admin:lottery_reconcile:item:{lid}",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

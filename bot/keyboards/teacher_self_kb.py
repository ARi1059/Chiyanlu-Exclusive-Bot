"""老师自助管理 inline keyboards（v2 §2.3 F3 + §2.5.5 老师菜单）"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.keyboards.common_kb import miniapp_entry_row


# ============ 老师主菜单 ============

def teacher_main_menu_kb(*, checked_in: bool = False) -> InlineKeyboardMarkup:
    """老师私聊主菜单（Phase A0 后 2026-05-23）

    Phase A0：移除「📅 今日状态」按钮（teacher_daily_status 功能整体下线）。
    剩余 2 按钮：
        - ✅ 今日签到 / 今日已签到（文案根据 checked_in 动态切换）
        - ✏️ 我的资料

    Args:
        checked_in: 当日是否已签到。
    """
    checkin_label = "✅ 今日已签到" if checked_in else "✅ 今日签到"
    return InlineKeyboardMarkup(inline_keyboard=[
        miniapp_entry_row(),  # 🚀 打开小程序（§16.3：老师端首选入口，FSM 保留兜底）
        [InlineKeyboardButton(text=checkin_label, callback_data="teacher_self:checkin")],
        [InlineKeyboardButton(text="✏️ 我的资料", callback_data="teacher_self:profile")],
    ])


# Phase A0（2026-05-23）已下线：teacher_status_kb / cancel_reason_kb（老师今日状态功能整体下线）


# ============ 我的资料字段编辑面板 ============

# 字段中文显示名（用于按钮标签 + 审核通知 + 驳回通知）
FIELD_LABELS: dict[str, str] = {
    "display_name": "艺名",
    "region": "地区",
    "price": "价格",
    "tags": "标签",
    "photo_file_id": "图片",
    "button_text": "按钮文本",
    # 锁定字段，仅用于展示提示
    "button_url": "链接",
}


def teacher_profile_kb() -> InlineKeyboardMarkup:
    """老师资料字段选择面板（UX-6.3：高频字段置顶）

    布局调整（PLAN §3.3.C 高频字段快捷入口 + UX-FEATURE-ITERATION §6 痛点 4）：
        第一行（高频）：💰 价格 / 📍 地区
        第二行（高频）：🏷️ 标签 / 🖼️ 图片
        第三行（低频）：📝 艺名 / 🔠 按钮文本
        第四行：🔗 链接（不可改） 锁定提示
        第五行：🔙 返回主菜单

    callback_data 全部保留（仅按钮位置重排）；
    旧 inline button（历史快照）依然能命中各字段 edit FSM。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 价格", callback_data="teacher_self:edit:price"),
            InlineKeyboardButton(text="📍 地区", callback_data="teacher_self:edit:region"),
        ],
        [
            InlineKeyboardButton(text="🏷️ 标签", callback_data="teacher_self:edit:tags"),
            InlineKeyboardButton(text="🖼️ 图片", callback_data="teacher_self:edit:photo_file_id"),
        ],
        [
            InlineKeyboardButton(text="📝 艺名", callback_data="teacher_self:edit:display_name"),
            InlineKeyboardButton(text="🔠 按钮文本", callback_data="teacher_self:edit:button_text"),
        ],
        [
            InlineKeyboardButton(text="🔗 链接（不可改）", callback_data="teacher_self:locked:button_url"),
        ],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="teacher_self:menu")],
    ])


def teacher_edit_cancel_kb() -> InlineKeyboardMarkup:
    """编辑字段时的取消按钮（也可发 /cancel 退出 FSM）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 取消", callback_data="teacher_self:profile")],
    ])


def teacher_back_to_profile_kb() -> InlineKeyboardMarkup:
    """资料字段修改完成后的返回按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回资料", callback_data="teacher_self:profile")],
    ])

"""老师自助管理 inline keyboards（v2 §2.3 F3 + §2.5.5 老师菜单）"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============ 老师主菜单 ============

def teacher_main_menu_kb() -> InlineKeyboardMarkup:
    """老师私聊主菜单（v2 §2.5.5 + Phase 5 今日状态）

    - 我的资料 → 自助管理入口（F3）
    - 今日签到 → 等价于发文字"签到"（v1 行为，并存）
    - 今日状态 → Phase 5 老师今日开课状态管理
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ 我的资料", callback_data="teacher_self:profile")],
        [InlineKeyboardButton(text="✅ 今日签到", callback_data="teacher_self:checkin")],
        [InlineKeyboardButton(text="📅 今日状态", callback_data="teacher:status")],
    ])


# ============ 老师今日状态 ============


def teacher_status_kb() -> InlineKeyboardMarkup:
    """老师今日状态菜单（移除"设置可约时间"后剩 3 操作）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🈵 标记今日已满", callback_data="teacher:status:mark_full")],
        [InlineKeyboardButton(text="❌ 取消今日开课", callback_data="teacher:status:cancel")],
        [InlineKeyboardButton(text="🔙 返回老师菜单", callback_data="teacher_self:menu")],
    ])


def cancel_reason_kb() -> InlineKeyboardMarkup:
    """取消今日开课时的输入引导：跳过 / 取消"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏭ 跳过原因", callback_data="teacher:status:cancel_skip"),
            InlineKeyboardButton(text="🔙 取消", callback_data="teacher:status"),
        ],
    ])


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
    """老师资料字段选择面板

    6 个可改字段（display_name / region / price / tags / photo_file_id / button_text）
    + 1 个锁定提示按钮（button_url，点击给提示）
    + 返回主菜单
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 艺名", callback_data="teacher_self:edit:display_name"),
            InlineKeyboardButton(text="📍 地区", callback_data="teacher_self:edit:region"),
        ],
        [
            InlineKeyboardButton(text="💰 价格", callback_data="teacher_self:edit:price"),
            InlineKeyboardButton(text="🏷️ 标签", callback_data="teacher_self:edit:tags"),
        ],
        [
            InlineKeyboardButton(text="🖼️ 图片", callback_data="teacher_self:edit:photo_file_id"),
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

"""普通用户私聊菜单的 inline keyboards（v2 §2.5 C1 私聊冷启动）"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ============ 用户主菜单 ============

def user_main_menu_kb() -> InlineKeyboardMarkup:
    """普通用户私聊主菜单（v2 §2.5.3）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 今日开课老师", callback_data="user:today")],
        [InlineKeyboardButton(text="⭐ 我的收藏", callback_data="user:favorites")],
        [InlineKeyboardButton(text="💝 收藏开课", callback_data="user:fav_today")],
        [InlineKeyboardButton(text="🔍 搜索老师", callback_data="user:search")],
    ])


# ============ 子菜单通用按钮 ============

def back_to_user_main_kb() -> InlineKeyboardMarkup:
    """单按钮：返回用户主菜单（v2 §2.5.4 所有子菜单都需要）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def search_cancel_kb() -> InlineKeyboardMarkup:
    """搜索引导：取消按钮（用户也可以发送 /cancel 退出）"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])

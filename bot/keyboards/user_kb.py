"""普通用户私聊菜单的 inline keyboards（v2 §2.5 C1 私聊冷启动）"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.utils.url import normalize_url


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


def my_favorites_kb(favorites: list[dict]) -> InlineKeyboardMarkup:
    """"我的收藏"列表 keyboard（v2 §2.1 F1）

    每行：[老师名 · 地区 · 价格] [❌]
        · 老师按钮：跳转 button_url（URL 无效时退化为带警告文案的 callback no-op）
        · ❌ 按钮：fav:rm_from_list:<teacher_id>，favorite handler 接住后取消并刷新列表
    末尾：[🔙 返回主菜单]

    Args:
        favorites: 已收藏老师列表（含 teachers 表全部字段）
    """
    rows: list[list[InlineKeyboardButton]] = []
    for t in favorites:
        url = normalize_url(t["button_url"])
        label = f"{t['display_name']} · {t['region']} · {t['price']}"
        if url:
            teacher_btn = InlineKeyboardButton(text=label, url=url)
        else:
            # button_url 无效：用 callback no-op，告知用户链接失效
            teacher_btn = InlineKeyboardButton(
                text=f"⚠️ {label}（链接失效）",
                callback_data="fav:invalid_url",
            )
        rm_btn = InlineKeyboardButton(
            text="❌",
            callback_data=f"fav:rm_from_list:{t['user_id']}",
        )
        rows.append([teacher_btn, rm_btn])

    rows.append([
        InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

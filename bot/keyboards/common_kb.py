"""跨角色复用的私聊 inline keyboard 组件。

目前仅含「🚀 打开小程序」WebApp 入口行（§16.3 FSM 降级引导）：
把 MiniApp 作为首选入口挂到用户 / 老师 / 管理员三个私聊主菜单顶部，
FSM 文字流程完整保留作兜底。

WebApp inline 按钮仅在私聊渲染、且要求 BotFather 已绑定域名
（本 bot 的 Menu Button 已可用 → 满足）。老旧客户端不支持会忽略该行，
不影响菜单其余按钮。
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, WebAppInfo

from bot.config import config


def miniapp_entry_row() -> list[InlineKeyboardButton]:
    """「🚀 打开小程序」单按钮行，直开 MiniApp（config.miniapp_url）。"""
    return [
        InlineKeyboardButton(
            text="🚀 打开小程序",
            web_app=WebAppInfo(url=config.miniapp_url),
        )
    ]

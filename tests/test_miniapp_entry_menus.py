"""§16.3 FSM 降级引导：三角色私聊主菜单顶部含「🚀 打开小程序」WebApp 入口。

用户 / 老师 / 管理员主菜单第一行都应是直开 MiniApp 的 web_app 按钮，
且 URL == config.miniapp_url。FSM 其余按钮保留（不删功能）。
"""
from __future__ import annotations

from bot.config import config
from bot.keyboards.admin_kb import main_menu_kb
from bot.keyboards.common_kb import miniapp_entry_row
from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
from bot.keyboards.user_kb import user_main_menu_kb


def _top_button(kb):
    return kb.inline_keyboard[0][0]


def test_common_helper_builds_web_app_button():
    btn = miniapp_entry_row()[0]
    assert btn.web_app is not None
    assert btn.web_app.url == config.miniapp_url
    assert "小程序" in btn.text


def test_user_menu_has_miniapp_entry_on_top():
    btn = _top_button(user_main_menu_kb())
    assert btn.web_app is not None
    assert btn.web_app.url == config.miniapp_url


def test_teacher_menu_has_miniapp_entry_on_top():
    btn = _top_button(teacher_main_menu_kb())
    assert btn.web_app is not None
    assert btn.web_app.url == config.miniapp_url


def test_teacher_menu_checked_in_variant_still_has_entry():
    btn = _top_button(teacher_main_menu_kb(checked_in=True))
    assert btn.web_app is not None and btn.web_app.url == config.miniapp_url


def test_admin_menu_has_miniapp_entry_on_top():
    btn = _top_button(main_menu_kb(is_super=True))
    assert btn.web_app is not None
    assert btn.web_app.url == config.miniapp_url


def test_admin_menu_nonsuper_also_has_entry():
    btn = _top_button(main_menu_kb(is_super=False))
    assert btn.web_app is not None and btn.web_app.url == config.miniapp_url


def test_fsm_buttons_preserved_user_menu():
    """入口是新增不是替换：用户菜单仍含「找老师」等既有 callback。"""
    kb = user_main_menu_kb()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert "user:find" in cbs
    assert "user:write_review" in cbs


def test_fsm_buttons_preserved_teacher_menu():
    """老师菜单仍含签到 + 我的资料。"""
    kb = teacher_main_menu_kb()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert "teacher_self:checkin" in cbs
    assert "teacher_self:profile" in cbs


def test_miniapp_url_defaults_to_production():
    """未配 MINIAPP_URL 时默认生产域名。"""
    assert config.miniapp_url.startswith("https://")

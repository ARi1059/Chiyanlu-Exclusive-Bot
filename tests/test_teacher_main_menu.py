"""老师主菜单契约测试（Sprint 6 §8 精简 PR）。

契约（详见 DESIGN.md §2.3.5 / TEACHER-PANEL-AUDIT-2026-05.md）：

    1. 按钮总数 ≤ 3：固化已达成的 §8.5 "按钮数量减少" 验收，未来任意 PR
       打破此契约 CI 拒绝。
    2. 签到置顶：第一行第一个按钮必须是签到 callback；UX-5.1 文案动态
       切换（未签到 / 已签到）。
    3. callback 命名空间：主菜单 callback 必须属于 teacher_self:* 或
       teacher:status*，禁止用户/管理员命名空间（teacher:view / similar
       / list / delete / enable / 等）。
    4. §8.4 不引入跨角色功能：主菜单不应包含 user:* / admin:* / menu:*。
    5. callback_data ≤ 64 字节（Telegram 限制）。

不连接真实 Telegram；纯静态 keyboard 断言。
"""

from __future__ import annotations

from bot.keyboards.teacher_self_kb import teacher_main_menu_kb


def _flatten(kb):
    return [b for row in kb.inline_keyboard for b in row]


def _callbacks(kb):
    return [b.callback_data for b in _flatten(kb)]


# ============ 按钮总数契约 ============


def test_main_menu_default_button_count_at_most_three():
    """§8.5 "按钮数量减少"：默认 (checked_in=False) 按钮 ≤ 3。"""
    kb = teacher_main_menu_kb()
    assert len(_flatten(kb)) <= 3


def test_main_menu_checked_in_button_count_at_most_three():
    """checked_in=True 时按钮数与默认一致（仅文案变化）。"""
    kb = teacher_main_menu_kb(checked_in=True)
    assert len(_flatten(kb)) <= 3


def test_main_menu_exactly_three_buttons_current_state():
    """当前确切状态：3 按钮（签到 / 资料 / 状态）。

    本断言用于检测"无意识减少"——若有 PR 把签到/资料/状态任一删掉而未
    显式调整本契约，CI 拒绝。配合上面 ≤ 3 的契约形成双向约束：
        按钮数必须 ∈ {1, 2, 3}，且当前生产为 3。
    """
    kb = teacher_main_menu_kb()
    assert len(_flatten(kb)) == 3


# ============ 签到置顶契约（UX-5.1） ============


def test_main_menu_checkin_in_first_row():
    """签到 callback 必须在第一行（UX-5.1 + §8.1 "突出签到"）。"""
    kb = teacher_main_menu_kb()
    first_row_cbs = [b.callback_data for b in kb.inline_keyboard[0]]
    assert "teacher_self:checkin" in first_row_cbs


def test_main_menu_checkin_is_first_button():
    """签到必须是第一行第一个（即整体第一个）按钮。"""
    kb = teacher_main_menu_kb()
    first_button = kb.inline_keyboard[0][0]
    assert first_button.callback_data == "teacher_self:checkin"


def test_main_menu_checkin_label_dynamic_when_not_checked_in():
    """未签到时文案 '今日签到'。"""
    kb = teacher_main_menu_kb(checked_in=False)
    first_button = kb.inline_keyboard[0][0]
    assert "签到" in first_button.text
    # 不应包含"已签到"
    assert "已签到" not in first_button.text


def test_main_menu_checkin_label_dynamic_when_checked_in():
    """已签到时文案 '今日已签到'（UX-5.1）。"""
    kb = teacher_main_menu_kb(checked_in=True)
    first_button = kb.inline_keyboard[0][0]
    assert "已签到" in first_button.text


def test_main_menu_default_checked_in_is_false():
    """缺省参数 checked_in=False（向后兼容，旧 caller 不传参时按未签到渲染）。"""
    default_kb = teacher_main_menu_kb()
    explicit_kb = teacher_main_menu_kb(checked_in=False)
    default_text = default_kb.inline_keyboard[0][0].text
    explicit_text = explicit_kb.inline_keyboard[0][0].text
    assert default_text == explicit_text


# ============ callback 命名空间契约 ============


_ALLOWED_NAMESPACES = (
    "teacher_self:",       # 老师私聊专属
    "teacher:status",      # 老师今日状态（handler 有 get_teacher 校验）
)


def test_main_menu_callbacks_only_in_allowed_namespaces():
    """主菜单 callback 必须属于 teacher_self:* 或 teacher:status*。"""
    kb = teacher_main_menu_kb()
    for cb in _callbacks(kb):
        assert any(cb.startswith(ns) for ns in _ALLOWED_NAMESPACES), (
            f"callback {cb!r} 不在允许的老师命名空间"
        )


def test_main_menu_no_user_callbacks():
    """§8.4：主菜单不应出现用户命名空间（user:*）。"""
    kb = teacher_main_menu_kb()
    for cb in _callbacks(kb):
        assert not cb.startswith("user:"), (
            f"老师主菜单不应嵌入用户入口: {cb}"
        )


def test_main_menu_no_admin_callbacks():
    """§8.4：主菜单不应出现管理员命名空间（admin:* / menu:*）。"""
    kb = teacher_main_menu_kb()
    for cb in _callbacks(kb):
        assert not cb.startswith("admin:"), (
            f"老师主菜单不应嵌入管理员入口: {cb}"
        )
        assert not cb.startswith("menu:"), (
            f"老师主菜单不应嵌入管理员主菜单入口: {cb}"
        )


def test_main_menu_no_teacher_view_or_admin_subspace():
    """主菜单不应出现 teacher:view/similar/list/delete/enable/confirm 等
    用户视角或管理员视角的 teacher:* 子路径（防御 §8.4 + 命名空间共用混淆）。"""
    kb = teacher_main_menu_kb()
    forbidden_prefixes = (
        "teacher:view",
        "teacher:similar",
        "teacher:list",
        "teacher:delete",
        "teacher:enable",
        "teacher:confirm",
        "teacher:select",
        "teacher:remind",
        "teacher:reviews",
        "teacher:toggle_fav",
    )
    for cb in _callbacks(kb):
        for prefix in forbidden_prefixes:
            assert not cb.startswith(prefix), (
                f"老师主菜单出现非老师命名空间 callback: {cb}"
            )


# ============ 防御 callback 重命名（保护签到路径） ============


def test_main_menu_checkin_callback_data_exact():
    """§8.4 "不删除老师侧任何与签到有关的 callback"。

    签到 callback_data 字符串必须精确为 `teacher_self:checkin`。任何 PR
    若要重命名（即便保持功能），必须显式更新本断言 —— CI 强制审查者
    意识到对历史 inline button 的影响。"""
    kb = teacher_main_menu_kb()
    first_button = kb.inline_keyboard[0][0]
    assert first_button.callback_data == "teacher_self:checkin"


def test_main_menu_includes_profile_and_status_callbacks():
    """资料与状态入口必须存在（防御性，避免无意识删除）。"""
    cbs = set(_callbacks(teacher_main_menu_kb()))
    assert "teacher_self:profile" in cbs
    assert "teacher:status" in cbs


# ============ callback_data 字节数限制 ============


def test_all_callbacks_within_telegram_limit():
    """主菜单所有 callback ≤ 64B（Telegram 通用限制）。"""
    for kb in (teacher_main_menu_kb(), teacher_main_menu_kb(checked_in=True)):
        for b in _flatten(kb):
            assert b.callback_data is not None
            assert len(b.callback_data.encode("utf-8")) <= 64, (
                f"callback {b.callback_data!r} 超 64B"
            )

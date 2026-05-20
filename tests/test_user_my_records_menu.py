"""用户「📝 我的记录」二级页（Sprint 5 §7.3.2）keyboard 契约测试。

测试范围：
    1. user_main_menu_kb 末行新增「📝 我的记录」独占一行（callback=user:my_records）
    2. 旧入口 user:write_review / user:reimburse / user:points / user:lottery
       在主菜单**完全保留**（§7.4 双跑期纪律）
    3. user_my_records_kb 二级页含 4 个子入口（全部复用既有 callback）+
       返回主菜单
    4. 所有 callback_data 长度 ≤ 64 字节

不连接真实 Telegram；纯静态 keyboard 断言。
"""

from __future__ import annotations

from bot.keyboards.user_kb import user_main_menu_kb, user_my_records_kb


def _flatten(kb):
    return [b for row in kb.inline_keyboard for b in row]


def _callbacks(kb):
    return [b.callback_data for b in _flatten(kb)]


# ============ 主菜单：新增「📝 我的记录」入口 ============


def test_user_main_menu_has_my_records_entry():
    kb = user_main_menu_kb()
    assert "user:my_records" in _callbacks(kb)


def test_user_main_menu_my_records_is_last_row_solo():
    """末行独占一行（与 UX-3 "🔎 找老师" 首行独占同模式）。"""
    kb = user_main_menu_kb()
    last_row = kb.inline_keyboard[-1]
    assert len(last_row) == 1
    assert last_row[0].callback_data == "user:my_records"
    assert "我的记录" in last_row[0].text


def test_user_main_menu_keeps_old_first_level_entries():
    """§7.4 实施纪律：旧入口完全保留（双跑期）。"""
    cbs = set(_callbacks(user_main_menu_kb()))
    for old in (
        "user:write_review",   # 旧"📝 写评价" 入口
        "user:reimburse",      # 旧"🧾 我的报销" 入口
        "user:points",         # 旧"💰 我的积分" 入口
        "user:lottery",        # 旧"🎁 抽奖中心" 入口
    ):
        assert old in cbs, f"旧入口被误删: {old}"


# ============ user_my_records_kb：二级页 ============


def test_my_records_kb_has_four_child_entries():
    """聚合 4 个子入口（与 §7.3.2 范围一致）。"""
    cbs = set(_callbacks(user_my_records_kb()))
    assert "user:write_review" in cbs       # 我的评价
    assert "user:reimburse" in cbs          # 我的报销
    assert "user:points" in cbs             # 积分流水
    assert "user:lottery:joined" in cbs     # 抽奖记录（直接进抽奖中心「我已参与」tab）


def test_my_records_kb_returns_to_main_menu():
    cbs = _callbacks(user_my_records_kb())
    assert "user:main" in cbs


def test_my_records_kb_button_count():
    """5 按钮：4 子入口 + 1 返回主菜单。"""
    kb = user_my_records_kb()
    assert len(_flatten(kb)) == 5


def test_my_records_kb_button_texts():
    """子按钮文案匹配各自含义。"""
    kb = user_my_records_kb()
    by_cb = {b.callback_data: b.text for b in _flatten(kb)}
    assert "我的评价" in by_cb["user:write_review"]
    assert "我的报销" in by_cb["user:reimburse"]
    assert "积分流水" in by_cb["user:points"]
    assert "抽奖记录" in by_cb["user:lottery:joined"]
    assert "返回" in by_cb["user:main"]


def test_my_records_kb_reuses_only_existing_callbacks():
    """§7.4：聚合页仅承担导航，不引入任何新 callback 命名空间。

    所有子入口 callback 必须存在于既有 user:* 命名空间；新 callback 只能是
    user:main（返回）。"""
    kb = user_my_records_kb()
    cbs = _callbacks(kb)
    allowed = {
        "user:write_review",
        "user:reimburse",
        "user:points",
        "user:lottery:joined",
        "user:main",
    }
    for cb in cbs:
        assert cb in allowed, f"unexpected callback: {cb}"


def test_my_records_no_new_namespace():
    """聚合页不应引入 user:my_records:* 子命名空间（§7.4 不修改子页业务）。"""
    kb = user_my_records_kb()
    for cb in _callbacks(kb):
        assert not cb.startswith("user:my_records:"), (
            f"my_records 不应有子命名空间，发现: {cb}"
        )


# ============ callback_data 字节数限制 ============


def test_all_callbacks_within_telegram_limit():
    for kb in (user_main_menu_kb(), user_my_records_kb()):
        for b in _flatten(kb):
            assert b.callback_data is not None
            assert len(b.callback_data.encode("utf-8")) <= 64

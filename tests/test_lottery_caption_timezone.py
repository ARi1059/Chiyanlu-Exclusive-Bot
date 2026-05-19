"""Sprint UX-5 第五项（UX-5.5 简化版）：抽奖帖 caption 显式标注时区契约测试。

范围（按 §11 决策方案 C 简化）：
    - bot.utils.lottery_publish.render_lottery_caption 的"⏰ 开奖时间"行
      追加时区中文标签，例如 `⏰ 开奖时间：2026-05-22 20:30（北京时间）`
    - 不引入"距开奖剩 X" 倒计时数字（避免 caption 首次渲染后变 stale）
    - 不新增周期 edit job（避免 Telegram flood 风控）

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §3.2 痛点 4 + §11.3）：
    频道帖时间字符串当前是 implicit 本地时区，跨时区用户需要心算；显式标注
    `（北京时间）` 让用户**首次**清楚开奖时刻所在时区。

约束：
    - caption 长度变化极小（约 +6 字符），渐进式截断逻辑仍可工作
    - 不改 callback_data；不引入 schema 迁移
    - 不动 keyboard / 时间窗口校验 / 参与扣分等业务逻辑
"""
from __future__ import annotations

import inspect

import pytest  # noqa: F401


# ============ helpers ============


def _src(module) -> str:
    return inspect.getsource(module)


# ============================================================
# 1. _timezone_label 映射契约
# ============================================================


def test_timezone_label_for_shanghai():
    """默认 Asia/Shanghai → 北京时间。"""
    from bot.utils.lottery_publish import _timezone_label
    from bot.config import config
    original = config.timezone
    config.timezone = "Asia/Shanghai"
    try:
        assert _timezone_label() == "北京时间"
    finally:
        config.timezone = original


def test_timezone_label_for_known_zones():
    """常见时区映射齐全。"""
    from bot.utils.lottery_publish import _timezone_label
    from bot.config import config
    original = config.timezone
    try:
        for tz, expected in [
            ("Asia/Hong_Kong", "香港时间"),
            ("Asia/Taipei",    "台北时间"),
            ("Asia/Tokyo",     "东京时间"),
            ("Asia/Seoul",     "首尔时间"),
            ("UTC",            "UTC"),
        ]:
            config.timezone = tz
            assert _timezone_label() == expected
    finally:
        config.timezone = original


def test_timezone_label_unknown_falls_back_to_iana():
    """未映射的时区回落到 IANA 字符串本身。"""
    from bot.utils.lottery_publish import _timezone_label
    from bot.config import config
    original = config.timezone
    config.timezone = "Europe/London"
    try:
        assert _timezone_label() == "Europe/London"
    finally:
        config.timezone = original


# ============================================================
# 2. caption 渲染契约
# ============================================================


def _build_lottery_fixture() -> dict:
    return {
        "id": 7,
        "name": "测试抽奖",
        "description": "活动说明",
        "prize_description": "奖品 X",
        "prize_count": 3,
        "draw_at": "2026-05-22 20:30",
        "entry_method": "button",
        "entry_code": None,
        "required_chat_ids": [],
        "entry_cost_points": 0,
    }


def test_caption_includes_draw_at_with_timezone():
    """caption 应包含「⏰ 开奖时间：{draw_at}（{tz_label}）」。"""
    from bot.utils.lottery_publish import render_lottery_caption
    from bot.config import config
    original = config.timezone
    config.timezone = "Asia/Shanghai"
    try:
        text = render_lottery_caption(
            _build_lottery_fixture(), "test_bot", chat_info_map={},
        )
        assert "⏰ 开奖时间：2026-05-22 20:30（北京时间）" in text
    finally:
        config.timezone = original


def test_caption_timezone_label_follows_config():
    """切换 config.timezone 时 caption 标签同步切换。"""
    from bot.utils.lottery_publish import render_lottery_caption
    from bot.config import config
    original = config.timezone
    try:
        config.timezone = "Asia/Tokyo"
        text = render_lottery_caption(
            _build_lottery_fixture(), "test_bot", chat_info_map={},
        )
        assert "（东京时间）" in text
        assert "（北京时间）" not in text
    finally:
        config.timezone = original


def test_caption_still_within_limit_when_short_input():
    """常规输入下 caption 长度仍 < CAPTION_MAX_LEN（1024）。"""
    from bot.utils.lottery_publish import render_lottery_caption, CAPTION_MAX_LEN
    text = render_lottery_caption(
        _build_lottery_fixture(), "test_bot", chat_info_map={},
    )
    assert len(text) <= CAPTION_MAX_LEN


def test_caption_truncation_still_works_with_long_description():
    """长 description 下渐进式截断仍能压到 ≤ CAPTION_MAX_LEN。"""
    from bot.utils.lottery_publish import render_lottery_caption, CAPTION_MAX_LEN
    lottery = _build_lottery_fixture()
    lottery["description"] = "活动说明" * 500  # 故意超长
    text = render_lottery_caption(
        lottery, "test_bot", chat_info_map={},
    )
    assert len(text) <= CAPTION_MAX_LEN


def test_caption_has_all_legacy_fields():
    """业务保护：UX-5.5 不破坏既有 caption 字段（奖品 / 参与方式 / footer）。"""
    from bot.utils.lottery_publish import render_lottery_caption
    text = render_lottery_caption(
        _build_lottery_fixture(), "test_bot", chat_info_map={},
    )
    assert "🎉 测试抽奖" in text
    assert "🎁 奖品" in text
    assert "🏆 中奖人数：3" in text
    assert "Powered by @test_bot" in text


def test_caption_code_method_still_shows_entry_code():
    """口令抽奖：业务保护 entry_code 仍在文案中。"""
    from bot.utils.lottery_publish import render_lottery_caption
    lottery = _build_lottery_fixture()
    lottery["entry_method"] = "code"
    lottery["entry_code"] = "SECRET42"
    text = render_lottery_caption(
        lottery, "test_bot", chat_info_map={},
    )
    assert "SECRET42" in text


def test_caption_cost_points_still_rendered_when_positive():
    """业务保护：entry_cost_points > 0 时仍渲染 "💰 参与消耗：X 积分"。"""
    from bot.utils.lottery_publish import render_lottery_caption
    lottery = _build_lottery_fixture()
    lottery["entry_cost_points"] = 5
    text = render_lottery_caption(
        lottery, "test_bot", chat_info_map={},
    )
    assert "💰 参与消耗：5 积分" in text


def test_caption_cost_points_hidden_when_zero():
    """业务保护：免费抽奖（entry_cost_points = 0）不渲染参与消耗行。"""
    from bot.utils.lottery_publish import render_lottery_caption
    text = render_lottery_caption(
        _build_lottery_fixture(), "test_bot", chat_info_map={},
    )
    assert "💰 参与消耗" not in text


# ============================================================
# 3. 没有引入周期 edit job（方案 C 简化约束）
# ============================================================


def test_no_lottery_caption_refresh_job_introduced():
    """UX-5.5 简化版不应新增 lottery_caption_refresh / lottery_predraw 等周期 job。
    （如未来做完整版，会涉及 APScheduler；本批保持零调度改动。）"""
    import bot.scheduler.lottery_tasks as mod
    src = _src(mod)
    # 既有 lottery_pub_<lid> / lottery_draw_<lid> 仍存在；不应有 refresh 命名
    assert "lottery_caption_refresh" not in src
    assert "lottery_predraw" not in src


def test_no_periodic_caption_edit_added_to_lottery_publish():
    """lottery_publish.py 不应新增 periodic edit；既有 60s debounce 仍是唯一更新路径。"""
    import bot.utils.lottery_publish as mod
    src = _src(mod)
    # 既有 update_lottery_entry_count 还在
    assert "update_lottery_entry_count" in src
    # 不应有 periodic / interval 字眼（除已有的 60s debounce 注释）
    # 静态扫描——避免本批意外引入周期 job
    # COUNT_EDIT_DEBOUNCE_SECONDS 是既有常量，不应被改变
    assert "COUNT_EDIT_DEBOUNCE_SECONDS: float = 60.0" in src


# ============================================================
# 4. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []

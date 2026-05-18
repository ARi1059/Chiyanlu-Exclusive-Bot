"""bot.handlers.start_router.parse_start_args 解析测试。

覆盖 Phase 4 / Phase 7.3 / Phase 8.1 / Phase 8.2 / Phase 9.5.4 / Phase L.2.3
所有 deep link 参数形式，以及不可识别的兜底分支。
"""

from __future__ import annotations

import pytest

from bot.handlers.start_router import parse_start_args


# ---------- 空参数 / 默认字段 ----------


def test_empty_returns_all_defaults():
    r = parse_start_args("")
    assert r["activate"] is False
    assert r["fav_teacher_id"] is None
    assert r["teacher_detail_id"] is None
    assert r["review_target_id"] is None
    assert r["lottery_id"] is None
    assert r["search_entry"] is False
    assert r["source_type"] is None
    assert r["source_id"] is None
    assert r["raw"] == ""


def test_none_input_treated_as_empty():
    # parse_start_args 接收 Optional 行为：raw or "" 容错
    r = parse_start_args(None)  # type: ignore[arg-type]
    assert r["raw"] == ""
    assert r["activate"] is False
    assert r["source_type"] is None


# ---------- 参数化主表 ----------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # 2. activate
        ("activate", {"activate": True}),

        # 3. fav_123
        ("fav_123", {"fav_teacher_id": 123}),

        # 4. fav_123_src_channel_abc
        (
            "fav_123_src_channel_abc",
            {"fav_teacher_id": 123, "source_type": "channel", "source_id": "abc"},
        ),

        # 5. fav_123_src_group_-100123
        (
            "fav_123_src_group_-100123",
            {"fav_teacher_id": 123, "source_type": "group", "source_id": "-100123"},
        ),

        # 6. fav_123_src_teacher_456
        (
            "fav_123_src_teacher_456",
            {"fav_teacher_id": 123, "source_type": "teacher", "source_id": "456"},
        ),

        # 7. fav_123_campaign_may
        (
            "fav_123_campaign_may",
            {"fav_teacher_id": 123, "source_type": "campaign", "source_id": "may"},
        ),

        # 8. fav_123_invite_abc
        (
            "fav_123_invite_abc",
            {"fav_teacher_id": 123, "source_type": "invite", "source_id": "abc"},
        ),

        # 9. teacher_123
        ("teacher_123", {"teacher_detail_id": 123}),

        # 10. write_123
        ("write_123", {"review_target_id": 123}),

        # 11. lottery_123
        ("lottery_123", {"lottery_id": 123}),

        # 12. search
        ("search", {"search_entry": True}),

        # 14. campaign_xxx
        ("campaign_xxx", {"source_type": "campaign", "source_id": "xxx"}),

        # 15. invite_xxx
        ("invite_xxx", {"source_type": "invite", "source_id": "xxx"}),

        # 16. src_channel_xxx
        ("src_channel_xxx", {"source_type": "channel", "source_id": "xxx"}),
    ],
    ids=[
        "activate", "fav_id",
        "fav_src_channel", "fav_src_group_negative", "fav_src_teacher",
        "fav_campaign", "fav_invite",
        "teacher_detail", "write_review", "lottery",
        "search_entry",
        "campaign", "invite", "src_channel",
    ],
)
def test_parse_main_cases(raw: str, expected: dict):
    r = parse_start_args(raw)
    for key, value in expected.items():
        assert r[key] == value, (
            f"raw={raw!r} key={key!r}: expected {value!r}, got {r[key]!r}"
        )
    # 所有 case 都应回填 raw
    assert r["raw"] == raw


# ---------- q_ 解码失败回退到 search_entry ----------


def test_q_empty_falls_back_to_search_entry():
    """raw='q_' → decode_query_from_deep_link('') → None → search_entry=True"""
    r = parse_start_args("q_")
    assert r["search_entry"] is True
    assert r["search_query"] is None


def test_q_invalid_base64_falls_back_to_search_entry():
    """非法 base64url 编码也应安全回退，不抛异常"""
    r = parse_start_args("q_!!!notbase64!!!")
    assert r["search_entry"] is True
    assert r["search_query"] is None


def test_q_valid_base64_decodes_to_query():
    """合法 base64url 应被解码到 search_query"""
    # base64url('hello') = 'aGVsbG8' (无 padding)
    r = parse_start_args("q_aGVsbG8")
    assert r["search_query"] == "hello"
    assert r["search_entry"] is False


# ---------- unknown 兜底 ----------


def test_unknown_payload_falls_back_to_unknown_source():
    raw = "unknown_payload"
    r = parse_start_args(raw)
    assert r["source_type"] == "unknown"
    # 实现里 source_id = raw[:64]，因此长度 ≤ 16 的 payload 完整保留
    assert r["source_id"] == raw
    assert r["raw"] == raw


def test_unknown_payload_truncated_to_64_chars():
    """实现层 source_id = raw[:64]，超长应被截断"""
    raw = "x" * 200
    r = parse_start_args(raw)
    assert r["source_type"] == "unknown"
    assert r["source_id"] == "x" * 64
    assert r["raw"] == raw  # raw 字段保留原始长度


# ---------- 失败容错：fav_<非数字> 也走 unknown ----------


def test_fav_non_numeric_falls_back_to_unknown():
    r = parse_start_args("fav_abc")
    assert r["source_type"] == "unknown"
    assert r["fav_teacher_id"] is None

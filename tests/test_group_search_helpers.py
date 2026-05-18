"""bot.utils.group_search 纯函数测试。

覆盖：
    - normalize_group_query        归一化（trim / lower / 空白塌缩）
    - split_query_tokens           按空白/逗号/顿号拆分 + 去重保持顺序
    - encode_query_for_deep_link   base64url 编码（无 padding，超长返回 None）
    - decode_query_from_deep_link  base64url 解码（失败返回 None）
"""

from __future__ import annotations

import pytest

from bot.utils.group_search import (
    decode_query_from_deep_link,
    encode_query_for_deep_link,
    normalize_group_query,
    split_query_tokens,
)


# ============ normalize_group_query ============


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", ""),
        ("   ", ""),
        ("ABC", "abc"),
        ("  hello   world  ", "hello world"),
        ("张三", "张三"),
        ("  张  三  ", "张 三"),
    ],
    ids=["empty", "whitespace_only", "uppercase", "multi_space", "chinese", "chinese_multi_space"],
)
def test_normalize_group_query(raw, expected):
    assert normalize_group_query(raw) == expected


def test_normalize_group_query_none_safe():
    # 函数签名是 raw: str，但内部用 ``if not raw`` 容错，传入 None 也应安全返回 ""
    assert normalize_group_query(None) == ""  # type: ignore[arg-type]


# ============ split_query_tokens ============


def test_split_empty_returns_empty_list():
    assert split_query_tokens("") == []


def test_split_whitespace_only():
    assert split_query_tokens("   ") == []


def test_split_by_spaces():
    assert split_query_tokens("a b c") == ["a", "b", "c"]


def test_split_by_chinese_separators():
    assert split_query_tokens("张三 李四,王五、赵六") == ["张三", "李四", "王五", "赵六"]


def test_split_mixed_chinese_english():
    assert split_query_tokens("张三 john 李四") == ["张三", "john", "李四"]


def test_split_dedupe_keeps_first_occurrence_and_case_insensitive():
    """重复 token 仅保留首次出现；大小写不同视为同一 token"""
    result = split_query_tokens("ABC abc XYZ")
    assert result == ["ABC", "XYZ"]


def test_split_multiple_separators_collapse():
    assert split_query_tokens("a,,,b   c、、d") == ["a", "b", "c", "d"]


# ============ encode / decode base64url 往返 ============


@pytest.mark.parametrize(
    "query",
    ["hello", "张三", "中文搜索", "abc 123", "a b,c、d"],
    ids=["english", "single_chinese", "chinese_phrase", "mixed_ascii_space", "with_separators"],
)
def test_encode_decode_roundtrip(query: str):
    encoded = encode_query_for_deep_link(query)
    assert encoded is not None
    # base64url 不含 padding 与 +/=
    assert "=" not in encoded
    assert "+" not in encoded
    assert "/" not in encoded
    # decode 后必须等于原值
    assert decode_query_from_deep_link(encoded) == query


def test_encode_empty_returns_none():
    assert encode_query_for_deep_link("") is None


def test_encode_too_long_returns_none():
    """超过 DEEP_LINK_QUERY_MAX_ENCODED_LEN（60 字符）应返回 None"""
    # 60 个中文 → 编码后远超 60 字符
    long_query = "中" * 60
    assert encode_query_for_deep_link(long_query) is None


def test_decode_empty_returns_none():
    assert decode_query_from_deep_link("") is None


def test_decode_invalid_base64_returns_none():
    """非法 base64url 字符（如 '!'）应被吞掉并返回 None，不抛异常"""
    assert decode_query_from_deep_link("!!!notbase64!!!") is None


def test_decode_whitespace_only_payload_returns_none():
    """解码后只剩空白 → 视为空 → 返回 None"""
    # base64url('   ') = 'ICAg'
    assert decode_query_from_deep_link("ICAg") is None

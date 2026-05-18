"""bot.database.compute_reimbursement_amount 纯函数测试。

规则（来自函数 docstring）：
    digits = 仅保留输入中的数字字符
    hundreds = int(digits) // 100
    hundreds <= 0 → 0
    1 <= hundreds <= 8 → 100
    hundreds == 9 → 150
    hundreds >= 10 → 200
    无法解析（空 / 无数字）→ 0

此测试纯函数，不连库。
"""

from __future__ import annotations

import pytest

from bot.database import compute_reimbursement_amount


@pytest.mark.parametrize(
    "price, expected",
    [
        # 空 / 无效 → 0
        ("", 0),
        ("P", 0),
        ("免费", 0),

        # 1–8 个百 → 100
        ("500P", 100),
        ("800P", 100),

        # 9 个百 → 150
        ("900P", 150),

        # ≥10 个百 → 200
        ("1000P", 200),
        ("2500P", 200),

        # 空白容忍
        (" 1000 P ", 200),

        # 数字嵌在字母中也能提取
        ("abc900xyz", 150),

        # None 也支持（函数内有显式分支）
        (None, 0),
    ],
    ids=[
        "empty", "letter_only", "chinese_only",
        "500P", "800P", "900P", "1000P", "2500P",
        "whitespace", "embedded_digits",
        "none",
    ],
)
def test_compute_reimbursement_amount(price, expected):
    assert compute_reimbursement_amount(price) == expected


def test_returns_int_type():
    """返回值必须是 int，不允许混入 float / str"""
    assert isinstance(compute_reimbursement_amount("1000P"), int)
    assert isinstance(compute_reimbursement_amount(None), int)

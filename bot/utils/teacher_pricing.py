"""老师价格派生纯函数（bot FSM 录入 与 MiniApp web 录入 同源，杜绝漂移）。

抽自 bot/handlers/teacher_profile.py（2026-06-29，P3 新增老师录入 web 化）：
价格→排序价 / 价位 tag / 档案描述 的派生逻辑，bot handler 与
bot/services/teacher_onboarding.py 都从此处 import。纯函数，不访问 DB / bot。
"""
from __future__ import annotations

import re
from typing import Optional

# Step 5 自动写死禁忌
DEFAULT_TABOOS: str = "桩机 粗大长 口嗨 变态 后花园 醉酒 无套 暴力 嗑药"


def _extract_largest_price(text: str) -> Optional[str]:
    """从「价格描述」抽出所有形如 '\\d+P' 的数字，取最大值作为价格（排序用）

    返回 'NP' 字符串；找不到任何 P 数字时返 None。
    """
    if not text:
        return None
    matches = re.findall(r"(\d+)\s*[Pp](?![a-zA-Z])", text)
    if not matches:
        return None
    try:
        nums = [int(m) for m in matches]
    except (TypeError, ValueError):
        return None
    return f"{max(nums)}P"


def _price_tag_bare(price: Optional[str]) -> str:
    """从 raw price（如 '800P'）抽展示价位 tag bare（无 #），如 '8P'

    规则：抽数字 // 100，附加 P。无数字 → 空串。
    """
    if not price:
        return ""
    digits = "".join(ch for ch in str(price) if ch.isdigit())
    if not digits:
        return ""
    return f"{int(digits) // 100}P"


def _inject_price_tag_into_tags(tags: list, price: Optional[str]) -> list:
    """让 tags 列表的价位 tag 与 price 字段对齐

    流程：
        1. 剥掉所有形如「数字+P」的旧 tag（不区分大小写）
        2. 若 price 可解析 → 在末尾追加新的价位 tag bare（如 '8P'）

    幂等：再次调用结果相同；price 变化后调用结果跟随变化。
    存储约定：tag 字符串不含 '#'（渲染时统一加）。
    """
    if not isinstance(tags, list):
        return tags
    cleaned: list = []
    for t in tags:
        s = str(t).strip().lstrip("#").upper()
        if re.fullmatch(r"\d+P", s):
            continue
        cleaned.append(t)
    pt = _price_tag_bare(price)
    if pt:
        cleaned.append(pt)
    return cleaned


def _compute_description_from_price(price: Optional[str]) -> str:
    """按 raw price 抽数字 // 100 = displayed 价位档自动生成描述

    - displayed ≤ 8  → 报销 100 元 → "出击加分 1分 报销金额 100元"
    - displayed == 9 → 报销 150 元 → "出击加分 1分 报销金额 150元"
    - displayed ≥ 10 → 报销 200 元 → "出击加分 1分 报销金额 200元"
    - 解析失败 / 无数字 → ""（保留空字符串，不影响保存）
    """
    if not price:
        return ""
    digits = "".join(c for c in str(price) if c.isdigit())
    if not digits:
        return ""
    n = int(digits) // 100
    if n <= 8:
        amount = 100
    elif n == 9:
        amount = 150
    else:
        amount = 200
    return f"出击加分 1分 报销金额 {amount}元"

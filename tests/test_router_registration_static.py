"""bot/routers.py 静态检查（不实例化真实 Bot / Dispatcher）。

2026-05-18 main.py 拆分后，所有 router 注册集中在 ``bot.routers.register_routers``。
拆分要求**注册顺序逐行等价于拆分前的 main.py L109-213**，本测试用纯文本读取
+ 顺序索引比较来保证这一不变量。

不实例化 Bot：因为本地 / CI 环境用的是 dummy token，aiogram 会做格式校验。
"""

from __future__ import annotations

import os
import re

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROUTERS_PY = os.path.join(_PROJECT_ROOT, "bot", "routers.py")


def _read() -> str:
    with open(_ROUTERS_PY) as f:
        return f.read()


def _include_router_calls(src: str) -> list[str]:
    """按出现顺序抽取所有 ``dp.include_router(<name>)`` 中的 <name>。

    跳过注释行（行首是 #）。匹配宽松：
        dp.include_router(some_router)
        dp.include_router(some_router)  # trailing comment
    """
    out: list[str] = []
    for raw in src.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            continue
        m = re.search(r"dp\.include_router\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)", raw)
        if m:
            out.append(m.group(1))
    return out


# ============ 模块级契约 ============


def test_routers_module_exists():
    assert os.path.isfile(_ROUTERS_PY)


def test_register_routers_function_defined():
    src = _read()
    # 接受不同的 type hint 写法
    assert re.search(r"^def register_routers\(", src, re.MULTILINE), (
        "未在 bot/routers.py 顶层找到 def register_routers(...)"
    )


def test_dispatcher_typed_parameter():
    """register_routers 参数应至少出现 Dispatcher（防止误参数化为别的类型）"""
    assert "from aiogram import Dispatcher" in _read()


# ============ 关键顺序断言（来自拆分前 main.py） ============


def test_start_router_is_first():
    """start_router 必须最先注册（/start 角色分流入口）"""
    calls = _include_router_calls(_read())
    assert calls, "未抽取到任何 include_router 调用"
    assert calls[0] == "start_router", f"第一条应为 start_router，实际：{calls[0]}"


def test_keyword_router_is_last():
    """keyword 是 catch-all，必须最后注册避免拦截其他消息"""
    calls = _include_router_calls(_read())
    assert calls[-1] == "keyword_router", f"最后一条应为 keyword_router，实际：{calls[-1]}"


def test_start_before_keyword():
    """常识性顺序断言：start 在 keyword 之前"""
    calls = _include_router_calls(_read())
    assert calls.index("start_router") < calls.index("keyword_router")


def test_critical_pairwise_orderings():
    """拆分前 main.py 注释中阐明的关键顺序对，必须全部保留。

    这些顺序由 callback 命名空间 / FSM 状态过滤 / message handler 命中关系决定，
    乱序会导致 FSM 抢占或 callback 不响应。
    """
    calls = _include_router_calls(_read())
    idx = {name: i for i, name in enumerate(calls)}

    pairs = [
        # callback 命名空间相关
        ("favorite_router", "teacher_detail_router"),
        ("teacher_detail_router", "review_list_router"),
        # admin 一族在 admin_panel 周围
        ("admin_review_router", "rreview_admin_router"),
        ("rreview_admin_router", "admin_panel_router"),
        ("admin_panel_router", "admin_points_router"),
        ("admin_panel_router", "admin_lottery_router"),
        ("admin_panel_router", "subreq_admin_router"),
        # teacher_profile 必须在 teacher_flow 之前（避免 teacher_flow 通用 handler 抢 FSM）
        ("teacher_profile_router", "teacher_flow_router"),
        # user_panel 系列在 user_search 之前
        ("user_panel_router", "user_search_router"),
        # review_card 在 review_submit 之前（card:* 优先匹配）
        ("review_card_router", "review_submit_router"),
        # 私聊消息匹配在 keyword 之前
        ("discussion_anchor_router", "keyword_router"),
        ("lottery_entry_router", "keyword_router"),
        ("user_search_router", "keyword_router"),
    ]
    for before, after in pairs:
        assert before in idx, f"router 缺失：{before}"
        assert after in idx, f"router 缺失：{after}"
        assert idx[before] < idx[after], (
            f"顺序违反：{before} (#{idx[before]}) 必须在 {after} (#{idx[after]}) 之前"
        )


def test_subsystem_routers_all_registered():
    """关键业务子系统的 router 都必须被注册（防止误删）"""
    calls = set(_include_router_calls(_read()))
    required = {
        # 评价 / 报告
        "review_card_router",
        "review_submit_router",
        "review_list_router",
        "admin_review_router",
        "rreview_admin_router",
        # 报销
        "admin_reimburse_router",
        "user_reimburse_router",
        # 抽奖
        "admin_lottery_router",
        "lottery_entry_router",
        # 积分
        "admin_points_router",
        "user_points_router",
        # 老师 / 用户主流程
        "start_router",
        "teacher_flow_router",
        "teacher_profile_router",
        "teacher_self_router",
        "user_panel_router",
        "user_search_router",
        "keyword_router",
    }
    missing = required - calls
    assert not missing, f"以下关键 router 未在 register_routers 中注册：{missing}"


def test_total_router_count_matches_pre_split():
    """拆分前 main.py 共 33 个 include_router 调用。本测试是回归网，防止有人不小心删了 router。"""
    calls = _include_router_calls(_read())
    assert len(calls) == 33, f"期望 33 个 include_router，实际 {len(calls)}"


def test_router_names_are_unique():
    """同一 router 不应被注册两次。"""
    calls = _include_router_calls(_read())
    assert len(calls) == len(set(calls)), "存在重复 router 注册"

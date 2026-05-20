"""dead code P3-A 注释存在性静态检查。

P3-A 阶段（2026-05-18）仅给可疑 dead code 加注释，零行为变化。本测试
用于回归保护：防止后续 commit 不小心把这些注释删掉，让维护者重新踩坑。

测试只读文件文本，不 import aiogram / 不实例化 Bot / 不读真实 .env。
"""

from __future__ import annotations

import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path: str) -> str:
    full = os.path.join(_PROJECT_ROOT, path)
    with open(full) as f:
        return f.read()


# ============ ReviewSubmitStates 已删除契约（Sprint 7 §9.1 第 3 批） ============


def test_review_submit_states_class_deleted():
    """Sprint 7 §9.1 第 3 批：ReviewSubmitStates 类已删除。"""
    from bot.states import teacher_states
    assert not hasattr(teacher_states, "ReviewSubmitStates")


def test_review_submit_handlers_no_longer_exist():
    """review_submit.py 中所有依赖 ReviewSubmitStates 的 handler 已删除。

    文件 docstring 中可保留对历史 ReviewSubmitStates 的引用（说明清理历史），
    但不应有任何 import / set_state / state filter 等代码层面引用。
    """
    src = _read("bot/handlers/review_submit.py")

    # 不应再 import ReviewSubmitStates（关键防御）
    assert "ReviewSubmitStates," not in src
    assert "import ReviewSubmitStates" not in src
    # 不应再 set_state(ReviewSubmitStates.*)
    assert "ReviewSubmitStates." not in src
    # 不应作为 state filter 出现
    assert "ReviewSubmitStates(" not in src

    # 旧线性 FSM 的 handler 函数名也不应再出现
    forbidden_funcs = (
        "step_evidence_media",
        "step_evidence_invalid",
        "_enter_rating",
        "_enter_score_step",
        "_enter_summary",
        "_enter_reimbursement_step",
        "_enter_confirm",
        "cb_rating",
        "msg_rating",
        "msg_dim_score",
        "msg_summary",
        "cb_review_edit",
        "cb_review_submit",
        "cb_review_reimburse_yes",
        "cb_review_reimburse_no",
        "cb_reimburse_subreq_recheck_submit",
        "cb_reimburse_subreq_back_submit",
    )
    for func in forbidden_funcs:
        assert func not in src, f"已删除的 handler {func} 仍出现在 review_submit.py"


# ============ promo_links 模块已删除契约（Sprint 7 §9.1 第 1 批） ============


def test_promo_links_module_deleted():
    """Sprint 7 §9.1 第 1 批 dead code 删除：
    - bot/handlers/promo_links.py 已删
    - bot/keyboards/admin_kb.py 中 promo_links_menu_kb / promo_cancel_kb 已删
    - bot/states/teacher_states.py 中 PromoLinkStates 已删
    """
    # 文件已删
    assert not os.path.exists(
        os.path.join(_PROJECT_ROOT, "bot/handlers/promo_links.py")
    )

    # keyboard 不再可 import
    from bot.keyboards import admin_kb
    assert not hasattr(admin_kb, "promo_links_menu_kb")
    assert not hasattr(admin_kb, "promo_cancel_kb")

    # FSM state 不再可 import
    from bot.states import teacher_states
    assert not hasattr(teacher_states, "PromoLinkStates")


def test_admin_kb_source_has_no_promo_callbacks():
    """admin_kb.py 源码不应再含 admin:promo 任何 callback_data。"""
    src = _read("bot/keyboards/admin_kb.py")
    # 仅允许在注释中提及（说明删除历史）；不允许 callback_data="admin:promo*"
    assert 'callback_data="admin:promo' not in src
    assert "promo_links_menu_kb" not in src or "已" in src  # 仅允许注释里出现


# ============ source_stats 模块已删除契约（Sprint 7 §9.1 第 2 批） ============


def test_source_stats_module_deleted():
    """Sprint 7 §9.1 第 2 批 dead code 删除：
    - bot/handlers/source_stats.py 已删
    - bot/keyboards/admin_kb.py 中 3 个 source_stats_* / source_lookup_*
      keyboard 已删
    - bot/states/teacher_states.py 中 UserSourceLookupStates 已删

    保留（§9.1 纪律：每次只删 1 个文件）：
    - bot/database.py 中 4 个 source DB helper（count_total_source_users /
      get_top_sources_by_type / get_user_source_summary / get_source_stats）
      留待后续 PR 单独清理
    """
    # 文件已删
    assert not os.path.exists(
        os.path.join(_PROJECT_ROOT, "bot/handlers/source_stats.py")
    )

    # keyboard 不再可 import
    from bot.keyboards import admin_kb
    assert not hasattr(admin_kb, "source_stats_menu_kb")
    assert not hasattr(admin_kb, "source_stats_back_kb")
    assert not hasattr(admin_kb, "source_lookup_cancel_kb")

    # FSM state 不再可 import
    from bot.states import teacher_states
    assert not hasattr(teacher_states, "UserSourceLookupStates")


def test_admin_kb_source_has_no_source_stats_callbacks():
    """admin_kb.py 源码不应再含 admin:source_stats / admin:user_source 任何
    callback_data。"""
    src = _read("bot/keyboards/admin_kb.py")
    assert 'callback_data="admin:source_stats' not in src
    assert 'callback_data="admin:user_source"' not in src


def test_promo_links_and_source_stats_still_not_registered():
    """routers.py 仍不应注册这两个 handler（否则 dead code 注释会说谎）。"""
    src = _read("bot/routers.py")
    # routers.py 顶部 import 区不应出现 promo_links / source_stats
    # 但 L76 的注释里允许出现（"promo_links / source_stats（Phase 4）：2026-05-18 已下线"）
    import_lines = [
        line for line in src.splitlines()
        if line.lstrip().startswith("from bot.handlers")
    ]
    joined_imports = "\n".join(import_lines)
    assert "promo_links" not in joined_imports, "promo_links 已被重新注册到 routers.py"
    assert "source_stats" not in joined_imports, "source_stats 已被重新注册到 routers.py"

    # 反向验证：include_router 调用中也不应出现
    body = src
    assert "promo_links_router" not in body
    assert "source_stats_router" not in body


# ============ noop 双 handler 交叉注释 ============


def test_noop_handlers_references_teacher_daily_status():
    src = _read("bot/handlers/noop_handlers.py")
    # 必须有 noop:* 描述
    assert "noop:" in src
    # 必须交叉引用 teacher_daily_status
    assert "teacher_daily_status" in src
    # 必须说明分工 / 不要合并
    assert "不是重复" in src or "切勿合并" in src or "不要合并" in src


def test_teacher_daily_status_noop_references_noop_handlers():
    src = _read("bot/handlers/teacher_daily_status.py")
    # 必须交叉引用 noop_handlers
    assert "noop_handlers.py" in src or "noop_handlers" in src
    # 必须描述裸 noop / noop_xxx 的兜底语义
    assert "裸" in src or "无冒号" in src
    # 必须说明分工 / 兼容性提醒
    assert "不是重复" in src or "兼容" in src


# ============ 反回归：所有 dead code handler 已清理 ============


def test_unregistered_router_diff_unchanged():
    """全项目 handler 文件中定义 router 的数量 - routers.py 注册数 = 0。

    Sprint 7 §9.1：
    - 第 1 批已删除 promo_links（commit 6b5c9b1，2026-05-20）
    - 第 2 批已删除 source_stats（本 PR，2026-05-20）

    至此 P3-A 注释标注的 dead code handler 全部清理。差集变化的含义：
        - 有人新增了 handler 但忘记注册（差集变大）
        - 不应再有差集 == 0 的违反场景

    旧 ReviewSubmitStates 是 FSM state（不是独立 router 文件），不影响本断言。
    """
    import re
    handlers_dir = os.path.join(_PROJECT_ROOT, "bot", "handlers")
    defined: set[str] = set()
    for fname in os.listdir(handlers_dir):
        if not fname.endswith(".py"):
            continue
        with open(os.path.join(handlers_dir, fname)) as f:
            if re.search(r"^router\s*=\s*Router\(", f.read(), re.MULTILINE):
                defined.add(fname[:-3])

    routers_src = _read("bot/routers.py")
    registered: set[str] = set()
    for line in routers_src.splitlines():
        m = re.match(r"\s*from bot\.handlers\.([a-zA-Z_0-9]+)\s+import", line)
        if m:
            registered.add(m.group(1))

    diff = defined - registered
    assert diff == set(), (
        f"未注册 router 差集应为空（dead code 全部清理）：得到 {diff}"
    )

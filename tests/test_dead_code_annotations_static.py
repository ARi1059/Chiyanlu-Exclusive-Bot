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


# ============ ReviewSubmitStates 旧线性 FSM 注释 ============


def test_review_submit_has_deprecated_annotation():
    src = _read("bot/handlers/review_submit.py")
    assert "ReviewSubmitStates" in src
    # 必须明确标注已无外部入口与 deprecated 语义之一
    assert "Deprecated" in src or "deprecated" in src or "已无外部入口" in src
    # 必须指向旧线性评价 FSM 的概念
    assert "旧线性评价 FSM" in src or "线性" in src
    # 必须引用审查报告，便于维护者查
    assert "DEAD-CODE-AUDIT-2026-05-18" in src


# ============ promo_links / source_stats 下线注释 ============


def test_promo_links_marked_dead_code():
    src = _read("bot/handlers/promo_links.py")
    assert "已下线" in src
    # 必须显式说明未注册到 routers.py
    assert "bot/routers.py" in src
    assert "未在" in src or "未注册" in src


def test_source_stats_marked_dead_code():
    src = _read("bot/handlers/source_stats.py")
    assert "已下线" in src
    assert "bot/routers.py" in src
    assert "未在" in src or "未注册" in src


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


# ============ 反回归：仍只在审查报告中列出的 2 个未注册 router ============


def test_unregistered_router_diff_unchanged():
    """全项目 handler 文件中定义 router 的数量 - routers.py 注册数 = 2 (promo_links + source_stats)。

    这是 dead code audit 的基本假设；如果该差集变化，说明：
        - 有人新增了 handler 但忘记注册（差集变大）
        - 有人重新启用了 dead code 之一（差集变小且失误）
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
    assert diff == {"promo_links", "source_stats"}, (
        f"未注册 router 差集变化：期望 {{promo_links, source_stats}}，得到 {diff}"
    )

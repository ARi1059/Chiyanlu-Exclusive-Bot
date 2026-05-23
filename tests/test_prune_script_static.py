"""scripts/prune.sh 静态检查（dry-run 路径专属）。

P2 dry-run 路径必须严格只读：
    - 文件存在、可执行、shebang 是 bash
    - 包含 --dry-run 入口
    - **dry-run 路径**对数据库执行的 SQL 仅 PRAGMA / SELECT
    - 包含拒绝 --delete / --vacuum / --execute 的逻辑
    - bash -n 语法通过

P3 confirm 路径（DELETE / INSERT INTO admin_audit_logs / RETURNING 等）的
契约由 tests/test_prune_script_confirm.py 单独覆盖；本文件只断言 dry-run
路径不退化。

策略：抓 dry-run 段（参数解析后到 confirm 段开始之前的统计 loop）做 SQL
关键字断言。confirm 段允许出现 DELETE / INSERT 等。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRUNE = os.path.join(_PROJECT_ROOT, "scripts", "prune.sh")


# ============ 基础存在性 ============


def test_prune_script_exists():
    assert os.path.isfile(_PRUNE), f"missing: {_PRUNE}"


def test_prune_script_is_executable():
    assert os.access(_PRUNE, os.X_OK), "scripts/prune.sh 缺少执行权限（chmod +x）"


def test_prune_script_has_bash_shebang():
    with open(_PRUNE, encoding="utf-8") as f:
        first = f.readline()
    assert first.startswith("#!"), "missing shebang"
    assert "bash" in first, f"shebang 应使用 bash，得到：{first.strip()!r}"


# ============ 内容契约 ============


def _read_script() -> str:
    with open(_PRUNE, encoding="utf-8") as f:
        return f.read()


def test_script_mentions_dry_run_flag():
    """脚本至少要包含 --dry-run 字面值（作为参数 case 分支）"""
    assert "--dry-run" in _read_script()


def test_script_rejects_dangerous_flags():
    """拒绝 --delete / --vacuum / --execute 的 case 分支应存在。

    注：--confirm 在 P3 已是合法参数（不再被拒绝），故从本断言移除。
    其它 3 个非法参数仍必须被拒绝。"""
    src = _read_script()
    for flag in ("--delete", "--vacuum", "--execute"):
        assert flag in src, f"未发现对 {flag} 的处理（应该拒绝）"


def test_script_has_set_euo_pipefail():
    assert "set -euo pipefail" in _read_script()


# ============ 严格只读断言（dry-run 段） ============


_DRY_RUN_BEGIN_MARKER = "if [[ \"${MODE}\" == \"dry-run\" ]]; then"
_DRY_RUN_END_MARKER = "# ============ Confirm: 5 秒安全倒计时"
_DANGEROUS_KEYWORDS = (
    "DELETE",
    "UPDATE",
    "INSERT",
    "VACUUM",
    "DROP",
    "ALTER",
    "REINDEX",
)


def _split_dry_run_and_confirm(src: str) -> tuple[str, str]:
    """把脚本分成 dry-run 段（含统计 loop）和 confirm 段。

    分界线：``# ============ Confirm: 5 秒安全倒计时`` 之前是 dry-run +
    共享段；之后是 confirm 专属段。
    """
    end_idx = src.find(_DRY_RUN_END_MARKER)
    if end_idx < 0:
        # 无 confirm 段（兼容退化 dry-run-only 版本）
        return src, ""
    return src[:end_idx], src[end_idx:]


def _extract_sqlite_call_lines(text: str) -> list[tuple[int, str]]:
    """抽取 ``sqlite3 "$DB_PATH" ...`` 命令行（含 heredoc 起始行）。

    跳过：
        - 以 # 开头的注释行
        - 元命令（``command -v sqlite3`` / ``which sqlite3``）—— 它们不带 DB 参数
    多行调用（用 \\ 续行）合并成一条逻辑行。
    """
    out: list[tuple[int, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            i += 1
            continue
        if re.search(r'(?:^|[\s=$(])sqlite3\s+"', raw):
            buf = raw
            start_no = i + 1
            while buf.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                buf = buf.rstrip()[:-1] + " " + lines[i]
            out.append((start_no, buf))
        i += 1
    return out


def test_dry_run_section_sqlite3_calls_are_readonly_only():
    """**dry-run 段**所有 sqlite3 调用仅含 PRAGMA / SELECT，不含 DELETE/UPDATE/INSERT/VACUUM/DROP/ALTER/REINDEX。

    confirm 段（包含 DELETE / INSERT INTO admin_audit_logs）由
    test_prune_script_confirm.py 单独覆盖。"""
    src = _read_script()
    dry_run_part, _confirm_part = _split_dry_run_and_confirm(src)
    calls = _extract_sqlite_call_lines(dry_run_part)
    assert calls, "未在 dry-run 段抓到 sqlite3 调用行，模式可能失效"

    for line_no, line in calls:
        upper = line.upper()
        for kw in _DANGEROUS_KEYWORDS:
            assert not re.search(rf"\b{kw}\b", upper), (
                f"prune.sh:{line_no} dry-run 段含危险关键字 {kw!r}: {line.strip()!r}"
            )
        assert ("PRAGMA" in upper) or ("SELECT" in upper), (
            f"prune.sh:{line_no} dry-run 段 sqlite3 调用既不是 PRAGMA 也不是 SELECT: {line.strip()!r}"
        )


def test_dry_run_section_does_not_contain_delete_or_insert():
    """**dry-run 段**字面文本不应出现 ``DELETE FROM`` / ``INSERT INTO`` / 完整 UPDATE 语句。

    confirm 段允许（且必须）出现这些字面值。"""
    src = _read_script()
    dry_run_part, _ = _split_dry_run_and_confirm(src)
    upper_dry_run = dry_run_part.upper()
    assert "DELETE FROM" not in upper_dry_run, "dry-run 段不应含 DELETE FROM"
    assert "INSERT INTO" not in upper_dry_run, "dry-run 段不应含 INSERT INTO"
    assert not re.search(r"\bUPDATE\s+\w+\s+SET\b", upper_dry_run, re.IGNORECASE), (
        "dry-run 段不应含完整 UPDATE 语句"
    )


# ============ bash -n 语法 ============


def test_prune_script_bash_n_passes():
    """bash -n 必须通过；如果环境没有 bash，跳过。"""
    bash = shutil.which("bash")
    if not bash:
        return  # silently skip — 不强行 require bash
    proc = subprocess.run(
        [bash, "-n", _PRUNE],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"bash -n failed: {proc.stderr}"


# ============ 行为契约（不真正跑 sqlite3） ============


def test_prune_script_help_works():
    """./scripts/prune.sh --help 应 exit 0 且打印帮助文本（不需要 DB）"""
    bash = shutil.which("bash")
    if not bash:
        return
    proc = subprocess.run(
        [_PRUNE, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--confirm" in proc.stdout  # P3：帮助里也得列 --confirm
    assert "用法" in proc.stdout


def test_prune_script_rejects_bare_confirm():
    """裸传 --confirm 不带 --days 必须 exit 1（强制运维显式输入 days）"""
    bash = shutil.which("bash")
    if not bash:
        return
    proc = subprocess.run(
        [_PRUNE, "--confirm"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 1
    assert "--days" in proc.stderr


def test_prune_script_rejects_dry_run_and_confirm_together():
    """--dry-run 与 --confirm 互斥。"""
    bash = shutil.which("bash")
    if not bash:
        return
    proc = subprocess.run(
        [_PRUNE, "--dry-run", "--confirm", "--days", "180"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 1
    assert "互斥" in proc.stderr or "exclusive" in proc.stderr.lower()


def test_prune_script_rejects_no_args():
    """什么参数都不传 → 必须 exit 1。"""
    bash = shutil.which("bash")
    if not bash:
        return
    proc = subprocess.run(
        [_PRUNE],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 1

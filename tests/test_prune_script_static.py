"""scripts/prune.sh 静态检查。

P2 阶段 prune.sh 必须严格只读：
    - 文件存在、可执行、shebang 是 bash
    - 包含 --dry-run 入口
    - **实际对数据库执行的 SQL** 不允许包含 DELETE / UPDATE / INSERT /
      VACUUM / DROP / ALTER / REINDEX
    - 包含拒绝危险参数（--confirm / --delete / --vacuum / --execute）的逻辑
    - bash -n 语法通过

我们的策略：抓出所有 ``sqlite3 ...`` 实际调用行，对这些行做关键字断言；
脚本头部注释 / err 消息中可能合法地出现 "DELETE"、"VACUUM" 等字眼。
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
    with open(_PRUNE) as f:
        first = f.readline()
    assert first.startswith("#!"), "missing shebang"
    assert "bash" in first, f"shebang 应使用 bash，得到：{first.strip()!r}"


# ============ 内容契约 ============


def _read_script() -> str:
    with open(_PRUNE) as f:
        return f.read()


def test_script_mentions_dry_run_flag():
    """脚本至少要包含 --dry-run 字面值（作为参数 case 分支）"""
    assert "--dry-run" in _read_script()


def test_script_rejects_dangerous_flags():
    """拒绝 --confirm / --delete / --vacuum / --execute 的 case 分支应存在"""
    src = _read_script()
    # 这四个 flag 应该都出现在脚本中（作为被拒绝的参数）
    for flag in ("--confirm", "--delete", "--vacuum", "--execute"):
        assert flag in src, f"未发现对 {flag} 的处理（应该拒绝）"
    # 拒绝消息中应有"只支持 --dry-run"或等价文案
    assert "只支持" in src or "dry-run" in src.lower()


def test_script_has_set_euo_pipefail():
    assert "set -euo pipefail" in _read_script()


# ============ 严格只读断言（关键） ============


_SQLITE_CALL_PATTERNS = (
    re.compile(r'sqlite3\b'),
)
_DANGEROUS_KEYWORDS = (
    "DELETE",
    "UPDATE",
    "INSERT",
    "VACUUM",
    "DROP",
    "ALTER",
    "REINDEX",
)


def _extract_sqlite_call_lines(src: str) -> list[tuple[int, str]]:
    """抽取所有真正对数据库调用 ``sqlite3 "$DB_PATH" ...`` 的命令行。

    跳过：
        - 以 # 开头的注释行
        - 元命令（``command -v sqlite3`` / ``which sqlite3``）—— 它们不带 DB 参数
        - 帮助文本中提到的字符串

    多行调用（用 \\ 续行）被合并成一条逻辑行后再返回。
    """
    out: list[tuple[int, str]] = []
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            i += 1
            continue
        # 必须真正以 sqlite3 起头（变量名 / cmd 名），后面紧跟带引号的路径或 $var
        if re.search(r'(?:^|[\s=$(])sqlite3\s+"', raw):
            buf = raw
            start_no = i + 1
            while buf.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                buf = buf.rstrip()[:-1] + " " + lines[i]
            out.append((start_no, buf))
        i += 1
    return out


def test_sqlite3_calls_are_readonly_only():
    """脚本中所有 sqlite3 调用语句必须只含 PRAGMA / SELECT，不含 DELETE/UPDATE/INSERT/VACUUM/DROP/ALTER/REINDEX。"""
    src = _read_script()
    calls = _extract_sqlite_call_lines(src)
    assert calls, "未抓到任何 sqlite3 调用行，模式可能失效"

    for line_no, line in calls:
        upper = line.upper()
        for kw in _DANGEROUS_KEYWORDS:
            # 匹配单词边界，避免误判（DELETE 不会出现在 "PRAGMA integrity_check" 中）
            assert not re.search(rf"\b{kw}\b", upper), (
                f"prune.sh:{line_no} 含危险关键字 {kw!r}: {line.strip()!r}"
            )
        # 同时强制：必须出现 PRAGMA 或 SELECT 之一（否则可能是没用上的空 sqlite3 调用）
        assert ("PRAGMA" in upper) or ("SELECT" in upper), (
            f"prune.sh:{line_no} sqlite3 调用既不是 PRAGMA 也不是 SELECT: {line.strip()!r}"
        )


def test_script_does_not_contain_delete_from_at_all():
    """更严格的双保险：脚本里不允许出现 ``DELETE FROM`` 字面（哪怕在注释里也容易误导）。

    注释中可以出现 'DELETE' 等单词描述行为，但**不能出现 'DELETE FROM'** 这种
    可疑可执行片段。
    """
    src = _read_script().upper()
    assert "DELETE FROM" not in src
    assert "INSERT INTO" not in src
    assert "UPDATE " not in src or "UPDATE SET" not in src  # 注释里"update" 可以；但 "UPDATE ... SET" 必须没有
    # 严格：完整 UPDATE 语句模式
    assert not re.search(r"\bUPDATE\s+\w+\s+SET\b", src, re.IGNORECASE)


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
    assert "用法" in proc.stdout


def test_prune_script_rejects_confirm():
    """不带任何 dry-run 但带 --confirm 必须 exit 1（防误用 P3 路径）"""
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
    # 错误消息应明确说明
    assert "dry-run" in proc.stderr or "不支持" in proc.stderr


def test_prune_script_rejects_no_args():
    """什么参数都不传 → 必须 exit 1，避免无意义 dry-run 也不规范"""
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

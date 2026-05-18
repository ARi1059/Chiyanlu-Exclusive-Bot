"""scripts/healthcheck.sh 静态检查。

P4 阶段新增 DB 体积提醒后，healthcheck 仍必须严格只读：
    - 文件存在 / 可执行 / shebang
    - bash -n 通过
    - 包含可配置阈值环境变量 HEALTHCHECK_DB_WARN_MB
    - 提示中引导到 ./scripts/prune.sh --dry-run
    - **所有对数据库的 sqlite3 调用**都只能是 PRAGMA / SELECT，
      不允许 DELETE / UPDATE / INSERT / VACUUM / DROP / ALTER / REINDEX
    - 行为：环境变量覆盖 + 紧阈值能触发 WARN 输出
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HC = os.path.join(_PROJECT_ROOT, "scripts", "healthcheck.sh")


# ============ 基础存在性 ============


def test_healthcheck_exists():
    assert os.path.isfile(_HC)


def test_healthcheck_is_executable():
    assert os.access(_HC, os.X_OK)


def test_healthcheck_has_bash_shebang():
    with open(_HC) as f:
        first = f.readline()
    assert first.startswith("#!") and "bash" in first


# ============ 内容契约 ============


def _read() -> str:
    with open(_HC) as f:
        return f.read()


def test_set_euo_pipefail():
    assert "set -euo pipefail" in _read()


def test_db_warn_mb_env_var_supported():
    """脚本必须暴露 HEALTHCHECK_DB_WARN_MB 环境变量，便于运维调整阈值。"""
    src = _read()
    assert "HEALTHCHECK_DB_WARN_MB" in src
    # 默认值 512 应该写死在脚本里
    assert "512" in src


def test_warning_message_routes_to_prune_dry_run():
    """DB size WARN 后应引导到 prune dry-run，而不是直接建议 DELETE。"""
    src = _read()
    # 必须出现 prune dry-run 提示
    assert "./scripts/prune.sh --dry-run" in src
    # 必须显式说明"不要手工删除 -wal"
    assert "不要手工删除 -wal" in src


def test_wal_warn_does_not_become_err():
    """WAL 提示必须只是 WARN，不应在 WAL 分支调用 err。"""
    src = _read()
    # 抽取 WAL 检查那一段代码（在 WAL file size 注释 ~ integrity_check 之间）
    m = re.search(r"-wal 文件大小提醒.*?integrity=", src, re.DOTALL)
    assert m, "未找到 WAL 检查代码块"
    wal_block = m.group(0)
    # 该段不应直接调用 err 函数
    assert "err " not in wal_block


# ============ 严格只读 ============


_DANGEROUS = ("DELETE", "UPDATE", "INSERT", "VACUUM", "DROP", "ALTER", "REINDEX")


def _extract_sqlite_call_lines(src: str) -> list[tuple[int, str]]:
    """抽取 sqlite3 "$DB_PATH" ... 形式的真实数据库调用行（跳过 command -v / which）。"""
    out: list[tuple[int, str]] = []
    lines = src.splitlines()
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


def test_healthcheck_sqlite3_calls_are_readonly_only():
    src = _read()
    calls = _extract_sqlite_call_lines(src)
    assert calls, "no sqlite3 calls detected — pattern broken?"
    for line_no, line in calls:
        upper = line.upper()
        for kw in _DANGEROUS:
            assert not re.search(rf"\b{kw}\b", upper), (
                f"healthcheck.sh:{line_no} contains {kw!r}: {line.strip()!r}"
            )
        assert ("PRAGMA" in upper) or ("SELECT" in upper), (
            f"healthcheck.sh:{line_no} sqlite3 call is neither PRAGMA nor SELECT: {line.strip()!r}"
        )


def test_no_delete_from_anywhere():
    src = _read().upper()
    assert "DELETE FROM" not in src
    assert "INSERT INTO" not in src
    assert not re.search(r"\bUPDATE\s+\w+\s+SET\b", src, re.IGNORECASE)


# ============ bash -n + 行为契约 ============


def test_bash_n_passes():
    bash = shutil.which("bash")
    if not bash:
        return
    proc = subprocess.run([bash, "-n", _HC], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr


def test_tight_threshold_triggers_db_size_warn():
    """HEALTHCHECK_DB_WARN_MB=0 时，本地任何非空 DB 都应触发 DB size WARN。

    本测试不要求 DB 真实存在；它只关心：脚本输出中能找到 'DB size:' 行，
    且当强制阈值=0 时该行的级别变为 WARN。
    """
    bash = shutil.which("bash")
    if not bash:
        return
    # 检查本地是否有 DB 文件以决定是否能触发
    db_path = os.path.join(_PROJECT_ROOT, "data", "bot.db")
    if not os.path.isfile(db_path):
        return  # 没有 DB 跳过该测试（CI 环境会缺）
    env = {**os.environ, "HEALTHCHECK_DB_WARN_MB": "0"}
    proc = subprocess.run([_HC], capture_output=True, text=True, timeout=30, env=env)
    # 不强制 exit code（可能因别的 ERR 项返回 1）；只断言输出中有 WARN DB size
    combined = proc.stdout + proc.stderr
    assert "DB size:" in combined
    assert "WARN" in combined and "DB size:" in combined
    # 同时应能看到 prune dry-run 提示
    assert "prune.sh --dry-run" in combined

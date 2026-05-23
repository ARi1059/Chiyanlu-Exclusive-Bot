"""update.sh schema_migrations 检查静态测试（P5）。

回归保护：确保未来 commit 不会
    - 删掉 _check_schema_migrations_status 函数
    - 把它接到错误位置或忘记调用
    - 把 SELECT 误改为 UPDATE / DELETE / INSERT
    - 删掉 hard failed 的 rollback 提示

只读文件文本，不实际执行 update.sh，不连 Telegram、不读真实 .env、
不访问真实数据库。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UPDATE = os.path.join(_PROJECT_ROOT, "update.sh")


def _read() -> str:
    with open(_UPDATE, encoding="utf-8") as f:
        return f.read()


# ============ 基础存在性 + 语法 ============


def test_update_sh_exists():
    assert os.path.isfile(_UPDATE)


def test_update_sh_bash_n_passes():
    bash = shutil.which("bash")
    if not bash:
        return  # silently skip if no bash
    proc = subprocess.run([bash, "-n", _UPDATE], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr


# ============ check 函数存在性 + 调用 ============


def test_check_schema_migrations_function_defined():
    """必须定义 _check_schema_migrations_status 函数。"""
    src = _read()
    assert re.search(r"_check_schema_migrations_status\s*\(\s*\)\s*\{", src), (
        "未在 update.sh 顶层找到 _check_schema_migrations_status() 函数定义"
    )


def test_check_schema_migrations_invoked_in_update_flow():
    """完整 update 流程必须调用 _check_schema_migrations_status 至少一次。"""
    src = _read()
    # 排除函数定义行本身，统计真实调用次数
    lines = src.splitlines()
    calls = 0
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # 调用形态：if _check_schema_migrations_status / _check_schema_migrations_status [;|EOF]
        if re.search(r"_check_schema_migrations_status\b", stripped) \
                and not re.search(r"_check_schema_migrations_status\s*\(\s*\)\s*\{", stripped):
            calls += 1
    assert calls >= 1, "完整 update 流程中未发现对 _check_schema_migrations_status 的调用"


# ============ SQL 契约 ============


def test_queries_schema_migrations_table():
    src = _read()
    assert "schema_migrations" in src


def test_queries_hard_failed_count():
    """必须有 hard kind + success=0 的 COUNT 查询。"""
    src = _read()
    pattern = re.compile(
        r"COUNT\(\*\).*FROM\s+schema_migrations.*WHERE\s+success\s*=\s*0\s+AND\s+kind\s*=\s*'hard'",
        re.IGNORECASE | re.DOTALL,
    )
    assert pattern.search(src), "未找到 hard failed 计数 SQL（COUNT WHERE success=0 AND kind='hard'）"


def test_queries_soft_failed_count():
    """必须有 soft kind + success=0 的 COUNT 查询。"""
    src = _read()
    pattern = re.compile(
        r"COUNT\(\*\).*FROM\s+schema_migrations.*WHERE\s+success\s*=\s*0\s+AND\s+kind\s*=\s*'soft'",
        re.IGNORECASE | re.DOTALL,
    )
    assert pattern.search(src), "未找到 soft failed 计数 SQL（COUNT WHERE success=0 AND kind='soft'）"


def test_does_not_select_error_column_for_output():
    """绝不应 SELECT error 字段并打印 — 避免 error 内容流入日志。"""
    src = _read()
    # 不允许形如 SELECT error FROM schema_migrations 或 SELECT ..., error, ... FROM schema_migrations
    bad = re.compile(
        r"SELECT\s+[^;]*\berror\b[^;]*FROM\s+schema_migrations",
        re.IGNORECASE,
    )
    matches = bad.findall(src)
    assert not matches, f"发现 SELECT error 字段查询：{matches}"


# ============ 只读 SQL 严格断言（不能出现针对 schema_migrations 的写操作） ============


def test_no_write_sql_against_schema_migrations():
    """update.sh 严格只读 schema_migrations —— 不允许 UPDATE / DELETE / INSERT。"""
    src = _read()
    for verb in ("UPDATE", "DELETE", "INSERT", "REPLACE", "DROP", "ALTER"):
        # 形如 'UPDATE schema_migrations' / 'INSERT INTO schema_migrations' / 'DELETE FROM schema_migrations'
        patterns = [
            rf"\b{verb}\s+schema_migrations\b",
            rf"\b{verb}\s+INTO\s+schema_migrations\b",
            rf"\b{verb}\s+FROM\s+schema_migrations\b",
        ]
        for p in patterns:
            assert not re.search(p, src, re.IGNORECASE), (
                f"update.sh 中发现对 schema_migrations 的 {verb} 写操作: 模式 {p!r}"
            )


def test_sqlite3_calls_for_schema_migrations_are_select_or_pragma_only():
    """所有 sqlite3 调用涉及 schema_migrations 时，SQL 必须是 SELECT 或 PRAGMA。"""
    src = _read()
    # 抽取所有 sqlite3 "$DB_PATH" "...SQL..." 调用（含跨行 \ 续行）
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if raw.lstrip().startswith("#"):
            i += 1
            continue
        if 'sqlite3 "$DB_PATH"' in raw:
            buf = raw
            while buf.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                buf = buf.rstrip()[:-1] + " " + lines[i]
            upper = buf.upper()
            if "SCHEMA_MIGRATIONS" in upper:
                assert "SELECT" in upper or "PRAGMA" in upper, (
                    f"line {i+1}: sqlite3 调用涉及 schema_migrations 但既无 SELECT 也无 PRAGMA: {buf.strip()!r}"
                )
        i += 1


# ============ 输出契约 ============


def test_hard_failed_branch_includes_rollback_hint():
    """hard failed 输出必须包含 './update.sh rollback' 字面值的回滚指引。"""
    src = _read()
    # 不仅存在 rollback 字眼，而且必须出现在 _check_schema_migrations_status 函数体内
    # 简化：全文搜 "./update.sh rollback" 至少出现 1 次（实际 update.sh 中本来也有其它 rollback 提示，所以这条更弱）
    assert "./update.sh rollback" in src
    # 同时函数体本身要含有 rollback 字眼
    func_match = re.search(
        r"_check_schema_migrations_status\s*\(\s*\)\s*\{.*?\n\}",
        src,
        re.DOTALL,
    )
    assert func_match, "无法定位 _check_schema_migrations_status 函数体"
    func_body = func_match.group(0)
    assert "rollback" in func_body.lower(), (
        "_check_schema_migrations_status 函数体内未发现 rollback 提示"
    )


def test_function_does_not_auto_run_rollback():
    """函数内不应自动调用 cmd_rollback 或 ./update.sh rollback —— 只提示，由人决定。"""
    src = _read()
    func_match = re.search(
        r"_check_schema_migrations_status\s*\(\s*\)\s*\{.*?\n\}",
        src,
        re.DOTALL,
    )
    assert func_match
    body = func_match.group(0)
    # 不能直接调用 cmd_rollback
    assert "cmd_rollback" not in body
    # 'rollback' 出现必须在 err / warn / echo 类提示中，而不是执行
    # 简单断言：函数体内不应有 `./update.sh rollback` 作为非引号的可执行命令
    # 我们的实现把它放在 err "..." 引号字符串里，所以 grep 'err.*rollback' 匹配
    rollback_lines = [ln for ln in body.splitlines() if "rollback" in ln.lower()]
    for line in rollback_lines:
        stripped = line.strip()
        # 可接受：err / warn / info / echo 加引号
        # 不可接受：./update.sh rollback 单独作为命令行
        if stripped.startswith(("./update.sh rollback", "$(./update.sh rollback", "`./update.sh rollback")):
            raise AssertionError(f"函数体内疑似自动执行 rollback 命令: {stripped!r}")

"""scripts/prune.sh --confirm 路径契约测试（Sprint 7 §9.2）。

A 类：静态契约（不实际跑脚本）—— 检测 confirm 段必须包含的文本特征
B 类：集成测试 —— 用临时 SQLite + 临时 backup 文件实际跑 prune.sh，验证
       完整 --confirm 流程；4 个边界场景

不连接生产数据库；不连接生产 backup 目录。每个集成测试在独立 tmpdir 中
铺设 fake project（scripts/ + data/ + backups/ + .env），完全隔离。
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile

import pytest


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRUNE = os.path.join(_PROJECT_ROOT, "scripts", "prune.sh")


def _read_script() -> str:
    with open(_PRUNE) as f:
        return f.read()


def _split_dry_run_and_confirm(src: str) -> tuple[str, str]:
    """与 test_prune_script_static.py 同口径分段。"""
    marker = "# ============ Confirm: 5 秒安全倒计时"
    end_idx = src.find(marker)
    if end_idx < 0:
        return src, ""
    return src[:end_idx], src[end_idx:]


# ============================================================
# A. 静态契约
# ============================================================


def test_confirm_section_exists():
    """confirm 段标记字符串必须在脚本中。"""
    src = _read_script()
    assert "# ============ Confirm: 5 秒安全倒计时" in src


def test_confirm_section_contains_delete_from_whitelist_only():
    """confirm 段必须含 DELETE FROM ${table} 模板，且 ${table} 来自 WHITELIST_TABLES 循环。"""
    src = _read_script()
    _, confirm = _split_dry_run_and_confirm(src)
    # DELETE 模板
    assert re.search(r"DELETE\s+FROM\s+\$\{table\}", confirm, re.IGNORECASE), (
        "confirm 段必须含 DELETE FROM ${table}"
    )
    # 循环必须遍历 WHITELIST_TABLES
    assert "WHITELIST_TABLES" in confirm, "confirm 段 DELETE 应在 WHITELIST_TABLES 循环内"


def test_confirm_section_uses_template_where_condition():
    """DELETE 的 WHERE 条件与 dry-run 共用模板：<time_col> < datetime('now', '-N days')。"""
    src = _read_script()
    _, confirm = _split_dry_run_and_confirm(src)
    assert "datetime('now', '-${DAYS} days')" in confirm or \
        re.search(r"datetime\(\s*'now'\s*,\s*'-\$\{DAYS\}\s*days'\s*\)", confirm), (
            "confirm 段 WHERE 应用 datetime('now', '-N days') 模板"
        )


def test_permanent_forbidden_tables_listed():
    """PERMANENT_FORBIDDEN_TABLES 必须包含 8 张权益表（POLICY 多处约束）。"""
    src = _read_script()
    forbidden_section = re.search(
        r"PERMANENT_FORBIDDEN_TABLES=\((.*?)\)",
        src,
        re.DOTALL,
    )
    assert forbidden_section, "找不到 PERMANENT_FORBIDDEN_TABLES 数组定义"
    body = forbidden_section.group(1)
    expected = [
        "point_transactions",
        "reimbursements",
        "lottery_entries",
        "teacher_reviews",
        "admin_audit_logs",
        "users",
        "teachers",
        "favorites",
    ]
    for table in expected:
        assert f'"{table}"' in body, f"PERMANENT_FORBIDDEN_TABLES 缺少 {table}"


def test_forbidden_intersection_check_present():
    """脚本必须含 WHITELIST × PERMANENT_FORBIDDEN 交集检查（编程错误防护）。"""
    src = _read_script()
    assert "PERMANENT_FORBIDDEN_TABLES" in src
    # 至少有一处对 WHITELIST 与 PERMANENT_FORBIDDEN 的双层 for 循环
    assert re.search(
        r'for\s+\w+\s+in\s+"\$\{WHITELIST_TABLES\[@\]\}".*'
        r'for\s+\w+\s+in\s+"\$\{PERMANENT_FORBIDDEN_TABLES\[@\]\}"',
        src,
        re.DOTALL,
    ), "缺少 WHITELIST × PERMANENT_FORBIDDEN 双层循环交集检查"


def test_confirm_path_has_integrity_check():
    """confirm 段必须含 PRAGMA integrity_check（删除后完整性校验）。"""
    src = _read_script()
    _, confirm = _split_dry_run_and_confirm(src)
    assert "PRAGMA integrity_check" in confirm
    # exit 2 表示完整性失败的特定退出码
    assert "exit 2" in confirm


def test_confirm_path_writes_audit_log():
    """confirm 段必须 INSERT INTO admin_audit_logs，action='prune_confirm'。"""
    src = _read_script()
    _, confirm = _split_dry_run_and_confirm(src)
    assert "INSERT INTO admin_audit_logs" in confirm
    assert "'prune_confirm'" in confirm
    # admin_id=0 表示运维脚本
    assert re.search(r"VALUES\s*\(\s*0\s*,\s*'prune_confirm'", confirm), (
        "audit log 应以 admin_id=0 写入"
    )


def test_confirm_path_uses_transactions():
    """每张表 DELETE 用 BEGIN / COMMIT；失败 ROLLBACK。"""
    src = _read_script()
    _, confirm = _split_dry_run_and_confirm(src)
    assert "BEGIN TRANSACTION" in confirm
    assert "COMMIT" in confirm
    assert "ROLLBACK" in confirm


def test_confirm_path_has_safety_delay():
    """5 秒安全倒计时必须存在（防误执行）。"""
    src = _read_script()
    _, confirm = _split_dry_run_and_confirm(src)
    assert "SAFETY_DELAY_SECONDS" in src  # 常量在头部
    # 倒计时 loop
    assert re.search(r"for\s*\(\(.*SAFETY_DELAY_SECONDS.*sleep\s+1", confirm, re.DOTALL), (
        "缺少 5 秒倒计时 sleep 1 loop"
    )


def test_confirm_path_checks_backup_existence():
    """confirm 段在 backup 检查段必须含当天 backup 路径校验。"""
    src = _read_script()
    # backup 检查在 banner 段（confirm 之前的共享 mode banner 区域）
    assert "manual.bak" in src
    assert "TODAY_TS" in src or "$(date +%Y%m%d)" in src
    assert "compgen -G" in src or "ls -1t" in src  # 至少一种 glob 检查方式


def test_confirm_action_string_present():
    """'prune_confirm' 字符串必须存在（admin_audit_logs.action）。"""
    src = _read_script()
    assert "'prune_confirm'" in src


# ============================================================
# B. 集成测试
# ============================================================


def _today_ts() -> str:
    return datetime.datetime.now().strftime("%Y%m%d")


@pytest.fixture
def fake_project(tmp_path):
    """在 tmpdir 内铺设最小 fake project：

        scripts/prune.sh         （从真项目复制）
        data/bot.db              （临时 SQLite，schema 含 admin_audit_logs +
                                  user_events + user_teacher_views）
        backups/                 （空目录）
        .env                     （DATABASE_PATH=data/bot.db）

    返回 (project_dir, db_path, backups_dir)
    """
    proj = tmp_path
    (proj / "scripts").mkdir()
    (proj / "data").mkdir()
    (proj / "backups").mkdir()

    # 复制 prune.sh（保留可执行权限）
    shutil.copy(_PRUNE, proj / "scripts" / "prune.sh")
    os.chmod(proj / "scripts" / "prune.sh", 0o755)

    # .env
    (proj / ".env").write_text("DATABASE_PATH=data/bot.db\n")

    # 临时 DB：含 user_events / user_teacher_views / admin_audit_logs（最简
    # schema，匹配生产）+ 4 张权益表（用于 prune 前后行数比对）
    db_path = proj / "data" / "bot.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE user_teacher_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            viewed_at TEXT NOT NULL
        );
        CREATE TABLE admin_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            detail TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        -- 权益表（用于核验 prune 前后行数 == ）
        CREATE TABLE point_transactions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER, delta INTEGER, reason TEXT
        );
        CREATE TABLE users (user_id INTEGER PRIMARY KEY);
        CREATE TABLE teachers (user_id INTEGER PRIMARY KEY);
        CREATE TABLE favorites (
            user_id INTEGER, teacher_id INTEGER,
            PRIMARY KEY(user_id, teacher_id)
        );
        """
    )

    # 200 行历史 user_events（创建时间 1 年前）
    for i in range(200):
        cur.execute(
            "INSERT INTO user_events(user_id, event_type, created_at) VALUES (?, ?, ?)",
            (1000 + i, "open", "2025-01-01 00:00:00"),
        )
    # 100 行近期 user_events
    for i in range(100):
        cur.execute(
            "INSERT INTO user_events(user_id, event_type, created_at) VALUES (?, ?, ?)",
            (2000 + i, "open", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
    # 50 行历史 user_teacher_views
    for i in range(50):
        cur.execute(
            "INSERT INTO user_teacher_views(user_id, teacher_id, viewed_at) VALUES (?, ?, ?)",
            (1000 + i, 9000 + i, "2025-01-01 00:00:00"),
        )
    # 权益表插点行
    cur.execute("INSERT INTO point_transactions VALUES (1, 100, 5, 'test')")
    cur.execute("INSERT INTO users VALUES (100)")
    cur.execute("INSERT INTO teachers VALUES (200)")
    cur.execute("INSERT INTO favorites VALUES (100, 200)")
    conn.commit()
    conn.close()

    return proj, db_path, proj / "backups"


def _create_today_backup(db_path, backups_dir, suffix: str = "000000"):
    """用 sqlite3 .backup 真生成一份 backups/bot.db.<today>-<suffix>.manual.bak。"""
    bak_file = backups_dir / f"bot.db.{_today_ts()}-{suffix}.manual.bak"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(bak_file))
    src.backup(dst)
    dst.close()
    src.close()
    return bak_file


def _run_prune(proj, *args, timeout=30):
    """在 fake_project 中跑 prune.sh，返回 CompletedProcess。"""
    bash = shutil.which("bash")
    assert bash, "需要 bash"
    proc = subprocess.run(
        [bash, str(proj / "scripts" / "prune.sh"), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(proj),
    )
    return proc


def _count(db_path, table: str) -> int:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    n = cur.fetchone()[0]
    conn.close()
    return n


# ---- 集成场景 ----


def test_dry_run_does_not_modify_db(fake_project):
    proj, db_path, _ = fake_project
    before_events = _count(db_path, "user_events")
    before_views = _count(db_path, "user_teacher_views")
    proc = _run_prune(proj, "--dry-run", "--days", "30")
    assert proc.returncode == 0, proc.stderr
    assert _count(db_path, "user_events") == before_events
    assert _count(db_path, "user_teacher_views") == before_views


def test_confirm_without_today_backup_refuses(fake_project):
    """无当天 .manual.bak → exit 1，DB 不变。"""
    proj, db_path, _backups = fake_project
    # 故意不创建 backup
    before_events = _count(db_path, "user_events")
    proc = _run_prune(proj, "--confirm", "--days", "30")
    assert proc.returncode == 1
    assert "manual" in proc.stderr.lower() or "未发现" in proc.stderr
    # DB 不变
    assert _count(db_path, "user_events") == before_events


def test_confirm_with_today_backup_deletes_old_rows(fake_project):
    """完整 confirm 流程：删除 200 行历史 user_events + 50 行历史 user_teacher_views。"""
    proj, db_path, backups = fake_project
    _create_today_backup(db_path, backups)

    before_events = _count(db_path, "user_events")          # 300
    before_views = _count(db_path, "user_teacher_views")    # 50
    before_pt = _count(db_path, "point_transactions")
    before_users = _count(db_path, "users")
    before_teachers = _count(db_path, "teachers")
    before_favs = _count(db_path, "favorites")
    before_audit = _count(db_path, "admin_audit_logs")

    # SAFETY_DELAY_SECONDS=5 → 集成测试需 timeout > 5
    proc = _run_prune(proj, "--confirm", "--days", "30", timeout=30)
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    # user_events: 200 历史删，100 近期保留
    assert _count(db_path, "user_events") == 100, (
        f"应保留 100 行近期 user_events; before={before_events}"
    )
    # user_teacher_views: 50 全删（全是历史）
    assert _count(db_path, "user_teacher_views") == 0
    # 权益表 prune 前后行数 == （核心安全断言）
    assert _count(db_path, "point_transactions") == before_pt
    assert _count(db_path, "users") == before_users
    assert _count(db_path, "teachers") == before_teachers
    assert _count(db_path, "favorites") == before_favs
    # admin_audit_logs 多了 1 条 prune_confirm 记录
    assert _count(db_path, "admin_audit_logs") == before_audit + 1

    # 验证 audit log 内容
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT admin_id, action, target_type, detail FROM admin_audit_logs "
        "WHERE action='prune_confirm' ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    assert row is not None
    admin_id, action, target_type, detail = row
    assert admin_id == 0
    assert action == "prune_confirm"
    assert target_type == "database"
    # detail 是 JSON 字符串，含 days / total_deleted / backup
    assert '"days": 30' in detail
    assert '"total_deleted": 250' in detail  # 200 + 50
    assert '"user_events": "200"' in detail
    assert '"user_teacher_views": "50"' in detail


def test_confirm_without_days_refuses(fake_project):
    """裸 --confirm 不带 --days → exit 1。"""
    proj, db_path, backups = fake_project
    _create_today_backup(db_path, backups)
    before_events = _count(db_path, "user_events")
    proc = _run_prune(proj, "--confirm")
    assert proc.returncode == 1
    assert "--days" in proc.stderr
    assert _count(db_path, "user_events") == before_events


def test_confirm_with_dry_run_together_refuses(fake_project):
    """--dry-run 与 --confirm 互斥。"""
    proj, db_path, backups = fake_project
    _create_today_backup(db_path, backups)
    before_events = _count(db_path, "user_events")
    proc = _run_prune(proj, "--dry-run", "--confirm", "--days", "30")
    assert proc.returncode == 1
    assert "互斥" in proc.stderr
    assert _count(db_path, "user_events") == before_events


def test_confirm_zero_matched_rows_skips_delete(fake_project):
    """命中 0 行时不应进入 DELETE 段（也无需 audit log）。

    给个非常大的 days，所有数据都在保留期内 → 0 命中 → 不删 / 不审计。"""
    proj, db_path, backups = fake_project
    _create_today_backup(db_path, backups)
    before_events = _count(db_path, "user_events")
    before_audit = _count(db_path, "admin_audit_logs")
    proc = _run_prune(proj, "--confirm", "--days", "9999")
    assert proc.returncode == 0
    # 全部行保留
    assert _count(db_path, "user_events") == before_events
    # audit log 不应增加（因为没真删）
    assert _count(db_path, "admin_audit_logs") == before_audit

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import aiosqlite
import os
from bot.config import config

logger = logging.getLogger(__name__)


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接

    每个连接都启用一组基础 SQLite PRAGMA（2026-05-18 Sprint 2 P1）：
      - foreign_keys=ON     —— 维持外键约束
      - journal_mode=WAL    —— 写不阻塞读、读不阻塞写；持久化属性，一次写入即长期生效
      - synchronous=NORMAL  —— WAL 模式下的推荐档：fsync 频率从 FULL 降到 NORMAL，
                              写吞吐显著提升；崩溃恢复仍依赖 WAL，零数据丢失风险
      - busy_timeout=5000   —— SQLite 锁等待 5s 再报 SQLITE_BUSY，
                              避免高峰瞬时锁冲突直接报错

    不引入连接池：当前单进程 polling 模式，open/close 开销可接受。
    """
    # dirname 可能为空（database_path 是裸文件名时），需先判空再 makedirs
    db_dir = os.path.dirname(config.database_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    db = await aiosqlite.connect(config.database_path)
    db.row_factory = aiosqlite.Row
    # PRAGMA 顺序：FK → WAL → synchronous → busy_timeout
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA journal_mode = WAL")
    await db.execute("PRAGMA synchronous = NORMAL")
    await db.execute("PRAGMA busy_timeout = 5000")
    return db


async def init_db():
    """初始化数据库表结构"""
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_super INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS teachers (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL,
                region TEXT NOT NULL,
                price TEXT NOT NULL,
                tags TEXT NOT NULL,
                photo_file_id TEXT,
                button_url TEXT NOT NULL,
                button_text TEXT,
                is_active INTEGER DEFAULT 1,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                checkin_date TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(teacher_id, checkin_date),
                FOREIGN KEY (teacher_id) REFERENCES teachers(user_id)
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS sent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sent_date TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_started_bot INTEGER DEFAULT 0,
                notify_enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_active_at TEXT
            );

            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, teacher_id),
                FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_favorites_teacher ON favorites(teacher_id);
            CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);

            CREATE TABLE IF NOT EXISTS teacher_edit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer_id INTEGER,
                reject_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                FOREIGN KEY (teacher_id) REFERENCES teachers(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_edit_requests_status ON teacher_edit_requests(status);
            CREATE INDEX IF NOT EXISTS idx_edit_requests_teacher
                ON teacher_edit_requests(teacher_id, created_at);

            CREATE TABLE IF NOT EXISTS user_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_user_events_created
                ON user_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_user_events_type_created
                ON user_events(event_type, created_at);
            CREATE INDEX IF NOT EXISTS idx_user_events_user_created
                ON user_events(user_id, created_at);

            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                detail TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_audit_admin_created
                ON admin_audit_logs(admin_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_audit_action_created
                ON admin_audit_logs(action, created_at);

            CREATE TABLE IF NOT EXISTS user_teacher_views (
                user_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                viewed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, teacher_id),
                FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_user_views_user_time
                ON user_teacher_views(user_id, viewed_at);

            CREATE TABLE IF NOT EXISTS user_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT,
                source_name TEXT,
                raw_payload TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, source_type, source_id)
            );

            CREATE INDEX IF NOT EXISTS idx_user_sources_user
                ON user_sources(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_sources_type
                ON user_sources(source_type, source_id);
            CREATE INDEX IF NOT EXISTS idx_user_sources_last_seen
                ON user_sources(last_seen_at);

            CREATE TABLE IF NOT EXISTS teacher_daily_status (
                teacher_id INTEGER NOT NULL,
                status_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                available_time TEXT,
                note TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (teacher_id, status_date),
                FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_daily_status_date
                ON teacher_daily_status(status_date);
            CREATE INDEX IF NOT EXISTS idx_daily_status_date_status
                ON teacher_daily_status(status_date, status);

            CREATE TABLE IF NOT EXISTS user_tags (
                user_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                score INTEGER DEFAULT 1,
                source TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, tag)
            );

            CREATE INDEX IF NOT EXISTS idx_user_tags_tag
                ON user_tags(tag);
            CREATE INDEX IF NOT EXISTS idx_user_tags_user
                ON user_tags(user_id);

            CREATE TABLE IF NOT EXISTS publish_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                template_text TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_publish_templates_default
                ON publish_templates(is_default, is_active);

            CREATE TABLE IF NOT EXISTS teacher_channel_posts (
                teacher_id              INTEGER PRIMARY KEY,
                channel_chat_id         INTEGER NOT NULL,
                channel_msg_id          INTEGER NOT NULL,
                media_group_msg_ids     TEXT,
                discussion_chat_id      INTEGER,
                discussion_anchor_id    INTEGER,
                review_count            INTEGER DEFAULT 0,
                positive_count          INTEGER DEFAULT 0,
                neutral_count           INTEGER DEFAULT 0,
                negative_count          INTEGER DEFAULT 0,
                avg_overall             REAL DEFAULT 0,
                avg_humanphoto          REAL DEFAULT 0,
                avg_appearance          REAL DEFAULT 0,
                avg_body                REAL DEFAULT 0,
                avg_service             REAL DEFAULT 0,
                avg_attitude            REAL DEFAULT 0,
                avg_environment         REAL DEFAULT 0,
                created_at              TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at              TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS teacher_reviews (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id                  INTEGER NOT NULL,
                user_id                     INTEGER NOT NULL,
                booking_screenshot_file_id  TEXT NOT NULL,
                -- 2026-05-21：手势照仅在用户选择参与报销时上传；普通评价路径
                -- 不再强制采集 → 改为可空。create_teacher_review 同步放宽
                -- 必填字段集；管理员审核侧（rreview_admin / rreview_notify /
                -- admin_kb）均加 None-guard 防止 NULL 进 InputMediaPhoto。
                gesture_photo_file_id       TEXT,
                rating                      TEXT NOT NULL,
                score_humanphoto            REAL NOT NULL,
                score_appearance            REAL NOT NULL,
                score_body                  REAL NOT NULL,
                score_service               REAL NOT NULL,
                score_attitude              REAL NOT NULL,
                score_environment           REAL NOT NULL,
                overall_score               REAL NOT NULL,
                summary                     TEXT,
                status                      TEXT NOT NULL DEFAULT 'pending',
                reviewer_id                 INTEGER,
                reject_reason               TEXT,
                discussion_chat_id          INTEGER,
                discussion_msg_id           INTEGER,
                request_reimbursement       INTEGER NOT NULL DEFAULT 0,
                anonymous                   INTEGER NOT NULL DEFAULT 0,
                created_at                  TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_at                 TEXT,
                published_at                TEXT,
                FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE,
                CHECK (
                    score_humanphoto BETWEEN 0 AND 10 AND
                    score_appearance BETWEEN 0 AND 10 AND
                    score_body BETWEEN 0 AND 10 AND
                    score_service BETWEEN 0 AND 10 AND
                    score_attitude BETWEEN 0 AND 10 AND
                    score_environment BETWEEN 0 AND 10 AND
                    overall_score BETWEEN 0 AND 10
                )
            );

            CREATE INDEX IF NOT EXISTS idx_reviews_teacher_status
                ON teacher_reviews(teacher_id, status);
            CREATE INDEX IF NOT EXISTS idx_reviews_status_created
                ON teacher_reviews(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_reviews_user_created
                ON teacher_reviews(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_reviews_user_teacher_created
                ON teacher_reviews(user_id, teacher_id, created_at);

            CREATE TABLE IF NOT EXISTS required_subscriptions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id      INTEGER NOT NULL UNIQUE,
                chat_type    TEXT NOT NULL,
                display_name TEXT NOT NULL,
                invite_link  TEXT NOT NULL,
                sort_order   INTEGER DEFAULT 0,
                is_active    INTEGER DEFAULT 1,
                created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_required_subs_active
                ON required_subscriptions(is_active, sort_order);

            CREATE TABLE IF NOT EXISTS point_transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                delta       INTEGER NOT NULL,
                reason      TEXT NOT NULL,
                related_id  INTEGER,
                operator_id INTEGER,
                note        TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_point_tx_user_time
                ON point_transactions(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_point_tx_related
                ON point_transactions(reason, related_id);

            CREATE TABLE IF NOT EXISTS reimbursements (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                review_id     INTEGER NOT NULL UNIQUE,
                teacher_id    INTEGER NOT NULL,
                amount        INTEGER NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                week_key      TEXT NOT NULL,
                month_key     TEXT NOT NULL,
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                decided_at    TEXT,
                decided_by    INTEGER,
                reject_reason TEXT,
                notified_at   TEXT,
                FOREIGN KEY (review_id) REFERENCES teacher_reviews(id),
                CHECK (status IN ('pending','approved','rejected','cancelled','queued'))
            );

            CREATE INDEX IF NOT EXISTS idx_reimb_user_week
                ON reimbursements(user_id, week_key);
            CREATE INDEX IF NOT EXISTS idx_reimb_status
                ON reimbursements(status);
            CREATE INDEX IF NOT EXISTS idx_reimb_month
                ON reimbursements(month_key);

            CREATE TABLE IF NOT EXISTS reimbursement_resets (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           INTEGER NOT NULL,
                granted_by        INTEGER NOT NULL,
                granted_at        TEXT DEFAULT CURRENT_TIMESTAMP,
                consumed          INTEGER NOT NULL DEFAULT 0,
                consumed_at       TEXT,
                consumed_reimb_id INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_reset_user_unused
                ON reimbursement_resets(user_id, consumed);

            CREATE TABLE IF NOT EXISTS lotteries (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                name                    TEXT NOT NULL,
                description             TEXT NOT NULL,
                cover_file_id           TEXT,
                entry_method            TEXT NOT NULL,
                entry_code              TEXT UNIQUE,
                prize_count             INTEGER NOT NULL,
                prize_description       TEXT NOT NULL,
                required_chat_ids       TEXT NOT NULL,
                entry_cost_points       INTEGER NOT NULL DEFAULT 0,
                publish_at              TEXT NOT NULL,
                draw_at                 TEXT NOT NULL,
                published_at            TEXT,
                drawn_at                TEXT,
                channel_chat_id         INTEGER,
                channel_msg_id          INTEGER,
                result_msg_id           INTEGER,
                status                  TEXT NOT NULL DEFAULT 'draft',
                created_by              INTEGER NOT NULL,
                created_at              TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at              TEXT DEFAULT CURRENT_TIMESTAMP,
                CHECK (entry_method IN ('button','code')),
                CHECK (status IN ('draft','scheduled','active','drawn','cancelled','no_entries')),
                CHECK (prize_count BETWEEN 1 AND 1000),
                CHECK (entry_cost_points BETWEEN 0 AND 1000000)
            );

            CREATE INDEX IF NOT EXISTS idx_lotteries_status
                ON lotteries(status);
            CREATE INDEX IF NOT EXISTS idx_lotteries_publish_at
                ON lotteries(publish_at, status);
            CREATE INDEX IF NOT EXISTS idx_lotteries_draw_at
                ON lotteries(draw_at, status);

            CREATE TABLE IF NOT EXISTS lottery_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lottery_id  INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                entered_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                won         INTEGER DEFAULT 0,
                notified_at TEXT,
                UNIQUE(lottery_id, user_id),
                FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_lottery_entries_won
                ON lottery_entries(lottery_id, won);
        """)
        await db.execute(
            """INSERT INTO admins (user_id, username, is_super)
            VALUES (?, NULL, 1)
            ON CONFLICT(user_id) DO UPDATE SET is_super = 1""",
            (config.super_admin_id,),
        )

        # schema_migrations 表（P2 baseline）：现有 _migrate_* 仍照旧执行，
        # 本表当前只用于"记录历史迁移"，不参与执行决策。
        await ensure_schema_migrations_table(db)

        # Phase 3 schema 增量：teachers 表新增 4 个字段
        await _migrate_teacher_ranking_columns(db)
        # Phase 4 schema 增量：users 表新增 4 个来源字段
        await _migrate_user_source_columns(db)
        # Phase 6.2：默认发布模板初始化（幂等）
        await _ensure_default_publish_template(db)
        # Phase 7.1 schema 增量：users 表新增 onboarding_seen
        await _migrate_user_onboarding_column(db)
        # Phase 9.1 schema 增量：teachers 表新增 10 个老师档案字段
        await _migrate_teacher_profile_columns(db)
        # Phase P.1 schema 增量：users 表新增 total_points
        await _migrate_users_total_points(db)
        # 抽奖参与积分门槛：lotteries 表新增 entry_cost_points
        await _migrate_lotteries_entry_cost(db)
        # 报销子系统：teacher_reviews 表新增 request_reimbursement
        await _migrate_reviews_request_reimbursement(db)
        await _migrate_reviews_anonymous(db)
        # 报销子系统：reimbursements.status CHECK 加 'queued'（功能关闭时静默录入）
        await _migrate_reimbursements_queued_status(db)

        # 上述 9 个 _migrate_* 执行完之后，把它们作为 baseline 写入 schema_migrations
        # （INSERT OR IGNORE，幂等；失败只 warning，不阻断启动）
        await baseline_schema_migrations(db)

        # P3 注册器执行：从 MIGRATIONS 列表读取新增迁移并真正执行。
        # 本阶段 MIGRATIONS = []（空），生产路径下此调用是 no-op；不影响旧迁移。
        # hard migration 失败会 raise，让 init_db 整体失败 → systemd 退出 → 触发回滚。
        await run_registered_migrations(db)

        await db.commit()
    finally:
        await db.close()


# ============ schema_migrations baseline (P2，详见 docs/INFRASTRUCTURE-DESIGN.md (Part A)) ============
#
# 本阶段仅做 baseline：
#   - 新增 schema_migrations 表
#   - 把当前版本已承认的 9 个历史迁移作为 baseline 记录写入（success=1）
#
# 现有 _migrate_* 函数仍按原顺序在 init_db() 中无条件执行。本表当前不参与执行
# 决策，仅供 healthcheck.sh / 运维查询使用。完整的"按 version 驱动执行"的注册器
# 见设计文档 §六；当前实现等价于设计文档 §八「阶段 A：Baseline」。

# (version, name, kind) — version 字典序 = 当前 init_db 中的执行顺序
SCHEMA_MIGRATIONS_BASELINE: list[tuple[str, str, str]] = [
    ("20260518_001_migrate_teacher_ranking_columns",
     "Phase 3: teachers 排序/精选字段（sort_weight/hot_score/is_featured/featured_until）",
     "soft"),
    ("20260518_002_migrate_users_source_fields",
     "Phase 4: users 来源追踪 4 字段（first_source_type/id, last_source_type/id）",
     "soft"),
    ("20260518_003_migrate_users_onboarding_seen",
     "Phase 7.1: users.onboarding_seen",
     "soft"),
    ("20260518_004_migrate_teacher_profile_columns",
     "Phase 9.1: teachers 老师档案 10 字段",
     "soft"),
    ("20260518_005_migrate_users_total_points",
     "Phase P.1: users.total_points",
     "soft"),
    ("20260518_006_migrate_lotteries_entry_cost_points",
     "抽奖参与积分门槛: lotteries.entry_cost_points",
     "soft"),
    ("20260518_007_migrate_reviews_request_reimbursement",
     "报销子系统: teacher_reviews.request_reimbursement",
     "soft"),
    ("20260518_008_migrate_reviews_anonymous",
     "评价匿名: teacher_reviews.anonymous",
     "soft"),
    ("20260518_009_migrate_reimbursements_queued_status",
     "报销 CHECK 重建 + 半完成态自愈（表重建型）",
     "hard"),
]


async def ensure_schema_migrations_table(db: aiosqlite.Connection) -> None:
    """幂等创建 schema_migrations 表。

    失败时只 logger.warning，不阻断启动 —— 本阶段（P2 baseline）尚未把该表纳入
    执行链路，缺失它不会影响业务 schema 与 _migrate_* 的正常运行。
    """
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                kind        TEXT NOT NULL DEFAULT 'soft',
                applied_at  TEXT,
                success     INTEGER NOT NULL DEFAULT 1,
                error       TEXT,
                checksum    TEXT,
                duration_ms INTEGER,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    except Exception as e:
        logger.warning("ensure_schema_migrations_table 失败: %s", e)


async def baseline_schema_migrations(db: aiosqlite.Connection) -> None:
    """把 SCHEMA_MIGRATIONS_BASELINE 中的历史迁移作为 baseline 写入（success=1）。

    用 INSERT OR IGNORE，幂等：
      - 同一 version 已存在时静默跳过，不覆盖
      - 这保证未来 P3 阶段如果给同一 version 写入了真实执行结果（success=0
        或更长的 error 内容），不会被这里的"已承认"基线覆盖

    失败时只 logger.warning，不阻断启动。
    """
    try:
        for version, name, kind in SCHEMA_MIGRATIONS_BASELINE:
            try:
                await db.execute(
                    "INSERT OR IGNORE INTO schema_migrations "
                    "(version, name, kind, applied_at, success, error) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1, NULL)",
                    (version, name, kind),
                )
            except Exception as e:
                logger.warning("baseline_schema_migrations row %s 失败: %s",
                               version, e)
    except Exception as e:
        logger.warning("baseline_schema_migrations 失败: %s", e)


# ============ schema_migrations P3：新迁移注册器 ============
#
# 与 P2 baseline 的区别：
#   - baseline_schema_migrations 把 9 个**历史** _migrate_* 以 success=1 record-only
#     方式写入 schema_migrations（事后承认，不真正执行）
#   - 本节的 run_registered_migrations 从下方 MIGRATIONS 列表读取**新增**迁移
#     并真正执行 + 记录结果
#
# **本阶段（P3 framework）MIGRATIONS 列表为空**：
#   - 现有 9 个 _migrate_* 函数仍按 init_db 中的原顺序无条件执行（未被迁入注册器）
#   - run_registered_migrations 在生产 main 下当前是 no-op
#   - 任何**未来**的新迁移须以 Migration 实例追加到 MIGRATIONS 列表，**不要**再加
#     新的 _migrate_* 顶级 async 函数 + init_db 手工调用
#
# 详见 docs/INFRASTRUCTURE-DESIGN.md (Part A) §五 / §六。


@dataclass(frozen=True)
class Migration:
    """单条注册迁移的元数据 + 执行函数。

    字段语义与 schema_migrations 表的列直接对应；不可变 (frozen) 防止运行时被改写。
    """
    version: str
    name: str
    kind: str  # "soft" | "hard"
    func: Callable[[aiosqlite.Connection], Awaitable[None]]


async def _migrate_001_teacher_draft_states(db: aiosqlite.Connection) -> None:
    """UX-9.3：admin teacher_profile 录入草稿表。

    保存 admin 在 `tprofile:add` 流程中的 state + data，允许"取消 → 重进 → 恢复"。
    使用 `INSERT OR IGNORE` 表创建幂等；同 admin 一次最多 1 个草稿（admin_id 作 PK）。
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_draft_states (
            admin_id    INTEGER PRIMARY KEY,
            fsm_state   TEXT NOT NULL,
            json_blob   TEXT NOT NULL,
            step_label  TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    await db.commit()


# UX-9.1 quick_entry_keywords seed：与历史 _QUICK_ENTRY_CONFIG 一一对应
# 保留为模块级常量，handler fallback 与 migration seed 共享同源数据
_QUICK_ENTRY_SEED: tuple[tuple[str, str, str, list], ...] = (
    # A0 后仅保留"今日"快捷词，按钮精简为仅"打开今日开课"（热门/筛选已下线）。
    (
        "今日",
        "📚 今日开课入口",
        "点击下方进入私聊查看今日开课老师。",
        [("打开今日开课", "today")],
    ),
)


async def _migrate_003_teacher_reviews_gesture_nullable(
    db: aiosqlite.Connection,
) -> None:
    """2026-05-21：把 teacher_reviews.gesture_photo_file_id 从 NOT NULL 改为可空。

    背景：评价前置改造后，普通评价（不参与报销）不再强制上传手势照。
    既有历史评价行均含手势照（旧 NOT NULL 保障），迁移后不受影响。

    SQLite 不支持 ALTER COLUMN DROP NOT NULL，必须 recreate-table。
    关键陷阱（2026-05-21 修复）：reimbursements.review_id FK 反向引用
    teacher_reviews(id) ON DELETE CASCADE；连接默认 PRAGMA foreign_keys=ON。
    若不先把 FK 关掉，`DROP TABLE teacher_reviews` 会被 SQLite 拒绝
    或级联清空 reimbursements。
    标准做法（参见 SQLite 官方 "ALTER TABLE" 第 7 节）：
        1. PRAGMA foreign_keys = OFF
        2. BEGIN
        3. CREATE new + 拷贝 + DROP old + RENAME new + 重建索引
        4. PRAGMA foreign_key_check 验证（出错回滚）
        5. COMMIT
        6. PRAGMA foreign_keys = ON

    幂等性：
        - notnull=0 → 直接 return（不重跑）
        - 残留 teacher_reviews_new（上次失败留下的）→ DROP IF EXISTS 清理
    """
    # 1) 幂等：列已可空则跳过
    cursor = await db.execute("PRAGMA table_info(teacher_reviews)")
    cols = await cursor.fetchall()
    gesture_notnull = next(
        (int(c[3]) for c in cols if c[1] == "gesture_photo_file_id"),
        None,
    )
    if gesture_notnull is None:
        return
    if gesture_notnull == 0:
        return

    # 2) 清理上次失败可能残留的中间表 + 把当前连接的隐式 tx 提交干净
    try:
        await db.commit()
    except Exception:
        pass
    await db.execute("DROP TABLE IF EXISTS teacher_reviews_new")
    await db.commit()

    # 3) PRAGMA foreign_keys = OFF 必须在 autocommit（无活跃 tx）状态下执行；
    #    上面 commit 已确保。设置后所有后续 statement 都不再触发 FK 校验/级联。
    await db.execute("PRAGMA foreign_keys = OFF")

    try:
        await db.execute("BEGIN")
        try:
            await db.execute(
                """
                CREATE TABLE teacher_reviews_new (
                    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_id                  INTEGER NOT NULL,
                    user_id                     INTEGER NOT NULL,
                    booking_screenshot_file_id  TEXT NOT NULL,
                    gesture_photo_file_id       TEXT,
                    rating                      TEXT NOT NULL,
                    score_humanphoto            REAL NOT NULL,
                    score_appearance            REAL NOT NULL,
                    score_body                  REAL NOT NULL,
                    score_service               REAL NOT NULL,
                    score_attitude              REAL NOT NULL,
                    score_environment           REAL NOT NULL,
                    overall_score               REAL NOT NULL,
                    summary                     TEXT,
                    status                      TEXT NOT NULL DEFAULT 'pending',
                    reviewer_id                 INTEGER,
                    reject_reason               TEXT,
                    discussion_chat_id          INTEGER,
                    discussion_msg_id           INTEGER,
                    request_reimbursement       INTEGER NOT NULL DEFAULT 0,
                    anonymous                   INTEGER NOT NULL DEFAULT 0,
                    created_at                  TEXT DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at                 TEXT,
                    published_at                TEXT,
                    FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE,
                    CHECK (
                        score_humanphoto BETWEEN 0 AND 10 AND
                        score_appearance BETWEEN 0 AND 10 AND
                        score_body BETWEEN 0 AND 10 AND
                        score_service BETWEEN 0 AND 10 AND
                        score_attitude BETWEEN 0 AND 10 AND
                        score_environment BETWEEN 0 AND 10 AND
                        overall_score BETWEEN 0 AND 10
                    )
                )
                """,
            )
            await db.execute(
                """
                INSERT INTO teacher_reviews_new (
                    id, teacher_id, user_id,
                    booking_screenshot_file_id, gesture_photo_file_id,
                    rating,
                    score_humanphoto, score_appearance, score_body,
                    score_service, score_attitude, score_environment,
                    overall_score, summary, status,
                    reviewer_id, reject_reason,
                    discussion_chat_id, discussion_msg_id,
                    request_reimbursement, anonymous,
                    created_at, reviewed_at, published_at
                )
                SELECT id, teacher_id, user_id,
                       booking_screenshot_file_id, gesture_photo_file_id,
                       rating,
                       score_humanphoto, score_appearance, score_body,
                       score_service, score_attitude, score_environment,
                       overall_score, summary, status,
                       reviewer_id, reject_reason,
                       discussion_chat_id, discussion_msg_id,
                       request_reimbursement, anonymous,
                       created_at, reviewed_at, published_at
                FROM teacher_reviews
                """,
            )
            await db.execute("DROP TABLE teacher_reviews")
            await db.execute("ALTER TABLE teacher_reviews_new RENAME TO teacher_reviews")
            # 重建索引（与 init_db schema 字符串中的 CREATE INDEX 一致）
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviews_teacher_status "
                "ON teacher_reviews(teacher_id, status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviews_status_created "
                "ON teacher_reviews(status, created_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviews_user_created "
                "ON teacher_reviews(user_id, created_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviews_user_teacher_created "
                "ON teacher_reviews(user_id, teacher_id, created_at)"
            )
            # 4) FK 完整性校验（事务内）—— reimbursements.review_id 等任何
            #    指向 teacher_reviews(id) 的 FK 不应有悬挂引用。
            cur = await db.execute("PRAGMA foreign_key_check")
            violations = await cur.fetchall()
            if violations:
                raise RuntimeError(
                    f"foreign_key_check 发现 {len(violations)} 条悬挂引用：{violations[:5]}"
                )
            await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            raise
    finally:
        # 5) 无论成功失败都恢复 foreign_keys=ON
        try:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.commit()
        except Exception:
            pass


async def _migrate_002_quick_entry_keywords(db: aiosqlite.Connection) -> None:
    """UX-9.1：群组快捷词配置表 + seed 默认 5 条。

    设计要点：
        - trigger 用 COLLATE NOCASE，匹配现网"大小写无关"语义
        - seeded=1 标记 migration 初始化的行，运营可改/删，不被 migration 再次覆盖
        - buttons_json 存 [(label, deep_link_target), ...]，与 _QUICK_ENTRY_CONFIG 同形
        - 表为空时 handler 走硬编码 _QUICK_ENTRY_CONFIG fallback（同源 _QUICK_ENTRY_SEED）
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS quick_entry_keywords (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger       TEXT NOT NULL UNIQUE COLLATE NOCASE,
            banner        TEXT NOT NULL DEFAULT '',
            body          TEXT NOT NULL DEFAULT '',
            buttons_json  TEXT NOT NULL DEFAULT '[]',
            enabled       INTEGER NOT NULL DEFAULT 1,
            hit_count     INTEGER NOT NULL DEFAULT 0,
            seeded        INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    # seed 5 条；INSERT OR IGNORE 保证幂等（trigger UNIQUE）
    for trigger, banner, body, buttons in _QUICK_ENTRY_SEED:
        await db.execute(
            """
            INSERT OR IGNORE INTO quick_entry_keywords
                (trigger, banner, body, buttons_json, enabled, seeded)
            VALUES (?, ?, ?, ?, 1, 1)
            """,
            (trigger, banner, body, json.dumps(buttons, ensure_ascii=False)),
        )
    await db.commit()


async def _migrate_004_teacher_is_deleted(db: aiosqlite.Connection) -> None:
    """软删除：teachers 表添加 is_deleted 列（与 is_active 正交）。

    is_active 管"停用/启用"（可一键恢复，仍显示在管理列表）；
    is_deleted 管"删除/恢复"（从所有用户端 + 管理端列表彻底隐藏，超管可恢复）。
    SQLite 不支持 ADD COLUMN IF NOT EXISTS，PRAGMA 检测后再 ADD，幂等可重入。
    """
    cur = await db.execute("PRAGMA table_info(teachers)")
    rows = await cur.fetchall()
    existing = {row["name"] for row in rows}
    if "is_deleted" not in existing:
        try:
            await db.execute(
                "ALTER TABLE teachers ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass
    await db.commit()


async def _migrate_005_remove_quick_entry_keywords(db: aiosqlite.Connection) -> None:
    """A0 后下线群组快捷词 菜单(启动) / 热门(老师) / 推荐(老师) / 筛选(老师)，仅保留"今日开课"。

    运营曾在 admin 界面把 seeded 行 trigger 改名（菜单→启动、今日→今日开课、
    热门→热门老师 等），故按"保留式 + seeded 护栏"删除：只删 seeded=1 且
    trigger 不属于"今日"白名单的行——抗改名，且绝不误删运营手建（seeded=0）行。
    """
    await db.execute(
        """
        DELETE FROM quick_entry_keywords
        WHERE seeded = 1 AND trigger NOT IN ('今日', '今日开课')
        """
    )
    await db.commit()


# 未来新增迁移在此追加。
MIGRATIONS: list[Migration] = [
    Migration(
        version="20260520_001_teacher_draft_states",
        name="UX-9.3 admin teacher_profile 录入草稿表",
        kind="soft",  # soft：表创建失败不阻断启动；handler 端会 try/except 容错
        func=_migrate_001_teacher_draft_states,
    ),
    Migration(
        version="20260520_002_quick_entry_keywords",
        name="UX-9.1 群组快捷词配置表 + seed 默认",
        kind="soft",  # soft：表缺失时 handler 走硬编码 fallback
        func=_migrate_002_quick_entry_keywords,
    ),
    Migration(
        version="20260521_001_teacher_reviews_gesture_nullable",
        name="评价前置：teacher_reviews.gesture_photo_file_id 改为可空",
        # hard：schema 不一致会让 create_teacher_review 在 req=0 路径插入 None
        # 时报 NOT NULL 错；启动失败便于 update.sh rollback 比静默放过更安全
        kind="hard",
        func=_migrate_003_teacher_reviews_gesture_nullable,
    ),
    Migration(
        version="20260613_001_teacher_is_deleted",
        name="软删除：teachers.is_deleted 列",
        # hard：用户/管理端全量查询都将引用 is_deleted，缺列会让 SELECT 报错；
        # 启动失败便于 update.sh rollback，比静默放过更安全
        kind="hard",
        func=_migrate_004_teacher_is_deleted,
    ),
    Migration(
        version="20260613_002_remove_quick_entry_keywords",
        name="下线群组快捷词 菜单/热门/推荐/筛选，仅保留今日",
        kind="soft",  # 删 seed 行失败不应阻断启动；与 002 同档
        func=_migrate_005_remove_quick_entry_keywords,
    ),
]


# error 字段截断上限（避免 SQLite 单行存超长 traceback）
_MIGRATION_ERROR_MAX_LEN: int = 500


async def run_registered_migrations(db: aiosqlite.Connection) -> None:
    """执行 MIGRATIONS 中尚未成功的注册迁移。

    行为：
      1. 确保 schema_migrations 表存在（防御性：未先跑 baseline 时也能用）
      2. 静态校验 MIGRATIONS：version 唯一、kind ∈ {soft, hard} —— 不合规直接
         raise ValueError，让启动失败便于开发者立即发现
      3. 按 version 字典序排序（确保新装库与旧装库执行顺序一致）
      4. 跳过 schema_migrations 中 success=1 的 version
      5. 对未成功的逐一执行：
         - 成功：UPSERT 一条 success=1 记录，error=NULL，写入 duration_ms
         - 失败 + kind='soft'：UPSERT success=0 + 截断 error，warning，不阻断
         - 失败 + kind='hard'：UPSERT success=0 + 截断 error，**raise** 让
           init_db 失败，便于 update.sh rollback

    本函数对**旧迁移行为零影响** —— 它只读 / 写 schema_migrations 一张表，
    不触碰任何业务表。
    """
    await ensure_schema_migrations_table(db)

    # 静态校验
    versions_seen: set[str] = set()
    for m in MIGRATIONS:
        if m.version in versions_seen:
            raise ValueError(f"MIGRATIONS 中存在重复 version: {m.version!r}")
        versions_seen.add(m.version)
        if m.kind not in ("soft", "hard"):
            raise ValueError(
                f"MIGRATIONS[{m.version!r}].kind = {m.kind!r}, 必须是 'soft' 或 'hard'"
            )

    if not MIGRATIONS:
        return  # 当前阶段：空列表 → no-op

    # 读已成功的 version 集合
    cursor = await db.execute(
        "SELECT version FROM schema_migrations WHERE success = 1"
    )
    rows = await cursor.fetchall()
    applied: set[str] = {row[0] for row in rows}

    # 按 version 字典序排序后逐一执行
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if migration.version in applied:
            continue

        start_t = time.monotonic()
        try:
            await migration.func(db)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_t) * 1000)
            error_msg = repr(exc)
            if len(error_msg) > _MIGRATION_ERROR_MAX_LEN:
                error_msg = error_msg[: _MIGRATION_ERROR_MAX_LEN]

            # 写失败记录（best-effort，单独 try）
            try:
                await db.execute(
                    """
                    INSERT INTO schema_migrations
                        (version, name, kind, applied_at, success, error, duration_ms, checksum)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, 0, ?, ?, NULL)
                    ON CONFLICT(version) DO UPDATE SET
                        name = excluded.name,
                        kind = excluded.kind,
                        applied_at = CURRENT_TIMESTAMP,
                        success = 0,
                        error = excluded.error,
                        duration_ms = excluded.duration_ms
                    """,
                    (migration.version, migration.name, migration.kind,
                     error_msg, duration_ms),
                )
                await db.commit()
            except Exception as inner:
                logger.warning(
                    "写入 schema_migrations 失败记录时再次失败 (version=%s): %s",
                    migration.version, inner,
                )

            if migration.kind == "hard":
                logger.error(
                    "hard migration %s 失败，启动应被阻断: %s",
                    migration.version, error_msg,
                )
                raise
            else:
                logger.warning(
                    "soft migration %s 失败（不阻断启动）: %s",
                    migration.version, error_msg,
                )
                continue

        # 成功路径
        duration_ms = int((time.monotonic() - start_t) * 1000)
        try:
            await db.execute(
                """
                INSERT INTO schema_migrations
                    (version, name, kind, applied_at, success, error, duration_ms, checksum)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1, NULL, ?, NULL)
                ON CONFLICT(version) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    applied_at = CURRENT_TIMESTAMP,
                    success = 1,
                    error = NULL,
                    duration_ms = excluded.duration_ms
                """,
                (migration.version, migration.name, migration.kind, duration_ms),
            )
            await db.commit()
            logger.info(
                "migration %s 执行成功 (%dms, kind=%s)",
                migration.version, duration_ms, migration.kind,
            )
        except Exception as inner:
            logger.warning(
                "写入 schema_migrations 成功记录失败 (version=%s): %s",
                migration.version, inner,
            )


async def _migrate_teacher_ranking_columns(db: aiosqlite.Connection) -> None:
    """Phase 3：teachers 表添加 sort_weight / hot_score / is_featured / featured_until

    SQLite 不支持 ADD COLUMN IF NOT EXISTS，通过 PRAGMA table_info 检测后再 ADD。
    历史已有列时跳过，安全可重入。
    """
    cur = await db.execute("PRAGMA table_info(teachers)")
    rows = await cur.fetchall()
    existing = {row["name"] for row in rows}

    additions: list[tuple[str, str]] = [
        ("sort_weight", "INTEGER DEFAULT 0"),
        ("hot_score", "INTEGER DEFAULT 0"),
        ("is_featured", "INTEGER DEFAULT 0"),
        ("featured_until", "TEXT"),
    ]
    for col, type_def in additions:
        if col in existing:
            continue
        try:
            await db.execute(f"ALTER TABLE teachers ADD COLUMN {col} {type_def}")
        except Exception:
            # 极端情况下 PRAGMA 与实际 schema 不一致 → 忽略 duplicate column
            pass


async def _migrate_user_source_columns(db: aiosqlite.Connection) -> None:
    """Phase 4：users 表添加 first_source_type / first_source_id / last_source_type / last_source_id

    PRAGMA 检测后再 ADD，幂等可重入。
    """
    cur = await db.execute("PRAGMA table_info(users)")
    rows = await cur.fetchall()
    existing = {row["name"] for row in rows}

    additions: list[tuple[str, str]] = [
        ("first_source_type", "TEXT"),
        ("first_source_id", "TEXT"),
        ("last_source_type", "TEXT"),
        ("last_source_id", "TEXT"),
    ]
    for col, type_def in additions:
        if col in existing:
            continue
        try:
            await db.execute(f"ALTER TABLE users ADD COLUMN {col} {type_def}")
        except Exception:
            pass


async def _migrate_user_onboarding_column(db: aiosqlite.Connection) -> None:
    """Phase 7.1：users 表添加 onboarding_seen 字段（新手引导曝光标记）

    PRAGMA 检测后再 ADD，幂等可重入。已有列时静默跳过。
    """
    try:
        cur = await db.execute("PRAGMA table_info(users)")
        rows = await cur.fetchall()
        existing = {row["name"] for row in rows}
        if "onboarding_seen" in existing:
            return
        await db.execute(
            "ALTER TABLE users ADD COLUMN onboarding_seen INTEGER DEFAULT 0"
        )
    except Exception as e:
        logger.warning("onboarding_seen 字段迁移失败（不阻断启动）: %s", e)


async def _migrate_users_total_points(db: aiosqlite.Connection) -> None:
    """Phase P.1：users 表添加 total_points 字段

    PRAGMA 检测后再 ADD，幂等可重入。
    """
    try:
        cur = await db.execute("PRAGMA table_info(users)")
        rows = await cur.fetchall()
        existing = {row["name"] for row in rows}
        if "total_points" in existing:
            return
        await db.execute(
            "ALTER TABLE users ADD COLUMN total_points INTEGER DEFAULT 0"
        )
    except Exception as e:
        logger.warning("total_points 字段迁移失败（不阻断启动）: %s", e)


async def _migrate_lotteries_entry_cost(db: aiosqlite.Connection) -> None:
    """lotteries 表添加 entry_cost_points（参与所需积分，默认 0 表示免费）

    PRAGMA 检测后再 ADD，幂等可重入。无法回填 CHECK 约束（SQLite ALTER 限制），
    校验交由 create_lottery / update_lottery_fields 业务层兜底。
    """
    try:
        cur = await db.execute("PRAGMA table_info(lotteries)")
        rows = await cur.fetchall()
        existing = {row["name"] for row in rows}
        if "entry_cost_points" in existing:
            return
        await db.execute(
            "ALTER TABLE lotteries ADD COLUMN entry_cost_points INTEGER NOT NULL DEFAULT 0"
        )
    except Exception as e:
        logger.warning("entry_cost_points 字段迁移失败（不阻断启动）: %s", e)


async def _migrate_reviews_request_reimbursement(db: aiosqlite.Connection) -> None:
    """teacher_reviews 表添加 request_reimbursement（报销意愿，默认 0 不申请）

    PRAGMA 检测后再 ADD，幂等可重入。老评价默认 0，不会触发自动创建报销记录。
    """
    try:
        cur = await db.execute("PRAGMA table_info(teacher_reviews)")
        rows = await cur.fetchall()
        existing = {row["name"] for row in rows}
        if "request_reimbursement" in existing:
            return
        await db.execute(
            "ALTER TABLE teacher_reviews ADD COLUMN request_reimbursement INTEGER NOT NULL DEFAULT 0"
        )
    except Exception as e:
        logger.warning("request_reimbursement 字段迁移失败（不阻断启动）: %s", e)


async def _migrate_reviews_anonymous(db: aiosqlite.Connection) -> None:
    """teacher_reviews 表添加 anonymous（匿名提交，默认 0=不匿名）

    PRAGMA 检测后再 ADD，幂等可重入。老评价默认 0=不匿名。
    """
    try:
        cur = await db.execute("PRAGMA table_info(teacher_reviews)")
        rows = await cur.fetchall()
        existing = {row["name"] for row in rows}
        if "anonymous" in existing:
            return
        await db.execute(
            "ALTER TABLE teacher_reviews ADD COLUMN anonymous INTEGER NOT NULL DEFAULT 0"
        )
    except Exception as e:
        logger.warning("anonymous 字段迁移失败（不阻断启动）: %s", e)


async def _migrate_reimbursements_queued_status(db: aiosqlite.Connection) -> None:
    """扩展 reimbursements.status CHECK 接受 'queued'（功能关闭时静默录入名单）

    SQLite 不支持 ALTER CHECK；本函数维护 5 种状态分支，确保幂等可重入
    且**对半完成态可自愈**（2026-05-18 P1 修复）：

      State A (正常已迁移)
        reimbursements 存在 + CHECK 已含 'queued' + 无 reimbursements_new
        → 直接 return

      State B (半完成态：DROP 已成功但 RENAME 前死亡)
        reimbursements 不存在 + reimbursements_new 存在
        → 自愈 RENAME + 重建 3 个索引

      State C (残留空 _new)
        reimbursements 存在 + CHECK 已含 'queued' + reimbursements_new 为空
        → DROP TABLE reimbursements_new 清理

      State D (残留非空 _new) ⚠
        reimbursements 存在 + reimbursements_new 非空（无论主表 CHECK 状态）
        → 不自动处理，warn 提示人工核对，避免数据丢失

      State E (标准重建)
        reimbursements 存在 + CHECK 不含 'queued' + 无 reimbursements_new
        → CREATE _new → INSERT SELECT → DROP 旧 → RENAME → 建索引
          全程包在 BEGIN IMMEDIATE / COMMIT 中以获得 SQLite 原生事务原子性

      表都不存在（首次 init_db 已含新 CHECK）→ return
    """
    try:
        # 一次性查两张表的 sqlite_master 元信息
        cur = await db.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name IN ('reimbursements','reimbursements_new')"
        )
        master_rows = await cur.fetchall()
        tables = {row["name"]: (row["sql"] or "") for row in master_rows}
        has_main = "reimbursements" in tables
        has_new = "reimbursements_new" in tables

        # ---- 空 schema：两张表都没有（首次 init_db 已带新 CHECK） ----
        if not has_main and not has_new:
            return

        # ---- State B：半完成态自愈 ----
        if (not has_main) and has_new:
            logger.warning(
                "检测到 reimbursements 半完成迁移：主表缺失但 reimbursements_new 存在。"
                "执行自愈 RENAME + 重建索引..."
            )
            await db.executescript("""
                ALTER TABLE reimbursements_new RENAME TO reimbursements;
                CREATE INDEX IF NOT EXISTS idx_reimb_user_week
                    ON reimbursements(user_id, week_key);
                CREATE INDEX IF NOT EXISTS idx_reimb_status
                    ON reimbursements(status);
                CREATE INDEX IF NOT EXISTS idx_reimb_month
                    ON reimbursements(month_key);
            """)
            logger.info(
                "reimbursements 半完成迁移已自愈：_new → reimbursements，"
                "索引已重建"
            )
            return

        # 此处 has_main == True，可以读 main_sql / 数 _new 行数
        main_sql = tables["reimbursements"]
        main_has_queued = ("'queued'" in main_sql) or ('"queued"' in main_sql)

        # ---- has_new 残留分支 ----
        if has_new:
            cur = await db.execute("SELECT COUNT(*) AS c FROM reimbursements_new")
            cnt_row = await cur.fetchone()
            new_count = int(cnt_row["c"]) if cnt_row else 0

            if main_has_queued and new_count == 0:
                # State C：主表正常 + _new 空残留 → 清理
                await db.execute("DROP TABLE reimbursements_new")
                logger.info("清理残留空表 reimbursements_new")
                return

            if new_count > 0:
                # State D：_new 非空 —— 无论主表 CHECK 状态都不自动处理
                #   - 若主表已含 queued：可能是上次清理失败遗留
                #   - 若主表未含 queued：可能是上次迁移 INSERT 之后、DROP 之前死亡
                # 两种情况都需要人工对比两表数据后决定如何收尾
                logger.warning(
                    "检测到残留非空 reimbursements_new（行数=%d）。"
                    "主表 CHECK 是否已含 queued: %s。"
                    "为避免数据丢失不自动处理，请人工对比两表后清理。"
                    "排查命令： sqlite3 data/bot.db "
                    "'SELECT COUNT(*) FROM reimbursements_new; "
                    "SELECT COUNT(*) FROM reimbursements;'",
                    new_count, main_has_queued,
                )
                return

            # 走到这里：has_new=True, new_count=0, main_has_queued=False
            # → 残留空 _new + 主表未迁移：DROP 空 _new，让后续 State E 走标准重建
            logger.warning(
                "检测到空残留 reimbursements_new 且主表 CHECK 未含 'queued'，"
                "DROP 空 _new 后走标准重建路径"
            )
            await db.execute("DROP TABLE reimbursements_new")
            # 继续 fall-through 到 State E
            has_new = False

        # ---- State A：主表正常 + 无 _new ----
        if main_has_queued:
            return

        # ---- State E：标准重建 ----
        # 整个重建过程包在 BEGIN IMMEDIATE / COMMIT 之内：SQLite 对包含 DDL
        # 的显式事务支持原子提交，任何一步失败都会整体回滚到 BEGIN 之前的状态。
        # 若进程在 COMMIT 前死亡，重启时 sqlite_master 仍只见旧主表（无 _new），
        # 重新走 State E；若进程在 COMMIT 之后死亡，进入 State A 直接 return。
        # 残留半完成态只有在 SQLite 引擎本身崩溃于 COMMIT 中间时才可能出现，
        # 那种极少数情况由 State B 兜底自愈。
        await db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE reimbursements_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                review_id     INTEGER NOT NULL UNIQUE,
                teacher_id    INTEGER NOT NULL,
                amount        INTEGER NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                week_key      TEXT NOT NULL,
                month_key     TEXT NOT NULL,
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                decided_at    TEXT,
                decided_by    INTEGER,
                reject_reason TEXT,
                notified_at   TEXT,
                FOREIGN KEY (review_id) REFERENCES teacher_reviews(id),
                CHECK (status IN ('pending','approved','rejected','cancelled','queued'))
            );
            INSERT INTO reimbursements_new
                (id, user_id, review_id, teacher_id, amount, status,
                 week_key, month_key, created_at, decided_at, decided_by,
                 reject_reason, notified_at)
            SELECT id, user_id, review_id, teacher_id, amount, status,
                   week_key, month_key, created_at, decided_at, decided_by,
                   reject_reason, notified_at FROM reimbursements;
            DROP TABLE reimbursements;
            ALTER TABLE reimbursements_new RENAME TO reimbursements;
            CREATE INDEX IF NOT EXISTS idx_reimb_user_week
                ON reimbursements(user_id, week_key);
            CREATE INDEX IF NOT EXISTS idx_reimb_status
                ON reimbursements(status);
            CREATE INDEX IF NOT EXISTS idx_reimb_month
                ON reimbursements(month_key);
            COMMIT;
        """)
        logger.info("reimbursements 表已扩展 CHECK 接受 'queued'")
    except Exception as e:
        logger.warning("reimbursements queued 状态迁移失败（不阻断启动）: %s", e)


async def _migrate_teacher_profile_columns(db: aiosqlite.Connection) -> None:
    """Phase 9.1：teachers 表添加 10 个老师档案字段（全部 NULLABLE）

    幂等：PRAGMA table_info 检测后再 ADD，重复执行安全。
    新字段都允许为 NULL，老数据不受影响；档案帖发布前由
    is_teacher_profile_complete 校验必填字段。
    """
    cur = await db.execute("PRAGMA table_info(teachers)")
    rows = await cur.fetchall()
    existing = {row["name"] for row in rows}

    additions: list[tuple[str, str]] = [
        ("age",              "INTEGER"),
        ("height_cm",        "INTEGER"),
        ("weight_kg",        "INTEGER"),
        ("bra_size",         "TEXT"),
        ("description",      "TEXT"),
        ("service_content",  "TEXT"),
        ("price_detail",     "TEXT"),
        ("taboos",           "TEXT"),
        ("contact_telegram", "TEXT"),
        ("photo_album",      "TEXT"),
    ]
    for col, type_def in additions:
        if col in existing:
            continue
        try:
            await db.execute(f"ALTER TABLE teachers ADD COLUMN {col} {type_def}")
        except Exception:
            # PRAGMA 与实际 schema 不一致 → 忽略 duplicate column
            pass


DEFAULT_PUBLISH_TEMPLATE_TEXT: str = (
    "📅 {date} 今日开课老师 {count} 位\n\n"
    "点击下方按钮查看详情。"
)

# 历史默认模板文本集合（用于检测「未被 admin 自定义」时自动更新到最新默认）
_LEGACY_DEFAULT_PUBLISH_TEMPLATES: tuple[str, ...] = (
    # v1 (含 {grouped_teachers} 重复列表) — 2026-05-17 被替换
    "📅 {date} 今日开课老师 {count} 位\n\n"
    "{grouped_teachers}\n\n"
    "点击下方按钮查看详情。",
)


async def _ensure_default_publish_template(db: aiosqlite.Connection) -> None:
    """若没有"默认且启用"的模板则插入；已存在且与旧默认完全一致 → 自动升级到新默认

    管理员手动改过的模板不会被覆盖（只匹配 verbatim 旧文本）。
    """
    try:
        cur = await db.execute(
            "SELECT id, template_text FROM publish_templates "
            "WHERE is_default = 1 AND is_active = 1 LIMIT 1"
        )
        row = await cur.fetchone()
        if row is None:
            await db.execute(
                """INSERT INTO publish_templates
                   (name, template_text, is_default, is_active)
                   VALUES (?, ?, 1, 1)""",
                ("默认模板", DEFAULT_PUBLISH_TEMPLATE_TEXT),
            )
            return
        # 已存在：若 verbatim 匹配某个历史默认 → 升级到新默认
        if row["template_text"] in _LEGACY_DEFAULT_PUBLISH_TEMPLATES:
            await db.execute(
                "UPDATE publish_templates SET template_text = ? WHERE id = ?",
                (DEFAULT_PUBLISH_TEMPLATE_TEXT, row["id"]),
            )
            logger.info(
                "默认发布模板已从历史版本升级到最新（id=%s）", row["id"],
            )
    except Exception:
        # init 阶段不能因为模板初始化失败而阻断 bot 启动
        pass


# ============ Admin CRUD ============

async def add_admin(user_id: int, username: str = None, is_super: int = 0) -> bool:
    """添加管理员，返回是否成功"""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO admins (user_id, username, is_super) VALUES (?, ?, ?)",
            (user_id, username, is_super),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def remove_admin(user_id: int) -> bool:
    """移除管理员"""
    db = await get_db()
    try:
        await db.execute("DELETE FROM admins WHERE user_id = ? AND is_super = 0", (user_id,))
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def get_admin(user_id: int) -> Optional[dict]:
    """获取管理员信息"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_all_admins() -> list[dict]:
    """获取所有管理员"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM admins ORDER BY is_super DESC, created_at")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def is_admin(user_id: int) -> bool:
    """检查是否为管理员"""
    admin = await get_admin(user_id)
    return admin is not None


async def is_super_admin(user_id: int) -> bool:
    """检查是否为超级管理员"""
    admin = await get_admin(user_id)
    return admin is not None and admin["is_super"] == 1


# ============ Teacher CRUD ============

async def add_teacher(data: dict) -> bool:
    """添加老师"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO teachers
            (user_id, username, display_name, region, price, tags, photo_file_id, button_url, button_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["user_id"],
                data["username"],
                data["display_name"],
                data["region"],
                data["price"],
                data["tags"],  # JSON string
                data.get("photo_file_id"),
                data["button_url"],
                data.get("button_text"),
            ),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def update_teacher(user_id: int, field: str, value) -> bool:
    """更新老师某个字段"""
    allowed_fields = {
        "username", "display_name", "region", "price",
        "tags", "photo_file_id", "button_url", "button_text", "is_active",
    }
    if field not in allowed_fields:
        return False
    db = await get_db()
    try:
        await db.execute(f"UPDATE teachers SET {field} = ? WHERE user_id = ?", (value, user_id))
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def remove_teacher(user_id: int) -> bool:
    """停用老师（软删除），保留历史签到记录"""
    db = await get_db()
    try:
        await db.execute("UPDATE teachers SET is_active = 0 WHERE user_id = ?", (user_id,))
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def get_teacher(user_id: int) -> Optional[dict]:
    """获取老师信息"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM teachers WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_all_teachers(
    active_only: bool = True, include_deleted: bool = False
) -> list[dict]:
    """获取所有老师

    active_only=True 仅返回启用（is_active=1）；include_deleted=False（默认）排除已软删除。
    管理端停用列表/档案列表用默认值即自动排除已删；恢复列表用 get_deleted_teachers()。
    """
    db = await get_db()
    try:
        where: list[str] = []
        if active_only:
            where.append("is_active = 1")
        if not include_deleted:
            where.append("is_deleted = 0")
        query = "SELECT * FROM teachers"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_teacher_by_name(display_name: str) -> Optional[dict]:
    """通过艺名精确查找老师"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM teachers WHERE display_name = ? AND is_active = 1 AND is_deleted = 0 COLLATE NOCASE",
            (display_name,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def search_teachers_by_keyword(keyword: str) -> list[dict]:
    """通过标签/地区/价格精确匹配老师列表"""
    db = await get_db()
    try:
        # 匹配 region、price，或 tags JSON 数组中包含该关键词
        cursor = await db.execute(
            """SELECT * FROM teachers
            WHERE is_active = 1 AND is_deleted = 0 AND (
                region = ? COLLATE NOCASE
                OR price = ? COLLATE NOCASE
                OR EXISTS (
                    SELECT 1 FROM json_each(tags) WHERE json_each.value = ? COLLATE NOCASE
                )
            )""",
            (keyword, keyword, keyword),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def search_teachers_smart_and(
    tokens: list[str],
) -> tuple[list[dict], list[str]]:
    """智能 AND 搜索（F4，v2 §2.4.2）

    规则:
        - 同类型 OR：多个标签 / 多个地区 / 多个价格之间用 OR
        - 跨类型 AND：标签条件、地区条件、价格条件之间用 AND
        - 类型自动识别：扫描所有 active 老师的 tags/region/price 集合，决定每个 token 属于哪些类型
        - 单个 token 可能同时属于多个类型（罕见，兜底处理）
        - 完全未匹配任何类型的 token 视为 unrecognized
        - 艺名不参与组合搜索（由调用方在更上一层做精确艺名匹配优先判断）

    Args:
        tokens: 用户输入拆分后的 token 列表（已 strip / 去重，大小写无关）

    Returns:
        (teachers, unrecognized):
            teachers: 命中老师列表（is_active=1，按 created_at 排序）
            unrecognized: 未识别为任何类型的原始 token，用于给用户提示

    特殊情形:
        - tokens 为空：返回 ([], [])
        - 全部 unrecognized：返回 ([], unrecognized)
    """
    if not tokens:
        return [], []

    db = await get_db()
    try:
        # 1. 加载所有 active 老师的 region / price / tags，构造小写集合用于类型识别
        cursor = await db.execute(
            "SELECT region, price, tags FROM teachers WHERE is_active = 1 AND is_deleted = 0"
        )
        rows = await cursor.fetchall()

        regions: set[str] = set()
        prices: set[str] = set()
        tags_set: set[str] = set()
        for row in rows:
            if row["region"]:
                regions.add(row["region"].lower())
            if row["price"]:
                prices.add(row["price"].lower())
            try:
                for t in json.loads(row["tags"] or "[]"):
                    tags_set.add(str(t).lower())
            except (json.JSONDecodeError, TypeError):
                continue

        # 2. token 类型识别（一个 token 可命中多个类型）
        token_tags: list[str] = []
        token_regions: list[str] = []
        token_prices: list[str] = []
        unrecognized: list[str] = []
        for raw in tokens:
            tl = raw.lower()
            matched = False
            if tl in tags_set:
                token_tags.append(tl)
                matched = True
            if tl in regions:
                token_regions.append(tl)
                matched = True
            if tl in prices:
                token_prices.append(tl)
                matched = True
            if not matched:
                unrecognized.append(raw)

        # 没有任何可识别 token，无法构造查询
        if not (token_tags or token_regions or token_prices):
            return [], unrecognized

        # 3. 构造 SQL：同类型 OR、跨类型 AND
        conditions: list[str] = []
        params: list = []

        if token_tags:
            sub = []
            for t in token_tags:
                sub.append(
                    "EXISTS (SELECT 1 FROM json_each(tags) "
                    "WHERE LOWER(json_each.value) = ?)"
                )
                params.append(t)
            conditions.append("(" + " OR ".join(sub) + ")")

        if token_regions:
            sub = []
            for r in token_regions:
                sub.append("LOWER(region) = ?")
                params.append(r)
            conditions.append("(" + " OR ".join(sub) + ")")

        if token_prices:
            sub = []
            for p in token_prices:
                sub.append("LOWER(price) = ?")
                params.append(p)
            conditions.append("(" + " OR ".join(sub) + ")")

        query = (
            "SELECT * FROM teachers WHERE is_active = 1 AND is_deleted = 0 AND "
            + " AND ".join(conditions)
            + " ORDER BY created_at"
        )
        cursor = await db.execute(query, params)
        result_rows = await cursor.fetchall()
        return [dict(r) for r in result_rows], unrecognized
    finally:
        await db.close()


# ============ Checkin CRUD ============

async def checkin_teacher(teacher_id: int, date_str: str) -> bool:
    """老师签到"""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO checkins (teacher_id, checkin_date) VALUES (?, ?)",
            (teacher_id, date_str),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def is_checked_in(teacher_id: int, date_str: str) -> bool:
    """检查老师是否已签到"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM checkins WHERE teacher_id = ? AND checkin_date = ?",
            (teacher_id, date_str),
        )
        return await cursor.fetchone() is not None
    finally:
        await db.close()


async def get_checked_in_teachers(date_str: str) -> list[dict]:
    """获取当日所有已签到老师"""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT t.* FROM teachers t
            INNER JOIN checkins c ON t.user_id = c.teacher_id
            WHERE c.checkin_date = ? AND t.is_active = 1 AND t.is_deleted = 0
            ORDER BY c.created_at""",
            (date_str,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_unchecked_teachers(date_str: str) -> list[dict]:
    """获取指定日期未签到的启用老师"""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT t.* FROM teachers t
            WHERE t.is_active = 1 AND t.is_deleted = 0
              AND NOT EXISTS (
                  SELECT 1 FROM checkins c
                  WHERE c.teacher_id = t.user_id AND c.checkin_date = ?
              )
            ORDER BY t.created_at""",
            (date_str,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_teacher_counts() -> dict:
    """获取老师数量统计"""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) AS inactive
            FROM teachers WHERE is_deleted = 0"""
        )
        row = await cursor.fetchone()
        return {
            "total": row["total"] or 0,
            "active": row["active"] or 0,
            "inactive": row["inactive"] or 0,
        }
    finally:
        await db.close()


async def get_checkin_stats(date_str: str) -> dict:
    """获取指定日期签到统计"""
    checked_in = await get_checked_in_teachers(date_str)
    unchecked = await get_unchecked_teachers(date_str)
    teacher_counts = await get_teacher_counts()
    active_total = teacher_counts["active"]
    checked_count = len(checked_in)
    rate = round((checked_count / active_total) * 100, 1) if active_total else 0
    return {
        "date": date_str,
        "active_total": active_total,
        "checked_count": checked_count,
        "unchecked_count": len(unchecked),
        "rate": rate,
        "checked_in": checked_in,
        "unchecked": unchecked,
    }


async def enable_teacher(user_id: int) -> bool:
    """启用老师"""
    return await update_teacher(user_id, "is_active", 1)


async def soft_delete_teacher(user_id: int) -> bool:
    """软删除老师：从所有用户端 + 管理端列表彻底隐藏，数据保留，可由超管恢复。

    与 is_active（停用）正交：删除后不论原来启用/停用，一律隐藏。
    """
    db = await get_db()
    try:
        await db.execute("UPDATE teachers SET is_deleted = 1 WHERE user_id = ?", (user_id,))
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def restore_teacher(user_id: int) -> bool:
    """恢复软删除的老师（超管）。恢复后回到删除前的 is_active 态（原为停用的仍需再启用）。"""
    db = await get_db()
    try:
        await db.execute("UPDATE teachers SET is_deleted = 0 WHERE user_id = ?", (user_id,))
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def get_deleted_teachers() -> list[dict]:
    """已软删除的老师列表（供"恢复老师"使用）。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM teachers WHERE is_deleted = 1 ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


# ============ Config CRUD ============

async def set_config(key: str, value: str):
    """设置配置项"""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def get_config(key: str) -> Optional[str]:
    """获取配置项"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else None
    finally:
        await db.close()


# ============ Sent Messages ============

async def save_sent_message(chat_id: int, message_id: int, sent_date: str):
    """保存已发送消息记录"""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO sent_messages (chat_id, message_id, sent_date) VALUES (?, ?, ?)",
            (chat_id, message_id, sent_date),
        )
        await db.commit()
    finally:
        await db.close()


async def get_sent_messages(sent_date: str) -> list[dict]:
    """获取某日发送的消息"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM sent_messages WHERE sent_date = ?", (sent_date,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def delete_sent_messages(sent_date: str):
    """删除某日的消息记录"""
    db = await get_db()
    try:
        await db.execute("DELETE FROM sent_messages WHERE sent_date = ?", (sent_date,))
        await db.commit()
    finally:
        await db.close()


# ============ Users CRUD ============

async def upsert_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> None:
    """插入或更新用户记录，同时刷新 last_active_at

    用于:
    - 用户首次私聊 bot 或发送任意消息
    - 群组里点收藏按钮时（此时 last_started_bot 保持 0，等 deep link 激活）

    不会改动 last_started_bot 和 notify_enabled 字段。
    """
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO users (user_id, username, first_name, last_active_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                   username = excluded.username,
                   first_name = excluded.first_name,
                   last_active_at = CURRENT_TIMESTAMP""",
            (user_id, username, first_name),
        )
        await db.commit()
    finally:
        await db.close()


async def get_user(user_id: int) -> Optional[dict]:
    """获取用户信息"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def mark_user_started(user_id: int) -> bool:
    """标记用户已和 bot 建立私聊（last_started_bot=1）

    在 /start deep link (?start=activate) 或首次私聊时调用。
    用户记录不存在时返回 False，调用方需先调用 upsert_user。
    """
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET last_started_bot = 1, last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def mark_user_unreachable(user_id: int) -> bool:
    """标记用户无法接收推送（被屏蔽或 chat 不存在）

    Step 4 通知任务捕获 TelegramForbiddenError / chat_not_found 时调用。
    """
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET last_started_bot = 0 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def set_user_notify_enabled(user_id: int, enabled: bool) -> bool:
    """设置用户级通知开关（预留，Step 4 使用）"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET notify_enabled = ? WHERE user_id = ?",
            (1 if enabled else 0, user_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def get_user_onboarding_seen(user_id: int) -> bool:
    """Phase 7.1：用户是否已看过新手引导

    返回规则：
        - 用户存在且 onboarding_seen=1 → True
        - 用户存在且 onboarding_seen=0 / NULL → False
        - 用户不存在 → False（首次进入，应展示引导）
        - 字段不存在 / 查询异常 → True（兼容降级，避免阻塞用户）
    """
    try:
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT onboarding_seen FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = await cur.fetchone()
            if not row:
                return False
            val = row["onboarding_seen"]
            return bool(val) if val is not None else False
        finally:
            await db.close()
    except Exception as e:
        logger.warning(
            "get_user_onboarding_seen 异常（降级为已看过）user=%s: %s", user_id, e,
        )
        return True


async def mark_user_onboarding_seen(user_id: int) -> None:
    """Phase 7.1：标记用户已看过新手引导

    字段不存在或更新异常仅记录 warning，不抛异常、不阻断主流程。
    """
    try:
        db = await get_db()
        try:
            await db.execute(
                "UPDATE users SET onboarding_seen = 1 WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception as e:
        logger.warning(
            "mark_user_onboarding_seen 失败 user=%s: %s", user_id, e,
        )


async def count_users() -> int:
    """用户总数"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) AS n FROM users")
        row = await cursor.fetchone()
        return row["n"] if row else 0
    finally:
        await db.close()


# ============ Favorites CRUD ============

async def add_favorite(user_id: int, teacher_id: int) -> bool:
    """添加收藏，重复时静默忽略（保持幂等）

    返回 True 表示本次实际插入了记录，False 表示已存在或失败。
    """
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO favorites (user_id, teacher_id) VALUES (?, ?)",
            (user_id, teacher_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def remove_favorite(user_id: int, teacher_id: int) -> bool:
    """取消收藏，返回是否实际删除了一行"""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM favorites WHERE user_id = ? AND teacher_id = ?",
            (user_id, teacher_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def is_favorited(user_id: int, teacher_id: int) -> bool:
    """是否已收藏"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND teacher_id = ?",
            (user_id, teacher_id),
        )
        return await cursor.fetchone() is not None
    finally:
        await db.close()


async def toggle_favorite(user_id: int, teacher_id: int) -> bool:
    """原子切换收藏状态

    返回值:
        True  = 切换后处于"已收藏"（本次是"添加"）
        False = 切换后处于"未收藏"（本次是"取消"）

    在同一个数据库连接里完成"查 → 写 → commit"，避免双击竞态。
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND teacher_id = ?",
            (user_id, teacher_id),
        )
        existed = await cursor.fetchone() is not None
        if existed:
            await db.execute(
                "DELETE FROM favorites WHERE user_id = ? AND teacher_id = ?",
                (user_id, teacher_id),
            )
        else:
            await db.execute(
                "INSERT INTO favorites (user_id, teacher_id) VALUES (?, ?)",
                (user_id, teacher_id),
            )
        await db.commit()
        return not existed
    finally:
        await db.close()


async def list_user_favorites(user_id: int, active_only: bool = True) -> list[dict]:
    """获取用户的收藏列表（含老师详情）

    Args:
        user_id: 用户 ID
        active_only: 仅返回 is_active=1 的老师，停用老师过滤掉

    每条记录包含 teachers 表全部字段，外加 favorited_at 字段。
    按收藏时间倒序（最新收藏在前）。
    """
    db = await get_db()
    try:
        query = (
            """SELECT t.*, f.created_at AS favorited_at
               FROM favorites f
               INNER JOIN teachers t ON f.teacher_id = t.user_id
               WHERE f.user_id = ? AND t.is_deleted = 0"""
        )
        if active_only:
            query += " AND t.is_active = 1"
        query += " ORDER BY f.created_at DESC"
        cursor = await db.execute(query, (user_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def count_teacher_favoriters(teacher_id: int) -> int:
    """该老师被多少用户收藏（运营数据，不暴露给老师本人）"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) AS n FROM favorites WHERE teacher_id = ?",
            (teacher_id,),
        )
        row = await cursor.fetchone()
        return row["n"] if row else 0
    finally:
        await db.close()


async def list_user_favorites_signed_in(
    user_id: int, date_str: str
) -> list[dict]:
    """用户的"收藏 ∩ 当天已签到"老师（用于 C1 "💝 收藏开课"子菜单）

    仅返回 is_active=1 的老师，按签到时间排序。
    LEFT JOIN teacher_daily_status：返回 daily_status 字段供 handler 过滤 full。
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT t.*, s.status AS daily_status
               FROM favorites f
               INNER JOIN teachers t ON f.teacher_id = t.user_id
               INNER JOIN checkins c ON t.user_id = c.teacher_id
               LEFT JOIN teacher_daily_status s
                  ON s.teacher_id = t.user_id AND s.status_date = ?
               WHERE f.user_id = ?
                 AND c.checkin_date = ?
                 AND t.is_active = 1
                 AND t.is_deleted = 0
               ORDER BY c.created_at""",
            (date_str, user_id, date_str),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_notification_targets(date_str: str) -> list[dict]:
    """F2 通知聚合：返回当天需要被推送的用户清单

    对每个有效收藏者（last_started_bot=1 且 notify_enabled=1），
    汇总其当天"收藏 ∩ 已签到"的老师列表。仅返回 teachers 非空的目标。

    返回结构:
        [
            {
                "user_id": int,
                "first_name": str | None,
                "username": str | None,
                "teachers": [
                    {
                        "user_id": int,
                        "display_name": str,
                        "button_url": str,
                        "button_text": str | None,
                    },
                    ...
                ],
            },
            ...
        ]
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT
                   u.user_id AS user_id,
                   u.first_name AS first_name,
                   u.username AS username,
                   t.user_id AS teacher_id,
                   t.display_name AS display_name,
                   t.button_url AS button_url,
                   t.button_text AS button_text
               FROM users u
               INNER JOIN favorites f ON u.user_id = f.user_id
               INNER JOIN teachers t ON f.teacher_id = t.user_id
               INNER JOIN checkins c ON t.user_id = c.teacher_id
               WHERE u.last_started_bot = 1
                 AND u.notify_enabled = 1
                 AND c.checkin_date = ?
                 AND t.is_active = 1
                 AND t.is_deleted = 0
               ORDER BY u.user_id, c.created_at""",
            (date_str,),
        )
        rows = await cursor.fetchall()
        result: dict[int, dict] = {}
        for row in rows:
            uid = row["user_id"]
            if uid not in result:
                result[uid] = {
                    "user_id": uid,
                    "first_name": row["first_name"],
                    "username": row["username"],
                    "teachers": [],
                }
            result[uid]["teachers"].append({
                "user_id": row["teacher_id"],
                "display_name": row["display_name"],
                "button_url": row["button_url"],
                "button_text": row["button_text"],
            })
        return list(result.values())
    finally:
        await db.close()


# ============ Teacher Edit Requests CRUD ============

# 老师可自助修改的字段白名单（v2 §2.3.2）
# button_url 锁定，仅管理员可改（防恶意引流）
TEACHER_EDITABLE_FIELDS: set[str] = {
    "display_name",
    "region",
    "price",
    "tags",
    "photo_file_id",
    "button_text",
}


async def create_edit_request(
    teacher_id: int,
    field_name: str,
    old_value: Optional[str],
    new_value: str,
) -> Optional[int]:
    """创建老师修改请求，返回 request_id

    field_name 必须在 TEACHER_EDITABLE_FIELDS 白名单内，否则返回 None。
    本函数仅记录请求，不更新 teachers 表；UPDATE teachers 由调用方在同一
    处理流程里另行执行（v2 §2.3.3）。
    """
    if field_name not in TEACHER_EDITABLE_FIELDS:
        return None
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO teacher_edit_requests
               (teacher_id, field_name, old_value, new_value, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (teacher_id, field_name, old_value, new_value),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def count_pending_edits() -> int:
    """待审核修改数（管理员主面板 [📝 待审核 (N)] 用）"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) AS n FROM teacher_edit_requests WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        return row["n"] if row else 0
    finally:
        await db.close()


async def list_pending_edits(limit: int = 50, offset: int = 0) -> list[dict]:
    """待审核修改列表，按修改时间倒序，JOIN 老师 display_name 便于展示"""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT r.*, t.display_name AS teacher_display_name
               FROM teacher_edit_requests r
               LEFT JOIN teachers t ON r.teacher_id = t.user_id
               WHERE r.status = 'pending'
               ORDER BY r.created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_edit_request(request_id: int) -> Optional[dict]:
    """获取单条修改请求"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM teacher_edit_requests WHERE id = ?",
            (request_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def approve_edit_request(request_id: int, reviewer_id: int) -> bool:
    """通过修改请求（v2 §2.3.3 + §2.3.3a 图片字段例外）

    文字字段（5 个）approve:
        - 不动 teachers 表（已经是新值，老师提交时立即更新）
        - 仅 UPDATE teacher_edit_requests.status='approved'

    图片字段（photo_file_id）approve:
        - UPDATE teachers SET photo_file_id = new_value（同连接内事务）
        - UPDATE teacher_edit_requests.status='approved'

    若 status 已经不是 pending，返回 False（不重复审核）。
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT teacher_id, field_name, new_value, status FROM teacher_edit_requests WHERE id = ?",
            (request_id,),
        )
        req = await cursor.fetchone()
        if not req or req["status"] != "pending":
            return False

        # 图片字段例外：approve 时需要把新 file_id 写入 teachers
        if req["field_name"] == "photo_file_id":
            await db.execute(
                "UPDATE teachers SET photo_file_id = ? WHERE user_id = ?",
                (req["new_value"], req["teacher_id"]),
            )

        await db.execute(
            """UPDATE teacher_edit_requests
               SET status = 'approved', reviewer_id = ?, reviewed_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'pending'""",
            (reviewer_id, request_id),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def reject_edit_request(
    request_id: int,
    reviewer_id: int,
    reason: Optional[str] = None,
) -> bool:
    """驳回修改请求（v2 §2.3.3 + §2.3.3a 图片字段例外）

    文字字段（5 个）reject:
        - UPDATE teachers SET <field> = old_value（回滚到修改前）
        - UPDATE teacher_edit_requests.status='rejected'

    图片字段（photo_file_id）reject:
        - 不动 teachers（teachers.photo_file_id 在 pending 期间从未变成 new_value，本来就是旧图）
        - 仅 UPDATE teacher_edit_requests.status='rejected'

    流程:
        1. 取请求详情（必须是 pending）
        2. 校验 field_name 在白名单（防 SQL 注入，因 UPDATE 用 f-string 拼字段名）
        3. 文字字段执行 UPDATE teachers 回滚；图片字段跳过此步
        4. UPDATE teacher_edit_requests SET status='rejected', ...
        5. commit
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT teacher_id, field_name, old_value, status FROM teacher_edit_requests WHERE id = ?",
            (request_id,),
        )
        req = await cursor.fetchone()
        if not req or req["status"] != "pending":
            return False
        if req["field_name"] not in TEACHER_EDITABLE_FIELDS:
            # 异常：数据库里出现了白名单外的 field_name（理论上不会发生）
            return False

        # 图片字段例外：reject 时不需要回滚 teachers（teachers 一直是 old_value）
        if req["field_name"] != "photo_file_id":
            await db.execute(
                f"UPDATE teachers SET {req['field_name']} = ? WHERE user_id = ?",
                (req["old_value"], req["teacher_id"]),
            )

        await db.execute(
            """UPDATE teacher_edit_requests
               SET status = 'rejected', reviewer_id = ?, reject_reason = ?,
                   reviewed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (reviewer_id, reason, request_id),
        )
        await db.commit()
        return True
    finally:
        await db.close()


# ============ 事件 / 审计日志 (Phase 1) ============


def _to_json_text(value) -> Optional[str]:
    """把 dict / list / 其他对象序列化为 JSON 字符串；str 直接返回；None 返回 None"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


async def log_user_event(
    user_id: int,
    event_type: str,
    payload=None,
) -> None:
    """记录用户侧事件（C1 用户主面板、搜索、收藏、查看等）

    payload 可为 dict / list / str / None；非字符串会被 JSON 序列化。
    本函数对调用方完全静默：内部异常不外抛，避免埋点失败连带核心流程出错。
    """
    payload_str = _to_json_text(payload)
    try:
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO user_events (user_id, event_type, payload) VALUES (?, ?, ?)",
                (user_id, event_type, payload_str),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception:
        # 埋点失败不影响业务，吞掉异常
        pass


async def log_admin_audit(
    admin_id: int,
    action: str,
    target_type: Optional[str] = None,
    target_id=None,
    detail=None,
) -> None:
    """记录管理员操作日志

    target_id 接受任意类型，内部统一转字符串；
    detail 接受 dict / list / str / None。
    内部异常被吞掉，避免审计失败导致业务异常。
    """
    target_id_str = None if target_id is None else str(target_id)
    detail_str = _to_json_text(detail)
    try:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO admin_audit_logs
                   (admin_id, action, target_type, target_id, detail)
                   VALUES (?, ?, ?, ?, ?)""",
                (admin_id, action, target_type, target_id_str, detail_str),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception:
        pass


async def list_recent_target_viewers(
    target_type: str,
    target_id,
    *,
    action: str,
    since_seconds: int = 300,
    exclude_admin_id: Optional[int] = None,
    limit: int = 5,
) -> list[dict]:
    """查近 N 秒内有谁查看（action='*_view'）某条 target（UX-7.4）。

    用于"详情页顶部提示：@adminX 几分钟前查看过此条"——避免多管理员并发审核同一条。

    Args:
        target_type: admin_audit_logs.target_type 字段（如 "edit_request" /
            "teacher_review" / "reimbursement"）
        target_id:   admin_audit_logs.target_id（内部转 str 对比）
        action:      仅 *_view 类 action 计入查看（如 "rreview_view" / "review_view"）
        since_seconds: 时间窗口（秒）；默认 5 分钟
        exclude_admin_id: 排除"自己"（避免显示"我刚才看过自己"）
        limit: 最多返回 N 条；按 created_at DESC，每个 admin 只取最新一条

    Returns:
        list[dict] 每条含 admin_id / created_at；为空表示近期无其他人查看。
    """
    target_id_str = str(target_id)
    db = await get_db()
    try:
        # 子查询：先按 admin_id 取每个的最新一条；外层按时间排序限制 limit
        sql = (
            "SELECT admin_id, MAX(created_at) AS created_at "
            "FROM admin_audit_logs "
            "WHERE action = ? AND target_type = ? AND target_id = ? "
            "AND admin_id != 0 "
            "AND created_at >= datetime('now', ?) "
        )
        args: list = [action, target_type, target_id_str, f"-{int(since_seconds)} seconds"]
        if exclude_admin_id is not None:
            sql += "AND admin_id != ? "
            args.append(int(exclude_admin_id))
        sql += "GROUP BY admin_id ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        cur = await db.execute(sql, args)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_dashboard_metrics(today_str: str, since_str: str) -> dict:
    """聚合管理员看板所需统计

    Args:
        today_str: 今日日期 'YYYY-MM-DD'
        since_str: N 天前的起始日期（含），用于 7 日窗口指标
    """
    db = await get_db()
    try:
        # ---- 用户 ----
        cur = await db.execute("SELECT COUNT(*) AS n FROM users")
        total_users = (await cur.fetchone())["n"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM users "
            "WHERE last_started_bot = 1 AND notify_enabled = 1"
        )
        reachable_users = (await cur.fetchone())["n"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE DATE(created_at) = ?",
            (today_str,),
        )
        new_users_today = (await cur.fetchone())["n"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE DATE(created_at) >= ?",
            (since_str,),
        )
        new_users_range = (await cur.fetchone())["n"] or 0

        # ---- 活跃（来自 user_events distinct user_id）----
        cur = await db.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM user_events "
            "WHERE DATE(created_at) = ?",
            (today_str,),
        )
        active_today = (await cur.fetchone())["n"] or 0

        cur = await db.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM user_events "
            "WHERE DATE(created_at) >= ?",
            (since_str,),
        )
        active_range = (await cur.fetchone())["n"] or 0

        # ---- 老师 ----
        cur = await db.execute(
            "SELECT "
            "SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active, "
            "SUM(CASE WHEN is_active=0 THEN 1 ELSE 0 END) AS inactive "
            "FROM teachers WHERE is_deleted = 0"
        )
        row = await cur.fetchone()
        active_teachers = (row["active"] if row else 0) or 0
        inactive_teachers = (row["inactive"] if row else 0) or 0

        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM checkins WHERE checkin_date = ?",
            (today_str,),
        )
        checkins_today = (await cur.fetchone())["n"] or 0

        # ---- 收藏 ----
        cur = await db.execute("SELECT COUNT(*) AS n FROM favorites")
        total_favorites = (await cur.fetchone())["n"] or 0

        # ---- 今日用户行为（按事件类型聚合）----
        cur = await db.execute(
            "SELECT event_type, COUNT(*) AS n FROM user_events "
            "WHERE DATE(created_at) = ? GROUP BY event_type",
            (today_str,),
        )
        events_rows = await cur.fetchall()
        events_today = {r["event_type"]: r["n"] for r in events_rows}

        # ---- 运营 ----
        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM teacher_edit_requests WHERE status = 'pending'"
        )
        pending_reviews = (await cur.fetchone())["n"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM sent_messages WHERE sent_date = ?",
            (today_str,),
        )
        publishes_today = (await cur.fetchone())["n"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM admin_audit_logs WHERE DATE(created_at) = ?",
            (today_str,),
        )
        audits_today = (await cur.fetchone())["n"] or 0

        return {
            "total_users": total_users,
            "reachable_users": reachable_users,
            "new_users_today": new_users_today,
            "new_users_range": new_users_range,
            "active_today": active_today,
            "active_range": active_range,
            "active_teachers": active_teachers,
            "inactive_teachers": inactive_teachers,
            "checkins_today": checkins_today,
            "total_favorites": total_favorites,
            "events_today": events_today,
            "pending_reviews": pending_reviews,
            "publishes_today": publishes_today,
            "audits_today": audits_today,
        }
    finally:
        await db.close()


async def save_teacher_draft(
    admin_id: int,
    fsm_state: str,
    data: dict,
    *,
    step_label: Optional[str] = None,
) -> bool:
    """保存 admin 当前 teacher_profile 录入草稿（UX-9.3，upsert）。

    Args:
        admin_id:  超管 / 管理员 user_id（PK，同 admin 一次最多 1 个草稿）
        fsm_state: 当前 FSM state 字符串（如 "TeacherProfileAddStates:waiting_age"）
        data:      state.get_data() 的字典，序列化为 JSON 存入
        step_label: 用户友好的 step 描述（如"已填到 Step 6 / 服务内容"）

    任何异常都被吞 + logger.warning 后返回 False，保证 caller 主流程不被破坏。
    """
    try:
        blob = json.dumps(data, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning("save_teacher_draft JSON 序列化失败 admin=%s: %s", admin_id, e)
        return False
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO teacher_draft_states
                  (admin_id, fsm_state, json_blob, step_label, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(admin_id) DO UPDATE SET
                  fsm_state  = excluded.fsm_state,
                  json_blob  = excluded.json_blob,
                  step_label = excluded.step_label,
                  updated_at = CURRENT_TIMESTAMP""",
            (int(admin_id), str(fsm_state), blob, step_label),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.warning("save_teacher_draft 写入失败 admin=%s: %s", admin_id, e)
        return False
    finally:
        await db.close()


async def load_teacher_draft(admin_id: int) -> Optional[dict]:
    """加载 admin 的 teacher_profile 草稿（UX-9.3）。

    Returns:
        含 admin_id / fsm_state / data (dict) / step_label / updated_at 的字典；
        无草稿 / DB 异常 / JSON 解码失败 → None（caller 按"无草稿"处理）。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM teacher_draft_states WHERE admin_id = ?",
            (int(admin_id),),
        )
        row = await cur.fetchone()
        if not row:
            return None
        row_dict = dict(row)
        try:
            row_dict["data"] = json.loads(row_dict.get("json_blob") or "{}")
        except json.JSONDecodeError as e:
            logger.warning(
                "load_teacher_draft JSON 解码失败 admin=%s: %s", admin_id, e,
            )
            return None
        return row_dict
    except Exception as e:
        logger.warning("load_teacher_draft 查询失败 admin=%s: %s", admin_id, e)
        return None
    finally:
        await db.close()


async def clear_teacher_draft(admin_id: int) -> bool:
    """删除 admin 的 teacher_profile 草稿（UX-9.3）。

    无草稿存在时返回 False（无操作）；删除成功返回 True。
    DB 异常时 logger.warning + 返回 False，不向上抛。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM teacher_draft_states WHERE admin_id = ?",
            (int(admin_id),),
        )
        await db.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.warning("clear_teacher_draft 删除失败 admin=%s: %s", admin_id, e)
        return False
    finally:
        await db.close()


# ============ 群组快捷词 (UX-9.1) ============


def _quick_entry_row_to_dict(row) -> dict:
    """统一把 quick_entry_keywords 行（aiosqlite.Row）转成可序列化 dict。

    buttons_json 字段会在此处解码：解码失败 → 视为空 list（前端降级到无按钮）。
    """
    if row is None:
        return None  # type: ignore[return-value]
    raw_btns = row["buttons_json"] or "[]"
    try:
        buttons = json.loads(raw_btns)
        if not isinstance(buttons, list):
            buttons = []
    except (json.JSONDecodeError, TypeError):
        buttons = []
    return {
        "id": row["id"],
        "trigger": row["trigger"],
        "banner": row["banner"] or "",
        "body": row["body"] or "",
        "buttons": buttons,
        "buttons_json": raw_btns,
        "enabled": int(row["enabled"] or 0),
        "hit_count": int(row["hit_count"] or 0),
        "seeded": int(row["seeded"] or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_quick_entry_keywords(
    *, enabled_only: bool = False, limit: int = 200,
) -> list[dict]:
    """列出群组快捷词（按 id 升序）；enabled_only=True 只取启用项。"""
    db = await get_db()
    try:
        sql = "SELECT * FROM quick_entry_keywords"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id ASC LIMIT ?"
        cur = await db.execute(sql, (int(limit),))
        rows = await cur.fetchall()
        return [_quick_entry_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_quick_entry_keywords 失败: %s", e)
        return []
    finally:
        await db.close()


async def get_quick_entry_keyword(kid: int) -> Optional[dict]:
    """按 id 取一行；不存在 → None。"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM quick_entry_keywords WHERE id = ?", (int(kid),),
        )
        row = await cur.fetchone()
        return _quick_entry_row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("get_quick_entry_keyword 失败 id=%s: %s", kid, e)
        return None
    finally:
        await db.close()


async def get_quick_entry_by_trigger(trigger: str) -> Optional[dict]:
    """按 trigger 取一行（大小写不敏感）；不存在 / 异常 → None。

    handler 端用本函数做关键词命中查询；trigger COLLATE NOCASE 走 UNIQUE 索引。
    """
    if not trigger:
        return None
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM quick_entry_keywords WHERE trigger = ? COLLATE NOCASE",
            (trigger,),
        )
        row = await cur.fetchone()
        return _quick_entry_row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("get_quick_entry_by_trigger 失败 trigger=%r: %s", trigger, e)
        return None
    finally:
        await db.close()


async def create_quick_entry_keyword(
    *,
    trigger: str,
    banner: str,
    body: str,
    buttons: list,
    enabled: bool = True,
) -> Optional[int]:
    """新增一条快捷词；trigger 冲突 → 返回 None。"""
    trigger = (trigger or "").strip()
    if not trigger:
        return None
    db = await get_db()
    try:
        cur = await db.execute(
            """
            INSERT INTO quick_entry_keywords
                (trigger, banner, body, buttons_json, enabled, seeded)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                trigger,
                banner or "",
                body or "",
                json.dumps(buttons or [], ensure_ascii=False),
                1 if enabled else 0,
            ),
        )
        await db.commit()
        return cur.lastrowid
    except aiosqlite.IntegrityError:
        return None
    except Exception as e:
        logger.warning("create_quick_entry_keyword 失败 trigger=%r: %s", trigger, e)
        return None
    finally:
        await db.close()


async def update_quick_entry_keyword(
    kid: int,
    *,
    trigger: Optional[str] = None,
    banner: Optional[str] = None,
    body: Optional[str] = None,
    buttons: Optional[list] = None,
    enabled: Optional[bool] = None,
) -> bool:
    """部分更新；trigger 冲突 → 返回 False。"""
    sets: list[str] = []
    args: list = []
    if trigger is not None:
        trigger = trigger.strip()
        if not trigger:
            return False
        sets.append("trigger = ?")
        args.append(trigger)
    if banner is not None:
        sets.append("banner = ?")
        args.append(banner)
    if body is not None:
        sets.append("body = ?")
        args.append(body)
    if buttons is not None:
        sets.append("buttons_json = ?")
        args.append(json.dumps(buttons, ensure_ascii=False))
    if enabled is not None:
        sets.append("enabled = ?")
        args.append(1 if enabled else 0)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    sql = f"UPDATE quick_entry_keywords SET {', '.join(sets)} WHERE id = ?"
    args.append(int(kid))
    db = await get_db()
    try:
        cur = await db.execute(sql, tuple(args))
        await db.commit()
        return cur.rowcount > 0
    except aiosqlite.IntegrityError:
        return False
    except Exception as e:
        logger.warning("update_quick_entry_keyword 失败 id=%s: %s", kid, e)
        return False
    finally:
        await db.close()


async def delete_quick_entry_keyword(kid: int) -> bool:
    """物理删除一行（含 seeded）；不存在 → False。"""
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM quick_entry_keywords WHERE id = ?", (int(kid),),
        )
        await db.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.warning("delete_quick_entry_keyword 失败 id=%s: %s", kid, e)
        return False
    finally:
        await db.close()


async def toggle_quick_entry_enabled(kid: int) -> Optional[bool]:
    """切换启用状态；返回切换后的状态（True=enabled / False=disabled），
    不存在 → None。"""
    db = await get_db()
    try:
        await db.execute(
            """UPDATE quick_entry_keywords
               SET enabled = 1 - enabled,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (int(kid),),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT enabled FROM quick_entry_keywords WHERE id = ?", (int(kid),),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return bool(row["enabled"])
    except Exception as e:
        logger.warning("toggle_quick_entry_enabled 失败 id=%s: %s", kid, e)
        return None
    finally:
        await db.close()


async def increment_quick_entry_hit_count(kid: int) -> None:
    """命中计数 +1；异常静默（埋点级别，不阻断业务）。"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE quick_entry_keywords SET hit_count = hit_count + 1 WHERE id = ?",
            (int(kid),),
        )
        await db.commit()
    except Exception as e:
        logger.debug("increment_quick_entry_hit_count 失败 id=%s: %s", kid, e)
    finally:
        await db.close()


async def list_recent_admin_audits(limit: int = 20) -> list[dict]:
    """最近 N 条管理员操作日志（按 id 倒序，新的在前）

    返回结构每行额外带 admin_username 字段（JOIN admins 表，可能为空字符串）。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT a.*, COALESCE(adm.username, '') AS admin_username
               FROM admin_audit_logs a
               LEFT JOIN admins adm ON a.admin_id = adm.user_id
               ORDER BY a.id DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def list_admin_audits_paged(
    *,
    offset: int = 0,
    limit: int = 10,
    action: Optional[str] = None,
) -> list[dict]:
    """分页 + 按 action 过滤的管理员操作日志（UX-9.6）。

    与 list_recent_admin_audits 一致：JOIN admins 拿 admin_username；
    按 id DESC（最新在前）排序。

    action=None / "" 视为不过滤。
    """
    db = await get_db()
    try:
        sql_parts = [
            "SELECT a.*, COALESCE(adm.username, '') AS admin_username",
            "FROM admin_audit_logs a",
            "LEFT JOIN admins adm ON a.admin_id = adm.user_id",
        ]
        args: list = []
        if action:
            sql_parts.append("WHERE a.action = ?")
            args.append(str(action))
        sql_parts.append("ORDER BY a.id DESC LIMIT ? OFFSET ?")
        args.append(int(limit))
        args.append(int(offset))
        cur = await db.execute(" ".join(sql_parts), args)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def count_admin_audits(
    *,
    action: Optional[str] = None,
) -> int:
    """统计管理员操作日志总数（按 action 过滤可选）（UX-9.6）。"""
    db = await get_db()
    try:
        if action:
            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM admin_audit_logs WHERE action = ?",
                (str(action),),
            )
        else:
            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM admin_audit_logs",
            )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


# ============ 最近浏览 / 热门老师（Phase 2） ============


async def record_teacher_view(user_id: int, teacher_id: int) -> None:
    """记录用户浏览过某位老师（详情页打开时调用）

    幂等语义：(user_id, teacher_id) 唯一，已存在时刷新 viewed_at。
    内部异常被吞掉，避免埋点失败影响主流程。
    """
    try:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO user_teacher_views (user_id, teacher_id, viewed_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id, teacher_id) DO UPDATE SET
                       viewed_at = CURRENT_TIMESTAMP""",
                (user_id, teacher_id),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception:
        pass


async def list_recent_teacher_views(user_id: int, limit: int = 10) -> list[dict]:
    """当前用户最近浏览的启用老师列表，按 viewed_at 倒序

    返回 teachers 表全部字段 + viewed_at。停用老师过滤掉。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT t.*, v.viewed_at
               FROM user_teacher_views v
               INNER JOIN teachers t ON v.teacher_id = t.user_id
               WHERE v.user_id = ? AND t.is_active = 1 AND t.is_deleted = 0
               ORDER BY v.viewed_at DESC
               LIMIT ?""",
            (user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_top_favorited_teachers(limit: int = 10) -> list[dict]:
    """收藏数最多的启用老师 TOP N

    返回 teachers 表全部字段 + fav_count。收藏数为 0 的老师不返回。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT t.*, COUNT(f.user_id) AS fav_count
               FROM teachers t
               LEFT JOIN favorites f ON t.user_id = f.teacher_id
               WHERE t.is_active = 1 AND t.is_deleted = 0
               GROUP BY t.user_id
               HAVING fav_count > 0
               ORDER BY fav_count DESC, t.created_at ASC
               LIMIT ?""",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ============ 排序 / 推荐 / 热度 (Phase 3) ============


def is_effective_featured(teacher: dict, today_str: str) -> bool:
    """纯函数：判断老师当前是否处于"有效推荐"状态

    is_featured=1 且 featured_until 为空 / 空字符串 → 长期推荐
    is_featured=1 且 featured_until >= today_str → 仍在推荐期内
    其他情况 → False
    """
    if not teacher.get("is_featured"):
        return False
    fu = teacher.get("featured_until")
    if fu is None:
        return True
    fu_str = str(fu).strip()
    if not fu_str:
        return True
    return fu_str >= today_str


def _today_str_local() -> str:
    """database 内部统一的"今日"字符串（按 config.timezone）"""
    from datetime import datetime
    from pytz import timezone as _tz
    return datetime.now(_tz(config.timezone)).strftime("%Y-%m-%d")


async def get_sorted_teachers(
    active_only: bool = True,
    signed_in_date: Optional[str] = None,
    limit: Optional[int] = None,
    exclude_unavailable: bool = False,
    exclude_full: bool = False,
) -> list[dict]:
    """按统一排序规则返回老师列表（Phase 3 §二 + Phase 5 接入 daily_status）

    排序规则（优先级高到低）：
        1. 当前有效推荐老师（is_featured=1 且未过期）优先
        2. sort_weight 高的优先
        3. hot_score 高的优先
        4. 收藏数高的优先
        5. 今日已签到的优先
        6. 创建时间较早的优先（稳定排序）

    Args:
        active_only: 仅启用老师
        signed_in_date: 不为空 → 仅返回当天已签到的老师（用于频道发布）
        limit: 限制返回条数
        exclude_unavailable: True → 过滤掉 daily_status='unavailable' 的老师
                             用于频道发布和用户今日开课列表（Phase 5 §五）
        exclude_full: True → 过滤掉 daily_status='full' 的老师（与 unavailable 合并视为下线）

    Returns:
        teachers list，每条带:
            fav_count / effective_featured / signed_in_today
            daily_status / daily_available_time / daily_note  (Phase 5)
    """
    today_str = _today_str_local()
    sign_date = signed_in_date or today_str

    # is_deleted=0 无条件排除（软删除老师对所有列表彻底隐藏，不受 active_only 影响）
    where_clauses: list[str] = ["t.is_deleted = 0"]
    if active_only:
        where_clauses.append("t.is_active = 1")
    if signed_in_date is not None:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM checkins c "
            "WHERE c.teacher_id = t.user_id AND c.checkin_date = ?)"
        )
    if exclude_unavailable and exclude_full:
        where_clauses.append("(s.status IS NULL OR s.status NOT IN ('unavailable','full'))")
    elif exclude_unavailable:
        where_clauses.append("(s.status IS NULL OR s.status != 'unavailable')")
    elif exclude_full:
        where_clauses.append("(s.status IS NULL OR s.status != 'full')")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    limit_sql = " LIMIT ?" if limit is not None else ""

    # 参数顺序：
    #   1. effective_featured 比较用 today_str
    #   2. signed_in_today 用 sign_date
    #   3. LEFT JOIN ON daily_status_date 用 sign_date
    #   4. signed_in_date 过滤（若启用）用 signed_in_date
    #   5. limit（若启用）
    params: list = [today_str, sign_date, sign_date]
    if signed_in_date is not None:
        params.append(signed_in_date)
    if limit is not None:
        params.append(limit)

    sql = (
        "SELECT t.*,"
        " (SELECT COUNT(*) FROM favorites f WHERE f.teacher_id = t.user_id) AS fav_count,"
        " CASE WHEN t.is_featured = 1"
        "      AND (t.featured_until IS NULL"
        "           OR TRIM(t.featured_until) = ''"
        "           OR DATE(t.featured_until) >= DATE(?))"
        "      THEN 1 ELSE 0 END AS effective_featured,"
        " CASE WHEN EXISTS (SELECT 1 FROM checkins c"
        "                   WHERE c.teacher_id = t.user_id AND c.checkin_date = ?)"
        "      THEN 1 ELSE 0 END AS signed_in_today,"
        " s.status AS daily_status,"
        " s.available_time AS daily_available_time,"
        " s.note AS daily_note"
        " FROM teachers t"
        " LEFT JOIN teacher_daily_status s"
        "   ON s.teacher_id = t.user_id AND s.status_date = ?"
        f" WHERE {where_sql}"
        " ORDER BY effective_featured DESC,"
        " COALESCE(t.sort_weight, 0) DESC,"
        " COALESCE(t.hot_score, 0) DESC,"
        " fav_count DESC,"
        " signed_in_today DESC,"
        " t.created_at ASC"
        f"{limit_sql}"
    )

    db = await get_db()
    try:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def list_featured_teachers() -> list[dict]:
    """列出所有 is_featured=1 的老师（含已过期），供管理员后台展示

    管理员需要看到全部推荐状态以便取消 / 修改，所以这里不过滤过期。
    用 is_effective_featured(t, today_str) 在展示时区分"有效推荐" / "已过期"。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM teachers "
            "WHERE is_featured = 1 AND is_deleted = 0 "
            "ORDER BY COALESCE(sort_weight, 0) DESC, created_at ASC"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_teacher_ranking(
    teacher_id: int,
    sort_weight: Optional[int] = None,
    is_featured: Optional[int] = None,
    featured_until: Optional[str] = None,
) -> bool:
    """更新老师排序 / 推荐相关字段（Phase 3 §二）

    None 参数视为"不更新该字段"。若所有参数都为 None，返回 False。
    要清空 featured_until，请显式传空字符串 ''。
    """
    fields: list[str] = []
    params: list = []
    if sort_weight is not None:
        fields.append("sort_weight = ?")
        params.append(sort_weight)
    if is_featured is not None:
        fields.append("is_featured = ?")
        params.append(int(is_featured))
    if featured_until is not None:
        # 空字符串明确表示清空
        fields.append("featured_until = ?")
        params.append(featured_until if featured_until != "" else None)

    if not fields:
        return False

    params.append(teacher_id)
    db = await get_db()
    try:
        await db.execute(
            f"UPDATE teachers SET {', '.join(fields)} WHERE user_id = ?",
            params,
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def recalculate_hot_scores() -> int:
    """重算所有老师的 hot_score（Phase 3 §二）

    公式: hot_score = 收藏数 * 10 + 浏览数 * 3
    （搜索命中数项暂未埋点，先不计入；后续 search_hit 事件接入后再扩展）

    兼容降级：
        - 若 user_teacher_views 表不存在 → 仅按 收藏数 * 10
        - 若 favorites 表不存在（不可能的极端） → 全部清零

    Returns:
        受影响的老师数（即 teachers 表行数）
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('favorites', 'user_teacher_views')"
        )
        existing = {row["name"] for row in await cur.fetchall()}

        fav_term = (
            "(SELECT COUNT(*) FROM favorites WHERE teacher_id = teachers.user_id) * 10"
            if "favorites" in existing else "0"
        )
        views_term = (
            "+ COALESCE((SELECT COUNT(*) FROM user_teacher_views "
            "             WHERE teacher_id = teachers.user_id), 0) * 3"
            if "user_teacher_views" in existing else ""
        )

        await db.execute(f"UPDATE teachers SET hot_score = {fav_term} {views_term}")
        await db.commit()

        cur = await db.execute("SELECT COUNT(*) AS n FROM teachers")
        row = await cur.fetchone()
        return int(row["n"] or 0) if row else 0
    finally:
        await db.close()


# ============ 用户来源追踪 (Phase 4) ============


async def record_user_source(
    user_id: int,
    source_type: str,
    source_id: Optional[str] = None,
    source_name: Optional[str] = None,
    raw_payload: Optional[str] = None,
) -> None:
    """记录用户来源（Phase 4 §二）

    行为：
    1. UPSERT user_sources：同一 (user_id, source_type, source_id) 已存在则更新 last_seen_at
    2. 更新 users.first_source_*（仅当 first_source_type 为空，首次写入时）
    3. 更新 users.last_source_*（每次都更新）

    source_id 为 None 时归一化为空字符串，使 UNIQUE 约束在 NULL 上也能正常工作。
    本函数全程包在 try/except 里，任何异常都不向上抛——来源追踪不能阻断主流程。
    """
    sid = "" if source_id is None else str(source_id)
    try:
        db = await get_db()
        try:
            # 1. UPSERT user_sources
            await db.execute(
                """INSERT INTO user_sources
                   (user_id, source_type, source_id, source_name, raw_payload,
                    first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id, source_type, source_id) DO UPDATE SET
                       last_seen_at = CURRENT_TIMESTAMP,
                       source_name = COALESCE(excluded.source_name, source_name),
                       raw_payload = COALESCE(excluded.raw_payload, raw_payload)""",
                (user_id, source_type, sid, source_name, raw_payload),
            )

            # 2. 取当前 users.first_source_type 决定是否首次
            cur = await db.execute(
                "SELECT first_source_type FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = await cur.fetchone()
            existing_first = row["first_source_type"] if row else None

            # 3. 写 users
            if row is None:
                # 用户行尚未建立（极端：start_router 没先 upsert_user 就调过来）→ 跳过
                pass
            elif not existing_first:
                await db.execute(
                    """UPDATE users SET
                           first_source_type = ?, first_source_id = ?,
                           last_source_type = ?, last_source_id = ?
                       WHERE user_id = ?""",
                    (source_type, sid, source_type, sid, user_id),
                )
            else:
                await db.execute(
                    """UPDATE users SET
                           last_source_type = ?, last_source_id = ?
                       WHERE user_id = ?""",
                    (source_type, sid, user_id),
                )

            await db.commit()
        finally:
            await db.close()
    except Exception:
        # 来源追踪静默失败，不影响 /start 主流程
        pass


# ============ 渠道统计 DB helper（Phase 4，已删除） ============
# 注：get_source_stats / get_top_sources_by_type / get_user_source_summary /
# count_total_source_users 已于 2026-05-20 Sprint 7 §9.1.4 第 3 批删除。
# 这 4 个 helper 仅被 source_stats handler 调用，handler 自身已于 §9.1
# 第 2 批清理（commit 0a84708），此后这些 helper 变为孤儿。
# user_sources 表本身保留（仍由 /start 时的来源追踪写入），仅删除查询接口。


# ============ 老师每日状态 (Phase 5) ============


# 可约时间段：固定 4 个值 + None；存储与展示统一使用中文（与 spec §一一致）
TEACHER_TIME_SLOTS: tuple[str, ...] = ("全天", "下午", "晚上", "自定义")
# 状态值：4 个枚举
TEACHER_DAILY_STATUSES: tuple[str, ...] = (
    "available", "unavailable", "full", "unknown",
)


def get_display_time_group(row: dict) -> str:
    """把老师当天的 daily_status / available_time 归到一个展示组（纯函数）

    返回值: 'all' / 'afternoon' / 'evening' / 'other' / 'full' / 'unavailable'

    规则：
        - daily_status == 'unavailable' → 'unavailable'
        - daily_status == 'full' → 'full'
        - available_time 是 '全天/下午/晚上' → 对应英文键
        - 其他（自定义 / 未设置 / NULL） → 'other'
    """
    status = (row.get("daily_status") or "").strip()
    if status == "unavailable":
        return "unavailable"
    if status == "full":
        return "full"
    avt = (row.get("daily_available_time") or "").strip()
    if avt == "全天":
        return "all"
    if avt == "下午":
        return "afternoon"
    if avt == "晚上":
        return "evening"
    return "other"


async def set_teacher_daily_status(
    teacher_id: int,
    status_date: str,
    status: str,
    available_time: Optional[str] = None,
    note: Optional[str] = None,
) -> bool:
    """UPSERT 老师当日状态（Phase 5 §二）

    UPSERT 语义：
        - 若 (teacher_id, status_date) 不存在 → 插入
        - 若已存在 → 更新 status / available_time / note / updated_at
        - available_time / note 显式传 None 时 COALESCE 到旧值（不清空）
          → 如需清空 note 请显式传空字符串 ''
    """
    if status not in TEACHER_DAILY_STATUSES:
        return False

    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO teacher_daily_status
               (teacher_id, status_date, status, available_time, note, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(teacher_id, status_date) DO UPDATE SET
                   status = excluded.status,
                   available_time = COALESCE(excluded.available_time, available_time),
                   note = COALESCE(excluded.note, note),
                   updated_at = CURRENT_TIMESTAMP""",
            (teacher_id, status_date, status, available_time, note),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def get_teacher_daily_status(
    teacher_id: int,
    status_date: str,
) -> Optional[dict]:
    """读取老师当日状态（Phase 5 §二）"""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT teacher_id, status_date, status, available_time, note, updated_at
               FROM teacher_daily_status
               WHERE teacher_id = ? AND status_date = ?""",
            (teacher_id, status_date),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_today_teacher_statuses(
    status_date: str,
    active_only: bool = True,
) -> list[dict]:
    """返回当天所有老师 + 签到状态 + daily_status（Phase 5 §二）

    用于管理员"今日开课状态总览"。
    返回每条:
        teachers.*（启用 + 已签到）
        + signed_in (bool)
        + daily_status / daily_available_time / daily_note (可能为 NULL)

    spec §二：
      "如果老师已签到但没有 teacher_daily_status，默认视为 available，
       available_time 可显示'未设置'。"
    所以这里返回 daily_status 为 NULL 时上层把它当作 available 渲染即可。
    """
    where = "t.is_deleted = 0"
    if active_only:
        where = "t.is_active = 1 AND t.is_deleted = 0"

    db = await get_db()
    try:
        cur = await db.execute(
            f"""SELECT t.*,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM checkins c
                       WHERE c.teacher_id = t.user_id AND c.checkin_date = ?
                   ) THEN 1 ELSE 0 END AS signed_in,
                   s.status AS daily_status,
                   s.available_time AS daily_available_time,
                   s.note AS daily_note
               FROM teachers t
               LEFT JOIN teacher_daily_status s
                 ON s.teacher_id = t.user_id AND s.status_date = ?
               WHERE {where}
                 AND (EXISTS (SELECT 1 FROM checkins c
                              WHERE c.teacher_id = t.user_id AND c.checkin_date = ?)
                      OR s.status IS NOT NULL)
               ORDER BY COALESCE(t.sort_weight, 0) DESC,
                        COALESCE(t.hot_score, 0) DESC,
                        t.created_at ASC""",
            (status_date, status_date, status_date),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def cancel_teacher_today(
    teacher_id: int,
    status_date: str,
    note: Optional[str] = None,
) -> bool:
    """老师取消今日开课：status='unavailable' + 可选原因（Phase 5 §四）"""
    return await set_teacher_daily_status(
        teacher_id=teacher_id,
        status_date=status_date,
        status="unavailable",
        note=note,
    )


async def mark_teacher_full_today(
    teacher_id: int,
    status_date: str,
    note: Optional[str] = None,
) -> bool:
    """老师标记今日已满：status='full'（Phase 5 §四）

    保留原有 available_time（COALESCE 不覆盖）。
    """
    return await set_teacher_daily_status(
        teacher_id=teacher_id,
        status_date=status_date,
        status="full",
        note=note,
    )


# ============ 用户画像标签 (Phase 6.1) ============


async def add_user_tag(
    user_id: int,
    tag: str,
    score_delta: int = 1,
    source: Optional[str] = None,
) -> None:
    """记一次用户画像标签（Phase 6.1 §三）

    UPSERT 语义：
        - tag 自动 strip；空 tag 直接返回（不写入）
        - score_delta < 1 时按 1 处理（最小累积单位）
        - 若 (user_id, tag) 已存在：score += score_delta，source 优先采用新值
          （传 None 时保留旧 source，便于追踪首次来源）
        - 否则插入新行 score = score_delta

    内部异常静默吞掉，标签写入失败不能影响主业务流程。
    """
    if tag is None:
        return
    t = str(tag).strip()
    if not t:
        return
    delta = int(score_delta) if score_delta else 1
    if delta < 1:
        delta = 1

    try:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO user_tags (user_id, tag, score, source, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id, tag) DO UPDATE SET
                       score = score + ?,
                       source = COALESCE(excluded.source, source),
                       updated_at = CURRENT_TIMESTAMP""",
                (user_id, t, delta, source, delta),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception:
        pass


async def get_user_tags(user_id: int, limit: int = 20) -> list[dict]:
    """某个用户的画像标签，按 score DESC, updated_at DESC（Phase 6.1 §三）"""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT user_id, tag, score, source, updated_at
               FROM user_tags
               WHERE user_id = ?
               ORDER BY score DESC, updated_at DESC
               LIMIT ?""",
            (user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_top_user_tags(limit: int = 20) -> list[dict]:
    """全站最热门用户画像标签 TOP N（Phase 6.1 §三）

    返回字段：tag / user_count / total_score
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT tag,
                      COUNT(DISTINCT user_id) AS user_count,
                      SUM(score) AS total_score
               FROM user_tags
               GROUP BY tag
               ORDER BY total_score DESC, user_count DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_users_by_tag(tag: str, limit: int = 50) -> list[dict]:
    """拥有某标签的用户列表，LEFT JOIN users 取 username / first_name（Phase 6.1 §三）

    users 表不存在时 LEFT JOIN 会让两列返回 None，不影响展示。
    """
    if not tag:
        return []
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT ut.user_id AS user_id,
                      ut.tag AS tag,
                      ut.score AS score,
                      ut.source AS source,
                      ut.updated_at AS updated_at,
                      u.username AS username,
                      u.first_name AS first_name
               FROM user_tags ut
               LEFT JOIN users u ON ut.user_id = u.user_id
               WHERE ut.tag = ?
               ORDER BY ut.score DESC, ut.updated_at DESC
               LIMIT ?""",
            (str(tag).strip(), limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


def infer_tags_from_teacher(teacher: dict) -> list[str]:
    """纯函数：从老师资料中提取用户画像标签（Phase 6.1 §三）

    抽取顺序：tags JSON 数组 → region → price
    返回去空 / 去重的字符串列表，保留原中文文本。
    JSON 解析失败时跳过 tags 部分，不抛异常。
    """
    if not teacher:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def _add(val) -> None:
        if val is None:
            return
        s = str(val).strip()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s)

    try:
        raw_tags = teacher.get("tags")
        if raw_tags:
            parsed = json.loads(raw_tags)
            if isinstance(parsed, list):
                for t in parsed:
                    _add(t)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    _add(teacher.get("region"))
    _add(teacher.get("price"))
    return out


# 动作权重表：(老师标签/地区/价格权重, 角色画像标签 + 权重, source 标识)
_TEACHER_ACTION_WEIGHTS: dict[str, tuple[int, str, int, str]] = {
    "view_teacher":   (1, "浏览型用户", 1, "view_teacher"),
    "favorite_add":   (3, "收藏型用户", 2, "favorite"),
    "booking_intent": (5, "高意向用户", 5, "booking_intent"),
}


async def update_user_tags_from_teacher_action(
    user_id: int,
    teacher_id: int,
    action: str,
) -> None:
    """根据老师 + 动作给用户加画像标签（Phase 6.1 §三 §6）

    完整流程：
        1. 取老师；不存在直接返回（不报错）
        2. 通过 infer_tags_from_teacher 取标签集
        3. 按 action 派生权重 + 附加角色标签
        4. 调 add_user_tag 累加

    全程包在 try/except 里，不允许阻断主业务。
    """
    if not action:
        return
    weights = _TEACHER_ACTION_WEIGHTS.get(action)
    if not weights:
        return
    tag_weight, persona_tag, persona_weight, source = weights

    try:
        teacher = await get_teacher(teacher_id)
        if not teacher:
            return
        tags = infer_tags_from_teacher(teacher)
        for t in tags:
            await add_user_tag(user_id, t, score_delta=tag_weight, source=source)
        await add_user_tag(
            user_id, persona_tag, score_delta=persona_weight, source=source,
        )
    except Exception:
        pass


# ============ 频道发布模板 (Phase 6.2) ============


# 模板支持的 5 个变量；render 时 str.replace，每个变量都做安全替换
_PUBLISH_TEMPLATE_VARS: tuple[str, ...] = (
    "date", "count", "grouped_teachers", "city", "weekday",
)


def render_publish_template(template_text: str, context: dict) -> str:
    """渲染发布模板（Phase 6.2 §四 6）

    安全策略：
        - 只对预定义的 5 个变量 {date} / {count} / {grouped_teachers} / {city} / {weekday}
          做字符串替换
        - 未知 {xxx} 保持字面量
        - context 缺失 / value 为 None 时替换为空字符串
        - 不执行任何模板代码，纯字符串替换
        - 内部不抛异常（任何错误返回空字符串或原文）
    """
    if template_text is None:
        return ""
    text = str(template_text)
    ctx = context or {}
    try:
        for key in _PUBLISH_TEMPLATE_VARS:
            val = ctx.get(key, "")
            if val is None:
                val = ""
            text = text.replace("{" + key + "}", str(val))
        return text
    except Exception:
        return str(template_text or "")


async def create_publish_template(
    name: str,
    template_text: str,
    is_default: int = 0,
) -> Optional[int]:
    """新建发布模板（Phase 6.2 §四 1）

    is_default=1 时：先把其他模板 is_default 清零，再插入新模板为默认。
    返回新模板 id；name/template_text 为空时返回 None。
    """
    n = (name or "").strip()
    body = (template_text or "").strip()
    if not n or not body:
        return None

    db = await get_db()
    try:
        if int(is_default) == 1:
            await db.execute(
                "UPDATE publish_templates SET is_default = 0"
            )
        cur = await db.execute(
            """INSERT INTO publish_templates
               (name, template_text, is_default, is_active, created_at, updated_at)
               VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (n, body, 1 if int(is_default) == 1 else 0),
        )
        await db.commit()
        return cur.lastrowid
    except Exception:
        return None
    finally:
        await db.close()


async def get_default_publish_template() -> Optional[dict]:
    """取默认模板（Phase 6.2 §四 2）

    优先级：
        1. is_default = 1 AND is_active = 1
        2. 任意 is_active = 1（按 updated_at DESC 取最新）
        3. None
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT * FROM publish_templates
               WHERE is_default = 1 AND is_active = 1
               LIMIT 1"""
        )
        row = await cur.fetchone()
        if row:
            return dict(row)

        cur = await db.execute(
            """SELECT * FROM publish_templates
               WHERE is_active = 1
               ORDER BY updated_at DESC
               LIMIT 1"""
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_publish_templates(active_only: bool = True) -> list[dict]:
    """列出发布模板（Phase 6.2 §四 3）

    active_only=True 时仅返回 is_active=1。
    按 is_default DESC, updated_at DESC 排序。
    """
    db = await get_db()
    try:
        where = "WHERE is_active = 1" if active_only else ""
        cur = await db.execute(
            f"""SELECT * FROM publish_templates
                {where}
                ORDER BY is_default DESC, updated_at DESC"""
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def set_default_publish_template(template_id: int) -> bool:
    """设为默认模板（Phase 6.2 §四 4）

    要求目标模板存在且 is_active=1。事务内：先全部清零，再置目标。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, is_active FROM publish_templates WHERE id = ?",
            (template_id,),
        )
        row = await cur.fetchone()
        if not row or not row["is_active"]:
            return False

        await db.execute("UPDATE publish_templates SET is_default = 0")
        await db.execute(
            "UPDATE publish_templates SET is_default = 1,"
            " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (template_id,),
        )
        await db.commit()
        return True
    except Exception:
        return False
    finally:
        await db.close()


async def update_publish_template(
    template_id: int,
    name: Optional[str] = None,
    template_text: Optional[str] = None,
    is_active: Optional[int] = None,
) -> bool:
    """只更新传入的字段（Phase 6.2 §四 5）

    全部为 None → 返回 False（不允许空更新）。
    updated_at 始终刷新。
    """
    sets: list[str] = []
    params: list = []
    if name is not None:
        n = str(name).strip()
        if not n:
            return False
        sets.append("name = ?")
        params.append(n)
    if template_text is not None:
        body = str(template_text).strip()
        if not body:
            return False
        sets.append("template_text = ?")
        params.append(body)
    if is_active is not None:
        sets.append("is_active = ?")
        params.append(1 if int(is_active) else 0)

    if not sets:
        return False

    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(template_id)
    db = await get_db()
    try:
        await db.execute(
            f"UPDATE publish_templates SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await db.commit()
        return db.total_changes > 0
    except Exception:
        return False
    finally:
        await db.close()


async def get_publish_template(template_id: int) -> Optional[dict]:
    """按 id 取模板（用于编辑 / 校验是否存在）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM publish_templates WHERE id = ?",
            (template_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


# ============ 相似推荐 / 搜索历史 (Phase 7.3) ============


async def get_similar_teachers(
    teacher_id: int,
    limit: int = 5,
) -> list[dict]:
    """相似老师推荐（Phase 7.3 §一）

    评分规则（命中越多越靠前）：
        + 每命中一个相同 tag：+10
        + 同地区：+20
        + 同价格：+10
        + 今日可约（signed_in_today=1 且 daily_status != unavailable）：+20
        + is_effective_featured：+30
        + hot_score：直接相加

    降级链：
        1. 目标老师不存在 → []
        2. 无可比对维度 / 评分全为 0 → 调 get_hot_teachers(limit)
        3. get_hot_teachers 不存在 / 异常 → get_all_teachers(active_only=True)[:limit]
        4. 全异常 → []
    """
    if limit <= 0:
        return []

    base = await get_teacher(teacher_id)
    if not base:
        return []

    today_str = _today_str_local()

    # base 标签 / 地区 / 价格集合
    try:
        base_tags = json.loads(base.get("tags") or "[]") or []
        if not isinstance(base_tags, list):
            base_tags = []
    except (json.JSONDecodeError, TypeError, ValueError):
        base_tags = []
    base_tag_set = {str(t).strip().lower() for t in base_tags if t}
    base_region = (base.get("region") or "").strip().lower()
    base_price = (base.get("price") or "").strip().lower()

    # 拉所有 active 老师 + daily_status / signed_in / fav_count
    try:
        candidates = await get_sorted_teachers(active_only=True)
    except Exception as e:
        logger.warning("get_sorted_teachers 失败，降级 get_all_teachers: %s", e)
        try:
            candidates = await get_all_teachers(active_only=True)
        except Exception:
            return []

    scored: list[tuple[float, dict]] = []
    for t in candidates:
        if t.get("user_id") == teacher_id:
            continue  # 排除自己

        score = 0.0

        # 相同 tag
        try:
            tags = json.loads(t.get("tags") or "[]") or []
            if not isinstance(tags, list):
                tags = []
        except (json.JSONDecodeError, TypeError, ValueError):
            tags = []
        for tag in tags:
            tl = str(tag).strip().lower()
            if tl and tl in base_tag_set:
                score += 10

        # 同地区
        region_lower = (t.get("region") or "").strip().lower()
        if base_region and region_lower == base_region:
            score += 20

        # 同价格
        price_lower = (t.get("price") or "").strip().lower()
        if base_price and price_lower == base_price:
            score += 10

        # 今日可约
        try:
            signed = bool(t.get("signed_in_today"))
            d_status = t.get("daily_status")
            if signed and d_status != "unavailable":
                score += 20
        except Exception:
            pass

        # is_effective_featured
        try:
            if is_effective_featured(t, today_str):
                score += 30
        except Exception:
            pass

        # hot_score
        try:
            score += float(t.get("hot_score") or 0)
        except (ValueError, TypeError):
            pass

        scored.append((score, t))

    if not scored:
        # 候选池为空 → 全回退到 hot
        try:
            return await get_hot_teachers(limit=limit)
        except Exception:
            try:
                fallback = await get_all_teachers(active_only=True)
                return [t for t in fallback if t.get("user_id") != teacher_id][:limit]
            except Exception:
                return []

    # 按 score DESC, signed_in_today DESC, created_at ASC
    scored.sort(
        key=lambda x: (
            -x[0],
            -(int(x[1].get("signed_in_today") or 0)),
            str(x[1].get("created_at") or ""),
        )
    )

    # 取所有 score > 0 的；若全 0 走回退
    positive = [t for s, t in scored if s > 0]
    if positive:
        return positive[:limit]

    # 评分全 0 → 回退到 hot
    try:
        hot = await get_hot_teachers(limit=limit)
        return [t for t in hot if t.get("user_id") != teacher_id][:limit]
    except Exception:
        try:
            fallback = await get_all_teachers(active_only=True)
            return [t for t in fallback if t.get("user_id") != teacher_id][:limit]
        except Exception:
            return []



# ============ 报表统计 (Phase 6.3) ============


async def _existing_tables(db: aiosqlite.Connection) -> set:
    """返回当前数据库中已存在的表名集合"""
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    return {row["name"] for row in await cur.fetchall()}


async def _existing_columns(db: aiosqlite.Connection, table: str) -> set:
    """返回某表的字段名集合；表不存在时返回空集合"""
    try:
        cur = await db.execute(f"PRAGMA table_info({table})")
        return {row["name"] for row in await cur.fetchall()}
    except Exception:
        return set()


async def get_report_stats(start_date: str, end_date: str) -> dict:
    """聚合日报 / 周报所需统计（Phase 6.3 §三）

    Args:
        start_date / end_date: 'YYYY-MM-DD' 闭区间
        日报时 start == end；周报时通常 start = end - 6 天

    返回 10 个字段：
        new_users / active_users / search_count / favorite_add_count /
        teacher_view_count / today_checkin_count /
        top_teachers / top_search_keywords / top_user_tags / top_sources

    兼容降级：所有指标在数据来源缺失 / 查询异常时返回 0 或 []，
    绝不抛异常。一项失败不影响其他指标。
    """
    result = {
        "new_users": 0,
        "active_users": 0,
        "search_count": 0,
        "favorite_add_count": 0,
        "teacher_view_count": 0,
        "today_checkin_count": 0,
        "top_teachers": [],
        "top_search_keywords": [],
        "top_user_tags": [],
        "top_sources": [],
    }

    db = await get_db()
    try:
        tables = await _existing_tables(db)

        # 1. new_users —— users.created_at 在闭区间内
        if "users" in tables:
            try:
                cur = await db.execute(
                    "SELECT COUNT(*) AS n FROM users "
                    "WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?",
                    (start_date, end_date),
                )
                row = await cur.fetchone()
                result["new_users"] = int(row["n"] or 0) if row else 0
            except Exception as e:
                logger.debug("new_users 查询失败: %s", e)

        # 2. active_users —— user_events 区间内 distinct user_id
        if "user_events" in tables:
            try:
                cur = await db.execute(
                    "SELECT COUNT(DISTINCT user_id) AS n FROM user_events "
                    "WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?",
                    (start_date, end_date),
                )
                row = await cur.fetchone()
                result["active_users"] = int(row["n"] or 0) if row else 0
            except Exception as e:
                logger.debug("active_users 查询失败: %s", e)

        # 3. search_count —— user_events event_type='search'
        if "user_events" in tables:
            try:
                cur = await db.execute(
                    "SELECT COUNT(*) AS n FROM user_events "
                    "WHERE event_type = 'search' "
                    "AND DATE(created_at) >= ? AND DATE(created_at) <= ?",
                    (start_date, end_date),
                )
                row = await cur.fetchone()
                result["search_count"] = int(row["n"] or 0) if row else 0
            except Exception as e:
                logger.debug("search_count 查询失败: %s", e)

        # 4. favorite_add_count —— 先看 user_events，0 时降级到 favorites.created_at
        if "user_events" in tables:
            try:
                cur = await db.execute(
                    "SELECT COUNT(*) AS n FROM user_events "
                    "WHERE event_type = 'favorite_add' "
                    "AND DATE(created_at) >= ? AND DATE(created_at) <= ?",
                    (start_date, end_date),
                )
                row = await cur.fetchone()
                result["favorite_add_count"] = int(row["n"] or 0) if row else 0
            except Exception as e:
                logger.debug("favorite_add_count(user_events) 失败: %s", e)
        if result["favorite_add_count"] == 0 and "favorites" in tables:
            try:
                cur = await db.execute(
                    "SELECT COUNT(*) AS n FROM favorites "
                    "WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?",
                    (start_date, end_date),
                )
                row = await cur.fetchone()
                result["favorite_add_count"] = int(row["n"] or 0) if row else 0
            except Exception as e:
                logger.debug("favorite_add_count(favorites) 失败: %s", e)

        # 5. teacher_view_count —— 先 user_events (view_teacher/teacher_view)，0 时降级 user_teacher_views
        if "user_events" in tables:
            try:
                cur = await db.execute(
                    "SELECT COUNT(*) AS n FROM user_events "
                    "WHERE event_type IN ('view_teacher', 'teacher_view') "
                    "AND DATE(created_at) >= ? AND DATE(created_at) <= ?",
                    (start_date, end_date),
                )
                row = await cur.fetchone()
                result["teacher_view_count"] = int(row["n"] or 0) if row else 0
            except Exception as e:
                logger.debug("teacher_view_count(user_events) 失败: %s", e)
        if result["teacher_view_count"] == 0 and "user_teacher_views" in tables:
            try:
                cur = await db.execute(
                    "SELECT COUNT(*) AS n FROM user_teacher_views "
                    "WHERE DATE(viewed_at) >= ? AND DATE(viewed_at) <= ?",
                    (start_date, end_date),
                )
                row = await cur.fetchone()
                result["teacher_view_count"] = int(row["n"] or 0) if row else 0
            except Exception as e:
                logger.debug("teacher_view_count(user_teacher_views) 失败: %s", e)

        # 6. today_checkin_count —— checkins.checkin_date 在闭区间内
        if "checkins" in tables:
            try:
                cur = await db.execute(
                    "SELECT COUNT(*) AS n FROM checkins "
                    "WHERE checkin_date >= ? AND checkin_date <= ?",
                    (start_date, end_date),
                )
                row = await cur.fetchone()
                result["today_checkin_count"] = int(row["n"] or 0) if row else 0
            except Exception as e:
                logger.debug("today_checkin_count 查询失败: %s", e)

        # 7. top_teachers —— 综合 hot_score + 收藏数
        if "teachers" in tables:
            try:
                t_cols = await _existing_columns(db, "teachers")
                score_parts: list[str] = []
                if "hot_score" in t_cols:
                    score_parts.append("COALESCE(t.hot_score, 0)")
                if "favorites" in tables:
                    score_parts.append(
                        "(SELECT COUNT(*) FROM favorites WHERE teacher_id = t.user_id)"
                    )
                if not score_parts:
                    score_parts = ["0"]
                score_expr = " + ".join(score_parts)

                order_parts: list[str] = []
                if "hot_score" in t_cols:
                    order_parts.append("COALESCE(t.hot_score, 0) DESC")
                if "sort_weight" in t_cols:
                    order_parts.append("COALESCE(t.sort_weight, 0) DESC")
                if "favorites" in tables:
                    order_parts.append(
                        "(SELECT COUNT(*) FROM favorites WHERE teacher_id = t.user_id) DESC"
                    )
                order_parts.append("t.created_at ASC")
                order_sql = ", ".join(order_parts)

                cur = await db.execute(
                    f"SELECT t.display_name, ({score_expr}) AS score "
                    "FROM teachers t WHERE t.is_active = 1 AND t.is_deleted = 0 "
                    f"ORDER BY {order_sql} LIMIT 10"
                )
                rows = await cur.fetchall()
                result["top_teachers"] = [
                    {"display_name": r["display_name"], "score": int(r["score"] or 0)}
                    for r in rows
                    if r["display_name"] and int(r["score"] or 0) > 0
                ]
            except Exception as e:
                logger.warning("top_teachers 查询失败: %s", e)

        # 8. top_search_keywords —— 解析 user_events event_type='search' 的 payload.tokens
        if "user_events" in tables:
            try:
                cur = await db.execute(
                    "SELECT payload FROM user_events "
                    "WHERE event_type = 'search' "
                    "AND DATE(created_at) >= ? AND DATE(created_at) <= ? "
                    "AND payload IS NOT NULL",
                    (start_date, end_date),
                )
                rows = await cur.fetchall()
                from collections import Counter
                counter: Counter = Counter()
                for r in rows:
                    payload = r["payload"]
                    if not payload:
                        continue
                    try:
                        data = json.loads(payload)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    tokens = None
                    if isinstance(data, dict):
                        tokens = data.get("tokens") or data.get("keywords")
                    if isinstance(tokens, list):
                        for tok in tokens:
                            s = str(tok or "").strip()
                            if s:
                                counter[s] += 1
                result["top_search_keywords"] = [
                    {"keyword": k, "count": c}
                    for k, c in counter.most_common(10)
                ]
            except Exception as e:
                logger.warning("top_search_keywords 查询失败: %s", e)

        # 9. top_user_tags —— 直接复用 Phase 6.1 表
        if "user_tags" in tables:
            try:
                cur = await db.execute(
                    """SELECT tag,
                              COUNT(DISTINCT user_id) AS user_count,
                              SUM(score) AS total_score
                       FROM user_tags
                       GROUP BY tag
                       ORDER BY total_score DESC, user_count DESC
                       LIMIT 10"""
                )
                rows = await cur.fetchall()
                result["top_user_tags"] = [dict(r) for r in rows]
            except Exception as e:
                logger.warning("top_user_tags 查询失败: %s", e)

        # 10. top_sources —— 直接 user_sources 聚合
        if "user_sources" in tables:
            try:
                cur = await db.execute(
                    """SELECT source_type, source_id,
                              MAX(source_name) AS source_name,
                              COUNT(DISTINCT user_id) AS user_count
                       FROM user_sources
                       GROUP BY source_type, source_id
                       ORDER BY user_count DESC
                       LIMIT 10"""
                )
                rows = await cur.fetchall()
                result["top_sources"] = [dict(r) for r in rows]
            except Exception as e:
                logger.warning("top_sources 查询失败: %s", e)
    finally:
        await db.close()

    return result


# ============ 老师档案 (Phase 9.1) ============

# 必填字段（用于 is_teacher_profile_complete 校验）；photo_album 单独要求 ≥ 1 张
TEACHER_PROFILE_REQUIRED_FIELDS: list[str] = [
    "display_name", "age", "height_cm", "weight_kg", "bra_size",
    "price_detail", "contact_telegram",
    "region", "price", "tags", "button_url",
]

# 可选字段（允许 NULL）
TEACHER_PROFILE_OPTIONAL_FIELDS: list[str] = [
    "description", "service_content", "taboos", "button_text",
]

# update_teacher_profile_field 接受的字段白名单
TEACHER_PROFILE_EDITABLE_FIELDS: set[str] = (
    set(TEACHER_PROFILE_REQUIRED_FIELDS)
    | set(TEACHER_PROFILE_OPTIONAL_FIELDS)
    | {"photo_album"}
)


def parse_basic_info(text: str) -> Optional[dict]:
    """解析 "年龄 身高 体重 罩杯" 一行四字段（spec §2 / PHASE-9.1 §4.3）

    成功返回 {"age", "height_cm", "weight_kg", "bra_size"}，失败返回 None。
    边界：年龄 15-60 / 身高 140-200 / 体重 35-120 / 罩杯 1-3 个字母。
    纯函数，不访问 DB。
    """
    if not text:
        return None
    parts = text.strip().split()
    if len(parts) != 4:
        return None
    try:
        age = int(parts[0])
        height = int(parts[1])
        weight = int(parts[2])
    except ValueError:
        return None
    bra = parts[3].strip().upper()
    if not (15 <= age <= 60):
        return None
    if not (140 <= height <= 200):
        return None
    if not (35 <= weight <= 120):
        return None
    if not (1 <= len(bra) <= 3) or not bra.isalpha():
        return None
    return {
        "age": age,
        "height_cm": height,
        "weight_kg": weight,
        "bra_size": bra,
    }


async def update_teacher_profile_field(user_id: int, field: str, value) -> bool:
    """更新老师档案单个字段（白名单 + 类型校验）

    支持：基础字段、Phase 9.1 新字段、photo_album（list 自动 JSON 序列化）。
    返回是否真有行被更新。
    """
    if field not in TEACHER_PROFILE_EDITABLE_FIELDS:
        return False

    # 类型规范化
    if field == "photo_album":
        if value is None:
            stored = None
        elif isinstance(value, list):
            stored = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, str):
            stored = value
        else:
            return False
    elif field == "tags":
        if isinstance(value, list):
            stored = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, str):
            stored = value
        else:
            return False
    elif field in {"age", "height_cm", "weight_kg"}:
        if value is None:
            stored = None
        else:
            try:
                stored = int(value)
            except (TypeError, ValueError):
                return False
    else:
        stored = value

    db = await get_db()
    try:
        await db.execute(
            f"UPDATE teachers SET {field} = ? WHERE user_id = ?",
            (stored, user_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def get_teacher_photos(user_id: int) -> list[str]:
    """读取老师相册 file_id 列表

    优先解析 photo_album JSON；为空时回退到旧字段 photo_file_id（单图相册）。
    返回 [] 表示该老师没有任何照片。
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT photo_album, photo_file_id FROM teachers WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return []
    raw = row["photo_album"]
    if raw:
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(x) for x in arr if x]
        except (json.JSONDecodeError, TypeError):
            pass
    # 回退到旧的单图字段
    legacy = row["photo_file_id"]
    return [legacy] if legacy else []


async def set_teacher_photos(user_id: int, file_ids: list[str]) -> bool:
    """整体替换老师相册（最多 10 张，Telegram 媒体组上限）

    file_ids 为空列表时写入 "[]"（不是 NULL），保留"显式清空"语义。
    同步把列表第一张写入旧字段 photo_file_id，保证旧逻辑兼容。
    """
    if file_ids is None:
        return False
    cleaned = [str(fid) for fid in file_ids if fid][:10]
    db = await get_db()
    try:
        await db.execute(
            "UPDATE teachers SET photo_album = ?, photo_file_id = ? WHERE user_id = ?",
            (
                json.dumps(cleaned, ensure_ascii=False),
                cleaned[0] if cleaned else None,
                user_id,
            ),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def add_teacher_photo(user_id: int, file_id: str) -> int:
    """追加一张照片到老师相册，返回追加后的相册总长度

    若已达 10 张上限，不追加，直接返回当前长度（调用方据此提示用户）。
    """
    if not file_id:
        return await count_teacher_photos(user_id)
    current = await get_teacher_photos(user_id)
    if len(current) >= 10:
        return len(current)
    current.append(str(file_id))
    await set_teacher_photos(user_id, current)
    return len(current)


async def remove_teacher_photo(user_id: int, index: int) -> bool:
    """按 1-based index 删除相册中某张照片"""
    current = await get_teacher_photos(user_id)
    if index < 1 or index > len(current):
        return False
    del current[index - 1]
    return await set_teacher_photos(user_id, current)


async def count_teacher_photos(user_id: int) -> int:
    """统计老师当前相册照片数（用于"已上传 X/10 张"提示）"""
    return len(await get_teacher_photos(user_id))


async def get_teacher_full_profile(user_id: int) -> Optional[dict]:
    """读取老师完整档案（含相册解析）

    返回的 dict 中：
    - tags 解析为 list[str]（失败时给 []）
    - photo_album 解析为 list[str]（失败回退 photo_file_id）
    其他字段原样保留。老师不存在时返回 None。
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM teachers WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return None
    data = dict(row)
    # tags JSON → list
    try:
        data["tags"] = json.loads(data.get("tags") or "[]")
        if not isinstance(data["tags"], list):
            data["tags"] = []
    except (json.JSONDecodeError, TypeError):
        data["tags"] = []
    # photo_album JSON → list（带回退）
    raw_album = data.get("photo_album")
    album: list[str] = []
    if raw_album:
        try:
            parsed = json.loads(raw_album)
            if isinstance(parsed, list):
                album = [str(x) for x in parsed if x]
        except (json.JSONDecodeError, TypeError):
            album = []
    if not album and data.get("photo_file_id"):
        album = [data["photo_file_id"]]
    data["photo_album"] = album
    return data


async def is_teacher_profile_complete(user_id: int) -> tuple[bool, list[str]]:
    """校验老师档案是否齐备（用于 [👁 预览] / Phase 9.2 发布前校验）

    Returns:
        (is_complete, missing_fields)
        - is_complete: 所有必填字段非空 且 相册 ≥ 1 张
        - missing_fields: 缺失字段名列表（顺序遵循 TEACHER_PROFILE_REQUIRED_FIELDS）
          相册不足单独以 "photo_album" 形式追加
    """
    profile = await get_teacher_full_profile(user_id)
    if profile is None:
        return False, ["__teacher_not_found__"]

    missing: list[str] = []
    for field in TEACHER_PROFILE_REQUIRED_FIELDS:
        val = profile.get(field)
        if field == "tags":
            if not isinstance(val, list) or len(val) == 0:
                missing.append(field)
        elif val is None or (isinstance(val, str) and not val.strip()):
            missing.append(field)
    # 相册要求至少 1 张
    if not profile.get("photo_album"):
        missing.append("photo_album")

    return (len(missing) == 0), missing


# ============ 档案帖发布 (Phase 9.2) ============


async def set_archive_channel_id(chat_id: int) -> None:
    """设置档案帖发布目标频道（config key=archive_channel_id）"""
    await set_config("archive_channel_id", str(int(chat_id)))


async def get_archive_channel_id() -> Optional[int]:
    """获取档案帖发布频道 ID

    优先级：
    1. config.archive_channel_id（Phase 9.2 新配置）
    2. 回退 publish_channel_id 第一个（与每日签到帖共用）
    3. 都没有时返回 None
    """
    raw = await get_config("archive_channel_id")
    if raw:
        try:
            return int(raw.strip())
        except (TypeError, ValueError):
            pass
    fallback = await get_config("publish_channel_id")
    if not fallback:
        return None
    first = fallback.split(",")[0].strip()
    if not first:
        return None
    try:
        return int(first)
    except (TypeError, ValueError):
        return None


async def upsert_teacher_channel_post(
    teacher_id: int,
    channel_chat_id: int,
    channel_msg_id: int,
    media_group_msg_ids: list[int],
) -> None:
    """新建或覆盖 teacher_channel_posts 行（首次发布 / 重发都走这里）

    保留已有的 review_count / avg_* 字段（评价聚合归 Phase 9.5 维护）。
    若不存在则 INSERT；存在则只覆盖与发布相关的 4 列 + updated_at。
    """
    mids_json = json.dumps([int(x) for x in media_group_msg_ids], ensure_ascii=False)
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT teacher_id FROM teacher_channel_posts WHERE teacher_id = ?",
            (teacher_id,),
        )
        existing = await cur.fetchone()
        if existing:
            await db.execute(
                """UPDATE teacher_channel_posts SET
                    channel_chat_id = ?,
                    channel_msg_id = ?,
                    media_group_msg_ids = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE teacher_id = ?""",
                (channel_chat_id, channel_msg_id, mids_json, teacher_id),
            )
        else:
            await db.execute(
                """INSERT INTO teacher_channel_posts
                    (teacher_id, channel_chat_id, channel_msg_id, media_group_msg_ids)
                    VALUES (?, ?, ?, ?)""",
                (teacher_id, channel_chat_id, channel_msg_id, mids_json),
            )
        await db.commit()
    finally:
        await db.close()


async def get_teacher_channel_post(teacher_id: int) -> Optional[dict]:
    """读取 teacher_channel_posts 一行

    media_group_msg_ids 解析为 list[int]；空时给 []。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM teacher_channel_posts WHERE teacher_id = ?",
            (teacher_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return None
    data = dict(row)
    raw = data.get("media_group_msg_ids")
    ids: list[int] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                ids = [int(x) for x in parsed]
        except (json.JSONDecodeError, TypeError, ValueError):
            ids = []
    data["media_group_msg_ids"] = ids
    return data


async def touch_teacher_channel_post(teacher_id: int) -> bool:
    """仅更新 updated_at（用于 caption edit 成功后刷新 debounce 计时）"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE teacher_channel_posts SET updated_at = CURRENT_TIMESTAMP "
            "WHERE teacher_id = ?",
            (teacher_id,),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def delete_teacher_channel_post(teacher_id: int) -> bool:
    """删除 teacher_channel_posts 一行（用于 unpublish / repost 前清理）"""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM teacher_channel_posts WHERE teacher_id = ?",
            (teacher_id,),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def seconds_since_last_caption_edit(teacher_id: int) -> Optional[float]:
    """距上次 update_at 经过的秒数（用于 60s debounce 判断）

    返回 None 表示没有记录；否则返回非负浮点秒数。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT (julianday('now') - julianday(updated_at)) * 86400.0 AS sec "
            "FROM teacher_channel_posts WHERE teacher_id = ?",
            (teacher_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row or row["sec"] is None:
        return None
    try:
        return max(0.0, float(row["sec"]))
    except (TypeError, ValueError):
        return None


# ============ 评价 / 必关频道 (Phase 9.3) ============

# 6 维度评分配置（spec §7.5）
REVIEW_DIMENSIONS: list[dict] = [
    {"key": "humanphoto",   "label": "🎨 人照",   "column": "score_humanphoto"},
    {"key": "appearance",   "label": "颜值",      "column": "score_appearance"},
    {"key": "body",         "label": "身材",      "column": "score_body"},
    {"key": "service",      "label": "服务",      "column": "score_service"},
    {"key": "attitude",     "label": "态度",      "column": "score_attitude"},
    {"key": "environment",  "label": "环境",      "column": "score_environment"},
]

REVIEW_RATINGS: list[dict] = [
    {"key": "positive", "emoji": "👍", "label": "好评"},
    {"key": "neutral",  "emoji": "😐", "label": "中评"},
    {"key": "negative", "emoji": "👎", "label": "差评"},
]

REVIEW_SCORE_MIN: float = 0.0
REVIEW_SCORE_MAX: float = 10.0
REVIEW_SCORE_DECIMAL_PLACES: int = 1
# 注：REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM / REVIEW_SCORE_QUICK_BUTTONS_FOR_OVERALL
# 已于 2026-05-20 Sprint 7 §9.1.4 第 2 批删除（旧线性 FSM 的快捷评分按钮，
# 卡片化重构后无 caller）。

REVIEW_SUMMARY_MIN_LEN: int = 50
REVIEW_SUMMARY_MAX_LEN: int = 300
# 注：REVIEW_SUMMARY_REQUIRED 已于 §9.1.4 第 2 批删除（无 caller，
# review_card 中过程描述始终必填，不需要此 flag）。

REVIEW_RATE_LIMIT_PER_TEACHER_24H: int = 3
REVIEW_RATE_LIMIT_PER_USER_DAY: int = 10
REVIEW_RATE_LIMIT_PER_USER_60S: int = 1


def parse_review_score(text: str) -> Optional[float]:
    """解析评分输入文字 → float in [0,10]，最多 1 位小数

    成功返回 round(x, 1)；失败返回 None。
    纯函数，不访问 DB。
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    # 不允许带空格 / 字母（"8.5 分"也返回 None，由 UI 引导用户）
    try:
        value = float(s)
    except ValueError:
        return None
    if value < REVIEW_SCORE_MIN or value > REVIEW_SCORE_MAX:
        return None
    # 小数位 > 1 → 拒绝；用 round 之前先看原字符串
    if "." in s:
        decimal_part = s.split(".", 1)[1]
        if len(decimal_part) > REVIEW_SCORE_DECIMAL_PLACES:
            return None
    return round(value, REVIEW_SCORE_DECIMAL_PLACES)


# ---- required_subscriptions CRUD ----

async def add_required_subscription(
    chat_id: int,
    chat_type: str,
    display_name: str,
    invite_link: str,
    sort_order: int = 0,
) -> Optional[int]:
    """新增必关订阅项；chat_id 冲突时返回 None"""
    db = await get_db()
    try:
        try:
            cur = await db.execute(
                """INSERT INTO required_subscriptions
                    (chat_id, chat_type, display_name, invite_link, sort_order)
                    VALUES (?, ?, ?, ?, ?)""",
                (chat_id, chat_type, display_name, invite_link, sort_order),
            )
        except Exception:
            return None
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def list_required_subscriptions(active_only: bool = False) -> list[dict]:
    """列出必关订阅项，按 sort_order ASC, id ASC"""
    db = await get_db()
    try:
        query = "SELECT * FROM required_subscriptions"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY sort_order, id"
        cur = await db.execute(query)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_required_subscription(item_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM required_subscriptions WHERE id = ?", (item_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def toggle_required_subscription(item_id: int) -> Optional[int]:
    """启停切换；返回切换后的 is_active 值；不存在时返回 None"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT is_active FROM required_subscriptions WHERE id = ?", (item_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        new_val = 0 if row["is_active"] else 1
        await db.execute(
            "UPDATE required_subscriptions SET is_active = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_val, item_id),
        )
        await db.commit()
        return new_val
    finally:
        await db.close()


async def remove_required_subscription(item_id: int) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM required_subscriptions WHERE id = ?", (item_id,)
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


# ---- teacher_reviews CRUD ----

async def create_teacher_review(data: dict) -> Optional[int]:
    """插入 pending 评价，返回 review_id

    data 必含：teacher_id / user_id / booking_screenshot_file_id /
              rating / 6 个 score_* / overall_score
    可选：summary（None 或字符串） / gesture_photo_file_id（2026-05-21 起
              仅 request_reimbursement=1 路径强制要求，普通评价为 None）
    """
    required = ["teacher_id", "user_id", "booking_screenshot_file_id",
                "rating", "overall_score"]
    for f in required:
        if data.get(f) is None:
            return None
    for d in REVIEW_DIMENSIONS:
        if data.get(d["column"]) is None:
            return None

    db = await get_db()
    try:
        try:
            cur = await db.execute(
                """INSERT INTO teacher_reviews (
                    teacher_id, user_id,
                    booking_screenshot_file_id, gesture_photo_file_id,
                    rating,
                    score_humanphoto, score_appearance, score_body,
                    score_service, score_attitude, score_environment,
                    overall_score, summary, status,
                    request_reimbursement, anonymous
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    int(data["teacher_id"]), int(data["user_id"]),
                    data["booking_screenshot_file_id"],
                    # 2026-05-21：可空，get 而非下标
                    data.get("gesture_photo_file_id"),
                    data["rating"],
                    float(data["score_humanphoto"]),
                    float(data["score_appearance"]),
                    float(data["score_body"]),
                    float(data["score_service"]),
                    float(data["score_attitude"]),
                    float(data["score_environment"]),
                    float(data["overall_score"]),
                    data.get("summary"),
                    int(data.get("request_reimbursement") or 0),
                    int(data.get("anonymous") or 0),
                ),
            )
        except Exception as e:
            logger.warning("create_teacher_review 失败: %s", e)
            return None
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def get_teacher_review(review_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM teacher_reviews WHERE id = ?", (review_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def count_recent_user_reviews(user_id: int, seconds: int) -> int:
    """近 seconds 秒内该用户提交的评价数（不分老师，含 pending/approved/rejected）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM teacher_reviews "
            "WHERE user_id = ? AND created_at >= datetime('now', ? || ' seconds')",
            (user_id, f"-{int(seconds)}"),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def count_recent_user_teacher_reviews(
    user_id: int, teacher_id: int, seconds: int,
) -> int:
    """近 seconds 秒内该用户对该老师的评价数"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM teacher_reviews "
            "WHERE user_id = ? AND teacher_id = ? "
            "  AND created_at >= datetime('now', ? || ' seconds')",
            (user_id, teacher_id, f"-{int(seconds)}"),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def count_pending_reviews() -> int:
    """待审核评价数（用于主面板 [📝 报告审核 (M)] 徽标，Phase 9.4 用）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM teacher_reviews WHERE status = 'pending'"
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def list_pending_reviews(limit: int = 50, offset: int = 0) -> list[dict]:
    """列出待审核评价（Phase 9.4 用），按 created_at ASC（最老的先审）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM teacher_reviews WHERE status = 'pending' "
            "ORDER BY created_at LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def approve_teacher_review(review_id: int, reviewer_id: int) -> bool:
    """超管通过评价：仅 pending → approved（含 reviewer_id + reviewed_at）"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE teacher_reviews SET status = 'approved', "
            "reviewer_id = ?, reviewed_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'pending'",
            (reviewer_id, review_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def reject_teacher_review(
    review_id: int, reviewer_id: int, reason: Optional[str] = None,
) -> bool:
    """超管驳回评价：仅 pending → rejected（reason 可空，私聊提示用户）"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE teacher_reviews SET status = 'rejected', "
            "reviewer_id = ?, reviewed_at = CURRENT_TIMESTAMP, "
            "reject_reason = ? "
            "WHERE id = ? AND status = 'pending'",
            (reviewer_id, reason, review_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def list_super_admins() -> list[int]:
    """所有 super_admin user_id（含主超管 config.super_admin_id + DB is_super=1），去重

    返回 list[int]；用于 Phase 9.4 新评价推送。
    """
    user_ids: set[int] = set()
    if config.super_admin_id:
        user_ids.add(int(config.super_admin_id))
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT user_id FROM admins WHERE is_super = 1"
        )
        rows = await cur.fetchall()
        for r in rows:
            user_ids.add(int(r["user_id"]))
    finally:
        await db.close()
    return sorted(user_ids)


# ============ 评价聚合 / 讨论群锚 (Phase 9.5) ============


async def recalculate_teacher_review_stats(teacher_id: int) -> dict:
    """重算 teacher_channel_posts 缓存的聚合统计（spec §4.4 通过审核时触发）

    - SELECT approved teacher_reviews 聚合 6 维 + overall AVG + 三级 rating count
    - UPDATE teacher_channel_posts 同字段（保留发布相关字段不动）+ updated_at
    - 若 teacher_channel_posts 行不存在仅返回聚合字典，不写入

    Returns: 含 review_count / positive_count / neutral_count / negative_count /
             avg_overall / avg_humanphoto / avg_appearance / avg_body /
             avg_service / avg_attitude / avg_environment 的字典
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT
                COUNT(*) AS review_count,
                SUM(CASE WHEN rating='positive' THEN 1 ELSE 0 END) AS positive_count,
                SUM(CASE WHEN rating='neutral'  THEN 1 ELSE 0 END) AS neutral_count,
                SUM(CASE WHEN rating='negative' THEN 1 ELSE 0 END) AS negative_count,
                AVG(overall_score)      AS avg_overall,
                AVG(score_humanphoto)   AS avg_humanphoto,
                AVG(score_appearance)   AS avg_appearance,
                AVG(score_body)         AS avg_body,
                AVG(score_service)      AS avg_service,
                AVG(score_attitude)     AS avg_attitude,
                AVG(score_environment)  AS avg_environment
            FROM teacher_reviews
            WHERE teacher_id = ? AND status = 'approved'""",
            (teacher_id,),
        )
        row = await cur.fetchone()
        stats = {
            "review_count":     int(row["review_count"] or 0),
            "positive_count":   int(row["positive_count"] or 0),
            "neutral_count":    int(row["neutral_count"] or 0),
            "negative_count":   int(row["negative_count"] or 0),
            "avg_overall":      float(row["avg_overall"] or 0),
            "avg_humanphoto":   float(row["avg_humanphoto"] or 0),
            "avg_appearance":   float(row["avg_appearance"] or 0),
            "avg_body":         float(row["avg_body"] or 0),
            "avg_service":      float(row["avg_service"] or 0),
            "avg_attitude":     float(row["avg_attitude"] or 0),
            "avg_environment":  float(row["avg_environment"] or 0),
        }
        # 检查 teacher_channel_posts 是否存在
        cur = await db.execute(
            "SELECT teacher_id FROM teacher_channel_posts WHERE teacher_id = ?",
            (teacher_id,),
        )
        exists = await cur.fetchone()
        if exists:
            await db.execute(
                """UPDATE teacher_channel_posts SET
                    review_count = ?,
                    positive_count = ?,
                    neutral_count = ?,
                    negative_count = ?,
                    avg_overall = ?,
                    avg_humanphoto = ?,
                    avg_appearance = ?,
                    avg_body = ?,
                    avg_service = ?,
                    avg_attitude = ?,
                    avg_environment = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE teacher_id = ?""",
                (
                    stats["review_count"],
                    stats["positive_count"],
                    stats["neutral_count"],
                    stats["negative_count"],
                    stats["avg_overall"],
                    stats["avg_humanphoto"],
                    stats["avg_appearance"],
                    stats["avg_body"],
                    stats["avg_service"],
                    stats["avg_attitude"],
                    stats["avg_environment"],
                    teacher_id,
                ),
            )
            await db.commit()
        return stats
    finally:
        await db.close()


async def update_teacher_channel_post_discussion(
    teacher_id: int,
    discussion_chat_id: int,
    discussion_anchor_id: int,
) -> bool:
    """写入讨论群锚消息 id（监听器自动捕获时调用）"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE teacher_channel_posts SET "
            "discussion_chat_id = ?, discussion_anchor_id = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE teacher_id = ?",
            (discussion_chat_id, discussion_anchor_id, teacher_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def update_review_discussion_msg(
    review_id: int,
    discussion_chat_id: int,
    discussion_msg_id: int,
) -> bool:
    """评价发布到讨论群后回写 teacher_reviews 对应字段 + published_at"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE teacher_reviews SET "
            "discussion_chat_id = ?, discussion_msg_id = ?, "
            "published_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (discussion_chat_id, discussion_msg_id, review_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def find_teacher_post_by_channel_msg(
    channel_chat_id: int,
    channel_msg_id: int,
) -> Optional[dict]:
    """根据频道 chat_id + msg_id 查找老师档案帖记录（监听器用）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM teacher_channel_posts "
            "WHERE channel_chat_id = ? AND channel_msg_id = ?",
            (channel_chat_id, channel_msg_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


# ============ 详情页评价展示 (Phase 9.6) ============


async def list_approved_reviews(
    teacher_id: int, limit: int = 10, offset: int = 0,
) -> list[dict]:
    """列出某老师已通过的评价（用于详情页 / 分页列表）

    按 created_at DESC（最新在前）。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM teacher_reviews "
            "WHERE teacher_id = ? AND status = 'approved' "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ? OFFSET ?",
            (teacher_id, int(limit), int(offset)),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def count_approved_reviews(teacher_id: int) -> int:
    """统计某老师已通过的评价总数"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM teacher_reviews "
            "WHERE teacher_id = ? AND status = 'approved'",
            (teacher_id,),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


# ============ 用户「我的评价」主页（2026-05-18） ============


_VALID_USER_REVIEW_STATUS: set[str] = {"pending", "approved", "rejected"}
_VALID_USER_REVIEW_RATING: set[str] = {"positive", "neutral", "negative"}


def _normalize_user_review_filters(
    status_filter: Optional[str], rating_filter: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    s = status_filter if status_filter in _VALID_USER_REVIEW_STATUS else None
    r = rating_filter if rating_filter in _VALID_USER_REVIEW_RATING else None
    return s, r


async def count_user_reviews(
    user_id: int,
    status_filter: Optional[str] = None,
    rating_filter: Optional[str] = None,
) -> int:
    """统计某用户已提交评价总数（可叠加 status / rating 过滤）"""
    s, r = _normalize_user_review_filters(status_filter, rating_filter)
    sql = "SELECT COUNT(*) AS c FROM teacher_reviews WHERE user_id = ?"
    params: list = [int(user_id)]
    if s:
        sql += " AND status = ?"; params.append(s)
    if r:
        sql += " AND rating = ?"; params.append(r)
    db = await get_db()
    try:
        cur = await db.execute(sql, tuple(params))
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def list_user_reviews_paged(
    user_id: int,
    status_filter: Optional[str] = None,
    rating_filter: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
) -> list[dict]:
    """列出某用户自己提交的评价（用于个人评价主页）

    排序：created_at DESC（最新在前）。可叠加 status / rating 过滤。
    """
    s, r = _normalize_user_review_filters(status_filter, rating_filter)
    sql = "SELECT * FROM teacher_reviews WHERE user_id = ?"
    params: list = [int(user_id)]
    if s:
        sql += " AND status = ?"; params.append(s)
    if r:
        sql += " AND rating = ?"; params.append(r)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])
    db = await get_db()
    try:
        cur = await db.execute(sql, tuple(params))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_user_review_stats(user_id: int) -> dict:
    """返回该用户评价分布：

    {
        "total": int,
        "status": {"pending": n, "approved": n, "rejected": n},
        "rating_approved": {"positive": n, "neutral": n, "negative": n},
            (仅统计 status='approved' 的评级分布；驳回的不计入)
    }
    """
    db = await get_db()
    try:
        # 总数 + status 分布
        cur = await db.execute(
            "SELECT status, COUNT(*) AS c FROM teacher_reviews "
            "WHERE user_id = ? GROUP BY status",
            (int(user_id),),
        )
        rows = await cur.fetchall()
        status_count = {"pending": 0, "approved": 0, "rejected": 0}
        total = 0
        for row in rows:
            total += int(row["c"])
            st = row["status"]
            if st in status_count:
                status_count[st] = int(row["c"])

        # approved 评级分布
        cur = await db.execute(
            "SELECT rating, COUNT(*) AS c FROM teacher_reviews "
            "WHERE user_id = ? AND status = 'approved' GROUP BY rating",
            (int(user_id),),
        )
        rows = await cur.fetchall()
        rating_count = {"positive": 0, "neutral": 0, "negative": 0}
        for row in rows:
            rt = row["rating"]
            if rt in rating_count:
                rating_count[rt] = int(row["c"])

        return {
            "total": total,
            "status": status_count,
            "rating_approved": rating_count,
        }
    finally:
        await db.close()


async def get_teachers_by_ids(user_ids: list[int]) -> dict[int, dict]:
    """批量取 teachers（按 user_id 主键）→ {teacher_id: dict}

    用于 Phase P.2 积分明细页反查老师名 / Phase P.3 等批量场景。
    不存在的 id 不会在 dict 中。
    """
    if not user_ids:
        return {}
    db = await get_db()
    try:
        placeholders = ",".join("?" * len(user_ids))
        cur = await db.execute(
            f"SELECT * FROM teachers WHERE user_id IN ({placeholders})",
            user_ids,
        )
        rows = await cur.fetchall()
        return {int(r["user_id"]): dict(r) for r in rows}
    finally:
        await db.close()


async def get_users_first_names(user_ids: list[int]) -> dict[int, Optional[str]]:
    """批量取 users.first_name → 用于详情页评价半匿名签名

    Returns: {user_id: first_name or None}；不存在的 user_id 不在 dict 中。
    """
    if not user_ids:
        return {}
    db = await get_db()
    try:
        # 注意：sqlite 不接受空 placeholder 列表，上面已 guard
        placeholders = ",".join("?" * len(user_ids))
        cur = await db.execute(
            f"SELECT user_id, first_name FROM users WHERE user_id IN ({placeholders})",
            user_ids,
        )
        rows = await cur.fetchall()
        return {int(r["user_id"]): r["first_name"] for r in rows}
    finally:
        await db.close()


# ============ 积分 (Phase P.1) ============


# 审核通过加分预设套餐（spec §1.2）
POINT_PACKAGE_OPTIONS: list[dict] = [
    {"key": "p",     "label": "P / PP",  "delta": 1},
    {"key": "hour",  "label": "包时",     "delta": 3},
    {"key": "night", "label": "包夜",     "delta": 5},
    {"key": "day",   "label": "包天",     "delta": 8},
    {"key": "zero",  "label": "不加分",   "delta": 0},
]

# 自定义加分输入范围（spec §4.3）
POINT_CUSTOM_MIN: int = 0
POINT_CUSTOM_MAX: int = 100


async def add_point_transaction(
    user_id: int,
    delta: int,
    reason: str,
    *,
    related_id: Optional[int] = None,
    operator_id: Optional[int] = None,
    note: Optional[str] = None,
) -> Optional[int]:
    """添加一条积分流水，同时同步 users.total_points

    Args:
        user_id: 评价者 user_id
        delta: 整数；正数加分，负数扣分（本期不开放扣分 UI，DB 层允许）
        reason: 'review_approved' / 'admin_grant' / 'admin_revoke' / ...
        related_id: 关联 review_id 等业务 id
        operator_id: 操作管理员 id（None 表示系统自动）
        note: 备注（手动加分时填）

    Returns:
        tx_id（成功） / None（失败：DB 异常或参数错误）

    容错：user 不在 users 表时 INSERT OR IGNORE 一条 minimal row。
    """
    try:
        delta_int = int(delta)
    except (TypeError, ValueError):
        return None
    if not reason:
        return None

    db = await get_db()
    try:
        # 兜底：user 可能不在 users 表（最早评价者从未进过 /start）
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )
        cur = await db.execute(
            """INSERT INTO point_transactions
                (user_id, delta, reason, related_id, operator_id, note)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, delta_int, reason, related_id, operator_id, note),
        )
        tx_id = cur.lastrowid
        # 同步 users.total_points（COALESCE 兼容老数据 NULL）
        await db.execute(
            "UPDATE users SET total_points = COALESCE(total_points, 0) + ? "
            "WHERE user_id = ?",
            (delta_int, user_id),
        )
        await db.commit()
        return tx_id
    except Exception as e:
        logger.warning(
            "add_point_transaction 失败 user=%s delta=%s reason=%s: %s",
            user_id, delta_int, reason, e,
        )
        return None
    finally:
        await db.close()


async def get_user_total_points(user_id: int) -> int:
    """获取用户当前 total_points（不存在 / NULL 时返回 0）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT total_points FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        if not row:
            return 0
        v = row["total_points"]
        return int(v) if v is not None else 0
    finally:
        await db.close()


async def get_user_points_summary(user_id: int) -> dict:
    """积分汇总：total / earned (SUM positive) / spent (ABS SUM negative) / tx_count"""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT
                COALESCE(SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END), 0) AS earned,
                COALESCE(SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END), 0) AS spent,
                COUNT(*) AS tx_count
            FROM point_transactions WHERE user_id = ?""",
            (user_id,),
        )
        row = await cur.fetchone()
        earned = int(row["earned"] or 0) if row else 0
        spent = int(row["spent"] or 0) if row else 0
        tx_count = int(row["tx_count"] or 0) if row else 0
        # total 用 users.total_points（防止应用层 / DB 层不一致时优先 users）
        cur = await db.execute(
            "SELECT total_points FROM users WHERE user_id = ?", (user_id,)
        )
        u_row = await cur.fetchone()
        total = int((u_row["total_points"] if u_row else 0) or 0)
    finally:
        await db.close()
    return {
        "total": total,
        "earned": earned,
        "spent": spent,
        "tx_count": tx_count,
    }


async def list_user_point_transactions(
    user_id: int, limit: int = 20, offset: int = 0,
) -> list[dict]:
    """列出某用户的积分流水（按 created_at DESC, id DESC）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM point_transactions WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (user_id, int(limit), int(offset)),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def count_user_point_transactions(user_id: int) -> int:
    """统计某用户的积分流水总数（用于分页）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM point_transactions WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def find_user_by_username(username: str) -> Optional[dict]:
    """通过 @username（或裸 username）查找用户

    自动 lstrip "@"；LOWER 不区分大小写比对（spec §3.2 手动加分输入）。
    返回完整 users row 或 None。
    """
    if not username:
        return None
    name = str(username).strip().lstrip("@")
    if not name:
        return None
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?) LIMIT 1",
            (name,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


# ============ 积分管理（Phase P.3） ============


# 手动加扣分原因预设（spec §3.2）
POINT_GRANT_REASON_OPTIONS: list[dict] = [
    {"key": "audit",   "label": "📝 报告审核补加", "reason": "admin_grant",  "note": "报告审核补加"},
    {"key": "event",   "label": "🎁 活动奖励",     "reason": "admin_grant",  "note": "活动奖励"},
    {"key": "violate", "label": "⚠️ 违规扣分",     "reason": "admin_revoke", "note": "违规扣分"},
    {"key": "fix",     "label": "🛠 系统修正",     "reason": "admin_grant",  "note": "系统修正"},
]


async def get_top_points_users(limit: int = 10) -> list[dict]:
    """TOP N 持币用户（仅 total_points > 0），按 DESC"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT user_id, username, first_name, total_points "
            "FROM users WHERE total_points > 0 "
            "ORDER BY total_points DESC, user_id LIMIT ?",
            (int(limit),),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def count_users_with_points() -> int:
    """持币用户数（total_points > 0）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE total_points > 0"
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def sum_total_points_earned() -> int:
    """累计加分总和（所有 delta > 0 的 point_transactions）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COALESCE(SUM(delta), 0) AS s FROM point_transactions WHERE delta > 0"
        )
        row = await cur.fetchone()
        return int(row["s"]) if row else 0
    finally:
        await db.close()



# ============ 报销子系统 ============


def compute_reimbursement_amount(price: Optional[str]) -> int:
    """根据老师 price 字段（如 '1000P' / '900P'）返回报销金额（元）

    规则（按 displayed price = digits // 100）：
        displayed <= 0  → 0（不报销）
        displayed <= 8  → 100
        displayed == 9  → 150
        displayed >= 10 → 200
        无法解析 → 0
    """
    if price is None:
        return 0
    s = str(price).strip()
    if not s:
        return 0
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return 0
    hundreds = int(digits) // 100
    if hundreds <= 0:
        return 0
    if hundreds <= 8:
        return 100
    if hundreds == 9:
        return 150
    return 200


def current_week_key(now=None) -> str:
    """返回 ISO 周 key 'YYYY-Www'（如 '2026-W20'）"""
    from datetime import datetime
    from pytz import timezone as _tz
    if now is None:
        now = datetime.now(_tz(config.timezone))
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def current_month_key(now=None) -> str:
    """返回 'YYYY-MM'"""
    from datetime import datetime
    from pytz import timezone as _tz
    if now is None:
        now = datetime.now(_tz(config.timezone))
    return now.strftime("%Y-%m")


async def create_reimbursement(
    user_id: int,
    review_id: int,
    teacher_id: int,
    amount: int,
    week_key: str,
    month_key: str,
    status: str = "pending",
) -> Optional[int]:
    """创建报销记录；UNIQUE(review_id) 冲突返 None

    status：默认 'pending'（admin 审核队列可见）。功能关闭时传 'queued'
    （admin 名单可见，不进 pending 队列）。
    """
    if status not in ("pending", "queued"):
        logger.warning("create_reimbursement status 非法: %s", status)
        return None
    db = await get_db()
    try:
        try:
            cur = await db.execute(
                """INSERT INTO reimbursements
                (user_id, review_id, teacher_id, amount, status, week_key, month_key)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (int(user_id), int(review_id), int(teacher_id),
                 int(amount), status, week_key, month_key),
            )
        except Exception as e:
            logger.warning("create_reimbursement 失败: %s", e)
            return None
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def count_queued_reimbursements() -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM reimbursements WHERE status = 'queued'"
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def list_queued_reimbursements_paged(
    limit: int = 20, offset: int = 0,
) -> list[dict]:
    """admin 查看「报销名单」分页（功能关闭期间静默录入的）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM reimbursements WHERE status = 'queued' "
            "ORDER BY created_at ASC, id ASC LIMIT ? OFFSET ?",
            (int(limit), int(offset)),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def activate_queued_reimbursement(reimb_id: int) -> bool:
    """把 queued → pending（admin 在「报销名单」点激活时调用）"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE reimbursements SET status = 'pending' "
            "WHERE id = ? AND status = 'queued'",
            (int(reimb_id),),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def get_reimbursement(reimb_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM reimbursements WHERE id = ?", (int(reimb_id),),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_reimbursement_by_review(review_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM reimbursements WHERE review_id = ?", (int(review_id),),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def count_pending_reimbursements() -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM reimbursements WHERE status = 'pending'"
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def list_pending_reimbursements(limit: int = 50) -> list[dict]:
    """按 created_at ASC 取 pending（先来先审）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM reimbursements WHERE status = 'pending' "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            (int(limit),),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def count_approved_reimbursements_in_week(
    user_id: int, week_key: str,
) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM reimbursements "
            "WHERE user_id = ? AND week_key = ? AND status = 'approved'",
            (int(user_id), week_key),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def sum_approved_reimbursements_in_month(month_key: str) -> int:
    """当月已批准报销总额（元）；用于池配额校验"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM reimbursements "
            "WHERE month_key = ? AND status = 'approved'",
            (month_key,),
        )
        row = await cur.fetchone()
        return int(row["s"]) if row else 0
    finally:
        await db.close()


async def approve_reimbursement(reimb_id: int, admin_id: int) -> bool:
    """仅 pending → approved；返回是否生效"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE reimbursements SET status = 'approved', "
            "decided_at = CURRENT_TIMESTAMP, decided_by = ? "
            "WHERE id = ? AND status = 'pending'",
            (int(admin_id), int(reimb_id)),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def reject_reimbursement(
    reimb_id: int, admin_id: int, reason: str,
) -> bool:
    """仅 pending → rejected；返回是否生效"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE reimbursements SET status = 'rejected', "
            "decided_at = CURRENT_TIMESTAMP, decided_by = ?, reject_reason = ? "
            "WHERE id = ? AND status = 'pending'",
            (int(admin_id), str(reason), int(reimb_id)),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def mark_reimbursement_notified(reimb_id: int) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE reimbursements SET notified_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (int(reimb_id),),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def list_user_reimbursements_paged(
    user_id: int, limit: int = 20, offset: int = 0,
) -> list[dict]:
    """用户「我的报销」分页（按 created_at DESC）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM reimbursements WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (int(user_id), int(limit), int(offset)),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def count_user_reimbursements(user_id: int) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM reimbursements WHERE user_id = ?",
            (int(user_id),),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def grant_reimbursement_reset(user_id: int, admin_id: int) -> Optional[int]:
    """超管给某用户发一张「本周报销额度」一次性 voucher；返回 reset_id"""
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO reimbursement_resets (user_id, granted_by) VALUES (?, ?)",
            (int(user_id), int(admin_id)),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def get_unused_reimbursement_reset(user_id: int) -> Optional[dict]:
    """取该用户最早一张未消耗的 reset voucher"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM reimbursement_resets "
            "WHERE user_id = ? AND consumed = 0 "
            "ORDER BY id ASC LIMIT 1",
            (int(user_id),),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def consume_reimbursement_reset(reset_id: int, reimb_id: int) -> bool:
    """消耗一张 reset voucher（绑到某条 reimbursement）"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE reimbursement_resets SET consumed = 1, "
            "consumed_at = CURRENT_TIMESTAMP, consumed_reimb_id = ? "
            "WHERE id = ? AND consumed = 0",
            (int(reimb_id), int(reset_id)),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


# ============ 报销专用必关频道 / 群组（与全局 subreq 分离） ============
#
# 数据存储：复用既有 config 表，key = "reimbursement_required_chats"
# 值格式：JSON array of dict，字段 chat_id / chat_type / display_name / invite_link / enabled
# 设计要点：
#   - 与全局 required_subscriptions 表完全独立，互不影响
#   - 解析失败 / key 不存在 → 返回空列表（=报销流程不拦截）
#   - 写操作必须由 caller 配套 log_admin_audit（在 handler 层调用）
#   - 不新增表 / 不新增 schema migration（spec 优先 config）

REIMBURSE_REQUIRED_CHATS_KEY = "reimbursement_required_chats"


async def get_reimburse_required_chats() -> list[dict]:
    """读取报销专用必关频道 / 群组配置。

    返回 list[dict]，每条含：chat_id(int) / chat_type / display_name /
    invite_link / enabled(bool)。

    config 缺失、JSON 解析失败、字段类型异常时一律返回空列表（=不拦截报销）。
    """
    raw = await get_config(REIMBURSE_REQUIRED_CHATS_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning(
            "get_reimburse_required_chats: JSON 解析失败 raw=%r: %s", raw, e,
        )
        return []
    if not isinstance(data, list):
        logger.warning(
            "get_reimburse_required_chats: 数据不是 list，类型=%s", type(data).__name__,
        )
        return []
    result: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            chat_id = int(item.get("chat_id"))
        except (TypeError, ValueError):
            continue
        result.append({
            "chat_id": chat_id,
            "chat_type": str(item.get("chat_type") or ""),
            "display_name": str(item.get("display_name") or ""),
            "invite_link": str(item.get("invite_link") or ""),
            "enabled": bool(item.get("enabled", True)),
        })
    return result


async def set_reimburse_required_chats(chats: list[dict]) -> None:
    """覆盖写入报销专用必关频道 / 群组配置（caller 应在调用前做去重 / 校验）。"""
    serializable = [
        {
            "chat_id": int(c["chat_id"]),
            "chat_type": str(c.get("chat_type") or ""),
            "display_name": str(c.get("display_name") or ""),
            "invite_link": str(c.get("invite_link") or ""),
            "enabled": bool(c.get("enabled", True)),
        }
        for c in chats
    ]
    await set_config(
        REIMBURSE_REQUIRED_CHATS_KEY,
        json.dumps(serializable, ensure_ascii=False),
    )


async def add_reimburse_required_chat(
    chat_id: int,
    chat_type: str,
    display_name: str,
    invite_link: str,
) -> bool:
    """新增一项报销必关配置；如 chat_id 已存在则返回 False（不覆盖）。

    成功写入返回 True。caller 负责调用 log_admin_audit 记录动作。
    """
    chats = await get_reimburse_required_chats()
    if any(c["chat_id"] == int(chat_id) for c in chats):
        return False
    chats.append({
        "chat_id": int(chat_id),
        "chat_type": str(chat_type or ""),
        "display_name": str(display_name or ""),
        "invite_link": str(invite_link or ""),
        "enabled": True,
    })
    await set_reimburse_required_chats(chats)
    return True


async def remove_reimburse_required_chat(chat_id: int) -> bool:
    """删除指定 chat_id 的报销必关项。

    返回 True 表示有条目被删除；False 表示原列表中没有匹配项。
    caller 负责调用 log_admin_audit 记录动作。
    """
    chats = await get_reimburse_required_chats()
    new_chats = [c for c in chats if c["chat_id"] != int(chat_id)]
    if len(new_chats) == len(chats):
        return False
    await set_reimburse_required_chats(new_chats)
    return True


# ============ 报销门槛 + 报销池重置基线（2026-05 新增） ============
#
# 设计要点：
#   - 报销门槛 reimbursement_min_points：复用既有 config key（之前各 handler
#     就读这个 key，fallback 硬编码 5）；本批新增 get/set helper 统一口径，
#     并把后台 UI 接上 set
#   - 月度报销池"重置基线"：新增 config key
#     reimbursement_monthly_pool_reset_baselines（JSON object，月份 → 基线明细）
#     不动 reimbursements 表，不改任何历史记录
#   - get_reimbursement_monthly_pool_usage(month_key) 是唯一 effective_used 口径
#     —— admin_reimburse.py 审批月池校验 + reimbursement_pool service 状态页
#     都必须用它

REIMBURSE_MIN_POINTS_KEY = "reimbursement_min_points"
REIMBURSE_MIN_POINTS_DEFAULT = 5
REIMBURSE_MIN_POINTS_MAX = 100  # 上限（防止误操作输入过大值）

REIMBURSE_POOL_RESET_BASELINES_KEY = "reimbursement_monthly_pool_reset_baselines"


async def get_reimbursement_min_points() -> int:
    """读取报销最低积分门槛；缺失 / 解析失败 / 越界 → 默认 5。

    0 表示"不启用门槛"，是合法值；上限 REIMBURSE_MIN_POINTS_MAX。
    """
    raw = await get_config(REIMBURSE_MIN_POINTS_KEY)
    if raw is None or raw == "":
        return REIMBURSE_MIN_POINTS_DEFAULT
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return REIMBURSE_MIN_POINTS_DEFAULT
    if v < 0 or v > REIMBURSE_MIN_POINTS_MAX:
        return REIMBURSE_MIN_POINTS_DEFAULT
    return v


async def set_reimbursement_min_points(value: int) -> None:
    """写入报销最低积分门槛；caller 必须先校验 0 <= value <= REIMBURSE_MIN_POINTS_MAX。"""
    v = int(value)
    if v < 0 or v > REIMBURSE_MIN_POINTS_MAX:
        raise ValueError(
            f"reimbursement_min_points must be in [0, {REIMBURSE_MIN_POINTS_MAX}], got {v}"
        )
    await set_config(REIMBURSE_MIN_POINTS_KEY, str(v))


# ---- 每周 approved 报销上限（2026-05 新增，原 POLICY §6.1 硬编码 1 次/周）----
REIMBURSE_WEEKLY_LIMIT_KEY = "reimbursement_weekly_limit"
REIMBURSE_WEEKLY_LIMIT_DEFAULT = 1
REIMBURSE_WEEKLY_LIMIT_MIN = 1
REIMBURSE_WEEKLY_LIMIT_MAX = 10


async def get_reimbursement_weekly_limit() -> int:
    """读取每用户每 ISO 周 approved 报销上限；缺失 / 解析失败 / 越界 → 默认 1。

    范围 [REIMBURSE_WEEKLY_LIMIT_MIN, REIMBURSE_WEEKLY_LIMIT_MAX]（1-10）；
    与月度池 0=不限的语义不同，本配置不允许 0（避免与 reset voucher 语义冲突）。
    """
    raw = await get_config(REIMBURSE_WEEKLY_LIMIT_KEY)
    if raw is None or raw == "":
        return REIMBURSE_WEEKLY_LIMIT_DEFAULT
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return REIMBURSE_WEEKLY_LIMIT_DEFAULT
    if v < REIMBURSE_WEEKLY_LIMIT_MIN or v > REIMBURSE_WEEKLY_LIMIT_MAX:
        return REIMBURSE_WEEKLY_LIMIT_DEFAULT
    return v


async def set_reimbursement_weekly_limit(value: int) -> None:
    """写入每周报销上限；caller 必须先校验
    REIMBURSE_WEEKLY_LIMIT_MIN <= value <= REIMBURSE_WEEKLY_LIMIT_MAX。"""
    v = int(value)
    if v < REIMBURSE_WEEKLY_LIMIT_MIN or v > REIMBURSE_WEEKLY_LIMIT_MAX:
        raise ValueError(
            f"reimbursement_weekly_limit must be in "
            f"[{REIMBURSE_WEEKLY_LIMIT_MIN}, {REIMBURSE_WEEKLY_LIMIT_MAX}], got {v}"
        )
    await set_config(REIMBURSE_WEEKLY_LIMIT_KEY, str(v))


# ---- 评价 footer 推广（2026-05 新增，原硬编码"出击报销八折" + URL）----
REIMBURSE_PROMO_TEXT_KEY = "reimbursement_promo_text"
REIMBURSE_PROMO_URL_KEY = "reimbursement_promo_url"
REIMBURSE_PROMO_TEXT_DEFAULT = "出击报销八折"
REIMBURSE_PROMO_URL_DEFAULT = "https://t.me/ChiYanDairy/553"
REIMBURSE_PROMO_TEXT_MAX_LEN = 100
REIMBURSE_PROMO_URL_MAX_LEN = 500


async def get_reimburse_promo_text() -> str:
    """读取评价 footer 推广文本；缺失返回默认。

    允许空字符串 "" 表示「不渲染 footer」（caller 在 render 阶段判断）。
    """
    raw = await get_config(REIMBURSE_PROMO_TEXT_KEY)
    if raw is None:
        return REIMBURSE_PROMO_TEXT_DEFAULT
    return raw  # 允许 ""（语义：不渲染整行）


async def get_reimburse_promo_url() -> str:
    """读取评价 footer 推广 URL；缺失返回默认。

    允许空字符串 "" 表示「不渲染 footer」（caller 在 render 阶段判断）。
    """
    raw = await get_config(REIMBURSE_PROMO_URL_KEY)
    if raw is None:
        return REIMBURSE_PROMO_URL_DEFAULT
    return raw  # 允许 ""


async def set_reimburse_promo_text(value: str) -> None:
    """写入推广文本；caller 必须先校验长度 / 内容（空串合法）。"""
    v = str(value or "")
    if len(v) > REIMBURSE_PROMO_TEXT_MAX_LEN:
        raise ValueError(
            f"reimbursement_promo_text must be ≤ {REIMBURSE_PROMO_TEXT_MAX_LEN} chars, "
            f"got {len(v)}"
        )
    await set_config(REIMBURSE_PROMO_TEXT_KEY, v)


async def set_reimburse_promo_url(value: str) -> None:
    """写入推广 URL；caller 必须先校验长度 + http(s):// 前缀（空串合法 = 禁用）。"""
    v = str(value or "")
    if len(v) > REIMBURSE_PROMO_URL_MAX_LEN:
        raise ValueError(
            f"reimbursement_promo_url must be ≤ {REIMBURSE_PROMO_URL_MAX_LEN} chars, "
            f"got {len(v)}"
        )
    if v and not (v.startswith("http://") or v.startswith("https://")):
        raise ValueError(
            f"reimbursement_promo_url must start with http:// or https://, got {v!r}"
        )
    await set_config(REIMBURSE_PROMO_URL_KEY, v)


async def get_reimburse_pool_reset_baselines() -> dict:
    """读取月度报销池重置基线 dict（月份 → {baseline_amount, reset_at, admin_id, reason}）。

    config 缺失 / JSON 解析失败 / 非 dict → 返回 {} （= 无任何月份有 baseline）。
    单项字段缺失 / 异常时跳过该项（容错）。
    """
    raw = await get_config(REIMBURSE_POOL_RESET_BASELINES_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning(
            "get_reimburse_pool_reset_baselines: JSON 解析失败 raw=%r: %s", raw, e,
        )
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "get_reimburse_pool_reset_baselines: 数据不是 dict，类型=%s",
            type(data).__name__,
        )
        return {}
    out: dict = {}
    for month_key, entry in data.items():
        if not isinstance(month_key, str) or not isinstance(entry, dict):
            continue
        try:
            baseline_amount = int(entry.get("baseline_amount") or 0)
        except (TypeError, ValueError):
            continue
        out[month_key] = {
            "baseline_amount": baseline_amount,
            "reset_at": str(entry.get("reset_at") or ""),
            "admin_id": int(entry["admin_id"]) if entry.get("admin_id") else None,
            "reason": str(entry.get("reason") or ""),
        }
    return out


async def set_reimburse_pool_reset_baseline(
    month_key: str,
    *,
    baseline_amount: int,
    admin_id: int,
    reason: str,
    reset_at: Optional[str] = None,
) -> dict:
    """新增 / 覆盖某月份的 reset baseline。

    返回写入后的该月份明细 dict（含 reset_at 时间戳）。
    caller 应在调用前已通过二次确认；本函数仅做存储，不做权限校验，
    caller 负责 log_admin_audit。
    """
    import datetime as _dt
    baselines = await get_reimburse_pool_reset_baselines()
    entry = {
        "baseline_amount": int(baseline_amount),
        "reset_at": reset_at or _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "admin_id": int(admin_id),
        "reason": str(reason or ""),
    }
    baselines[str(month_key)] = entry
    await set_config(
        REIMBURSE_POOL_RESET_BASELINES_KEY,
        json.dumps(baselines, ensure_ascii=False),
    )
    return entry


async def get_reimbursement_monthly_pool_usage(month_key: str) -> dict:
    """**唯一** effective_used 口径——审批月池校验 + 状态页都必须用本函数。

    返回 dict 含：
        raw_used (int)         —— 本月 approved 总额（直接来自 reimbursements）
        reset_baseline (int)   —— 本月 reset baseline（无重置则 0）
        effective_used (int)   —— max(0, raw_used - reset_baseline)

    raw_used 查询失败 → 视为 0；baseline 缺失 → 视为 0；都是容错语义。
    """
    raw_used: int = 0
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM reimbursements "
            "WHERE month_key = ? AND status = 'approved'",
            (str(month_key),),
        )
        row = await cursor.fetchone()
        if row is not None and row[0] is not None:
            raw_used = int(row[0])
    except Exception as e:
        logger.warning(
            "get_reimbursement_monthly_pool_usage: raw_used 查询失败 month=%s: %s",
            month_key, e,
        )
    finally:
        await db.close()
    baselines = await get_reimburse_pool_reset_baselines()
    entry = baselines.get(str(month_key))
    reset_baseline = int(entry["baseline_amount"]) if entry else 0
    effective_used = max(0, raw_used - reset_baseline)
    return {
        "raw_used": raw_used,
        "reset_baseline": reset_baseline,
        "effective_used": effective_used,
    }

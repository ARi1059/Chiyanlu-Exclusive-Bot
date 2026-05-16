from __future__ import annotations

import json
import logging
from typing import Optional

import aiosqlite
import os
from bot.config import config

logger = logging.getLogger(__name__)


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接"""
    os.makedirs(os.path.dirname(config.database_path), exist_ok=True)
    db = await aiosqlite.connect(config.database_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
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
                gesture_photo_file_id       TEXT NOT NULL,
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
                CHECK (prize_count BETWEEN 1 AND 1000)
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

        await db.commit()
    finally:
        await db.close()


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
    "{grouped_teachers}\n\n"
    "点击下方按钮查看详情。"
)


async def _ensure_default_publish_template(db: aiosqlite.Connection) -> None:
    """Phase 6.2：若没有"默认且启用"的模板则插入一条（幂等，不覆盖管理员配置）"""
    try:
        cur = await db.execute(
            "SELECT 1 FROM publish_templates "
            "WHERE is_default = 1 AND is_active = 1 LIMIT 1"
        )
        row = await cur.fetchone()
        if row:
            return
        await db.execute(
            """INSERT INTO publish_templates
               (name, template_text, is_default, is_active)
               VALUES (?, ?, 1, 1)""",
            ("默认模板", DEFAULT_PUBLISH_TEMPLATE_TEXT),
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


async def get_all_teachers(active_only: bool = True) -> list[dict]:
    """获取所有老师"""
    db = await get_db()
    try:
        query = "SELECT * FROM teachers"
        if active_only:
            query += " WHERE is_active = 1"
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
            "SELECT * FROM teachers WHERE display_name = ? AND is_active = 1 COLLATE NOCASE",
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
            WHERE is_active = 1 AND (
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
            "SELECT region, price, tags FROM teachers WHERE is_active = 1"
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
            "SELECT * FROM teachers WHERE is_active = 1 AND "
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
            WHERE c.checkin_date = ? AND t.is_active = 1
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
            WHERE t.is_active = 1
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
            FROM teachers"""
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
               WHERE f.user_id = ?"""
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
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT t.*
               FROM favorites f
               INNER JOIN teachers t ON f.teacher_id = t.user_id
               INNER JOIN checkins c ON t.user_id = c.teacher_id
               WHERE f.user_id = ?
                 AND c.checkin_date = ?
                 AND t.is_active = 1
               ORDER BY c.created_at""",
            (user_id, date_str),
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
            "FROM teachers"
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
               WHERE v.user_id = ? AND t.is_active = 1
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
               WHERE t.is_active = 1
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

    Returns:
        teachers list，每条带:
            fav_count / effective_featured / signed_in_today
            daily_status / daily_available_time / daily_note  (Phase 5)
    """
    today_str = _today_str_local()
    sign_date = signed_in_date or today_str

    where_clauses: list[str] = []
    if active_only:
        where_clauses.append("t.is_active = 1")
    if signed_in_date is not None:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM checkins c "
            "WHERE c.teacher_id = t.user_id AND c.checkin_date = ?)"
        )
    if exclude_unavailable:
        where_clauses.append("(s.status IS NULL OR s.status != 'unavailable')")

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


async def get_hot_teachers(limit: int = 10) -> list[dict]:
    """普通用户"热门老师"列表：按统一排序取前 N 位 active 老师

    不要求今日签到（与频道发布不同），目的是给用户提供长期可见的推荐。
    """
    return await get_sorted_teachers(
        active_only=True,
        signed_in_date=None,
        limit=limit,
    )


async def list_featured_teachers() -> list[dict]:
    """列出所有 is_featured=1 的老师（含已过期），供管理员后台展示

    管理员需要看到全部推荐状态以便取消 / 修改，所以这里不过滤过期。
    用 is_effective_featured(t, today_str) 在展示时区分"有效推荐" / "已过期"。
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM teachers "
            "WHERE is_featured = 1 "
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


async def get_source_stats(limit: int = 20) -> list[dict]:
    """渠道统计：按用户数倒序返回 TOP 来源（Phase 4 §二）

    返回每条:
        source_type / source_id / source_name / user_count / last_seen_at
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT source_type, source_id,
                   MAX(source_name) AS source_name,
                   COUNT(DISTINCT user_id) AS user_count,
                   MAX(last_seen_at) AS last_seen_at
               FROM user_sources
               GROUP BY source_type, source_id
               ORDER BY user_count DESC, last_seen_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_top_sources_by_type(source_type: str, limit: int = 10) -> list[dict]:
    """指定 source_type 的 TOP N source_id（Phase 4 §二）"""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT source_type, source_id,
                   MAX(source_name) AS source_name,
                   COUNT(DISTINCT user_id) AS user_count,
                   MAX(last_seen_at) AS last_seen_at
               FROM user_sources
               WHERE source_type = ?
               GROUP BY source_id
               ORDER BY user_count DESC, last_seen_at DESC
               LIMIT ?""",
            (source_type, limit),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_user_source_summary(user_id: int) -> Optional[dict]:
    """某个用户的首次 / 最近来源 + 全量来源记录（Phase 4 §二）"""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT first_source_type, first_source_id,
                      last_source_type, last_source_id
               FROM users WHERE user_id = ?""",
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None

        cur = await db.execute(
            """SELECT source_type, source_id, source_name,
                      first_seen_at, last_seen_at, raw_payload
               FROM user_sources
               WHERE user_id = ?
               ORDER BY first_seen_at""",
            (user_id,),
        )
        sources = [dict(r) for r in await cur.fetchall()]

        return {
            "user_id": user_id,
            "first_source_type": row["first_source_type"],
            "first_source_id": row["first_source_id"],
            "last_source_type": row["last_source_type"],
            "last_source_id": row["last_source_id"],
            "sources": sources,
        }
    finally:
        await db.close()


async def count_total_source_users() -> int:
    """来源覆盖的去重用户数（用于渠道统计页头部）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM user_sources"
        )
        row = await cur.fetchone()
        return int(row["n"] or 0) if row else 0
    finally:
        await db.close()


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
    where = "1=1"
    if active_only:
        where = "t.is_active = 1"

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


# ============ 条件筛选 / 智能推荐 (Phase 7.2) ============


async def get_filter_options(
    option_type: str,
    limit: int = 12,
) -> list[dict]:
    """统计当前 active 老师的某维度可选值（Phase 7.2 §四）

    支持类型：
        - region : SELECT region, COUNT(*) GROUP BY region
        - price  : SELECT price, COUNT(*) GROUP BY price
        - tag    : 拆 tags JSON 后聚合

    返回 [{"value": str, "count": int}, ...] 按 count DESC，limit 限制条数。
    类型不支持、teachers 表缺失、SQL 异常 → 返回 []。
    """
    if option_type not in {"region", "price", "tag"}:
        return []
    if limit <= 0:
        return []

    db = await get_db()
    try:
        if option_type == "tag":
            cur = await db.execute(
                """SELECT LOWER(TRIM(je.value)) AS value, COUNT(*) AS n
                   FROM teachers t, json_each(t.tags) je
                   WHERE t.is_active = 1
                     AND je.value IS NOT NULL
                     AND TRIM(je.value) != ''
                   GROUP BY LOWER(TRIM(je.value))
                   ORDER BY n DESC, value ASC
                   LIMIT ?""",
                (limit,),
            )
        else:
            col = option_type  # 已校验白名单
            cur = await db.execute(
                f"""SELECT {col} AS value, COUNT(*) AS n
                    FROM teachers
                    WHERE is_active = 1
                      AND {col} IS NOT NULL
                      AND TRIM({col}) != ''
                    GROUP BY {col}
                    ORDER BY n DESC, {col} ASC
                    LIMIT ?""",
                (limit,),
            )
        rows = await cur.fetchall()
        return [
            {"value": str(r["value"]), "count": int(r["n"] or 0)}
            for r in rows if r["value"] is not None
        ]
    except Exception as e:
        logger.warning("get_filter_options(%s) 失败: %s", option_type, e)
        return []
    finally:
        await db.close()


async def search_teachers_by_filter(
    filter_type: str,
    value: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """根据筛选维度返回 active 老师列表（Phase 7.2 §四）

    filter_type:
        - region / price / tag : 需要 value，按值匹配（COLLATE NOCASE）
        - today                : 当天已签到 + status != unavailable
        - hot                  : 复用 get_hot_teachers
        - new                  : 按 created_at DESC

    返回项尽量带 daily_status / signed_in_today / fav_count，供结果页渲染。
    任何异常路径都做兼容降级，不抛。
    """
    if limit <= 0:
        return []

    today_str = _today_str_local()

    # --- hot ---
    if filter_type == "hot":
        try:
            return await get_hot_teachers(limit=limit)
        except Exception as e:
            logger.warning("get_hot_teachers 失败，降级到 active 老师: %s", e)
            try:
                fallback = await get_all_teachers(active_only=True)
                return fallback[:limit]
            except Exception:
                return []

    # --- today ---
    if filter_type == "today":
        try:
            return await get_sorted_teachers(
                active_only=True,
                signed_in_date=today_str,
                exclude_unavailable=True,
                limit=limit,
            )
        except Exception as e:
            logger.warning("get_sorted_teachers(today) 失败，降级 checkins: %s", e)
            try:
                rows = await get_checked_in_teachers(today_str)
                return rows[:limit]
            except Exception:
                return []

    # --- new ---
    if filter_type == "new":
        db = await get_db()
        try:
            cur = await db.execute(
                """SELECT t.*,
                          (SELECT COUNT(*) FROM favorites f
                           WHERE f.teacher_id = t.user_id) AS fav_count,
                          CASE WHEN EXISTS (
                              SELECT 1 FROM checkins c
                              WHERE c.teacher_id = t.user_id
                                AND c.checkin_date = ?
                          ) THEN 1 ELSE 0 END AS signed_in_today,
                          s.status AS daily_status,
                          s.available_time AS daily_available_time,
                          s.note AS daily_note
                     FROM teachers t
                     LEFT JOIN teacher_daily_status s
                       ON s.teacher_id = t.user_id AND s.status_date = ?
                    WHERE t.is_active = 1
                    ORDER BY t.created_at DESC
                    LIMIT ?""",
                (today_str, today_str, limit),
            )
            return [dict(r) for r in await cur.fetchall()]
        except Exception as e:
            logger.warning("search by 'new' 失败，降级到 created_at: %s", e)
            try:
                cur = await db.execute(
                    "SELECT * FROM teachers WHERE is_active = 1 "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                return [dict(r) for r in await cur.fetchall()]
            except Exception:
                return []
        finally:
            await db.close()

    # --- region / price / tag ---
    if filter_type in ("region", "price", "tag"):
        if value is None or not str(value).strip():
            return []
        v_lower = str(value).strip().lower()

        # 拿全量带 daily_status 的排序结果，再 Python 端按 value 过滤
        try:
            all_sorted = await get_sorted_teachers(active_only=True)
        except Exception as e:
            logger.warning("get_sorted_teachers 失败，降级 get_all_teachers: %s", e)
            try:
                all_sorted = await get_all_teachers(active_only=True)
            except Exception:
                return []

        results: list[dict] = []
        for t in all_sorted:
            if filter_type == "region":
                if (t.get("region") or "").strip().lower() == v_lower:
                    results.append(t)
            elif filter_type == "price":
                if (t.get("price") or "").strip().lower() == v_lower:
                    results.append(t)
            elif filter_type == "tag":
                try:
                    tags = json.loads(t.get("tags") or "[]")
                    if isinstance(tags, list):
                        for tag in tags:
                            if str(tag).strip().lower() == v_lower:
                                results.append(t)
                                break
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
            if len(results) >= limit:
                break
        return results

    return []


async def get_recommended_teachers_for_user(
    user_id: int,
    limit: int = 5,
) -> list[dict]:
    """根据 user_tags 给用户推荐老师（Phase 7.2 §六）

    评分构成：
        + 用户标签命中：每命中一个老师 tag/region/price，加 (该用户标签 score * 10)
        + 今日可约：+30（已签到且 daily_status != unavailable）
        + is_effective_featured：+50
        + hot_score：直接相加
        + fav_count * 3

    降级：
        - 用户无 user_tags 记录 → get_hot_teachers(limit)
        - get_hot_teachers 缺失 → get_all_teachers(active_only=True)[:limit]
        - 全程异常 → []
    """
    if limit <= 0:
        return []

    today_str = _today_str_local()

    # --- 读用户画像 ---
    try:
        raw_tags = await get_user_tags(user_id, limit=10)
    except Exception as e:
        logger.warning("get_user_tags(%s) 失败，降级到 hot: %s", user_id, e)
        raw_tags = []

    if not raw_tags:
        # spec §六.9：无画像 → 回退 get_hot_teachers
        try:
            return await get_hot_teachers(limit=limit)
        except Exception:
            try:
                fallback = await get_all_teachers(active_only=True)
                return fallback[:limit]
            except Exception:
                return []

    user_tag_map: dict[str, int] = {}
    for r in raw_tags:
        tag = (r.get("tag") or "").strip().lower()
        if not tag:
            continue
        try:
            user_tag_map[tag] = int(r.get("score") or 0)
        except (ValueError, TypeError):
            user_tag_map[tag] = 0

    # --- 取所有 active 老师（带 daily_status / signed_in / fav_count） ---
    try:
        teachers = await get_sorted_teachers(active_only=True)
    except Exception as e:
        logger.warning("get_sorted_teachers 失败，降级 get_all_teachers: %s", e)
        try:
            teachers = await get_all_teachers(active_only=True)
        except Exception:
            return []

    scored: list[tuple[float, dict]] = []
    for t in teachers:
        score = 0.0

        # 1. 标签 / 地区 / 价格命中
        try:
            raw = t.get("tags") or "[]"
            tags = json.loads(raw) if raw else []
            if not isinstance(tags, list):
                tags = []
        except (json.JSONDecodeError, TypeError, ValueError):
            tags = []
        for tag in tags:
            tl = str(tag).strip().lower()
            if tl and tl in user_tag_map:
                score += user_tag_map[tl] * 10

        region_lower = (t.get("region") or "").strip().lower()
        if region_lower and region_lower in user_tag_map:
            score += user_tag_map[region_lower] * 10

        price_lower = (t.get("price") or "").strip().lower()
        if price_lower and price_lower in user_tag_map:
            score += user_tag_map[price_lower] * 10

        # 2. 今日可约 +30
        try:
            signed = bool(t.get("signed_in_today"))
            d_status = t.get("daily_status")
            if signed and d_status != "unavailable":
                score += 30
        except Exception:
            pass

        # 3. is_effective_featured +50
        try:
            if is_effective_featured(t, today_str):
                score += 50
        except Exception:
            pass

        # 4. hot_score
        try:
            score += float(t.get("hot_score") or 0)
        except (ValueError, TypeError):
            pass

        # 5. fav_count * 3
        try:
            score += float(t.get("fav_count") or 0) * 3
        except (ValueError, TypeError):
            pass

        scored.append((score, t))

    # 排序：score DESC, signed_in_today DESC, created_at ASC
    scored.sort(
        key=lambda x: (
            -x[0],
            -(int(x[1].get("signed_in_today") or 0)),
            str(x[1].get("created_at") or ""),
        )
    )

    return [t for _, t in scored[:limit]]


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


async def get_user_search_history(
    user_id: int,
    limit: int = 10,
) -> list[str]:
    """从 user_events 中读取该用户最近搜索词（Phase 7.3 §二）

    依赖 event_type='search'，payload 形如 {"raw": "御姐 1000P", "tokens": [...]}.
    解析优先级：payload.raw > payload.tokens 拼接 > 跳过该条。

    去重：按"小写后比较"保留最早出现位置的原始 query。
    按 created_at DESC 排序。

    异常 / 表缺失 → 返回 []。
    """
    if limit <= 0:
        return []
    try:
        db = await get_db()
        try:
            cur = await db.execute(
                """SELECT payload FROM user_events
                   WHERE user_id = ? AND event_type = 'search'
                     AND payload IS NOT NULL
                   ORDER BY id DESC
                   LIMIT ?""",
                (user_id, limit * 5),  # 多取一些，便于去重后仍能凑齐 limit
            )
            rows = await cur.fetchall()
        finally:
            await db.close()
    except Exception as e:
        logger.warning("get_user_search_history(user=%s) 查询失败: %s", user_id, e)
        return []

    seen_lower: set[str] = set()
    result: list[str] = []
    for r in rows:
        payload_str = r["payload"]
        if not payload_str:
            continue
        try:
            data = json.loads(payload_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue

        # 优先 raw，其次 tokens 拼接
        query: Optional[str] = None
        raw = data.get("raw")
        if raw and isinstance(raw, str) and raw.strip():
            query = raw.strip()
        else:
            tokens = data.get("tokens")
            if isinstance(tokens, list):
                parts = [str(t).strip() for t in tokens if t and str(t).strip()]
                if parts:
                    query = " ".join(parts)

        if not query:
            continue

        key = query.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        result.append(query)

        if len(result) >= limit:
            break

    return result


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
                    "FROM teachers t WHERE t.is_active = 1 "
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
REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM: list[float] = [6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0]
REVIEW_SCORE_QUICK_BUTTONS_FOR_OVERALL: list[float] = [7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0]

REVIEW_SUMMARY_MIN_LEN: int = 5
REVIEW_SUMMARY_MAX_LEN: int = 100
REVIEW_SUMMARY_REQUIRED: bool = False

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
              gesture_photo_file_id / rating / 6 个 score_* / overall_score
    可选：summary（None 或字符串）
    """
    required = ["teacher_id", "user_id", "booking_screenshot_file_id",
                "gesture_photo_file_id", "rating", "overall_score"]
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
                    overall_score, summary, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    int(data["teacher_id"]), int(data["user_id"]),
                    data["booking_screenshot_file_id"],
                    data["gesture_photo_file_id"],
                    data["rating"],
                    float(data["score_humanphoto"]),
                    float(data["score_appearance"]),
                    float(data["score_body"]),
                    float(data["score_service"]),
                    float(data["score_attitude"]),
                    float(data["score_environment"]),
                    float(data["overall_score"]),
                    data.get("summary"),
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


# ============ 抽奖 (Phase L.1) ============

# 抽奖状态机（spec §7）
LOTTERY_STATUSES: list[dict] = [
    {"key": "draft",       "label": "📝 草稿",     "emoji": "📝"},
    {"key": "scheduled",   "label": "⏰ 已计划",   "emoji": "⏰"},
    {"key": "active",      "label": "🎯 进行中",   "emoji": "🎯"},
    {"key": "drawn",       "label": "🏆 已开奖",   "emoji": "🏆"},
    {"key": "cancelled",   "label": "❌ 已取消",   "emoji": "❌"},
    {"key": "no_entries",  "label": "⚪ 无人参与", "emoji": "⚪"},
]

# 终态：不允许变更
LOTTERY_TERMINAL_STATUSES: set[str] = {"drawn", "cancelled", "no_entries"}

# 字段白名单（update_lottery_fields 用）
LOTTERY_EDITABLE_FIELDS: set[str] = {
    "name", "description", "cover_file_id",
    "entry_method", "entry_code",
    "prize_count", "prize_description",
    "required_chat_ids",
    "publish_at", "draw_at",
    "published_at", "drawn_at",
    "channel_chat_id", "channel_msg_id", "result_msg_id",
    "status",
}


async def create_lottery(data: dict) -> Optional[int]:
    """创建抽奖记录（默认 status='draft'）

    必填字段：name / description / entry_method / prize_count / prize_description /
              required_chat_ids (list 自动 JSON) / publish_at / draw_at / created_by

    返回 lottery_id；entry_code 冲突 / CHECK 越界 / 缺字段时返回 None。
    """
    required = ["name", "description", "entry_method", "prize_count",
                "prize_description", "required_chat_ids",
                "publish_at", "draw_at", "created_by"]
    for f in required:
        if data.get(f) is None:
            return None

    rc = data["required_chat_ids"]
    if isinstance(rc, list):
        rc_json = json.dumps(rc, ensure_ascii=False)
    elif isinstance(rc, str):
        rc_json = rc
    else:
        return None

    db = await get_db()
    try:
        try:
            cur = await db.execute(
                """INSERT INTO lotteries (
                    name, description, cover_file_id,
                    entry_method, entry_code,
                    prize_count, prize_description,
                    required_chat_ids,
                    publish_at, draw_at,
                    status, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(data["name"]).strip(),
                    str(data["description"]).strip(),
                    data.get("cover_file_id"),
                    str(data["entry_method"]),
                    data.get("entry_code"),
                    int(data["prize_count"]),
                    str(data["prize_description"]).strip(),
                    rc_json,
                    str(data["publish_at"]),
                    str(data["draw_at"]),
                    data.get("status", "draft"),
                    int(data["created_by"]),
                ),
            )
        except Exception as e:
            logger.warning("create_lottery 失败: %s", e)
            return None
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


def _parse_lottery_row(row: Optional[dict]) -> Optional[dict]:
    """统一解析 required_chat_ids JSON"""
    if row is None:
        return None
    data = dict(row)
    raw = data.get("required_chat_ids")
    ids: list[int] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                ids = [int(x) for x in parsed]
        except (json.JSONDecodeError, TypeError, ValueError):
            ids = []
    data["required_chat_ids"] = ids
    return data


async def get_lottery(lottery_id: int) -> Optional[dict]:
    """单条抽奖（解析 required_chat_ids JSON）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM lotteries WHERE id = ?", (lottery_id,)
        )
        row = await cur.fetchone()
        return _parse_lottery_row(dict(row) if row else None)
    finally:
        await db.close()


async def find_lottery_by_entry_code(code: str) -> Optional[dict]:
    """口令抽奖反查：active 状态优先；大小写不敏感（spec §2.2）"""
    if not code:
        return None
    c = str(code).strip()
    if not c:
        return None
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM lotteries "
            "WHERE LOWER(entry_code) = LOWER(?) "
            "  AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (c,),
        )
        row = await cur.fetchone()
        return _parse_lottery_row(dict(row) if row else None)
    finally:
        await db.close()


async def list_lotteries_by_status(
    status: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> list[dict]:
    """列出抽奖；status=None 表示全部，按 created_at DESC"""
    db = await get_db()
    try:
        if status:
            cur = await db.execute(
                "SELECT * FROM lotteries WHERE status = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (status, int(limit), int(offset)),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM lotteries "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            )
        rows = await cur.fetchall()
        return [_parse_lottery_row(dict(r)) for r in rows]
    finally:
        await db.close()


async def count_lotteries_by_status(status: Optional[str] = None) -> int:
    db = await get_db()
    try:
        if status:
            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM lotteries WHERE status = ?",
                (status,),
            )
        else:
            cur = await db.execute("SELECT COUNT(*) AS c FROM lotteries")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def update_lottery_fields(lottery_id: int, **fields) -> bool:
    """按白名单更新抽奖字段；终态拒绝更新（除非显式改 status）

    list 自动 JSON 序列化（required_chat_ids 等）。
    """
    if not fields:
        return False
    # 白名单 + 类型转换
    sets: list[str] = []
    params: list = []
    for k, v in fields.items():
        if k not in LOTTERY_EDITABLE_FIELDS:
            continue
        if k == "required_chat_ids" and isinstance(v, list):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(lottery_id)
    db = await get_db()
    try:
        await db.execute(
            f"UPDATE lotteries SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def cancel_lottery(lottery_id: int) -> bool:
    """取消抽奖（仅 draft / scheduled / active 可改）

    终态（drawn / cancelled / no_entries）不变。
    """
    db = await get_db()
    try:
        await db.execute(
            "UPDATE lotteries SET status = 'cancelled', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status IN ('draft','scheduled','active')",
            (lottery_id,),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def count_lottery_entries(lottery_id: int) -> int:
    """统计某抽奖的参与人数（用于列表角标 / 详情显示）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM lottery_entries WHERE lottery_id = ?",
            (lottery_id,),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def create_lottery_entry(lottery_id: int, user_id: int) -> Optional[int]:
    """创建参与记录；UNIQUE(lottery_id, user_id) 冲突时返回 None"""
    db = await get_db()
    try:
        try:
            cur = await db.execute(
                "INSERT INTO lottery_entries (lottery_id, user_id) VALUES (?, ?)",
                (int(lottery_id), int(user_id)),
            )
        except Exception:
            return None
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def get_lottery_entry(lottery_id: int, user_id: int) -> Optional[dict]:
    """查询用户在某抽奖的参与记录"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM lottery_entries WHERE lottery_id = ? AND user_id = ?",
            (int(lottery_id), int(user_id)),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def mark_lottery_published(
    lottery_id: int,
    channel_chat_id: int,
    channel_msg_id: int,
) -> bool:
    """标记抽奖已发布到频道：status → active + published_at + 记录 msg id"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE lotteries SET "
            "status = 'active', "
            "published_at = CURRENT_TIMESTAMP, "
            "channel_chat_id = ?, "
            "channel_msg_id = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status IN ('draft','scheduled')",
            (channel_chat_id, channel_msg_id, lottery_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def touch_lottery(lottery_id: int) -> bool:
    """仅刷新 updated_at（用于计数 debounce 时间戳）"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE lotteries SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (lottery_id,),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def seconds_since_lottery_updated(lottery_id: int) -> Optional[float]:
    """距上次 lotteries.updated_at 经过的秒数（用于计数 60s debounce）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT (julianday('now') - julianday(updated_at)) * 86400.0 AS sec "
            "FROM lotteries WHERE id = ?",
            (lottery_id,),
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


async def list_active_or_scheduled_lotteries() -> list[dict]:
    """列出所有 scheduled / active 抽奖（bot 重启时扫描重注册定时任务）"""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM lotteries WHERE status IN ('scheduled','active') "
            "ORDER BY publish_at"
        )
        rows = await cur.fetchall()
        return [_parse_lottery_row(dict(r)) for r in rows]
    finally:
        await db.close()

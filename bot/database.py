from __future__ import annotations

import json
from typing import Optional

import aiosqlite
import os
from bot.config import config


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

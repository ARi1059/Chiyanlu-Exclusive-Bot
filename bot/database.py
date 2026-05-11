from __future__ import annotations

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
        """)
        await db.execute(
            """INSERT INTO admins (user_id, username, is_super)
            VALUES (?, NULL, 1)
            ON CONFLICT(user_id) DO UPDATE SET is_super = 1""",
            (config.super_admin_id,),
        )
        await db.commit()
    finally:
        await db.close()


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
    """通过修改请求

    仅改 status，不动 teachers 表（已经是新值）。
    若 status 已经不是 pending，返回 False。
    """
    db = await get_db()
    try:
        await db.execute(
            """UPDATE teacher_edit_requests
               SET status = 'approved', reviewer_id = ?, reviewed_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'pending'""",
            (reviewer_id, request_id),
        )
        await db.commit()
        return db.total_changes > 0
    finally:
        await db.close()


async def reject_edit_request(
    request_id: int,
    reviewer_id: int,
    reason: Optional[str] = None,
) -> bool:
    """驳回修改请求并回滚 teachers 字段（同连接内事务）

    流程:
        1. 取请求详情（必须是 pending）
        2. 校验 field_name 在白名单（防 SQL 注入，因 UPDATE 用 f-string 拼字段名）
        3. UPDATE teachers SET <field> = old_value
        4. UPDATE teacher_edit_requests SET status='rejected', ...
        5. commit

    两个 UPDATE 在同一连接里执行；任一失败 commit 不会发生，状态保持 pending。
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

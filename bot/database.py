from __future__ import annotations

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


async def get_admin(user_id: int) -> dict | None:
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


async def get_teacher(user_id: int) -> dict | None:
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


async def get_teacher_by_name(display_name: str) -> dict | None:
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


async def get_config(key: str) -> str | None:
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

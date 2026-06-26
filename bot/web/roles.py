"""MiniApp 角色解析（P0·T3）。

把已验签的 user_id 映射到四级角色 —— 与 bot 私聊菜单分流（start_router）完全
同源，复用现有 db 判定函数 + config.super_admin_id，不另立一套权限体系。

优先级：superadmin > admin > teacher > user。
"""
from __future__ import annotations

from bot.config import config
from bot.database import get_teacher, is_admin, is_super_admin

# 角色常量（与 session payload.role / 前端路由守卫对齐）。
ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "admin"
ROLE_TEACHER = "teacher"
ROLE_USER = "user"


async def resolve_role(user_id: int) -> str:
    """解析 user_id 的角色。

    与 start_router._is_admin_user / _route_by_role 语义一致：
      - superadmin：config.super_admin_id（可能不在 admins 表）或 admins.is_super；
      - admin：admins 表任意成员；
      - teacher：teachers 表存在记录；
      - 其余：user。
    """
    if user_id == config.super_admin_id or await is_super_admin(user_id):
        return ROLE_SUPERADMIN
    if await is_admin(user_id):
        return ROLE_ADMIN
    if await get_teacher(user_id) is not None:
        return ROLE_TEACHER
    return ROLE_USER

"""bot/web/roles.py · 角色解析单测（P0·T3）。

不连真实 db：monkeypatch roles 模块引用的 db 判定函数 + config.super_admin_id。
async 经 asyncio.run 包裹（项目无 pytest-asyncio，与既有 service 测试一致）。
"""
from __future__ import annotations

import asyncio

from bot.web import roles


def _run(coro):
    return asyncio.run(coro)


async def _true(_uid):
    return True


async def _false(_uid):
    return False


async def _none(_uid):
    return None


def _patch(monkeypatch, *, super_admin=_false, admin=_false, teacher=_none, super_admin_id=-1):
    monkeypatch.setattr(roles, "is_super_admin", super_admin)
    monkeypatch.setattr(roles, "is_admin", admin)
    monkeypatch.setattr(roles, "get_teacher", teacher)
    monkeypatch.setattr(roles.config, "super_admin_id", super_admin_id)


def test_superadmin_by_config(monkeypatch):
    _patch(monkeypatch, super_admin_id=999)
    assert _run(roles.resolve_role(999)) == roles.ROLE_SUPERADMIN


def test_superadmin_by_db(monkeypatch):
    _patch(monkeypatch, super_admin=_true)
    assert _run(roles.resolve_role(5)) == roles.ROLE_SUPERADMIN


def test_admin(monkeypatch):
    _patch(monkeypatch, admin=_true)
    assert _run(roles.resolve_role(5)) == roles.ROLE_ADMIN


def test_teacher(monkeypatch):
    async def _teacher(_uid):
        return {"user_id": _uid, "display_name": "T"}

    _patch(monkeypatch, teacher=_teacher)
    assert _run(roles.resolve_role(5)) == roles.ROLE_TEACHER


def test_user(monkeypatch):
    _patch(monkeypatch)
    assert _run(roles.resolve_role(5)) == roles.ROLE_USER


def test_priority_superadmin_over_admin(monkeypatch):
    # 同时命中 super 与 admin → superadmin 优先
    _patch(monkeypatch, super_admin=_true, admin=_true)
    assert _run(roles.resolve_role(5)) == roles.ROLE_SUPERADMIN

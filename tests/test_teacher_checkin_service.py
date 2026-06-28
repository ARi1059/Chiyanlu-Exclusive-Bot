"""老师签到共享 service 单元测试（§清理重复·item1）。

覆盖 perform_checkin 的 6 个状态：not_teacher / inactive / closed / already /
success / failed。叶子函数（get_teacher / get_config / is_checked_in /
checkin_teacher）在 service 命名空间内 monkeypatch。

时间窗口用 publish_time="00:00"（必然已截止）/ "23:59"（几乎不截止）触发，
与既有 web 签到测试同手法。
"""
from __future__ import annotations

import asyncio

import bot.services.teacher_checkin as svc


def _run(coro):
    return asyncio.run(coro)


def _patch(monkeypatch, *, teacher, publish="23:59", checked=False, checkin_ok=True):
    async def fake_get_teacher(uid):
        return teacher

    async def fake_get_config(key):
        return publish if key == "publish_time" else None

    async def fake_is_checked_in(uid, day):
        return checked

    called = {"checkin": False}

    async def fake_checkin(uid, day):
        called["checkin"] = True
        return checkin_ok

    monkeypatch.setattr(svc, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(svc, "get_config", fake_get_config)
    monkeypatch.setattr(svc, "is_checked_in", fake_is_checked_in)
    monkeypatch.setattr(svc, "checkin_teacher", fake_checkin)
    return called


def test_not_teacher(monkeypatch):
    _patch(monkeypatch, teacher=None)
    r = _run(svc.perform_checkin(1))
    assert r.status == "not_teacher" and r.checked_in is False


def test_inactive(monkeypatch):
    _patch(monkeypatch, teacher={"user_id": 1, "display_name": "X", "is_active": 0})
    r = _run(svc.perform_checkin(1))
    assert r.status == "inactive" and r.checked_in is False


def test_closed_window(monkeypatch):
    _patch(monkeypatch, teacher={"user_id": 1, "display_name": "X", "is_active": 1}, publish="00:00")
    r = _run(svc.perform_checkin(1))
    assert r.status == "closed" and r.checked_in is False
    assert r.deadline == "00:00"


def test_already_idempotent(monkeypatch):
    called = _patch(
        monkeypatch, teacher={"user_id": 1, "display_name": "X", "is_active": 1},
        publish="23:59", checked=True,
    )
    r = _run(svc.perform_checkin(1))
    assert r.status == "already" and r.checked_in is True
    assert called["checkin"] is False  # 已签到不再落库


def test_success(monkeypatch):
    called = _patch(
        monkeypatch, teacher={"user_id": 1, "display_name": "苏乔晚", "is_active": 1},
        publish="23:59", checked=False, checkin_ok=True,
    )
    r = _run(svc.perform_checkin(1))
    assert r.status == "success" and r.checked_in is True
    assert called["checkin"] is True
    assert r.teacher["display_name"] == "苏乔晚"
    assert r.today_str and r.now_hm  # 供调用方渲染


def test_failed(monkeypatch):
    _patch(
        monkeypatch, teacher={"user_id": 1, "display_name": "X", "is_active": 1},
        publish="23:59", checked=False, checkin_ok=False,
    )
    r = _run(svc.perform_checkin(1))
    assert r.status == "failed" and r.checked_in is False

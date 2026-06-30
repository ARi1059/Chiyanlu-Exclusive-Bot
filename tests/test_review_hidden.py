"""评价隐藏（超管「通过并隐藏」）service 单测。

核心断言：hidden=True 时——
  - **不发评论区**（publish_review_comment 未调用）；
  - 加分 / recalc / 通知用户「已通过」**照常**；
  - notify_teacher_review_approved 收到 hidden=True；
  - 落库 set_review_hidden(True)；audit detail 带 hidden。
hidden=False 行为与现状一致（publish 被调）——零回归。
set_review_visibility_core：取消隐藏补发 / 事后隐藏删消息。

副作用全 monkeypatch（模块级 import patch 在 review_moderation；函数内 import patch 在源模块）。
"""
from __future__ import annotations

import asyncio

import bot.services.review_moderation as mod
import bot.database as db
import bot.utils.review_comment as rc
import bot.utils.rreview_notify as rn
import bot.utils.teacher_channel_publish as tcp


def _run(coro):
    return asyncio.run(coro)


def _review(**over) -> dict:
    d = {
        "id": 5, "teacher_id": 100, "user_id": 12345678, "status": "pending",
        "rating": "positive", "overall_score": 8.2, "request_reimbursement": 0,
        "discussion_chat_id": None, "discussion_msg_id": None,
    }
    d.update(over)
    return d


def _patch_approve(monkeypatch, review):
    """装好 approve_review 的全部副作用桩，返回 calls 记录器。"""
    calls = {
        "set_hidden": [], "points": 0, "recalc": 0, "publish": 0,
        "notify_teacher": [], "notify_user": 0, "audit": [],
    }

    async def fake_get_review(rid):
        return review

    async def fake_approve(rid, reviewer_id):
        review["status"] = "approved"
        return True

    async def fake_set_hidden(rid, hidden):
        calls["set_hidden"].append(bool(hidden))
        review["hidden"] = 1 if hidden else 0
        return True

    async def fake_add_points(*a, **k):
        calls["points"] += 1
        return 1

    async def fake_total(uid):
        return 42

    async def fake_get_teacher(tid):
        return {"user_id": tid, "display_name": "小美"}

    async def fake_audit(**kw):
        calls["audit"].append(kw)

    async def fake_recalc(tid):
        calls["recalc"] += 1

    async def fake_caption(bot, tid, **k):
        return None

    async def fake_publish(bot, rid):
        calls["publish"] += 1
        return {}

    async def fake_notify_teacher(bot, rid, *, hidden=False):
        calls["notify_teacher"].append(hidden)
        return True

    async def fake_notify_user(*a, **k):
        calls["notify_user"] += 1

    # 模块级 import（在 review_moderation 命名空间）
    monkeypatch.setattr(mod, "get_teacher_review", fake_get_review)
    monkeypatch.setattr(mod, "approve_teacher_review", fake_approve)
    monkeypatch.setattr(mod, "set_review_hidden", fake_set_hidden)
    monkeypatch.setattr(mod, "add_point_transaction", fake_add_points)
    monkeypatch.setattr(mod, "get_user_total_points", fake_total)
    monkeypatch.setattr(mod, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(mod, "log_admin_audit", fake_audit)
    monkeypatch.setattr(mod, "notify_review_approved", fake_notify_user)
    # 函数内 import（在源模块命名空间）
    monkeypatch.setattr(db, "recalculate_teacher_review_stats", fake_recalc)
    monkeypatch.setattr(tcp, "update_teacher_post_caption", fake_caption)
    monkeypatch.setattr(rc, "publish_review_comment", fake_publish)
    monkeypatch.setattr(rn, "notify_teacher_review_approved", fake_notify_teacher)
    return calls


def test_approve_hidden_skips_publish_keeps_rest(monkeypatch):
    review = _review()
    calls = _patch_approve(monkeypatch, review)
    res = _run(mod.approve_review(
        object(), review_id=5, reviewer_id=1, delta=3, package_label="包时", hidden=True,
    ))
    assert res.ok and res.hidden is True
    assert calls["publish"] == 0          # 评论区未发
    assert calls["points"] == 1           # 加分照常
    assert calls["recalc"] == 1           # 数据照常
    assert calls["notify_user"] == 1      # 通知用户已通过
    assert calls["notify_teacher"] == [True]   # 老师收到 hidden 提示
    assert calls["set_hidden"] == [True]  # 落库隐藏
    assert review["hidden"] == 1
    assert calls["audit"][0]["detail"]["hidden"] is True


def test_approve_visible_publishes_no_regression(monkeypatch):
    review = _review()
    calls = _patch_approve(monkeypatch, review)
    res = _run(mod.approve_review(
        object(), review_id=5, reviewer_id=1, delta=1, package_label="P", hidden=False,
    ))
    assert res.ok and res.hidden is False
    assert calls["publish"] == 1          # 正常发评论区
    assert calls["points"] == 1
    assert calls["notify_teacher"] == [False]
    assert calls["set_hidden"] == []      # 不动 hidden
    assert calls["audit"][0]["detail"]["hidden"] is False


def test_approve_default_is_visible(monkeypatch):
    """不传 hidden → 默认 False，行为同现状。"""
    review = _review()
    calls = _patch_approve(monkeypatch, review)
    res = _run(mod.approve_review(
        object(), review_id=5, reviewer_id=1, delta=0, package_label="不加分",
    ))
    assert res.ok and res.hidden is False
    assert calls["publish"] == 1


# ============ set_review_visibility_core ============

def _patch_visibility(monkeypatch, review):
    calls = {"set_hidden": [], "audit": [], "publish": 0, "deleted": [], "cleared": 0, "notify": []}

    async def fake_get_review(rid):
        return review

    async def fake_set_hidden(rid, hidden):
        calls["set_hidden"].append(bool(hidden))
        return True

    async def fake_audit(**kw):
        calls["audit"].append(kw["action"])

    async def fake_publish(bot, rid):
        calls["publish"] += 1
        return {}

    async def fake_clear(rid):
        calls["cleared"] += 1
        return True

    async def fake_notify(bot, rid, *, hidden):
        calls["notify"].append(hidden)
        return True

    monkeypatch.setattr(mod, "get_teacher_review", fake_get_review)
    monkeypatch.setattr(mod, "set_review_hidden", fake_set_hidden)
    monkeypatch.setattr(mod, "log_admin_audit", fake_audit)
    monkeypatch.setattr(mod, "clear_review_discussion_msg", fake_clear)
    monkeypatch.setattr(rc, "publish_review_comment", fake_publish)
    monkeypatch.setattr(rn, "notify_teacher_review_visibility", fake_notify)
    return calls


class _FakeBot:
    def __init__(self):
        self.deleted = []

    async def delete_message(self, *, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


def test_visibility_unhide_republishes(monkeypatch):
    review = _review(status="approved", hidden=1, discussion_msg_id=None)
    calls = _patch_visibility(monkeypatch, review)
    res = _run(mod.set_review_visibility_core(
        _FakeBot(), review_id=5, reviewer_id=1, hidden=False,
    ))
    assert res.ok and res.hidden is False
    assert calls["set_hidden"] == [False]
    assert calls["publish"] == 1          # 无讨论群消息 → 补发
    assert "rreview_unhide" in calls["audit"]
    assert calls["notify"] == [False]


def test_visibility_hide_deletes_comment(monkeypatch):
    review = _review(status="approved", hidden=0, discussion_chat_id=-100, discussion_msg_id=999)
    calls = _patch_visibility(monkeypatch, review)
    bot = _FakeBot()
    res = _run(mod.set_review_visibility_core(
        bot, review_id=5, reviewer_id=1, hidden=True,
    ))
    assert res.ok and res.hidden is True
    assert calls["set_hidden"] == [True]
    assert bot.deleted == [(-100, 999)]   # 删讨论群评论
    assert calls["cleared"] == 1          # 清引用
    assert "rreview_hide" in calls["audit"]


def test_visibility_rejects_non_approved(monkeypatch):
    review = _review(status="pending")
    calls = _patch_visibility(monkeypatch, review)
    res = _run(mod.set_review_visibility_core(
        _FakeBot(), review_id=5, reviewer_id=1, hidden=True,
    ))
    assert res.ok is False
    assert calls["set_hidden"] == []      # 非 approved 不动

"""报销打款共享 core 单测（§15.5）。

覆盖 reimbursement_moderation 的 compute_payout_precheck / payout_reimbursement_core /
grant_reset_core —— 动钱路径的关键安全性质：
  - 配额四态（ok / need_voucher / week_blocked / over_pool）
  - **先发后批**：safe_send_user_payout 失败 → 不 approve、不 audit
  - voucher 消耗、mark_notified、audit 仅记 mask_token（不落明文）
  - token 长度边界

DB / 发送全 monkeypatch（核心是编排逻辑，底层原语已在别处测）。
"""
from __future__ import annotations

import asyncio

import bot.services.reimbursement_moderation as m


def _run(coro):
    return asyncio.run(coro)


def _reimb(**over) -> dict:
    d = {
        "id": 1, "user_id": 555, "review_id": 7, "teacher_id": 100,
        "amount": 200, "status": "pending",
        "week_key": "2026-W26", "month_key": "2026-06",
    }
    d.update(over)
    return d


def _setup(
    monkeypatch, *, reimb=None, week_used=0, weekly_limit=3, reset=None,
    pool=0, month_used=0, send_ok=True,
):
    """装好所有依赖，返回 calls 记录器。reimb 默认一条 pending。"""
    if reimb is None:
        reimb = _reimb()
    calls = {"send": [], "approve": [], "consume": [], "notified": [], "audit": []}

    async def get_reimbursement(rid):
        return reimb if reimb and int(rid) == int(reimb["id"]) else None

    async def count_week(uid, wk):
        return week_used

    async def weekly():
        return weekly_limit

    async def unused_reset(uid):
        return reset

    async def pool_usage(mk):
        return {"effective_used": month_used, "raw_used": month_used, "reset_baseline": 0}

    async def get_config(k):
        return str(pool)

    async def send(bot, *, user_id, token, amount):
        calls["send"].append({"user_id": user_id, "token": token, "amount": amount})
        return (send_ok, None if send_ok else "Forbidden: bot blocked")

    async def approve(rid, aid):
        calls["approve"].append((rid, aid))
        return True

    async def consume(vid, rid):
        calls["consume"].append((vid, rid))
        return True

    async def notified(rid):
        calls["notified"].append(rid)
        return True

    async def audit(**kw):
        calls["audit"].append(kw)

    monkeypatch.setattr(m, "get_reimbursement", get_reimbursement)
    monkeypatch.setattr(m, "count_approved_reimbursements_in_week", count_week)
    monkeypatch.setattr(m, "get_reimbursement_weekly_limit", weekly)
    monkeypatch.setattr(m, "get_unused_reimbursement_reset", unused_reset)
    monkeypatch.setattr(m, "get_reimbursement_monthly_pool_usage", pool_usage)
    monkeypatch.setattr(m, "get_config", get_config)
    monkeypatch.setattr(m, "safe_send_user_payout", send)
    monkeypatch.setattr(m, "approve_reimbursement", approve)
    monkeypatch.setattr(m, "consume_reimbursement_reset", consume)
    monkeypatch.setattr(m, "mark_reimbursement_notified", notified)
    monkeypatch.setattr(m, "log_admin_audit", audit)
    return calls


# ============ compute_payout_precheck：四态 ============

def test_precheck_ok(monkeypatch):
    _setup(monkeypatch, week_used=0, weekly_limit=3, pool=0)
    pre = _run(m.compute_payout_precheck(_reimb()))
    assert pre.state == "ok" and pre.reset_voucher_id is None


def test_precheck_need_voucher(monkeypatch):
    _setup(monkeypatch, week_used=3, weekly_limit=3, reset={"id": 9})
    pre = _run(m.compute_payout_precheck(_reimb()))
    assert pre.state == "need_voucher" and pre.reset_voucher_id == 9


def test_precheck_week_blocked(monkeypatch):
    _setup(monkeypatch, week_used=3, weekly_limit=3, reset=None)
    pre = _run(m.compute_payout_precheck(_reimb()))
    assert pre.state == "week_blocked" and pre.reset_voucher_id is None


def test_precheck_over_pool_takes_priority(monkeypatch):
    # 月池仅剩 100，本次 200 → over_pool，即便周也满也优先报 over_pool
    _setup(monkeypatch, pool=100, month_used=0, week_used=9, weekly_limit=3, reset={"id": 9})
    pre = _run(m.compute_payout_precheck(_reimb(amount=200)))
    assert pre.state == "over_pool" and pre.pool_remaining == 100


# ============ payout_reimbursement_core：动钱安全 ============

def test_payout_happy_sends_then_approves_and_masks(monkeypatch):
    calls = _setup(monkeypatch, week_used=0, weekly_limit=3, pool=0)
    token = "ABCD1234SECRET"
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token=token))
    assert res.ok and res.amount == 200
    assert len(calls["send"]) == 1 and calls["send"][0]["token"] == token
    assert calls["approve"] == [(1, 42)]
    assert calls["notified"] == [1]
    assert calls["consume"] == []  # 无 voucher
    assert len(calls["audit"]) == 1
    a = calls["audit"][0]
    assert a["action"] == "reimburse_payout_sent"
    assert a["target_type"] == "reimbursement" and a["target_id"] == "1"
    # 明文口令绝不落 audit；只记 mask
    assert a["detail"]["token_masked"] == m.mask_token(token)
    assert token not in str(a["detail"])
    assert a["detail"]["reset_consumed"] is None


def test_payout_send_fail_does_not_approve(monkeypatch):
    calls = _setup(monkeypatch, send_ok=False)
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token="ABCD1234"))
    assert res.ok is False
    assert len(calls["send"]) == 1       # 尝试发了
    assert calls["approve"] == []        # 但没 approve
    assert calls["notified"] == []
    assert calls["audit"] == []          # 也没 audit


def test_payout_need_voucher_consumes(monkeypatch):
    calls = _setup(monkeypatch, week_used=3, weekly_limit=3, reset={"id": 9})
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token="ABCD1234"))
    assert res.ok is True
    assert calls["consume"] == [(9, 1)]
    assert calls["audit"][0]["detail"]["reset_consumed"] == 9


def test_payout_over_pool_blocked_no_send(monkeypatch):
    calls = _setup(monkeypatch, pool=100, month_used=0)
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token="ABCD1234"))
    assert res.ok is False and "超月池" in (res.error or "")
    assert calls["send"] == [] and calls["approve"] == []


def test_payout_week_blocked_no_send(monkeypatch):
    calls = _setup(monkeypatch, week_used=3, weekly_limit=3, reset=None)
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token="ABCD1234"))
    assert res.ok is False and "周配额" in (res.error or "")
    assert calls["send"] == []


def test_payout_token_too_short(monkeypatch):
    calls = _setup(monkeypatch)
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token="ab"))
    assert res.ok is False and calls["send"] == []


def test_payout_token_too_long(monkeypatch):
    calls = _setup(monkeypatch)
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token="x" * 201))
    assert res.ok is False and calls["send"] == []


def test_payout_not_pending(monkeypatch):
    calls = _setup(monkeypatch, reimb=_reimb(status="approved"))
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token="ABCD1234"))
    assert res.ok is False and calls["send"] == []


def test_payout_missing(monkeypatch):
    calls = _setup(monkeypatch, reimb=_reimb(id=999))  # get_reimbursement(1) → None
    res = _run(m.payout_reimbursement_core(object(), reimb_id=1, admin_id=42, token="ABCD1234"))
    assert res.ok is False and calls["send"] == []


# ============ grant_reset_core ============

def test_grant_reset_core_audits(monkeypatch):
    calls = {"grant": [], "audit": []}

    async def grant(uid, aid):
        calls["grant"].append((uid, aid))
        return 77

    async def audit(**kw):
        calls["audit"].append(kw)

    monkeypatch.setattr(m, "grant_reimbursement_reset", grant)
    monkeypatch.setattr(m, "log_admin_audit", audit)

    res = _run(m.grant_reset_core(reimb_id=1, user_id=555, admin_id=42))
    assert res.ok and res.voucher_id == 77
    assert calls["grant"] == [(555, 42)]
    assert calls["audit"][0]["action"] == "reimburse_reset"
    assert calls["audit"][0]["detail"]["voucher_id"] == 77

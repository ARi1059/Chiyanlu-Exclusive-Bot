"""bot.handlers.review_card 评价前置 intent 流程契约测试（2026-05-21）。

覆盖：
    - start_card_review 后状态正确分支（eligible → choosing_reimburse_intent；
      ineligible → card）+ state.data 写入正确（_reimburse_eligibility_info /
      request_reimbursement）
    - 4 个 intent handler 静态契约（cb_card_intent_yes / _no / _retry / _fallback）
    - intent kb / subreq fail kb 形状 + callback
    - render_card_or_intent dispatcher 根据 state 选择正确渲染
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_intent_{uuid.uuid4().hex}_", suffix=".db",
    )
    os.close(fd)
    from bot.config import config as _config
    original_path = _config.database_path
    _config.database_path = path
    try:
        from bot.database import init_db
        asyncio.run(init_db())
        yield path
    finally:
        _config.database_path = original_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass


def _run(coro):
    return asyncio.run(coro)


def _src(module) -> str:
    return inspect.getsource(module)


async def _make_teacher(user_id: int = 100, price: str = "1000P", is_active: bool = True):
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO teachers
               (user_id, username, display_name, region, price, tags, button_url, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "u", "T", "成都", price, "[]", "https://t.me/x",
             1 if is_active else 0),
        )
        await db.commit()
        return user_id
    finally:
        await db.close()


async def _baseline(*, feature_on=True, min_pts=5, pool=0):
    from bot.database import set_config, set_reimbursement_min_points
    await set_config("reimbursement_feature_enabled", "1" if feature_on else "0")
    await set_reimbursement_min_points(min_pts)
    await set_config("reimbursement_monthly_pool", str(pool))


async def _set_user_points(uid: int, points: int):
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, total_points) VALUES (?, ?)",
            (uid, points),
        )
        await db.commit()
    finally:
        await db.close()


class _FakeFSM:
    """轻量 FSM：模拟 aiogram FSMContext 的 get_state / set_state / get_data /
    set_data / update_data，仅在内存里维护两个变量，避免完整 storage 配套。
    """
    def __init__(self):
        self._state = None
        self._data: dict = {}

    async def get_state(self):
        return self._state

    async def set_state(self, s):
        # aiogram State 对象有 .state 字符串属性；这里转字符串保留以便测试
        self._state = s.state if hasattr(s, "state") else s

    async def get_data(self):
        return dict(self._data)

    async def set_data(self, d: dict):
        self._data = dict(d)

    async def update_data(self, **kw):
        self._data.update(kw)

    async def clear(self):
        self._state = None
        self._data = {}


# ============================================================
# 1. start_card_review 分支
# ============================================================


def test_start_card_review_eligible_routes_to_intent(temp_db, monkeypatch):
    """eligible 用户 → state = choosing_reimburse_intent + info 入 data，
    不写 request_reimbursement（等用户选 yes/no 时再写）。"""
    _run(_baseline(feature_on=True, min_pts=5, pool=0))
    tid = _run(_make_teacher(price="1000P"))
    _run(_set_user_points(999, 10))

    # 桩 check_user_subscribed（全局必关）→ pass
    async def _fake_subscribed(*args, **kw):
        return True, []
    from bot.handlers import review_card
    monkeypatch.setattr(review_card, "check_user_subscribed", _fake_subscribed)

    state = _FakeFSM()
    status, extra = _run(review_card.start_card_review(
        bot=None, user_id=999, teacher_id=tid, state=state,
    ))
    assert status == "ok"
    assert extra["needs_intent"] is True
    assert extra["eligibility"]["reason"] is None
    from bot.states.teacher_states import CardReviewStates
    assert state._state == CardReviewStates.choosing_reimburse_intent.state
    assert state._data["_reimburse_eligibility_info"]["amount"] == 200
    assert "request_reimbursement" not in state._data


def test_start_card_review_ineligible_routes_to_card(temp_db, monkeypatch):
    """积分不足 → 直接 card + request_reimbursement=0 + info 存 reason。"""
    _run(_baseline(feature_on=True, min_pts=5, pool=0))
    tid = _run(_make_teacher(price="1000P"))
    _run(_set_user_points(999, 1))  # below threshold

    async def _fake_subscribed(*args, **kw):
        return True, []
    from bot.handlers import review_card
    monkeypatch.setattr(review_card, "check_user_subscribed", _fake_subscribed)

    state = _FakeFSM()
    status, extra = _run(review_card.start_card_review(
        bot=None, user_id=999, teacher_id=tid, state=state,
    ))
    assert status == "ok"
    assert extra["needs_intent"] is False
    assert extra["eligibility"]["reason"] == "below_threshold"
    from bot.states.teacher_states import CardReviewStates
    assert state._state == CardReviewStates.card.state
    assert state._data["request_reimbursement"] == 0
    assert state._data["_reimburse_eligibility_info"]["reason"] == "below_threshold"


def test_start_card_review_feature_off_routes_to_card(temp_db, monkeypatch):
    """功能关闭 → 直接 card + request_reimbursement=0 + reason=feature_off。"""
    _run(_baseline(feature_on=False))
    tid = _run(_make_teacher(price="1000P"))
    _run(_set_user_points(999, 100))

    async def _fake_subscribed(*args, **kw):
        return True, []
    from bot.handlers import review_card
    monkeypatch.setattr(review_card, "check_user_subscribed", _fake_subscribed)

    state = _FakeFSM()
    status, extra = _run(review_card.start_card_review(
        bot=None, user_id=999, teacher_id=tid, state=state,
    ))
    assert status == "ok"
    assert extra["eligibility"]["reason"] == "feature_off"
    assert state._data["request_reimbursement"] == 0


# ============================================================
# 2. intent handler 源码静态契约
# ============================================================


def test_intent_yes_handler_calls_subreq_check_and_sets_req_1():
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def cb_card_intent_yes(")
    assert idx > 0
    end = src.find("async def ", idx + 1)
    body = src[idx:end]
    assert "check_user_subscribed_for_reimburse" in body
    assert "request_reimbursement=1" in body
    assert "CardReviewStates.card" in body


def test_intent_no_handler_sets_req_0_without_subreq_check():
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def cb_card_intent_no(")
    assert idx > 0
    end = src.find("async def ", idx + 1)
    body = src[idx:end]
    assert "request_reimbursement=0" in body
    assert "check_user_subscribed_for_reimburse" not in body  # 不参与无需检查


def test_intent_retry_handler_rechecks_subreq():
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def cb_card_intent_retry(")
    assert idx > 0
    end = src.find("async def ", idx + 1)
    body = src[idx:end]
    assert "check_user_subscribed_for_reimburse" in body
    assert "request_reimbursement=1" in body


def test_intent_fallback_handler_sets_req_0():
    """fallback：用户放弃报销改为不参与 → req=0 + 进 card。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def cb_card_intent_fallback(")
    assert idx > 0
    end = src.find("async def ", idx + 1)
    body = src[idx:end]
    assert "request_reimbursement=0" in body
    assert "check_user_subscribed_for_reimburse" not in body


def test_all_intent_handlers_gated_on_intent_state():
    """4 个 intent handler 都必须 state-gate 在 choosing_reimburse_intent。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    for fn in ("cb_card_intent_yes", "cb_card_intent_no",
               "cb_card_intent_retry", "cb_card_intent_fallback"):
        idx = src.find(f"async def {fn}(")
        # 反向找前面的 @router 装饰段
        decorator_start = src.rfind("@router.callback_query(", 0, idx)
        decorator_body = src[decorator_start:idx]
        assert "CardReviewStates.choosing_reimburse_intent" in decorator_body, (
            f"{fn} 必须 state-gate 在 choosing_reimburse_intent"
        )


# ============================================================
# 3. intent kb 形状
# ============================================================


def test_review_intent_kb_has_yes_no_cancel():
    from bot.keyboards.user_kb import review_intent_kb
    kb = review_intent_kb(amount=200)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "card:intent:yes" in cbs
    assert "card:intent:no" in cbs
    assert "card:cancel" in cbs
    # yes 按钮文案带金额
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("200" in t for t in texts)


def test_review_intent_subreq_fail_kb_has_retry_fallback_cancel():
    from bot.keyboards.user_kb import review_intent_subreq_fail_kb
    missing = [{"display_name": "测试群", "invite_link": "https://t.me/x", "chat_id": -100}]
    kb = review_intent_subreq_fail_kb(missing)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "card:intent:retry" in cbs
    assert "card:intent:fallback" in cbs
    assert "card:cancel" in cbs
    # 邀请链接为 URL 按钮（callback_data 为 None）
    urls = [b.url for row in kb.inline_keyboard for b in row if b.url]
    assert "https://t.me/x" in urls


def test_review_intent_subreq_fail_kb_empty_missing_still_has_actions():
    from bot.keyboards.user_kb import review_intent_subreq_fail_kb
    kb = review_intent_subreq_fail_kb([])
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "card:intent:retry" in cbs
    assert "card:intent:fallback" in cbs


# ============================================================
# 4. render_card_or_intent dispatcher
# ============================================================


def test_render_card_or_intent_dispatches_to_intent_when_state_matches():
    """state == choosing_reimburse_intent → 调 render_intent_screen。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def render_card_or_intent(")
    assert idx > 0
    end = src.find("async def ", idx + 1)
    body = src[idx:end]
    assert "choosing_reimburse_intent" in body
    assert "render_intent_screen" in body
    assert "render_card" in body  # 兜底分支


def test_render_intent_screen_exists():
    """render_intent_screen 函数存在且使用 review_intent_kb。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def render_intent_screen(")
    assert idx > 0
    end = src.find("async def ", idx + 1)
    body = src[idx:end]
    assert "review_intent_kb" in body
    assert "_reimburse_eligibility_info" in body

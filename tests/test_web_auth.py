"""bot/web/auth.py · initData 验签单元测试（P0·T1）。

不连数据库、不连 Telegram、不依赖 conftest 的 BOT_TOKEN——验签函数把 bot_token
作为参数显式传入，测试自给一组确定性数据。验签是同步纯函数，无需 asyncio 包裹。

覆盖：合法验签 / 错误 token（hash 不匹配）/ 篡改字段 / 过期 / 缺 hash / 缺 user /
user.id 非法。
"""
from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from bot.web.auth import (
    InvalidInitData,
    InvalidSession,
    WebAppInitData,
    issue_session,
    verify_init_data,
    verify_session,
)

_TOKEN = "123456:dummy-bot-token"


def _sign(fields: dict, *, bot_token: str = _TOKEN) -> str:
    """按官方算法给 fields 生成合法 initData（含 hash）。"""
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})


def _fields(uid: int = 123, auth_date: int = 1_000) -> dict:
    return {
        "user": json.dumps({"id": uid, "first_name": "T", "username": "t"}),
        "auth_date": str(auth_date),
    }


def test_valid_init_data_returns_payload():
    init = _sign(_fields(uid=777, auth_date=1_000))
    res = verify_init_data(init, _TOKEN, now=1_000.0)
    assert isinstance(res, WebAppInitData)
    assert res.user_id == 777
    assert res.user["username"] == "t"
    assert res.auth_date == 1_000
    assert "hash" not in res.raw  # hash 已剔除，不进入可信载荷


def test_wrong_token_fails_hash():
    # 用别的 token 签名，在正确 token 下验签应失败
    init = _sign(_fields(), bot_token="999:other-token")
    with pytest.raises(InvalidInitData):
        verify_init_data(init, _TOKEN, now=1_000.0)


def test_tampered_field_fails_hash():
    init = _sign(_fields(uid=123, auth_date=1_000))
    # 合法签名后篡改 auth_date 的值，hash 未重算 → 验签失败
    tampered = init.replace("auth_date=1000", "auth_date=2000")
    assert tampered != init
    with pytest.raises(InvalidInitData):
        verify_init_data(tampered, _TOKEN, now=2_000.0)


def test_expired_init_data():
    init = _sign(_fields(auth_date=1_000))
    with pytest.raises(InvalidInitData):
        verify_init_data(init, _TOKEN, max_age_seconds=3_600, now=1_000 + 3_601)


def test_missing_hash():
    with pytest.raises(InvalidInitData):
        verify_init_data("user=%7B%22id%22%3A1%7D&auth_date=1000", _TOKEN, now=1_000.0)


def test_empty_init_data():
    with pytest.raises(InvalidInitData):
        verify_init_data("", _TOKEN, now=1_000.0)


def test_missing_user():
    init = _sign({"auth_date": "1000"})  # 没有 user 字段但 hash 合法
    with pytest.raises(InvalidInitData):
        verify_init_data(init, _TOKEN, now=1_000.0)


def test_user_id_not_int():
    init = _sign({"user": json.dumps({"id": "abc"}), "auth_date": "1000"})
    with pytest.raises(InvalidInitData):
        verify_init_data(init, _TOKEN, now=1_000.0)


# ============ session token ============

def test_session_roundtrip():
    tok = issue_session(123, "admin", _TOKEN, ttl_seconds=3_600, now=1_000.0)
    payload = verify_session(tok, _TOKEN, now=1_000.0)
    assert payload["uid"] == 123
    assert payload["role"] == "admin"
    assert payload["exp"] == 1_000 + 3_600


def test_session_expired():
    tok = issue_session(1, "user", _TOKEN, ttl_seconds=60, now=1_000.0)
    with pytest.raises(InvalidSession):
        verify_session(tok, _TOKEN, now=1_000 + 61)


def test_session_tampered_sig():
    tok = issue_session(1, "user", _TOKEN, now=1_000.0)
    with pytest.raises(InvalidSession):
        verify_session(tok + "x", _TOKEN, now=1_000.0)


def test_session_wrong_secret():
    tok = issue_session(1, "user", _TOKEN, now=1_000.0)
    with pytest.raises(InvalidSession):
        verify_session(tok, "other-secret", now=1_000.0)


def test_session_bad_format():
    with pytest.raises(InvalidSession):
        verify_session("no-separator", _TOKEN, now=1_000.0)

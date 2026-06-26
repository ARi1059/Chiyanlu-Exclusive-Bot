"""Telegram WebApp initData 验签（P0·T1）。

MiniApp 启动时 `window.Telegram.WebApp.initData` 携带一个由 Bot Token 签名的
query string。后端必须验签后才信任其中的 `user.id`，这是 MiniApp 唯一可信的
身份来源（详见 docs/MINIAPP-MIGRATION.md §三）。

验签算法（Telegram 官方）：
    1. secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    2. data_check_string = 除 hash 外所有字段按 key 升序，"k=v" 以 \\n 连接
    3. 比对 HMAC_SHA256(key=secret_key, msg=data_check_string) == hash
    4. 校验 auth_date 时间窗，防重放

本模块只依赖标准库（hmac / hashlib / json / urllib），**不 import bot.config /
bot.database**，因此：
    - 纯函数、无副作用、无 I/O，可独立单测（bot_token 由调用方显式传入）；
    - session 签发 / 角色解析（依赖 config / db）放后续 task，不污染本文件。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl


class InvalidInitData(ValueError):
    """initData 验签失败 / 过期 / 结构非法。统一用一种异常，调用方据此回 401。"""


class InvalidSession(ValueError):
    """session token 签名不匹配 / 过期 / 格式非法。调用方据此回 401。"""


@dataclass(frozen=True)
class WebAppInitData:
    """验签通过后的可信载荷。

    user_id / user 来自已验签的 `user` 字段，可直接用于角色解析；
    raw 保留除 hash 外的全部原始字段（已 URL-decode），供来源追踪等扩展使用。
    """
    user_id: int
    user: dict
    auth_date: int
    raw: dict


# 默认时间窗：24h。超过则视为过期，拒绝（防重放）。
DEFAULT_MAX_AGE_SECONDS: int = 86_400


def verify_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: Optional[float] = None,
) -> WebAppInitData:
    """验签 initData；成功返回可信载荷，失败抛 ``InvalidInitData``。

    Args:
        init_data: `Telegram.WebApp.initData` 原始 query string。
        bot_token: 本 bot 的 token（验签密钥来源）。显式传入以保持本模块无配置依赖。
        max_age_seconds: auth_date 允许的最大年龄；<=0 表示不校验时间（仅测试用）。
        now: 当前 epoch 秒；缺省取 ``time.time()``（注入以便单测确定性）。

    Raises:
        InvalidInitData: 空串 / 缺 hash / hash 不匹配 / 过期 / user 结构非法。
    """
    if not init_data:
        raise InvalidInitData("空 initData")

    # parse_qsl 已对 value 做 URL-decode；initData 无重复键，dict() 安全。
    pairs: dict[str, str] = dict(parse_qsl(init_data, keep_blank_values=True))

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InvalidInitData("缺少 hash 字段")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InvalidInitData("hash 校验失败")

    # ---- auth_date 时间窗 ----
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InvalidInitData(f"auth_date 非法: {pairs.get('auth_date')!r}") from exc
    cur = now if now is not None else time.time()
    if max_age_seconds > 0 and (cur - auth_date) > max_age_seconds:
        raise InvalidInitData(f"initData 过期（auth_date={auth_date}）")

    # ---- user 字段 ----
    user_raw = pairs.get("user")
    if not user_raw:
        raise InvalidInitData("缺少 user 字段")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InvalidInitData("user 字段非法 JSON") from exc
    uid = user.get("id")
    if not isinstance(uid, int):
        raise InvalidInitData("user.id 缺失或非整数")

    return WebAppInitData(user_id=uid, user=user, auth_date=auth_date, raw=pairs)


# ============ session token（自签 HMAC，零依赖；§三 / §十九 #2 选型）============
# 选用自签 HMAC 而非 PyJWT：本项目崇尚最小依赖（生产依赖仅 4 个）。payload +
# HMAC-SHA256 + 过期校验已满足 P0 需求，零新增依赖。token 形如
# "<b64url(payload)>.<b64url(sig)>"；secret 由调用方传入（复用 bot_token）。

# session 默认有效期（秒）：60 分钟（§十二 P0：30–60min）。
SESSION_DEFAULT_TTL_SECONDS: int = 3_600


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_session(
    user_id: int,
    role: str,
    secret: str,
    *,
    ttl_seconds: int = SESSION_DEFAULT_TTL_SECONDS,
    now: Optional[float] = None,
) -> str:
    """签发 session token：payload={uid, role, exp} + HMAC-SHA256 签名。"""
    cur = int(now if now is not None else time.time())
    payload = {"uid": int(user_id), "role": role, "exp": cur + int(ttl_seconds)}
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url_encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session(token: str, secret: str, *, now: Optional[float] = None) -> dict:
    """校验 session token；成功返回 payload，失败抛 ``InvalidSession``。

    校验顺序：格式 → 签名（防伪造）→ 过期。签名先于反序列化，避免对未验证数据
    做 json.loads。
    """
    if not token or "." not in token:
        raise InvalidSession("token 格式错误")
    body, _, sig = token.partition(".")
    expected = _b64url_encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        raise InvalidSession("签名不匹配")
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidSession("payload 非法") from exc
    cur = int(now if now is not None else time.time())
    if int(payload.get("exp", 0)) < cur:
        raise InvalidSession("session 过期")
    return payload


# ============ 照片访问签名（<img> 无法带 Bearer，改用 URL 短期签名）============
# 浏览器 <img src> 不会带 Authorization 头，照片端点不能用 session 鉴权。改为
# URL 携带签名：HMAC(teacher_id.exp)。exp 按天边界对齐——同一天内同一老师 URL 稳定
# （利于浏览器/反代缓存），1–2 天后失效，兼顾访问控制与缓存。secret 复用 bot_token。
_PHOTO_BUCKET_SECONDS: int = 86_400  # 过期按天对齐


def sign_photo(teacher_id: int, secret: str, *, now: Optional[float] = None) -> str:
    """签发照片访问令牌 "<exp>.<sig>"。exp 对齐到 1–2 天后的整天边界。"""
    cur = int(now if now is not None else time.time())
    exp = (cur // _PHOTO_BUCKET_SECONDS + 2) * _PHOTO_BUCKET_SECONDS
    msg = f"{int(teacher_id)}.{exp}".encode()
    sig = _b64url_encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest())
    return f"{exp}.{sig}"


def verify_photo(teacher_id: int, token: str, secret: str, *, now: Optional[float] = None) -> bool:
    """校验照片令牌：格式 → 签名（防伪造）→ 过期。任一失败返回 False。"""
    if not token or "." not in token:
        return False
    exp_str, _, sig = token.partition(".")
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    expected = _b64url_encode(
        hmac.new(secret.encode(), f"{int(teacher_id)}.{exp}".encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, sig):
        return False
    cur = int(now if now is not None else time.time())
    return exp >= cur

"""审核 claim 内存锁（UX-7.1）。

并发审核场景下，让两个超管不会同时进入同一条审核详情。

核心 API：
    - try_claim(kind, target_id, admin_id) → (ok, existing)
        ok=True：自己持有 / 锁已过期 / 是同一人 → 成功声明
        ok=False, existing=ClaimInfo：被别人持有 → 失败
    - force_claim(kind, target_id, admin_id) → ClaimInfo
        强制接管（覆盖现有持有者）。必须配合 audit log + 二次确认使用。
    - release_claim(kind, target_id, admin_id) → bool
        释放锁；仅当自己持有时才真正释放（防止误释放别人的）。
    - get_claim(kind, target_id) → Optional[ClaimInfo]
        只读：拿当前锁信息（自动跳过已过期锁）。

设计取舍：
    - 单副本内存 dict，TTL = 5 分钟。**当前项目单副本部署**，多副本部署时
      此锁将失效（应改为 Redis/DB；属下个 sprint 范围）。
    - kind 字符串区分命名空间：'edit_request'（老师资料）/ 'teacher_review'（评价）/
      'reimbursement'（报销）—— 与 audit log target_type 对齐。
    - 写入失败不抛；读取过期锁返回 None；不依赖外部 I/O。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import RLock
from typing import Optional

logger = logging.getLogger(__name__)


# 默认 TTL：5 分钟无操作 → 锁自动过期
CLAIM_TTL_SECONDS: float = 300.0


@dataclass(frozen=True)
class ClaimInfo:
    """锁持有信息。"""
    kind: str
    target_id: str
    admin_id: int
    acquired_at: float  # epoch seconds


# 内部状态：(kind, target_id_str) → ClaimInfo
_claims: dict[tuple[str, str], ClaimInfo] = {}
_lock = RLock()


def _now() -> float:
    return time.time()


def _is_expired(claim: ClaimInfo, *, now: Optional[float] = None) -> bool:
    cur = now if now is not None else _now()
    return (cur - claim.acquired_at) >= CLAIM_TTL_SECONDS


def get_claim(
    kind: str, target_id, *, now: Optional[float] = None,
) -> Optional[ClaimInfo]:
    """读取当前锁信息；锁已过期或不存在时返回 None。"""
    key = (str(kind), str(target_id))
    with _lock:
        claim = _claims.get(key)
        if claim is None:
            return None
        if _is_expired(claim, now=now):
            # 顺手清掉过期记录（避免内存无界增长）
            _claims.pop(key, None)
            return None
        return claim


def try_claim(
    kind: str, target_id, admin_id: int, *, now: Optional[float] = None,
) -> tuple[bool, Optional[ClaimInfo]]:
    """尝试声明审核占用（UX-7.1 内存锁）。

    Returns:
        (True, None)        声明成功（无锁 / 过期 / 自己持有 → 刷新时间戳）
        (False, existing)   失败：另一管理员持有未过期锁
    """
    if admin_id <= 0:
        # admin_id=0 是历史 placeholder，永远视为成功（不写入锁，避免污染）
        return True, None
    key = (str(kind), str(target_id))
    cur = now if now is not None else _now()
    with _lock:
        existing = _claims.get(key)
        if existing is not None and not _is_expired(existing, now=cur):
            if int(existing.admin_id) == int(admin_id):
                # 自己持有 → 刷新 acquired_at（视为"重新进入"）
                refreshed = ClaimInfo(
                    kind=existing.kind,
                    target_id=existing.target_id,
                    admin_id=existing.admin_id,
                    acquired_at=cur,
                )
                _claims[key] = refreshed
                return True, None
            return False, existing
        # 无锁 / 已过期 → 声明
        new_claim = ClaimInfo(
            kind=str(kind),
            target_id=str(target_id),
            admin_id=int(admin_id),
            acquired_at=cur,
        )
        _claims[key] = new_claim
        return True, None


def force_claim(
    kind: str, target_id, admin_id: int, *, now: Optional[float] = None,
) -> ClaimInfo:
    """强制接管：覆盖现有持有者（UX-7.1）。

    调用方应在二次确认 + audit log 写入"force_claim" action 之后才调用本函数。
    """
    key = (str(kind), str(target_id))
    cur = now if now is not None else _now()
    new_claim = ClaimInfo(
        kind=str(kind),
        target_id=str(target_id),
        admin_id=int(admin_id),
        acquired_at=cur,
    )
    with _lock:
        _claims[key] = new_claim
    return new_claim


def release_claim(
    kind: str, target_id, admin_id: int,
) -> bool:
    """释放锁；仅当 admin_id 与持有者一致时才释放（防止误释放）。

    Returns:
        True 表示释放成功；False 表示未持有 / 持有者不是 admin_id。
    """
    key = (str(kind), str(target_id))
    with _lock:
        existing = _claims.get(key)
        if existing is None:
            return False
        if int(existing.admin_id) != int(admin_id):
            return False
        _claims.pop(key, None)
        return True


def reset_for_test() -> None:
    """仅供测试使用：清空所有锁（避免测试间互相污染）。"""
    with _lock:
        _claims.clear()

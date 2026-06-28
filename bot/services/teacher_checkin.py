"""老师签到共享 service（bot 文字「签到」/ bot 按钮 / MiniApp web 同源）。

三处入口此前各写一遍「老师存在 → is_active → 时间窗口(< publish_time) → 幂等(未签)
→ 落库」逻辑，规则一改要同步三处、易漂移。抽到这里做单一真相源；各入口只负责
各自表面的渲染（文字 reply / callback alert / JSON）。

对齐既有 service 架构（review_submit / teacher_self_edit）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pytz import timezone

from bot.config import config
from bot.database import checkin_teacher, get_config, get_teacher, is_checked_in


@dataclass
class CheckinResult:
    """签到结果。

    status:
        not_teacher → 不在老师名单
        inactive    → 账号已停用
        closed      → 已过 publish_time 截止窗口
        already     → 今日已签到（幂等）
        success     → 本次签到成功
        failed      → checkin_teacher 落库失败
    """
    status: str
    teacher: Optional[dict] = None
    today_str: str = ""
    now_hm: str = ""        # 当前本地时间 HH:MM
    deadline: str = ""      # publish_time HH:MM

    @property
    def checked_in(self) -> bool:
        """是否处于「今日已签到」态（成功或幂等已签）。"""
        return self.status in ("success", "already")


async def perform_checkin(teacher_id: int) -> CheckinResult:
    """执行老师签到的全部业务校验 + 落库（三表面共用）。

    校验链与历史三处逐字一致：老师存在 → is_active → 时间窗口(现在 < publish_time)
    → 幂等(未签) → checkin_teacher。时区用 config.timezone（Asia/Shanghai）。
    """
    tz = timezone(config.timezone)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    now_hm = now.strftime("%H:%M")

    teacher = await get_teacher(teacher_id)
    if not teacher:
        return CheckinResult("not_teacher", today_str=today_str, now_hm=now_hm)
    if not teacher.get("is_active"):
        return CheckinResult("inactive", teacher=teacher, today_str=today_str, now_hm=now_hm)

    publish_time = await get_config("publish_time") or config.publish_time
    try:
        hour, minute = map(int, str(publish_time).split(":"))
    except (ValueError, AttributeError):
        hour, minute = 14, 0

    res = CheckinResult(
        "", teacher=teacher, today_str=today_str, now_hm=now_hm,
        deadline=str(publish_time),
    )

    # 时间窗口：现在 ≥ publish_time → 截止
    if now.hour > hour or (now.hour == hour and now.minute >= minute):
        res.status = "closed"
        return res

    # 幂等：今日已签
    if await is_checked_in(teacher_id, today_str):
        res.status = "already"
        return res

    success = await checkin_teacher(teacher_id, today_str)
    res.status = "success" if success else "failed"
    return res

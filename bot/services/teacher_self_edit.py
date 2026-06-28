"""老师自助改资料共享 service（bot FSM + MiniApp web 同源）。

抽自 handlers/teacher_self.py 的编辑核心，杜绝 bot/web 两端逻辑漂移
（对齐既有 review_submit / review_moderation 架构）。

规则（v2 §2.3.3 / §2.3.3a，与 bot 一致）：
    - 6 字段白名单：display_name / region / price / tags / photo_file_id / button_text
    - 文字字段（5 个）：UPDATE teachers 立即生效 + INSERT edit_request(pending)
      → 管理员审核；驳回时回滚到旧值。
    - 图片字段（photo_file_id）：不动 teachers + INSERT edit_request
      → 审核通过后才切换到新图，期间展示旧图。
    - old == new 直接拒（避免无意义审核）。
    - 每次修改推一条私聊给所有管理员（含超管，去重）。
"""
from __future__ import annotations

import json
import logging
import re

from bot.config import config
from bot.database import (
    create_edit_request,
    get_all_admins,
    get_teacher,
    update_teacher,
)

logger = logging.getLogger(__name__)

# 老师可自助改的字段白名单（必须与 database.TEACHER_EDITABLE_FIELDS 一致）。
EDITABLE_FIELDS: set[str] = {
    "display_name",
    "region",
    "price",
    "tags",
    "photo_file_id",
    "button_text",
}

# 字段中文名（用于审核通知 + 结果文案）。
FIELD_LABELS: dict[str, str] = {
    "display_name": "艺名",
    "region": "地区",
    "price": "价格",
    "tags": "标签",
    "photo_file_id": "图片",
    "button_text": "按钮文本",
}

# 文字字段（立即生效）。photo_file_id 走延后生效分支。
_TEXT_FIELDS: set[str] = EDITABLE_FIELDS - {"photo_file_id"}

DISPLAY_NAME_MAX_LEN = 40


def parse_tags(text: str) -> str:
    """把用户输入的标签串转成 JSON 数组字符串。

    支持空格 / 中文逗号 / 英文逗号 / 顿号分隔；去空 + 去重保序。
    全空时返回 "[]"（调用方据此判定无效）。
    """
    parts = re.split(r"[\s,，、]+", text or "")
    seen: list[str] = []
    seen_set: set[str] = set()
    for p in parts:
        p = p.strip()
        if not p:
            continue
        key = p.lower()
        if key in seen_set:
            continue
        seen_set.add(key)
        seen.append(p)
    return json.dumps(seen, ensure_ascii=False)


def validate_field(field: str, raw) -> tuple[bool, object, str | None]:
    """校验 + 规范化单字段新值。

    Returns (ok, normalized, error_code)。error_code ∈
        unknown_field / empty / too_long / empty_tags。
    photo_file_id：raw 应为 file_id 串，非空即可。
    文字字段：strip 后非空；display_name 额外 ≤40 字。
    tags：parse_tags 后非 "[]"。
    """
    if field not in EDITABLE_FIELDS:
        return False, None, "unknown_field"

    if field == "photo_file_id":
        fid = (raw or "").strip() if isinstance(raw, str) else raw
        if not fid:
            return False, None, "empty"
        return True, fid, None

    text = (raw or "").strip() if isinstance(raw, str) else ""
    if not text:
        return False, None, "empty"

    if field == "tags":
        encoded = parse_tags(text)
        if encoded == "[]":
            return False, None, "empty_tags"
        return True, encoded, None

    if field == "display_name" and len(text) > DISPLAY_NAME_MAX_LEN:
        return False, None, "too_long"

    return True, text, None


_ERROR_MESSAGES: dict[str, str] = {
    "unknown_field": "无效字段",
    "not_teacher": "你不在老师名单内",
    "empty": "内容不能为空",
    "too_long": f"艺名过长（最多 {DISPLAY_NAME_MAX_LEN} 字）",
    "empty_tags": "至少输入一个有效标签",
    "same": "新值与旧值相同，无需修改",
    "update_failed": "修改失败，请稍后重试",
    "create_request_failed": "创建审核请求失败",
}


def error_message(code: str) -> str:
    return _ERROR_MESSAGES.get(code, "修改失败")


async def notify_admins(
    bot,
    teacher: dict,
    field_name: str,
    old_value: str | None,
    new_value: str,
    request_id: int,
) -> None:
    """老师改一次 → 推一条私聊给所有管理员（含超管，去重）。失败仅记日志。"""
    label = FIELD_LABELS.get(field_name, field_name)

    if field_name == "photo_file_id":
        old_repr = "已上传" if old_value else "（空）"
        new_repr = "新图（待审核）"
        note = "\n\n⚠️ 图片字段：审核通过后才会切换到新图，旧图继续展示。"
    else:
        old_repr = old_value if old_value else "（空）"
        new_repr = new_value if new_value else "（空）"
        note = ""

    text = (
        f"📝 老师修改通知\n"
        f"━━━━━━━━━━━━━━━\n"
        f"老师: {teacher.get('display_name')} (ID: {teacher.get('user_id')})\n"
        f"字段: {label}\n"
        f"原值: {old_repr}\n"
        f"新值: {new_repr}\n"
        f"请求 ID: {request_id}{note}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"在管理面板「📝 待审核」中处理。"
    )

    admins = await get_all_admins()
    target_ids = {a["user_id"] for a in admins}
    target_ids.add(config.super_admin_id)

    for admin_id in target_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception as e:
            logger.warning("通知管理员 %s 失败: %s", admin_id, e)


async def submit_field_edit(bot, teacher_id: int, field: str, raw_value) -> dict:
    """提交单字段修改（bot/web 共用）。

    raw_value：文字字段=用户输入串；图片字段=已取好的 file_id 串。
    复刻 teacher_self.on_edit_value：校验 → 文字立即生效 / 图片延后 →
    建 edit_request → 通知管理员。

    Returns dict：
        {ok, applied(bool), request_id, field, label, message, error}
        applied=True  文字字段已即时写入 teachers（可回滚）
        applied=False 图片字段仅入审核队列（审核后才生效）
    """
    label = FIELD_LABELS.get(field, field)

    def _fail(code: str) -> dict:
        return {
            "ok": False, "applied": False, "request_id": None,
            "field": field, "label": label,
            "message": error_message(code), "error": code,
        }

    ok, normalized, err = validate_field(field, raw_value)
    if not ok:
        return _fail(err or "update_failed")

    teacher = await get_teacher(teacher_id)
    if not teacher:
        return _fail("not_teacher")

    old_value = teacher.get(field)

    # 图片字段（延后生效）：不动 teachers，仅建 edit_request。
    if field == "photo_file_id":
        request_id = await create_edit_request(
            teacher_id=teacher_id,
            field_name="photo_file_id",
            old_value=old_value,
            new_value=normalized,
        )
        if request_id is None:
            return _fail("create_request_failed")
        await notify_admins(bot, teacher, "photo_file_id", old_value, normalized, request_id)
        return {
            "ok": True, "applied": False, "request_id": request_id,
            "field": field, "label": label,
            "message": "🖼️ 图片已提交审核，通过后生效；期间展示旧图。",
            "error": None,
        }

    # 文字字段（立即生效）。
    if old_value == normalized:
        return _fail("same")

    updated = await update_teacher(teacher_id, field, normalized)
    if not updated:
        return _fail("update_failed")

    request_id = await create_edit_request(
        teacher_id=teacher_id,
        field_name=field,
        old_value=old_value,
        new_value=normalized,
    )
    if request_id is None:
        # 白名单已校验，理论不会到这；teachers 已改但缺审核单，记错误。
        logger.error(
            "create_edit_request 返回 None: teacher=%s field=%s", teacher_id, field,
        )
    else:
        await notify_admins(bot, teacher, field, old_value, normalized, request_id)

    return {
        "ok": True, "applied": True, "request_id": request_id,
        "field": field, "label": label,
        "message": f"✅ {label}修改已生效，管理员审核中（不通过会自动回滚）。",
        "error": None,
    }

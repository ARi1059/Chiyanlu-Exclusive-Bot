"""管理员新增老师档案编排（bot FSM 录入 与 MiniApp web 录入 同源 service）。

抽自 bot/handlers/teacher_profile.py 的 cb_profile_save（落库三步）+ 各 step 校验，
集中成一个 create_teacher_from_form(form)：校验 → 派生 → 查重 → 落库（add_teacher +
update_teacher_profile_field 批量 + set_teacher_photos）。

身份录入 = 手填 user_id（不依赖 bot 转发）；与 FSM 手动路径（Step1a/1b/1c）校验一致。
错误统一 {ok, error, field, message}（形态同 teacher_self_edit）。价格派生纯函数复用
bot/utils/teacher_pricing（bot/web 同源，杜绝漂移）。
"""
from __future__ import annotations

import json
import logging
import re

from bot.database import (
    add_teacher,
    get_teacher,
    parse_basic_info,
    set_teacher_photos,
    update_teacher_profile_field,
)
from bot.utils.teacher_pricing import (
    DEFAULT_TABOOS,
    _compute_description_from_price,
    _extract_largest_price,
    _inject_price_tag_into_tags,
)
from bot.utils.url import normalize_url

logger = logging.getLogger(__name__)

DISPLAY_NAME_MAX = 40
ALBUM_MAX = 10

_USERNAME_RE = re.compile(r"[A-Za-z0-9_]{4,32}")
_CONTACT_RE = re.compile(r"@[A-Za-z0-9_]{4,32}")

_ERR: dict[str, str] = {
    "invalid_user_id": "user_id 必须是纯数字",
    "duplicate": "该 user_id 已存在老师",
    "bad_username": "username 需 4-32 位字母/数字/下划线",
    "bad_contact": "联系电报必须 @ 开头，4-32 位字母/数字/下划线（如 @chixiaoxia）",
    "empty_display_name": "艺名不能为空",
    "too_long_display_name": f"艺名过长（最多 {DISPLAY_NAME_MAX} 字）",
    "bad_basic_info": "基本信息格式错误（年龄15-60 / 身高140-200 / 体重35-120 / 罩杯1-3字母）",
    "empty_region": "地区不能为空",
    "no_price": "价格描述里找不到「数字+P」（如 800P）",
    "bad_url": "跳转链接格式不正确（需 http/https/tg）",
    "empty_tags": "至少输入一个标签",
    "no_photos": "至少上传 1 张照片",
    "too_many_photos": f"相册最多 {ALBUM_MAX} 张",
    "save_failed": "保存失败，请稍后重试",
}


def _fail(code: str, *, field: str | None = None) -> dict:
    return {"ok": False, "error": code, "field": field, "message": _ERR.get(code, "录入失败")}


def _norm_user_id(raw) -> int | None:
    s = str(raw).strip()
    return int(s) if s.isdigit() else None


def _norm_username(raw) -> str | None:
    s = str(raw or "").strip().lstrip("@")
    return s if _USERNAME_RE.fullmatch(s) else None


def _norm_contact(raw) -> str | None:
    s = str(raw or "").strip()
    return s if _CONTACT_RE.fullmatch(s) else None


def _norm_tags(raw) -> list[str]:
    """分隔 + 去 # + 去空。照搬 FSM step_tags 口径（不去重，去重交给 _inject）。"""
    if isinstance(raw, list):
        parts = [str(t) for t in raw]
    else:
        parts = re.split(r"[,，\s]+", str(raw or ""))
    return [t.strip().lstrip("#") for t in parts if t.strip()]


async def create_teacher_from_form(form: dict) -> dict:
    """管理员一屏新增老师（校验 → 派生 → 查重 → 落库三步）。

    form 键：user_id, username, contact_telegram, display_name,
             basic_info(str「年龄 身高 体重 罩杯」) 或拆开的 age/height_cm/weight_kg/bra_size,
             region, price_detail, service_content(可选), tags, button_url, photos[](file_id)
    Returns {ok, user_id?, error?, field?, message?}
    """
    form = form or {}

    # 1) 身份（手填，照搬 FSM 手动路径校验）
    uid = _norm_user_id(form.get("user_id"))
    if uid is None:
        return _fail("invalid_user_id", field="user_id")
    username = _norm_username(form.get("username"))
    if username is None:
        return _fail("bad_username", field="username")
    contact = _norm_contact(form.get("contact_telegram"))
    if contact is None:
        return _fail("bad_contact", field="contact_telegram")

    # 2) 基本信息：支持整串或已拆字段
    if form.get("basic_info"):
        basic = parse_basic_info(str(form["basic_info"]))
    else:
        basic = parse_basic_info(
            f'{form.get("age", "")} {form.get("height_cm", "")} '
            f'{form.get("weight_kg", "")} {form.get("bra_size", "")}'
        )
    if basic is None:
        return _fail("bad_basic_info", field="basic_info")

    # 3) 文字字段
    display_name = str(form.get("display_name") or "").strip()
    if not display_name:
        return _fail("empty_display_name", field="display_name")
    if len(display_name) > DISPLAY_NAME_MAX:
        return _fail("too_long_display_name", field="display_name")
    region = str(form.get("region") or "").strip()
    if not region:
        return _fail("empty_region", field="region")

    # 4) 价格派生（与 FSM step_price_detail 一致）
    price_detail = str(form.get("price_detail") or "").strip()
    price = _extract_largest_price(price_detail)
    if not price:
        return _fail("no_price", field="price_detail")
    description = _compute_description_from_price(price)
    taboos = DEFAULT_TABOOS

    # 5) 跳转链接
    button_url = normalize_url(str(form.get("button_url") or ""))
    if not button_url:
        return _fail("bad_url", field="button_url")

    # 6) 标签 + 注入价位 tag
    tags = _norm_tags(form.get("tags"))
    if not tags:
        return _fail("empty_tags", field="tags")
    tags = _inject_price_tag_into_tags(tags, price)

    # 7) 相册（已是 file_id 数组）
    photos = [str(p) for p in (form.get("photos") or []) if p]
    if not photos:
        return _fail("no_photos", field="photos")
    if len(photos) > ALBUM_MAX:
        return _fail("too_many_photos", field="photos")

    # 8) 查重（先查给明确错误码；add_teacher 的 INSERT OR IGNORE 再兜底竞态）
    if await get_teacher(uid):
        return _fail("duplicate", field="user_id")

    # 9) 落库三步（照搬 cb_profile_save）
    auto_button_text = f"{region} {display_name}".strip() or display_name
    ok = await add_teacher({
        "user_id": uid,
        "username": username,
        "display_name": display_name,
        "region": region,
        "price": price,
        "tags": json.dumps(tags, ensure_ascii=False),
        "photo_file_id": photos[0],
        "button_url": button_url,
        "button_text": auto_button_text,
    })
    if not ok:  # 并发竞态：查重后被插入
        return _fail("duplicate", field="user_id")

    service_content = str(form.get("service_content") or "").strip() or None
    for field, value in (
        ("age", basic["age"]),
        ("height_cm", basic["height_cm"]),
        ("weight_kg", basic["weight_kg"]),
        ("bra_size", basic["bra_size"]),
        ("description", description),
        ("service_content", service_content),
        ("price_detail", price_detail),
        ("taboos", taboos),
        ("contact_telegram", contact),
    ):
        if value is None:
            continue
        await update_teacher_profile_field(uid, field, value)

    await set_teacher_photos(uid, photos)

    return {
        "ok": True, "user_id": uid, "error": None, "field": None,
        "message": f"老师「{display_name}」已创建（{len(photos)} 张照片）",
    }

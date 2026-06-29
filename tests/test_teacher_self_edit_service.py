"""老师自助改资料共享 service 单元测试（§16.3）。

覆盖：
    - validate_field：空 / 过长 / 标签去重去空 / 图片 file_id / 未知字段
    - parse_tags：分隔符 / 去重保序
    - submit_field_edit：文字立即生效（update + edit_request + notify）/
      图片延后（仅 edit_request + notify，不动 teachers）/ old==new 拒 /
      not_teacher / 各类校验失败码

叶子函数（get_teacher / update_teacher / create_edit_request / get_all_admins）
monkeypatch（service 把它们 import 进自身命名空间）。
"""
from __future__ import annotations

import asyncio
import json

import bot.services.teacher_self_edit as tse


def _run(coro):
    return asyncio.run(coro)


class _FakeBot:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        # 真实 bot.send_message 接受 reply_markup 等；测试只记录 chat_id/text。
        self.sent.append({"chat_id": chat_id, "text": text})

    async def get_me(self):
        class _Me:
            username = "fakebot"
        return _Me()


# ============ validate_field ============

def test_validate_unknown_field():
    ok, _, err = tse.validate_field("button_url", "x")
    assert ok is False and err == "unknown_field"


def test_validate_empty_text():
    ok, _, err = tse.validate_field("region", "   ")
    assert ok is False and err == "empty"


def test_validate_display_name_too_long():
    ok, _, err = tse.validate_field("display_name", "名" * 41)
    assert ok is False and err == "too_long"


def test_validate_display_name_ok_at_limit():
    ok, val, err = tse.validate_field("display_name", "名" * 40)
    assert ok is True and err is None and val == "名" * 40


def test_validate_tags_dedup_to_json():
    ok, val, err = tse.validate_field("tags", "御姐, 御姐  颜值、服务")
    assert ok is True and err is None
    assert json.loads(val) == ["御姐", "颜值", "服务"]


def test_validate_tags_all_empty_rejected():
    ok, _, err = tse.validate_field("tags", "  ,，、 ")
    assert ok is False and err == "empty_tags"


def test_validate_photo_file_id_nonempty():
    ok, val, err = tse.validate_field("photo_file_id", "AgACfileid123")
    assert ok is True and err is None and val == "AgACfileid123"


def test_validate_photo_file_id_empty():
    ok, _, err = tse.validate_field("photo_file_id", "")
    assert ok is False and err == "empty"


# ============ parse_tags ============

def test_parse_tags_mixed_separators_preserve_order():
    assert json.loads(tse.parse_tags("a b,c，d、e")) == ["a", "b", "c", "d", "e"]


def test_parse_tags_case_insensitive_dedup():
    # 大小写视为重复，保留首次出现
    assert json.loads(tse.parse_tags("Abc abc ABC x")) == ["Abc", "x"]


# ============ submit_field_edit：文字字段立即生效 ============

def _patch_text_path(monkeypatch, *, old_value="旧", update_ok=True, request_id=99):
    calls = {"update": None, "edit_request": None}

    async def fake_get_teacher(uid):
        return {"user_id": uid, "display_name": "老师A", "region": old_value}

    async def fake_update(uid, field, value):
        calls["update"] = (uid, field, value)
        return update_ok

    async def fake_create_req(teacher_id, field_name, old_value, new_value):
        calls["edit_request"] = {
            "teacher_id": teacher_id, "field_name": field_name,
            "old_value": old_value, "new_value": new_value,
        }
        return request_id

    async def fake_get_admins():
        return [{"user_id": 1001}]

    monkeypatch.setattr(tse, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(tse, "update_teacher", fake_update)
    monkeypatch.setattr(tse, "create_edit_request", fake_create_req)
    monkeypatch.setattr(tse, "get_all_admins", fake_get_admins)
    return calls


def test_submit_text_applies_immediately(monkeypatch):
    calls = _patch_text_path(monkeypatch, old_value="旧地区")
    bot = _FakeBot()

    res = _run(tse.submit_field_edit(bot, 555, "region", "新地区"))

    assert res["ok"] is True and res["applied"] is True
    assert res["request_id"] == 99
    # 立即生效：UPDATE teachers 被调用
    assert calls["update"] == (555, "region", "新地区")
    # 建了审核单（old/new 正确）
    assert calls["edit_request"]["field_name"] == "region"
    assert calls["edit_request"]["new_value"] == "新地区"
    # 通知了管理员（含超管去重）
    assert any(m["chat_id"] == 1001 for m in bot.sent)


def test_submit_text_same_value_rejected(monkeypatch):
    _patch_text_path(monkeypatch, old_value="同值")
    bot = _FakeBot()
    res = _run(tse.submit_field_edit(bot, 555, "region", "同值"))
    assert res["ok"] is False and res["error"] == "same"
    assert bot.sent == []  # 同值不通知


def test_submit_text_update_failed(monkeypatch):
    _patch_text_path(monkeypatch, old_value="旧", update_ok=False)
    bot = _FakeBot()
    res = _run(tse.submit_field_edit(bot, 555, "region", "新"))
    assert res["ok"] is False and res["error"] == "update_failed"


def test_submit_not_teacher(monkeypatch):
    async def fake_get_teacher(uid):
        return None

    monkeypatch.setattr(tse, "get_teacher", fake_get_teacher)
    bot = _FakeBot()
    res = _run(tse.submit_field_edit(bot, 555, "region", "新"))
    assert res["ok"] is False and res["error"] == "not_teacher"


def test_submit_validation_error_short_circuits(monkeypatch):
    # 校验失败时不应触碰 DB（get_teacher 不被调用）
    async def boom(*a, **k):
        raise AssertionError("校验失败不应查 DB")

    monkeypatch.setattr(tse, "get_teacher", boom)
    bot = _FakeBot()
    res = _run(tse.submit_field_edit(bot, 555, "display_name", "x" * 41))
    assert res["ok"] is False and res["error"] == "too_long"


# ============ submit_field_edit：图片字段延后生效 ============

def test_submit_photo_deferred(monkeypatch):
    calls = {"update": False, "edit_request": None}

    async def fake_get_teacher(uid):
        return {"user_id": uid, "display_name": "老师A", "photo_file_id": "old_fid"}

    async def fake_update(uid, field, value):
        calls["update"] = True
        return True

    async def fake_create_req(teacher_id, field_name, old_value, new_value):
        calls["edit_request"] = {"field_name": field_name, "new_value": new_value}
        return 77

    async def fake_get_admins():
        return []

    monkeypatch.setattr(tse, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(tse, "update_teacher", fake_update)
    monkeypatch.setattr(tse, "create_edit_request", fake_create_req)
    monkeypatch.setattr(tse, "get_all_admins", fake_get_admins)

    bot = _FakeBot()
    res = _run(tse.submit_field_edit(bot, 555, "photo_file_id", "new_fid"))

    assert res["ok"] is True and res["applied"] is False  # 延后
    assert res["request_id"] == 77
    assert calls["update"] is False  # 图片不动 teachers
    assert calls["edit_request"]["new_value"] == "new_fid"
    # 超管被通知（get_all_admins 返回空，但 super_admin_id 仍在目标集）
    assert len(bot.sent) >= 1


def test_editable_fields_matches_db_whitelist():
    from bot.database import TEACHER_EDITABLE_FIELDS
    assert tse.EDITABLE_FIELDS == TEACHER_EDITABLE_FIELDS


# ============ admin_set_field（阶段2：管理员直改，即时生效、无审核/无通知）============

def _patch_admin(monkeypatch, *, current=None, update_ok=True):
    """patch get_teacher / update_teacher；current=老师当前字段值（用于幂等判定）。"""
    calls = {"update": None, "get": 0}

    async def fake_get_teacher(uid):
        calls["get"] += 1
        return {"user_id": uid, "display_name": "老师A", **(current or {})}

    async def fake_update(uid, field, value):
        calls["update"] = (uid, field, value)
        return update_ok

    monkeypatch.setattr(tse, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(tse, "update_teacher", fake_update)
    return calls


def test_admin_set_unknown_field_no_db(monkeypatch):
    # 图片不在 ADMIN_EDITABLE_FIELDS（相册另走）→ 直接拒，不查 DB
    async def boom(*a, **k):
        raise AssertionError("未知字段不应查 DB")

    monkeypatch.setattr(tse, "get_teacher", boom)
    res = _run(tse.admin_set_field(555, "photo_file_id", "fid"))
    assert res["ok"] is False and res["error"] == "unknown_field"


def test_admin_set_text_applies_immediately(monkeypatch):
    calls = _patch_admin(monkeypatch, current={"region": "旧"})
    res = _run(tse.admin_set_field(555, "region", "心岛"))
    assert res["ok"] is True and res["field"] == "region"
    assert res["message"] == "✅ 地区已更新"
    assert calls["update"] == (555, "region", "心岛")


def test_admin_set_not_teacher(monkeypatch):
    async def fake_get_teacher(uid):
        return None

    monkeypatch.setattr(tse, "get_teacher", fake_get_teacher)
    res = _run(tse.admin_set_field(555, "region", "心岛"))
    assert res["ok"] is False and res["error"] == "not_teacher"


def test_admin_set_validation_error_short_circuits(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("校验失败不应查 DB")

    monkeypatch.setattr(tse, "get_teacher", boom)
    res = _run(tse.admin_set_field(555, "display_name", "名" * 41))
    assert res["ok"] is False and res["error"] == "too_long"


def test_admin_set_button_url_valid(monkeypatch):
    # button_url 是老师改不了、仅管理员可改的字段；走真实 normalize_url
    calls = _patch_admin(monkeypatch, current={"button_url": ""})
    res = _run(tse.admin_set_field(555, "button_url", "https://t.me/abc"))
    assert res["ok"] is True
    assert calls["update"] == (555, "button_url", "https://t.me/abc")


def test_admin_set_button_url_invalid_no_db(monkeypatch):
    # 缺 scheme → normalize_url 判非法；不查 DB
    async def boom(*a, **k):
        raise AssertionError("非法链接不应查 DB")

    monkeypatch.setattr(tse, "get_teacher", boom)
    res = _run(tse.admin_set_field(555, "button_url", "t.me/abc"))
    assert res["ok"] is False and res["error"] == "bad_url"


def test_admin_set_button_url_empty_clears(monkeypatch):
    # 允许空串=清空链接
    calls = _patch_admin(monkeypatch, current={"button_url": "https://t.me/old"})
    res = _run(tse.admin_set_field(555, "button_url", ""))
    assert res["ok"] is True
    assert calls["update"] == (555, "button_url", "")


def test_admin_set_idempotent_same_value_ok(monkeypatch):
    # update 返回 False（无行改动）但现值==新值 → 仍视为成功
    _patch_admin(monkeypatch, current={"price": "1000P"}, update_ok=False)
    res = _run(tse.admin_set_field(555, "price", "1000P"))
    assert res["ok"] is True


def test_admin_set_update_failed(monkeypatch):
    # update 返回 False 且现值≠新值 → update_failed
    _patch_admin(monkeypatch, current={"price": "1000P"}, update_ok=False)
    res = _run(tse.admin_set_field(555, "price", "2000P"))
    assert res["ok"] is False and res["error"] == "update_failed"

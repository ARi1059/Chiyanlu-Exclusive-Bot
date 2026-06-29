"""新增老师录入 service 单元测试（bot/web 同源）。

覆盖 create_teacher_from_form：
    - 各校验分支错误码 + field
    - basic_info 整串 / 拆字段两路径
    - 价格派生正确性（price / 价位 tag / description / taboos）
    - 落库三步调用（add_teacher×1 / update_teacher_profile_field×N / set_teacher_photos）
    - 查重（get_teacher 命中 / add_teacher 返 False 竞态）

DB 叶子函数（add_teacher / update_teacher_profile_field / set_teacher_photos / get_teacher）
在 service 模块命名空间，monkeypatch。parse_basic_info / normalize_url / 派生函数是纯函数不 patch。
"""
from __future__ import annotations

import asyncio
import json

import bot.services.teacher_onboarding as to


def _run(coro):
    return asyncio.run(coro)


def _valid_form(**over) -> dict:
    f = {
        "user_id": "12345",
        "username": "chixiaoxia",
        "contact_telegram": "@chixiaoxia",
        "display_name": "苏乔晚",
        "basic_info": "25 172 90 B",
        "region": "心岛",
        "price_detail": "包夜 800P 半天 500P",
        "service_content": "包夜含 X 项",
        "tags": "御姐 高颜值",
        "button_url": "https://t.me/chixiaoxia",
        "photos": ["fid_a", "fid_b"],
    }
    f.update(over)
    return f


def _patch_db(monkeypatch, *, existing=None, add_ok=True):
    """patch 落库四函数；记录调用。existing=get_teacher 返回值（查重）。"""
    calls = {"add": None, "fields": [], "photos": None}

    async def fake_get_teacher(uid):
        return existing

    async def fake_add(data):
        calls["add"] = data
        return add_ok

    async def fake_update_field(uid, field, value):
        calls["fields"].append((field, value))
        return True

    async def fake_set_photos(uid, file_ids):
        calls["photos"] = (uid, list(file_ids))
        return True

    monkeypatch.setattr(to, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(to, "add_teacher", fake_add)
    monkeypatch.setattr(to, "update_teacher_profile_field", fake_update_field)
    monkeypatch.setattr(to, "set_teacher_photos", fake_set_photos)
    return calls


# ============ 成功路径 + 派生 + 落库三步 ============

def test_create_success_full(monkeypatch):
    calls = _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form()))
    assert res["ok"] is True and res["user_id"] == 12345

    # add_teacher：user_id/username/display_name/region + 派生 price + button_text="地区 艺名"
    add = calls["add"]
    assert add["user_id"] == 12345 and add["username"] == "chixiaoxia"
    assert add["display_name"] == "苏乔晚" and add["region"] == "心岛"
    assert add["price"] == "800P"  # _extract_largest_price 取最大
    assert add["button_text"] == "心岛 苏乔晚"
    assert add["photo_file_id"] == "fid_a"  # 第一张
    # tags 是 JSON 串，含原标签 + 注入价位 tag 8P（800//100）
    tags = json.loads(add["tags"])
    assert "御姐" in tags and "高颜值" in tags and "8P" in tags

    # update_teacher_profile_field：9 项（含 service_content）
    fields = dict(calls["fields"])
    assert fields["age"] == 25 and fields["height_cm"] == 172
    assert fields["weight_kg"] == 90 and fields["bra_size"] == "B"
    assert fields["description"] == "出击加分 1分 报销金额 100元"  # 8档→100
    assert fields["taboos"] == to.DEFAULT_TABOOS
    assert fields["price_detail"] == "包夜 800P 半天 500P"
    assert fields["contact_telegram"] == "@chixiaoxia"
    assert fields["service_content"] == "包夜含 X 项"
    assert len(calls["fields"]) == 9

    # set_teacher_photos：完整数组
    assert calls["photos"] == (12345, ["fid_a", "fid_b"])


def test_create_basic_info_split_fields(monkeypatch):
    # basic_info 缺省 → 用拆开的 age/height_cm/weight_kg/bra_size
    calls = _patch_db(monkeypatch)
    form = _valid_form()
    del form["basic_info"]
    form.update(age="30", height_cm="165", weight_kg="50", bra_size="C")
    res = _run(to.create_teacher_from_form(form))
    assert res["ok"] is True
    fields = dict(calls["fields"])
    assert fields["age"] == 30 and fields["bra_size"] == "C"


def test_create_service_content_skipped_when_blank(monkeypatch):
    calls = _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(service_content="")))
    assert res["ok"] is True
    # service_content 空 → 跳过，只 8 项
    assert "service_content" not in dict(calls["fields"])
    assert len(calls["fields"]) == 8


def test_create_price_derivation_900_tier(monkeypatch):
    calls = _patch_db(monkeypatch)
    _run(to.create_teacher_from_form(_valid_form(price_detail="全套 900P")))
    add = calls["add"]
    assert add["price"] == "900P"
    assert "9P" in json.loads(add["tags"])
    assert dict(calls["fields"])["description"] == "出击加分 1分 报销金额 150元"  # 9档→150


# ============ 校验分支 ============

def test_invalid_user_id(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(user_id="abc")))
    assert res["ok"] is False and res["error"] == "invalid_user_id" and res["field"] == "user_id"


def test_duplicate_via_get_teacher(monkeypatch):
    _patch_db(monkeypatch, existing={"user_id": 12345, "display_name": "已存在"})
    res = _run(to.create_teacher_from_form(_valid_form()))
    assert res["ok"] is False and res["error"] == "duplicate"


def test_duplicate_via_add_race(monkeypatch):
    # get_teacher 查重通过，但 add_teacher 返 False（并发竞态）
    _patch_db(monkeypatch, add_ok=False)
    res = _run(to.create_teacher_from_form(_valid_form()))
    assert res["ok"] is False and res["error"] == "duplicate"


def test_bad_username(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(username="ab")))  # <4
    assert res["error"] == "bad_username" and res["field"] == "username"


def test_bad_contact(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(contact_telegram="chixiaoxia")))  # 缺 @
    assert res["error"] == "bad_contact"


def test_empty_display_name(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(display_name="  ")))
    assert res["error"] == "empty_display_name"


def test_too_long_display_name(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(display_name="名" * 41)))
    assert res["error"] == "too_long_display_name"


def test_bad_basic_info_out_of_range(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(basic_info="99 172 90 B")))  # age>60
    assert res["error"] == "bad_basic_info" and res["field"] == "basic_info"


def test_bad_basic_info_wrong_arity(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(basic_info="25 172 90")))  # 3 段
    assert res["error"] == "bad_basic_info"


def test_empty_region(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(region="")))
    assert res["error"] == "empty_region"


def test_no_price(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(price_detail="面议")))  # 无数字+P
    assert res["error"] == "no_price" and res["field"] == "price_detail"


def test_bad_url(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(button_url="t.me/x")))  # 缺 scheme
    assert res["error"] == "bad_url"


def test_empty_tags(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(tags="  ")))
    assert res["error"] == "empty_tags"


def test_no_photos(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(photos=[])))
    assert res["error"] == "no_photos" and res["field"] == "photos"


def test_too_many_photos(monkeypatch):
    _patch_db(monkeypatch)
    res = _run(to.create_teacher_from_form(_valid_form(photos=[f"f{i}" for i in range(11)])))
    assert res["error"] == "too_many_photos"


def test_validation_short_circuits_before_db(monkeypatch):
    # 校验失败时不应触碰落库（add_teacher 不被调）
    calls = _patch_db(monkeypatch)
    _run(to.create_teacher_from_form(_valid_form(user_id="x")))
    assert calls["add"] is None

"""管理员侧 gesture_photo_file_id=None 的安全审核契约（2026-05-21）。

覆盖：
    - rreview_action_kb(has_gesture=False) 隐藏「✋ 重看手势照片」按钮
    - rreview_action_kb 默认 has_gesture=True 兼容旧调用
    - rreview_admin.py 媒体组构造按 gesture 可用性过滤
    - rreview_admin.py 「rreview:photo:gesture:*」callback 对 None 给友好 alert
    - rreview_notify.py 媒体组同样过滤 None
    - rreview_admin 发送审核详情时把 has_gesture 传给 keyboard
"""
from __future__ import annotations

import inspect


def _src(module) -> str:
    return inspect.getsource(module)


def _flat_cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


# ============================================================
# 1. rreview_action_kb
# ============================================================


def test_rreview_action_kb_default_has_gesture_button():
    """has_gesture 默认 True（兼容历史 caller）。"""
    from bot.keyboards.admin_kb import rreview_action_kb
    kb = rreview_action_kb(review_id=1, has_prev=False, has_next=False)
    cbs = _flat_cbs(kb)
    assert "rreview:photo:gesture:1" in cbs


def test_rreview_action_kb_no_gesture_hides_button():
    """has_gesture=False → 不渲染「✋ 重看手势照片」按钮。"""
    from bot.keyboards.admin_kb import rreview_action_kb
    kb = rreview_action_kb(
        review_id=1, has_prev=False, has_next=False, has_gesture=False,
    )
    cbs = _flat_cbs(kb)
    assert "rreview:photo:gesture:1" not in cbs
    # booking 按钮仍在
    assert "rreview:photo:booking:1" in cbs


def test_rreview_action_kb_no_gesture_still_has_other_buttons():
    """除手势按钮外其它按钮（通过 / 驳回 / nav / 返回）全部保留。"""
    from bot.keyboards.admin_kb import rreview_action_kb
    kb = rreview_action_kb(
        review_id=42, has_prev=True, has_next=True, has_gesture=False,
    )
    cbs = _flat_cbs(kb)
    assert "rreview:approve:42" in cbs
    assert "rreview:reject:42" in cbs
    assert "rreview:nav:prev:42" in cbs
    assert "rreview:nav:next:42" in cbs


# ============================================================
# 2. rreview_admin.py 媒体组按 gesture 过滤
# ============================================================


def test_rreview_admin_media_group_filters_none_gesture():
    """rreview_admin 在构造媒体组时若 gesture 为 None 应过滤；源码静态契约：
    InputMediaPhoto(gesture) 必须在 `if review.get("gesture_photo_file_id"):`
    分支内。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    # 找到媒体组构造区域
    media_idx = src.find('caption="📸 约课记录"')
    assert media_idx > 0
    window = src[media_idx:media_idx + 800]
    # 手势照应只在 if gesture 分支内出现
    assert 'caption="✋ 现场手势"' in window
    if_pos = window.find('if review.get("gesture_photo_file_id")')
    gesture_pos = window.find('caption="✋ 现场手势"')
    assert 0 < if_pos < gesture_pos


def test_rreview_admin_passes_has_gesture_to_kb():
    """发送审核详情时调用 rreview_action_kb 必须传 has_gesture。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    idx = src.find("rreview_action_kb(")
    assert idx > 0
    window = src[idx:idx + 500]
    assert "has_gesture=" in window


# ============================================================
# 3. rreview_admin.py：重看手势照片 callback 安全处理 None
# ============================================================


def test_rreview_photo_gesture_callback_guards_none():
    """rreview:photo:gesture:* callback 在 fid 为 None 时应回 alert，不调 send_photo。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    # 找 kind == "gesture" 分支
    idx = src.find('kind == "gesture"')
    assert idx > 0
    window = src[idx:idx + 800]
    # 必须 use `.get(...)` 而非 `["gesture_photo_file_id"]` 下标
    assert 'review.get("gesture_photo_file_id")' in window or "review.get('gesture_photo_file_id')" in window
    # None 时 alert
    assert "show_alert=True" in window


# ============================================================
# 4. rreview_notify.py 媒体组按 gesture 过滤
# ============================================================


def test_rreview_notify_media_group_filters_none_gesture():
    """notify_super_admins_new_review 媒体组同样过滤 None。"""
    import bot.utils.rreview_notify as mod
    src = _src(mod)
    media_idx = src.find('caption="📸 约课记录"')
    assert media_idx > 0
    window = src[media_idx:media_idx + 600]
    if_pos = window.find('if review.get("gesture_photo_file_id")')
    gesture_pos = window.find('caption="✋ 现场手势"')
    assert 0 < if_pos < gesture_pos

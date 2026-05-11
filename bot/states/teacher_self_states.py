"""老师自助管理 FSM 状态（v2 §2.3 F3）

TeacherEditStates.waiting_new_value:
    老师点击"修改 [字段]"后，等待输入新值。
    state.data 保存:
        - field_name: 当前在改的字段
        - is_photo: 是否是图片字段（影响是否接收 message.photo 还是 message.text）

ReviewStates.waiting_reject_reason:
    管理员点击"填写驳回原因"后，等待输入文字。
    state.data 保存:
        - request_id: 当前在审核的请求 id
"""

from aiogram.fsm.state import State, StatesGroup


class TeacherEditStates(StatesGroup):
    """老师自助修改某字段的状态"""
    waiting_new_value = State()


class ReviewStates(StatesGroup):
    """管理员驳回时填写原因的状态"""
    waiting_reject_reason = State()

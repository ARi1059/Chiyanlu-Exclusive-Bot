from aiogram.fsm.state import State, StatesGroup


class AddTeacherStates(StatesGroup):
    """添加老师引导流程状态"""
    waiting_user_id = State()
    waiting_username = State()
    waiting_display_name = State()
    waiting_region = State()
    waiting_price = State()
    waiting_tags = State()
    waiting_photo = State()
    waiting_button_url = State()
    confirm = State()


class EditTeacherStates(StatesGroup):
    """编辑老师状态"""
    select_teacher = State()
    select_field = State()
    waiting_new_value = State()


class AddAdminStates(StatesGroup):
    """添加管理员状态"""
    waiting_user_id = State()


class SetChannelStates(StatesGroup):
    """设置频道/群组状态"""
    waiting_channel_id = State()


class SetGroupStates(StatesGroup):
    """设置响应群组状态"""
    waiting_group_id = State()


class SystemSettingStates(StatesGroup):
    """系统设置状态"""
    waiting_value = State()

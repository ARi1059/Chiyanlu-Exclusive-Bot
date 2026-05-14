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


class HotManageStates(StatesGroup):
    """热门推荐管理状态（Phase 3）"""
    waiting_feature_id = State()    # 添加推荐：等待老师 ID
    waiting_weight_id = State()      # 修改权重：等待老师 ID
    waiting_weight_value = State()   # 修改权重：等待权重值（state.data 含 teacher_id）
    waiting_remove_id = State()      # 取消推荐：等待老师 ID


class PromoLinkStates(StatesGroup):
    """推广链接生成器状态（Phase 4）

    state.data: {"link_type": "channel"|"group"|"teacher"|"campaign"|"invite"}
    """
    waiting_input = State()


class UserSourceLookupStates(StatesGroup):
    """管理员查用户来源状态（Phase 4）"""
    waiting_user_id = State()


class TeacherDailyStatusStates(StatesGroup):
    """老师每日状态：自定义时间 / 取消原因 输入（Phase 5）"""
    waiting_custom_time = State()       # 自定义时间段文字
    waiting_cancel_reason = State()     # 取消原因（可选）

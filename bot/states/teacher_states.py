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


class SetArchiveChannelStates(StatesGroup):
    """Phase 9.2：设置档案帖目标频道（archive_channel_id 单 chat_id）"""
    waiting_chat_id = State()


class SubReqAddStates(StatesGroup):
    """Phase 9.3：添加必关频道/群组 3 步 FSM

    state.data 累加：
        waiting_chat_id    → chat_id (int) + precheck 结果（chat_type/title）
        waiting_display_name → display_name (str)
        waiting_invite_link  → invite_link (str)
    """
    waiting_chat_id     = State()
    waiting_display_name = State()
    waiting_invite_link  = State()


class RReviewRejectStates(StatesGroup):
    """Phase 9.4：超管驳回报告时填写自定义原因 FSM

    state.data：{"review_id": int}
    """
    waiting_custom_reason = State()


class RReviewApprovePointsStates(StatesGroup):
    """Phase P.1：审核通过时填写自定义积分 FSM

    state.data：{"review_id": int}
    """
    waiting_custom_delta = State()


class AdminPointsQueryStates(StatesGroup):
    """Phase P.3：超管查询用户积分 FSM"""
    waiting_input = State()


class AdminPointsGrantStates(StatesGroup):
    """Phase P.3：超管手动加扣分 4 步 FSM

    state.data：
        target_user_id / target_username / target_first_name / current_total
        delta / package_label
        reason / reason_note
    """
    waiting_target        = State()
    waiting_delta         = State()
    waiting_custom_delta  = State()
    waiting_reason        = State()
    waiting_custom_reason = State()
    waiting_confirm       = State()


class ReviewSubmitStates(StatesGroup):
    """Phase 9.3：用户提交评价 12 步 FSM（前置 3 步证据 + 9 步评分）

    本 phase 仅从 teacher_detail [📝 写评价] 入口（teacher_id 已知），
    Step A 选老师留给 9.5。state.data 累加：
        teacher_id / booking_screenshot_file_id / gesture_photo_file_id /
        rating / score_humanphoto / score_appearance / score_body /
        score_service / score_attitude / score_environment / overall_score /
        summary（可空）/ jump_back（确认页跳回时为 True）
    """
    waiting_booking_screenshot = State()  # Step B
    waiting_gesture_photo      = State()  # Step C
    waiting_rating             = State()  # Step 1
    waiting_score_humanphoto   = State()  # Step 2
    waiting_score_appearance   = State()  # Step 3
    waiting_score_body         = State()  # Step 4
    waiting_score_service      = State()  # Step 5
    waiting_score_attitude     = State()  # Step 6
    waiting_score_environment  = State()  # Step 7
    waiting_overall_score      = State()  # Step 8
    waiting_summary            = State()  # Step 9
    waiting_confirm            = State()


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


class UserTagsQueryStates(StatesGroup):
    """管理员查标签用户 FSM（Phase 6.1）"""
    waiting_tag = State()


class PublishTemplateStates(StatesGroup):
    """发布模板管理 FSM（Phase 6.2）

    state.data:
        waiting_create_text: {"name": str}
        waiting_edit_text:   {"template_id": int}
    """
    waiting_create_name = State()
    waiting_create_text = State()
    waiting_edit_text = State()
    waiting_set_default_id = State()


class ReportSettingsStates(StatesGroup):
    """报表设置 FSM（Phase 6.3）

    分 4 类输入：日报时间 / 周报时间 / 周报星期(1-7) / 接收 chat_id
    """
    waiting_daily_time = State()
    waiting_weekly_time = State()
    waiting_weekly_day = State()
    waiting_chat_id = State()


class TeacherProfileAddStates(StatesGroup):
    """Phase 9.1：完整老师档案录入 FSM（13 步）

    state.data 会累加：display_name/age/height_cm/weight_kg/bra_size/description/
    service_content/price_detail/taboos/contact_telegram/region/price/tags/
    button_url/button_text/photos(list[str])。
    """
    waiting_user_id          = State()  # 复用 Telegram user_id（新建必须）
    waiting_username         = State()  # @ username
    waiting_display_name     = State()
    waiting_basic_info       = State()  # 一行 "年龄 身高 体重 罩杯"
    waiting_description      = State()  # 可跳过
    waiting_service_content  = State()  # 可跳过
    waiting_price_detail     = State()  # 必填
    waiting_taboos           = State()  # 可跳过
    waiting_contact_telegram = State()  # 必须含 @
    waiting_region           = State()
    waiting_price            = State()
    waiting_tags             = State()
    waiting_button_url       = State()
    waiting_button_text      = State()  # 可跳过
    waiting_photos           = State()  # 多图 + 回复 "完成"
    waiting_confirm          = State()


class TeacherProfileEditStates(StatesGroup):
    """Phase 9.1：单字段编辑 FSM

    state.data：{"target_user_id": int, "field_key": str}
    waiting_field_value 通用接收新值；photo_album / tags 走对应解析分支。
    """
    waiting_target_teacher = State()
    waiting_field_choice   = State()
    waiting_field_value    = State()


class TeacherProfileAlbumStates(StatesGroup):
    """Phase 9.1：相册管理 FSM

    state.data：{"target_user_id": int, "mode": "add"|"replace", "buffer": list[str]}
    """
    waiting_target_teacher = State()
    waiting_album_action   = State()  # 选 add/remove/replace
    waiting_add_photos     = State()  # 收图
    waiting_remove_index   = State()  # 选 index 删除
    waiting_replace_photos = State()  # 收图（整体替换）

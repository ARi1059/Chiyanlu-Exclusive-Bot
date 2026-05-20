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


class ReimburseSubReqAddStates(StatesGroup):
    """报销专用必关频道 / 群组添加 FSM（与全局 SubReqAddStates 隔离）。

    state.data 累加：
        waiting_chat_id      → chat_id (int) + chat_type / display_name 来自 precheck
        waiting_display_name → display_name (str)，允许覆盖 precheck 默认值
        waiting_invite_link  → invite_link (str)，需以 http(s)://t.me/ 开头
    最终通过 system:reimburse_subreq:add_confirm 二次确认后写入 config。
    """
    waiting_chat_id      = State()
    waiting_display_name = State()
    waiting_invite_link  = State()


class ReimbursePayoutStates(StatesGroup):
    """报销支付宝口令红包发放 FSM（2026-05 新增）。

    流程：
        超管点击「✅ 同意报销」(reimburse:approve:<id>) → 进入 waiting_token
        超管输入口令 → 进入 confirming
        超管点确认（reimburse:payout:confirm:<id>） →
            尝试给用户发送口令；成功才调 approve_reimbursement → status: approved
            失败保留 pending；超管可重试或取消

    state.data 累加：
        reimbursement_id (int)
        user_id (int)
        amount (int)
        token (str)  —— 仅 FSM 临时持有；确认发送后由 state.clear() 清理
    """
    waiting_token = State()
    confirming    = State()


class ReimburseMinPointsStates(StatesGroup):
    """报销最低积分门槛配置 FSM（2026-05 新增）。

    state.data：
        old_value (int) —— 修改前的门槛值
        new_value (int) —— 待确认的新门槛值（0 ≤ v ≤ REIMBURSE_MIN_POINTS_MAX）
    """
    waiting_value = State()
    confirming    = State()


class ReimbursePoolResetStates(StatesGroup):
    """本月报销池重置基线 FSM（2026-05 新增）。

    设计：通过 config baseline 间接重置，不动 reimbursements 表。

    state.data：
        month_key (str)            —— 重置的月份
        baseline_amount (int)      —— 当前 raw_used，重置后将作为 baseline
        monthly_pool (int)         —— 月度池上限（用于展示）
        prev_effective_used (int)  —— 重置前 effective_used（用于展示）
        reason (str)               —— 重置原因，必填
    """
    waiting_reason = State()
    confirming     = State()


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


class LotteryContactUrlStates(StatesGroup):
    """Phase L.4.1：客服链接配置 FSM"""
    waiting_url = State()


class ReimburseRejectStates(StatesGroup):
    """报销驳回原因输入"""
    waiting_reason = State()


class LotteryEditStates(StatesGroup):
    """Phase L.4.2：active 抽奖编辑 FSM

    state.data: {"lottery_id": int, "field_key": str}
    """
    waiting_field_choice = State()
    waiting_new_value    = State()


class LotteryCreateStates(StatesGroup):
    """Phase L.1 + UX-9.5：超管创建抽奖 11 步 FSM（原 10 步，UX-9.5 把
    entry_cost_points 升为主线 Step 8）。

    state.data 累加：
        name / description / cover_file_id /
        entry_method ('button'|'code') / entry_code (仅 code) /
        prize_count / prize_description /
        required_chat_ids (list[int]) /
        entry_cost_points (int, UX-9.5 主线必填) /
        publish_mode ('immediate'|'scheduled') / publish_at / draw_at

    步骤序号（spec §3.3 + UX-9.5 修订）：
        Step 1 name → Step 2 description → Step 3 cover →
        Step 4 entry_method → (Step 4.5 entry_code, code 模式) →
        Step 5 prize_count → Step 6 prize_description →
        Step 7 required_chats → **Step 8 entry_cost（UX-9.5 新增）** →
        Step 9 publish_mode → (Step 9b publish_at, scheduled 模式) →
        Step 10 draw_at → Step 11 confirm
    """
    waiting_name              = State()
    waiting_description       = State()
    waiting_cover             = State()
    waiting_entry_method      = State()
    waiting_entry_code        = State()
    waiting_prize_count       = State()
    waiting_prize_count_input = State()
    waiting_prize_description = State()
    waiting_required_chats    = State()
    waiting_required_chat_id  = State()
    waiting_entry_cost        = State()  # UX-9.5：主线 Step 8 入口
    waiting_publish_mode      = State()
    waiting_publish_at        = State()
    waiting_draw_at           = State()
    waiting_confirm           = State()
    waiting_entry_cost_input  = State()  # 确认页 [💰 设置参与所需积分] 返修入口
                                         # （UX-9.5：保留旧 callback 兼容；与 waiting_entry_cost 区分）


class UserReviewsHomeStates(StatesGroup):
    """主菜单 [📝 写评价] → 个人评价主页 浏览/筛选 状态（2026-05-18）

    state.data 累加：
        status_filter: "pending"|"approved"|"rejected"|None
        rating_filter: "positive"|"neutral"|"negative"|None
        page: int (0-based)
        pre_rating: str|None  ← 用户在主页选中的评级（兼作写车评的预选评级）
    """
    viewing = State()


class WriteReviewLookupStates(StatesGroup):
    """主菜单 [📝 写评价] → 等待用户输入艺名 → 查到老师后转 CardReviewStates"""
    waiting_teacher_name = State()


class CardReviewStates(StatesGroup):
    """卡片驱动评价 FSM（2026-05-18 Phase 2）

    用户在「评价卡片」状态下可任意点击 8 个字段按钮进入对应 editing_X
    状态填写，填完返回卡片视图。无强制顺序。

    旧线性 ReviewSubmitStates FSM 已于 2026-05-20 Sprint 7 §9.1 第 3 批
    dead code 删除中清理。

    state.data 累加：
        teacher_id /
        booking_screenshot_file_id / gesture_photo_file_id /
        rating /
        score_humanphoto / score_appearance / score_body /
        score_service / score_attitude / score_environment /
        summary /
        anonymous (0/1) /
        request_reimbursement (0/1/2) — 提交时通过 reimbursement step 设置
        _card_msg_id — 卡片消息 id，用于编辑刷新
        _evidence_files — 临时累积 evidence 媒体组
    """
    card               = State()  # 卡片视图（idle）
    editing_evidence   = State()
    editing_rating     = State()
    editing_humanphoto = State()
    editing_appearance = State()
    editing_body       = State()
    editing_service    = State()
    editing_attitude   = State()
    editing_environment = State()
    editing_summary    = State()
    waiting_reimbursement_choice = State()  # 报销询问步（可选）


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


# Phase 4 dead code 历史注释：
# - PromoLinkStates 于 2026-05-20 Sprint 7 §9.1 第 1 批 dead code 删除中清理。
# - UserSourceLookupStates 于 2026-05-20 Sprint 7 §9.1 第 2 批清理。
# 原 promo_links / source_stats handler 自 2026-05-18 Phase 4 下线。


class TeacherDailyStatusStates(StatesGroup):
    """老师每日状态：取消原因 输入"""
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
    """老师完整档案录入 FSM（v2 2026-05-17：9 步精简版 + 3 备用步）

    主路径：
        Step 1 转发老师消息  → 自动抓 user_id + username + @contact_telegram
        Step 2 艺名 display_name
        Step 3 基本信息 age/height_cm/weight_kg/bra_size
        Step 4 地区 region
        Step 5 价格描述 price_detail → 自动派生 price（最大金额）+ description（积分/报销档）+ taboos（写死）
        Step 6 服务内容 service_content（可跳过）
        Step 7 标签 tags
        Step 8 跳转链接 button_url
        Step 9 上传相册 photos（支持媒体组）
        → button_text 自动 = "{region} {display_name}"
        → confirm 预览 + 保存

    Step 1 备用：转发消息缺 forward_from 时进 3 个手动步骤
    """
    # Step 1 主：转发
    waiting_forward          = State()
    # Step 1 备用（fallback：转发缺 forward_from 时手动 3 步）
    waiting_manual_user_id   = State()
    waiting_manual_username  = State()
    waiting_manual_contact   = State()
    # Step 2-9
    waiting_display_name     = State()
    waiting_basic_info       = State()  # 一行 "年龄 身高 体重 罩杯"
    waiting_region           = State()
    waiting_price_detail     = State()  # 必填；自动派生 price / description / taboos
    waiting_service_content  = State()  # 可跳过
    waiting_tags             = State()
    waiting_button_url       = State()
    waiting_photos           = State()  # 支持媒体组聚合 + "完成"
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


class QuickEntryKeywordStates(StatesGroup):
    """UX-9.1：群组快捷词配置 FSM

    state.data：
        新增（add 模式）: {"mode": "add", "trigger": str, "banner": str, "body": str}
        编辑（edit 模式）: {"mode": "edit", "kid": int, "field": str}
    """
    waiting_add_trigger = State()
    waiting_add_banner  = State()
    waiting_add_body    = State()
    waiting_add_buttons = State()
    waiting_edit_value  = State()

from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    """普通用户私聊搜索状态（F4，v2 §2.4）"""
    waiting_query = State()


# A0 后下线（条件筛选）：FilterStates —— 随 user_filter 功能移除，见 docs/DELETED-FEATURES.md


# Phase A0（2026-05-23）已下线：SearchHistoryStates
# 删除原因：见 docs/DELETED-FEATURES.md。

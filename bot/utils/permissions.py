from functools import wraps
from aiogram import types
from bot.database import is_admin, is_super_admin
from bot.config import config


def admin_required(func):
    """管理员权限装饰器"""

    @wraps(func)
    async def wrapper(event, *args, **kwargs):
        if isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
        elif isinstance(event, types.Message):
            user_id = event.from_user.id
        else:
            return

        # 超级管理员始终有权限
        if user_id == config.super_admin_id:
            return await func(event, *args, **kwargs)

        if not await is_admin(user_id):
            if isinstance(event, types.CallbackQuery):
                await event.answer("您没有管理员权限", show_alert=True)
            else:
                await event.reply("您没有管理员权限")
            return

        return await func(event, *args, **kwargs)

    return wrapper


def super_admin_required(func):
    """超级管理员权限装饰器"""

    @wraps(func)
    async def wrapper(event, *args, **kwargs):
        if isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
        elif isinstance(event, types.Message):
            user_id = event.from_user.id
        else:
            return

        if user_id != config.super_admin_id and not await is_super_admin(user_id):
            if isinstance(event, types.CallbackQuery):
                await event.answer("此操作需要超级管理员权限", show_alert=True)
            else:
                await event.reply("此操作需要超级管理员权限")
            return

        return await func(event, *args, **kwargs)

    return wrapper

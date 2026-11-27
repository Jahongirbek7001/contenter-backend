from aiogram.types import User as TelegramUser

from app.domain.users import Profile


def telegram_profile(user: TelegramUser) -> Profile:
    return Profile(first_name=user.first_name, last_name=user.last_name, username=user.username)

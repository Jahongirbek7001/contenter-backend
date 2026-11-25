from urllib.parse import urlencode

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.callbacks import GalleryCb, LanguageCb, PickCb, RegenCb, RulesCb
from app.bot.texts import t
from app.models.enums import Language, TrendAudience

AUDIENCE_KEYS = {
    TrendAudience.ALL: "filter_all",
    TrendAudience.WOMEN: "filter_women",
    TrendAudience.MEN: "filter_men",
}


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇺🇿 O'zbekcha", callback_data=LanguageCb(language=Language.UZ).pack()
                ),
                InlineKeyboardButton(
                    text="🇷🇺 Русский", callback_data=LanguageCb(language=Language.RU).pack()
                ),
            ]
        ]
    )


def main_menu(language: Language) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(language, "menu_trends"))],
            [
                KeyboardButton(text=t(language, "menu_balance")),
                KeyboardButton(text=t(language, "menu_language")),
                KeyboardButton(text=t(language, "menu_help")),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def rules_keyboard(language: Language, template_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "rules_accept"),
                    callback_data=RulesCb(template_id=template_id).pack(),
                )
            ]
        ]
    )


def gallery_keyboard(
    language: Language,
    audience: TrendAudience,
    index: int,
    total: int,
    template_id: int,
    price: int,
) -> InlineKeyboardMarkup:
    filters = [
        InlineKeyboardButton(
            text=("• " if option is audience else "") + t(language, key),
            callback_data=GalleryCb(audience=option, index=0).pack(),
        )
        for option, key in AUDIENCE_KEYS.items()
    ]
    previous_index = (index - 1) % total
    next_index = (index + 1) % total
    navigation = [
        InlineKeyboardButton(
            text="◀️", callback_data=GalleryCb(audience=audience, index=previous_index).pack()
        ),
        InlineKeyboardButton(
            text=f"{index + 1}/{total}",
            callback_data=GalleryCb(audience=audience, index=index).pack(),
        ),
        InlineKeyboardButton(
            text="▶️", callback_data=GalleryCb(audience=audience, index=next_index).pack()
        ),
    ]
    pick = [
        InlineKeyboardButton(
            text=t(language, "pick", price=price),
            callback_data=PickCb(template_id=template_id).pack(),
        )
    ]
    return InlineKeyboardMarkup(inline_keyboard=[filters, navigation, pick])


def result_keyboard(
    language: Language, generation_id: int, price: int, bot_username: str
) -> InlineKeyboardMarkup:
    share_url = "https://t.me/share/url?" + urlencode(
        {"url": f"https://t.me/{bot_username}", "text": t(language, "share_text")}
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "regenerate", price=price),
                    callback_data=RegenCb(generation_id=generation_id).pack(),
                )
            ],
            [InlineKeyboardButton(text=t(language, "share"), url=share_url)],
        ]
    )

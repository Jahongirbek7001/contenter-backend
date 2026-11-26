from urllib.parse import urlencode

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.callbacks import (
    GalleryCb,
    LanguageCb,
    OptionAction,
    OptionCb,
    PickCb,
    RegenCb,
    ResolutionCb,
    RulesCb,
    ScriptAction,
    ScriptCb,
    SpokenRulesCb,
    StyleCb,
)
from app.bot.texts import t
from app.models import ScriptStyle
from app.models.enums import Language, Product, Resolution, TrendAudience

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
                KeyboardButton(text=t(language, "menu_talking")),
                KeyboardButton(text=t(language, "menu_series")),
            ],
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


def _share_button(language: Language, bot_username: str) -> InlineKeyboardButton:
    share_url = "https://t.me/share/url?" + urlencode(
        {"url": f"https://t.me/{bot_username}", "text": t(language, "share_text")}
    )
    return InlineKeyboardButton(text=t(language, "share"), url=share_url)


def result_keyboard(
    language: Language, generation_id: int, price: int, bot_username: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "regenerate", price=price),
                    callback_data=RegenCb(generation_id=generation_id).pack(),
                )
            ],
            [_share_button(language, bot_username)],
        ]
    )


def share_keyboard(language: Language, bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_share_button(language, bot_username)]])


def style_title(style: ScriptStyle, language: Language) -> str:
    return style.title_ru if language is Language.RU else style.title_uz


def style_keyboard(
    language: Language, product: Product, styles: list[ScriptStyle]
) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=style_title(style, language),
            callback_data=StyleCb(product=product, style_id=style.id).pack(),
        )
        for style in styles
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    )


def spoken_rules_keyboard(
    language: Language, product: Product, style_id: int
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "rules_accept"),
                    callback_data=SpokenRulesCb(product=product, style_id=style_id).pack(),
                )
            ]
        ]
    )


def script_keyboard(language: Language) -> InlineKeyboardMarkup:
    def button(key: str, action: ScriptAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=t(language, key), callback_data=ScriptCb(action=action).pack()
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("script_approve", ScriptAction.APPROVE)],
            [
                button("script_rewrite", ScriptAction.REWRITE),
                button("script_edit", ScriptAction.EDIT),
            ],
        ]
    )


def resolution_keyboard(language: Language, prices: dict[Resolution, int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "resolution_button", resolution=resolution.value, price=price),
                    callback_data=ResolutionCb(resolution=resolution).pack(),
                )
            ]
            for resolution in Resolution
            if (price := prices.get(resolution)) is not None
        ]
    )


def options_keyboard(language: Language, subtitles: bool, price: int) -> InlineKeyboardMarkup:
    def button(text: str, action: OptionAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=OptionCb(action=action).pack())

    subtitles_key = "option_subtitles_on" if subtitles else "option_subtitles_off"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(t(language, subtitles_key), OptionAction.SUBTITLES),
                button(t(language, "option_contact"), OptionAction.CONTACT),
            ],
            [button(t(language, "option_create", price=price), OptionAction.CREATE)],
        ]
    )

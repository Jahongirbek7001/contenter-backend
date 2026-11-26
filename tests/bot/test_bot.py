import re

import pytest

from app.bot.callbacks import (
    BuyCb,
    GalleryCb,
    OptionAction,
    OptionCb,
    PickCb,
    RegenCb,
    ResolutionCb,
    ScriptAction,
    ScriptCb,
    ShopAction,
    ShopCb,
    SpokenRulesCb,
    StyleCb,
)
from app.bot.keyboards import (
    gallery_keyboard,
    resolution_keyboard,
    result_keyboard,
    shop_keyboard,
)
from app.bot.notifier import failure_text, paid_text
from app.bot.shop import _pack_id
from app.bot.spoken import _menu_product
from app.bot.texts import MENU_TEXTS, TEXTS, t
from app.domain.generations.trend import Outcome, RejectReason
from app.domain.payments.notify import Notice
from app.models import Pack
from app.models.enums import Language, Product, Resolution, TrendAudience

PLACEHOLDER = re.compile(r"{(\w+)}")


def test_every_text_exists_in_both_languages_with_same_placeholders() -> None:
    uz, ru = TEXTS[Language.UZ], TEXTS[Language.RU]
    assert uz.keys() == ru.keys()
    for key in uz:
        assert set(PLACEHOLDER.findall(uz[key])) == set(PLACEHOLDER.findall(ru[key])), key


@pytest.mark.parametrize("reason", list(RejectReason))
def test_every_reject_reason_has_a_message(reason: RejectReason) -> None:
    for language in Language:
        text = failure_text(language, Outcome.PHOTO_REJECTED, reason)
        assert t(language, "failed_refund_note") in text


def test_failure_messages_promise_refund() -> None:
    assert "⚡" in failure_text(Language.UZ, Outcome.BLOCKED, None)
    assert "⚡" in failure_text(Language.RU, Outcome.FAILED, None)


def test_callback_data_fits_telegram_limit() -> None:
    # Telegram rejects callback_data longer than 64 bytes.
    for packed in (
        GalleryCb(audience=TrendAudience.WOMEN, index=999).pack(),
        PickCb(template_id=2**31).pack(),
        RegenCb(generation_id=2**62).pack(),
    ):
        assert len(packed.encode()) <= 64


def test_gallery_navigation_wraps_around() -> None:
    keyboard = gallery_keyboard(Language.UZ, TrendAudience.ALL, 0, 4, 11, 2)
    previous_button, counter, _ = keyboard.inline_keyboard[1]
    assert GalleryCb.unpack(previous_button.callback_data or "").index == 3
    assert counter.text == "1/4"
    pick = keyboard.inline_keyboard[2][0]
    assert PickCb.unpack(pick.callback_data or "").template_id == 11
    assert "2 ⚡" in pick.text


def test_result_keyboard_shares_bot_link() -> None:
    keyboard = result_keyboard(Language.RU, 5, 2, "contentorai_bot")
    share = keyboard.inline_keyboard[1][0]
    assert share.url is not None
    assert share.url.startswith("https://t.me/share/url?")
    assert "t.me%2Fcontentorai_bot" in share.url


def test_spoken_callbacks_fit_telegram_limit() -> None:
    for packed in (
        StyleCb(product=Product.SERIES, style_id=2**31).pack(),
        SpokenRulesCb(product=Product.TALKING, style_id=2**31).pack(),
        ScriptCb(action=ScriptAction.REWRITE).pack(),
        ResolutionCb(resolution=Resolution.P1080).pack(),
        OptionCb(action=OptionAction.CREATE).pack(),
    ):
        assert len(packed.encode()) <= 64


def test_resolution_keyboard_lists_only_priced_resolutions_in_order() -> None:
    keyboard = resolution_keyboard(Language.UZ, {Resolution.P1080: 15, Resolution.P360: 3})
    labels = [row[0].text for row in keyboard.inline_keyboard]
    assert labels == ["360p · 3 ⚡", "1080p · 15 ⚡"]


def test_menu_buttons_are_never_taken_as_free_text() -> None:
    for language in Language:
        for key in ("menu_talking", "menu_series", "menu_trends", "menu_balance"):
            assert t(language, key) in MENU_TEXTS
    assert _menu_product(t(Language.RU, "menu_series")) is Product.SERIES
    assert _menu_product("Salom") is None


def test_shop_lists_only_star_priced_packs_and_fits_callback_limit() -> None:
    priced = Pack(
        id=2**31,
        code="start",
        title_uz="Start",
        title_ru="Старт",
        price_uzs=1,
        price_stars=210,
        credits=5,
        bonus_credits=1,
        is_one_time=False,
    )
    site_only = Pack(
        id=3,
        code="pro",
        title_uz="Pro",
        title_ru="Про",
        price_uzs=1,
        price_stars=None,
        credits=100,
        bonus_credits=0,
        is_one_time=False,
    )
    keyboard = shop_keyboard(Language.RU, [priced, site_only])
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert buttons[0].text == "Старт · 6 ⚡ — 210 ⭐"
    assert len(keyboard.inline_keyboard) == 2
    for button in buttons:
        assert len((button.callback_data or "").encode()) <= 64
    assert BuyCb.unpack(buttons[0].callback_data or "").pack_id == 2**31
    assert ShopCb.unpack(buttons[1].callback_data or "").action is ShopAction.PROMO


def test_stars_payload_round_trip() -> None:
    assert _pack_id("pack:12") == 12
    assert _pack_id("pack:x") is None
    assert _pack_id("generation:1") is None


def test_paid_message_mentions_referral_bonus() -> None:
    notice = Notice(chat_id=1, language=Language.UZ, credits=5, available=7, referral_bonus=2)
    text = paid_text(notice)
    assert "+5 ⚡" in text and "+2 ⚡" in text and "7 ⚡" in text
    assert "+2" not in paid_text(Notice(chat_id=1, language=Language.RU, credits=5, available=5))

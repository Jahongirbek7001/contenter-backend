import re

import pytest

from app.bot.callbacks import (
    GalleryCb,
    OptionAction,
    OptionCb,
    PickCb,
    RegenCb,
    ResolutionCb,
    ScriptAction,
    ScriptCb,
    SpokenRulesCb,
    StyleCb,
)
from app.bot.keyboards import gallery_keyboard, resolution_keyboard, result_keyboard
from app.bot.notifier import failure_text
from app.bot.spoken import _menu_product
from app.bot.texts import MENU_TEXTS, TEXTS, t
from app.domain.generations.trend import Outcome, RejectReason
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

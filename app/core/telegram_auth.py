"""Validation of Telegram Mini App initData (core.telegram.org/bots/webapps#validating-data)."""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode

MAX_AGE_SECONDS = 24 * 60 * 60


class InitDataError(ValueError):
    pass


@dataclass(frozen=True)
class MiniAppUser:
    telegram_id: int
    language_code: str | None
    start_param: str | None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


def validate_init_data(
    init_data: str, bot_token: str, now: float | None = None, max_age: int = MAX_AGE_SECONDS
) -> MiniAppUser:
    fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("hash is missing")
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("signature mismatch")

    try:
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
        telegram_id = int(user["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InitDataError("auth_date or user is missing") from exc
    if (now if now is not None else time.time()) - auth_date > max_age:
        raise InitDataError("initData expired")

    def text(key: str) -> str | None:
        value = user.get(key)
        return value if isinstance(value, str) else None

    return MiniAppUser(
        telegram_id=telegram_id,
        language_code=text("language_code"),
        start_param=fields.get("start_param"),
        first_name=text("first_name"),
        last_name=text("last_name"),
        username=text("username"),
    )


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Builds signed initData the way Telegram does; used by tests."""
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


# Telegram Login Widget (core.telegram.org/widgets/login#checking-authorization): the secret
# is SHA-256 of the bot token, unlike the mini app's "WebAppData" HMAC key.
LOGIN_MAX_AGE_SECONDS = 24 * 60 * 60


def validate_login_widget(
    fields: dict[str, str],
    bot_token: str,
    now: float | None = None,
    max_age: int = LOGIN_MAX_AGE_SECONDS,
) -> int:
    """Returns the Telegram user id of a genuine, fresh widget login."""
    data = dict(fields)
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InitDataError("hash is missing")
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("signature mismatch")
    try:
        auth_date = int(data["auth_date"])
        telegram_id = int(data["id"])
    except (KeyError, ValueError) as exc:
        raise InitDataError("auth_date or id is missing") from exc
    if (now if now is not None else time.time()) - auth_date > max_age:
        raise InitDataError("login expired")
    return telegram_id


def sign_login_widget(fields: dict[str, str], bot_token: str) -> dict[str, str]:
    """Builds signed widget data the way Telegram does; used by tests."""
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hashlib.sha256(bot_token.encode()).digest()
    digest = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return {**fields, "hash": digest}

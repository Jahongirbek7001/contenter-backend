"""Owner-editable numbers (admin cabinet → Sozlamalar)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting


@dataclass(frozen=True)
class SettingSpec:
    key: str
    default: int
    minimum: int
    maximum: int


# ⚡ every new customer gets on first contact. 0 turns it off; fake accounts make it costly.
WELCOME_BONUS = SettingSpec("welcome_bonus", default=0, minimum=0, maximum=20)
# Alert the owner when today's model spend passes this many US dollars. 0 turns it off.
DAILY_COST_ALERT_USD = SettingSpec("daily_cost_alert_usd", default=50, minimum=0, maximum=10_000)

SETTINGS = {spec.key: spec for spec in (WELCOME_BONUS, DAILY_COST_ALERT_USD)}


async def get_setting(session: AsyncSession, spec: SettingSpec) -> int:
    value = await session.scalar(select(AppSetting.value).where(AppSetting.key == spec.key))
    return spec.default if value is None else value


async def all_settings(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(select(AppSetting.key, AppSetting.value))
    stored = {key: value for key, value in rows}
    return {key: stored.get(key, spec.default) for key, spec in SETTINGS.items()}


async def set_setting(session: AsyncSession, spec: SettingSpec, value: int) -> None:
    if not spec.minimum <= value <= spec.maximum:
        raise ValueError(f"{spec.key} must be between {spec.minimum} and {spec.maximum}")
    statement = insert(AppSetting).values(key=spec.key, value=value)
    await session.execute(
        statement.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    )

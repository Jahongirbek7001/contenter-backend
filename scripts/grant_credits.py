"""Give ⚡ to a user for local testing until payments (S4) and the admin customers page exist.

uv run python -m scripts.grant_credits <telegram_id> <amount> --note "owner test"
"""

import argparse
import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.domain.credits.service import get_balance, grant_bonus
from app.models import User


async def main(telegram_id: int, amount: int, note: str) -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session, session.begin():
            user_id = await session.scalar(select(User.id).where(User.telegram_id == telegram_id))
            if user_id is None:
                raise SystemExit("user not found: send /start to the bot first")
            await grant_bonus(session, user_id, amount, note)
            balance = await get_balance(session, user_id)
    finally:
        await engine.dispose()
    print(f"granted {amount} ⚡, available now {balance.available} ⚡")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("telegram_id", type=int)
    parser.add_argument("amount", type=int)
    parser.add_argument("--note", default="manual grant")
    args = parser.parse_args()
    if args.amount <= 0:
        parser.error("amount must be positive")
    asyncio.run(main(args.telegram_id, args.amount, args.note))

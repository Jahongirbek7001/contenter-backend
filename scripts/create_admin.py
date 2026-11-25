"""Create an admin cabinet account and print its generated password once.

uv run python -m scripts.create_admin owner@example.com --role owner
"""

import argparse
import asyncio
import secrets

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.domain.admin.service import create_admin
from app.models.enums import AdminRole


async def main(email: str, role: AdminRole) -> None:
    password = secrets.token_urlsafe(12)
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session, session.begin():
            admin = await create_admin(session, email, password, role)
    finally:
        await engine.dispose()
    print(f"created {admin.role.value}: {admin.email}")
    print(f"password: {password}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--role", choices=[r.value for r in AdminRole], default=AdminRole.ADMIN)
    args = parser.parse_args()
    asyncio.run(main(args.email, AdminRole(args.role)))

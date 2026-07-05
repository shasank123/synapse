"""Create tables and seed a development user + API key.

``seed_dev_key`` is idempotent: it reuses the dev user/key if present so you can
run it repeatedly. It prints the raw key (shown once) to configure the CLI:

    synapse config --key <printed_key>
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from synapse_backend.auth.api_keys import create_api_key_sync
from synapse_backend.auth.passwords import hash_password
from synapse_backend.db.database import Base, SessionLocal, sync_engine
from synapse_backend.db.models import ApiKey, User

logger = logging.getLogger(__name__)

DEV_EMAIL = "dev@synapse.local"
DEV_PASSWORD = "synapse-dev"


def create_tables() -> None:
    Base.metadata.create_all(bind=sync_engine)
    logger.info("Tables ensured")


def seed_dev_key() -> str | None:
    """Ensure a dev user + one API key exist. Returns the raw key if newly created."""
    session = SessionLocal()
    try:
        user = session.execute(
            select(User).where(User.email == DEV_EMAIL)
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=DEV_EMAIL,
                password_hash=hash_password(DEV_PASSWORD),
                full_name="Synapse Dev",
            )
            session.add(user)
            session.commit()
            session.refresh(user)

        existing_key = session.execute(
            select(ApiKey).where(ApiKey.user_id == user.id)
        ).scalar_one_or_none()
        if existing_key is not None:
            print(
                f"[seed] Dev user already has a key ({existing_key.key_prefix}…). "
                f"Raw key was only shown at creation time.\n"
                f"[seed] To mint a new one: python -m synapse_backend.scripts_entry new-key"
            )
            return None

        _, raw = create_api_key_sync(session, user.id, name="dev-cli")
        print("\n" + "=" * 64)
        print("  Synapse dev API key (store it — shown once):")
        print(f"    {raw}")
        print("  Configure the CLI with:")
        print(f"    synapse config --key {raw}")
        print("=" * 64 + "\n")
        return raw
    finally:
        session.close()


def new_key() -> str:
    """Mint an additional key for the dev user and print it."""
    session = SessionLocal()
    try:
        user = session.execute(
            select(User).where(User.email == DEV_EMAIL)
        ).scalar_one_or_none()
        if user is None:
            seed_dev_key()
            user = session.execute(
                select(User).where(User.email == DEV_EMAIL)
            ).scalar_one()
        _, raw = create_api_key_sync(session, user.id, name="dev-cli")
        print(f"\nNew key: {raw}\n")
        return raw
    finally:
        session.close()

#!/usr/bin/env python
"""Create an administrator account.

    ./scripts/create_admin.py admin@cheeringshop.online

Deliberately NOT an API endpoint. A public "make me an admin" route is an
obvious hole, and even an admin-only one has a bootstrap problem: the first
administrator has to come from somewhere. Requiring shell access to the server
means the privilege is gated on infrastructure access, not on knowing a URL.

Run it inside the container:
    docker compose exec api python scripts/create_admin.py admin@example.com
"""

import asyncio
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    email = sys.argv[1].strip().lower()

    password = getpass.getpass("Password (blank to generate one): ").strip()
    generated = False
    if not password:
        password = secrets.token_urlsafe(18)
        generated = True
    elif len(password) < 12:
        # Stricter than the API's 8: this account can approve vendors and read
        # everything.
        print("Refusing: an admin password must be at least 12 characters.")
        return 1
    else:
        if password != getpass.getpass("Confirm: ").strip():
            print("Passwords do not match.")
            return 1

    async with SessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is not None:
            if existing.role != UserRole.ADMIN:
                print(
                    f"Refusing: {email} already exists as {existing.role}. "
                    "Roles are fixed at creation — use a different address."
                )
                return 1
            existing.password_hash = hash_password(password)
            print(f"Reset the password for existing admin {email}")
        else:
            db.add(
                User(
                    role=UserRole.ADMIN.value,
                    email=email,
                    password_hash=hash_password(password),
                    is_email_verified=True,
                    full_name="Administrator",
                )
            )
            print(f"Created admin {email}")
        await db.commit()

    if generated:
        print(f"\n  Generated password: {password}")
        print("  Save it now — it is not stored anywhere and cannot be recovered.\n")

    print("Sign in via POST /api/v1/auth/login, then use /api/v1/admin/*")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

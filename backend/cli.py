"""
CyberDrishti AI — Administrative Command-Line Interface (CLI)
Used for one-time initialization, administrative bootstrapping, and ledger verification.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
import uuid
from typing import Optional

from argon2 import PasswordHasher
from sqlalchemy import select

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.models import User, AuditLog
from db.session import AsyncSessionLocal
from utils.audit import append_audit


async def _bootstrap_admin(
    username: str,
    email: str,
    password: Optional[str],
    full_name: str,
) -> None:
    generated = False
    if not password:
        password = secrets.token_urlsafe(16)
        generated = True

    ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32)
    hashed = ph.hash(password)

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.username == username))
        existing = res.scalar_one_or_none()

        if existing is not None:
            existing.hashed_password = hashed
            existing.email = email
            existing.full_name = full_name
            existing.role = "admin"
            existing.is_active = True
            existing.must_change_password = True
            user_id = existing.id
            action = "ADMIN_PASSWORD_RESET"
            print(f"✓ Updated existing administrator account: '{username}'")
        else:
            new_user = User(
                id=uuid.uuid4(),
                username=username,
                email=email,
                hashed_password=hashed,
                full_name=full_name,
                role="admin",
                is_active=True,
                must_change_password=True,
            )
            db.add(new_user)
            user_id = new_user.id
            action = "ADMIN_BOOTSTRAPPED"
            print(f"✓ Created new administrator account: '{username}'")

        await db.commit()

        # Write to audit ledger
        await append_audit(
            db,
            action=action,
            user_id=user_id,
            resource_type="user",
            resource_id=str(user_id),
            details={
                "username": username,
                "email": email,
                "must_change_password": True,
                "hasher": "argon2id",
            },
        )
        await db.commit()

    print("\n============================================================")
    print("  ADMINISTRATOR CREDENTIALS BOOTSTRAPPED")
    print("============================================================")
    print(f"  Username: {username}")
    print(f"  Email:    {email}")
    print(f"  Password: {password}")
    if generated:
        print("  Notice:   A random password was generated.")
    print("  Policy:   'must_change_password' flag is ACTIVE.")
    print("            You will be forced to change this on first login.")
    print("============================================================\n")


def main():
    parser = argparse.ArgumentParser(description="CyberDrishti AI Administrator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    boot_parser = subparsers.add_parser("bootstrap-admin", help="Bootstrap initial administrator account")
    boot_parser.add_argument("--username", default="admin", help="Administrator username")
    boot_parser.add_argument("--email", default="admin@cyberdrishti.gov.in", help="Administrator email")
    boot_parser.add_argument("--password", default=None, help="Initial password (random if omitted)")
    boot_parser.add_argument("--full-name", default="System Administrator", help="Full name")

    args = parser.parse_args()

    if args.command == "bootstrap-admin":
        asyncio.run(_bootstrap_admin(args.username, args.email, args.password, args.full_name))


if __name__ == "__main__":
    main()

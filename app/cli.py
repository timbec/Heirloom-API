"""Admin commands. Run with: uv run python -m app.cli <command> --help"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import User
from app.security import hash_password

MIN_PASSWORD_LENGTH = 8


async def create_user(email: str, name: str, password: str, admin: bool) -> User:
    async with SessionLocal() as db:
        email = email.strip().lower()
        if await db.scalar(select(User).where(User.email == email)):
            raise SystemExit(f"A user with email {email} already exists.")
        user = User(email=email, name=name, password_hash=hash_password(password), is_admin=admin)
        db.add(user)
        await db.commit()
        return user


async def set_password(email: str, password: str) -> None:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise SystemExit(f"No user with email {email}.")
        user.password_hash = hash_password(password)
        await db.commit()


def _read_password(given: str | None) -> str:
    password = given or getpass.getpass("Password: ")
    if given is None and password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords don't match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


async def _run(args: argparse.Namespace) -> None:
    try:
        if args.command == "create-user":
            password = _read_password(args.password)
            user = await create_user(args.email, args.name, password, args.admin)
            role = "admin" if user.is_admin else "user"
            print(f"Created {role} {user.email} (id {user.id}).")
        elif args.command == "set-password":
            await set_password(args.email, _read_password(args.password))
            print(f"Password updated for {args.email}.")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="Create a user (no public sign-up yet)")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--admin", action="store_true", help="Can use the admin panel")
    create.add_argument("--password", help="Omit to be prompted (keeps it out of shell history)")

    reset = commands.add_parser("set-password", help="Set a user's password")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password", help="Omit to be prompted")

    asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    main(sys.argv[1:])

"""Management CLI.

    python -m app.cli create-admin --email admin@example.com        # prompts for password
    python -m app.cli create-admin --email admin@example.com --password-stdin < pw.txt

The password is never accepted as a command-line argument (it would leak into shell history
and process listings).
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.db.models import User
from app.db.session import create_engine, create_session_factory
from app.repositories.users import UserRepository
from app.schemas.auth import Email, NewPassword
from app.services.auth import AuthService

_email_adapter: TypeAdapter[str] = TypeAdapter(Email)
_password_adapter: TypeAdapter[str] = TypeAdapter(NewPassword)


class CliError(Exception):
    """A user-facing error: printed without a traceback, exit code 1."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="DharaDrishti admin")
    commands = parser.add_subparsers(dest="command", required=True)

    create_admin = commands.add_parser(
        "create-admin", help="Create an admin user, or promote an existing user to admin."
    )
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from stdin instead of prompting (for scripts).",
    )
    return parser


def read_password(*, from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        raise CliError("Passwords do not match.")
    return password


def _first_error(exc: ValidationError) -> str:
    return str(exc.errors()[0]["msg"])


def validate_credentials(email: str, password: str) -> tuple[str, str]:
    try:
        clean_email = _email_adapter.validate_python(email)
    except ValidationError as exc:
        raise CliError(f"Invalid email: {_first_error(exc)}") from exc
    try:
        clean_password = _password_adapter.validate_python(password)
    except ValidationError as exc:
        raise CliError(f"Invalid password: {_first_error(exc)}") from exc
    return clean_email, clean_password


async def create_admin(settings: Settings, email: str, password: str) -> tuple[User, bool]:
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            service = AuthService(users=UserRepository(session), uow=session, settings=settings)
            return await service.ensure_admin(email, password)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    try:
        if args.command == "create-admin":
            email, password = validate_credentials(
                args.email, read_password(from_stdin=args.password_stdin)
            )
            user, created = asyncio.run(create_admin(settings, email, password))
            action = "Created admin" if created else "Ensured admin role for existing user"
            sys.stdout.write(f"{action}: {user.email} (id={user.id})\n")
    except (CliError, AppError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

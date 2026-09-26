import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app import cli
from app.core.config import Settings
from app.db.models import User, UserRole


def test_parser_requires_command() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_parser_create_admin() -> None:
    args = cli.build_parser().parse_args(["create-admin", "--email", "a@example.com"])

    assert args.command == "create-admin"
    assert args.email == "a@example.com"
    assert not args.password_stdin


def test_read_password_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("from-stdin-pass\n"))

    assert cli.read_password(from_stdin=True) == "from-stdin-pass"


def test_read_password_prompt_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["first-password", "second-password"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    with pytest.raises(cli.CliError, match="do not match"):
        cli.read_password(from_stdin=False)


def test_read_password_prompt_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "same-password")

    assert cli.read_password(from_stdin=False) == "same-password"


def test_validate_credentials_normalizes_email() -> None:
    assert cli.validate_credentials(" Admin@Example.COM ", "long-enough") == (
        "admin@example.com",
        "long-enough",
    )


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [("nope", "long-enough", "Invalid email"), ("a@example.com", "short", "Invalid password")],
)
def test_validate_credentials_errors(email: str, password: str, message: str) -> None:
    with pytest.raises(cli.CliError, match=message):
        cli.validate_credentials(email, password)


def _admin() -> User:
    return User(
        id=uuid.uuid4(), email="admin@example.com", hashed_password="x", role=UserRole.ADMIN
    )


@pytest.mark.parametrize(("created", "word"), [(True, "Created admin"), (False, "Ensured")])
def test_main_create_admin_success(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    created: bool,
    word: str,
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("long-enough-pass\n"))
    fake = AsyncMock(return_value=(_admin(), created))

    with patch.object(cli, "create_admin", fake):
        code = cli.main(
            ["create-admin", "--email", "Admin@Example.com", "--password-stdin"], settings
        )

    assert code == 0
    fake.assert_awaited_once_with(settings, "admin@example.com", "long-enough-pass")
    assert word in capsys.readouterr().out


def test_main_reports_errors_without_traceback(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))

    code = cli.main(["create-admin", "--email", "a@example.com", "--password-stdin"], settings)

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: Invalid password")
    assert "Traceback" not in err

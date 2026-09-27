import asyncio
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app import cli
from app.core.config import Settings
from app.db.models import DocumentStatus, User, UserRole
from app.schemas.documents import DocumentRead
from app.services.ingestion.mappings import LoadResult


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


# ---------------------------------------------------------------- ingest / load-mappings
def test_parser_ingest_and_mappings() -> None:
    parser = cli.build_parser()

    ingest = parser.parse_args(
        ["ingest", "--file", "x.pdf", "--act", "tst", "--name", "N", "--year", "2000", "--wait"]
    )
    mappings = parser.parse_args(["load-mappings", "--replace"])

    assert (ingest.act, ingest.year, ingest.wait) == ("tst", 2000, True)
    assert mappings.replace
    assert mappings.file is None


def test_build_act_metadata_validates() -> None:
    args = cli.build_parser().parse_args(["ingest", "--file", "x.pdf", "--act", "1bad"])

    with pytest.raises(cli.CliError, match="Invalid act metadata"):
        cli.build_act_metadata(args)


def _view(status: str, error: str | None = None) -> DocumentRead:
    now = datetime.now(UTC)
    return DocumentRead(
        id=uuid.uuid4(),
        act_short_code="TST",
        filename="x.pdf",
        status=DocumentStatus(status),
        progress=100 if status == "ready" else 40,
        error=error,
        pages=3,
        chunks_count=7,
        created_at=now,
        updated_at=now,
    )


def test_main_ingest_reports_result(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    fake = AsyncMock(return_value=_view("ready"))

    with patch.object(cli, "ingest_file", fake):
        code = cli.main(["ingest", "--file", "x.pdf", "--act", "TST"], settings)

    assert code == 0
    assert "ready (100%), 7 chunks, 3 pages" in capsys.readouterr().out


def test_main_ingest_failure_exit_code(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = AsyncMock(return_value=_view("failed", error="No sections were detected."))

    with patch.object(cli, "ingest_file", fake):
        code = cli.main(["ingest", "--file", "x.pdf", "--act", "TST", "--wait"], settings)

    assert code == 1
    assert "No sections were detected." in capsys.readouterr().err


def test_ingest_missing_file(settings: Settings, tmp_path: Path) -> None:
    act = cli.build_act_metadata(
        cli.build_parser().parse_args(["ingest", "--file", "x", "--act", "TST"])
    )

    with pytest.raises(cli.CliError, match="File not found"):
        asyncio.run(cli.ingest_file(settings, tmp_path / "missing.pdf", act, wait=False))


def test_main_load_mappings_uses_default_path(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = AsyncMock(return_value=LoadResult(rows_in_file=3, upserted=3, deleted=2))

    with patch.object(cli, "load_mapping_file", fake):
        code = cli.main(["load-mappings", "--replace"], settings)

    assert code == 0
    fake.assert_awaited_once_with(
        settings, settings.data_dir / "mappings" / "ipc_bns.csv", replace=True
    )
    assert "Loaded 3 mappings" in capsys.readouterr().out

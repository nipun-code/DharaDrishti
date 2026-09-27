"""Management CLI.

    python -m app.cli create-admin --email admin@example.com        # prompts for password
    python -m app.cli create-admin --email admin@example.com --password-stdin < pw.txt

    python -m app.cli ingest --file /data/raw/act.pdf --act CODE --name "Full Name" --year 2000
    python -m app.cli load-mappings [--file /data/mappings/ipc_bns.csv] [--replace]
    python -m app.cli download-models

The password is never accepted as a command-line argument (it would leak into shell history
and process listings). `ingest` queues the same background job as the upload API, so the
worker must be running; add --wait to follow its progress.
"""

import argparse
import asyncio
import getpass
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

from arq.connections import ArqRedis
from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.db.models import ActStatus, DocumentStatus, User
from app.db.session import create_engine, create_session_factory
from app.repositories.users import UserRepository
from app.schemas.auth import Email, NewPassword
from app.schemas.documents import ActUpsert, DocumentRead
from app.services.auth import AuthService
from app.services.documents import DocumentService
from app.services.ingestion.embedder import SentenceTransformerEmbedder
from app.services.ingestion.mappings import (
    LoadResult,
    MappingFileError,
    load_mappings,
    parse_mapping_csv,
)
from app.services.ingestion.storage import DocumentStorage
from app.services.retrieval.reranker import CrossEncoderReranker
from app.workers.queue import ArqJobQueue

_email_adapter: TypeAdapter[str] = TypeAdapter(Email)
_password_adapter: TypeAdapter[str] = TypeAdapter(NewPassword)
_POLL_SECONDS = 2.0
_FINISHED = (DocumentStatus.READY, DocumentStatus.FAILED)


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

    ingest = commands.add_parser("ingest", help="Queue a bare-act PDF for ingestion.")
    ingest.add_argument("--file", required=True, type=Path, help="Path to the PDF.")
    ingest.add_argument("--act", required=True, help="Act short code, e.g. BNS.")
    ingest.add_argument("--name", help="Act full name (required for a new act).")
    ingest.add_argument("--year", type=int, help="Act year (required for a new act).")
    ingest.add_argument("--status", choices=[s.value for s in ActStatus], help="in_force/repealed")
    ingest.add_argument("--wait", action="store_true", help="Wait and show progress until done.")

    mappings = commands.add_parser(
        "load-mappings", help="Load the IPC->BNS mapping CSV into section_mappings."
    )
    mappings.add_argument(
        "--file", type=Path, help="CSV path (default: <DATA_DIR>/mappings/ipc_bns.csv)."
    )
    mappings.add_argument(
        "--replace", action="store_true", help="Delete all existing mappings first."
    )

    commands.add_parser(
        "download-models",
        help="Download/load the embedding and re-ranker models now (cached under HF_HOME).",
    )
    return parser


def download_models(settings: Settings) -> list[str]:
    """Load both models once so the first query doesn't wait for a ~1 GB download."""
    loaded = []
    for model in (
        SentenceTransformerEmbedder(
            settings.embedding_model_name, device=settings.embedding_device
        ),
        CrossEncoderReranker(settings.reranker_model_name, device=settings.embedding_device),
    ):
        model.warm_up()
        loaded.append(model.model_name)
    return loaded


# ---------------------------------------------------------------- create-admin
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


# ---------------------------------------------------------------- ingest
class _FileReader:
    """Adapts a binary file to the async `read(size)` interface the upload service expects."""

    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle

    async def read(self, size: int = -1) -> bytes:
        return await asyncio.to_thread(self._handle.read, size)


def build_act_metadata(args: argparse.Namespace) -> ActUpsert:
    try:
        return ActUpsert(
            act_short_code=args.act,
            act_full_name=args.name,
            act_year=args.year,
            act_status=args.status,
        )
    except ValidationError as exc:
        raise CliError(f"Invalid act metadata: {_first_error(exc)}") from exc


async def ingest_file(
    settings: Settings, path: Path, act: ActUpsert, *, wait: bool
) -> DocumentRead:
    if not await asyncio.to_thread(path.is_file):
        raise CliError(f"File not found: {path}")
    engine = create_engine(settings)
    arq = ArqRedis.from_url(settings.redis_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            service = DocumentService(
                session=session,
                storage=DocumentStorage(settings.upload_dir),
                queue=ArqJobQueue(arq),
                settings=settings,
            )
            with path.open("rb") as handle:
                document = await service.upload(
                    _FileReader(handle), path.name, "application/pdf", act
                )
            document_id = document.id
            sys.stdout.write(f"Queued {path.name} as document {document_id}\n")
        return await _follow(factory, settings, document_id, wait=wait)
    finally:
        await arq.aclose()
        await engine.dispose()


async def _follow(
    factory: object, settings: Settings, document_id: uuid.UUID, *, wait: bool
) -> DocumentRead:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: PLC0415

    assert isinstance(factory, async_sessionmaker)  # noqa: S101
    session_factory: async_sessionmaker[AsyncSession] = factory
    last_progress = -1
    while True:
        async with session_factory() as session:
            view = await DocumentService(
                session=session,
                storage=DocumentStorage(settings.upload_dir),
                queue=_NoQueue(),
                settings=settings,
            ).get(document_id)
        if not wait or view.status in _FINISHED:
            return view
        if view.progress != last_progress:
            sys.stdout.write(f"  {view.status.value:<10} {view.progress:>3}%\n")
            last_progress = view.progress
        await asyncio.sleep(_POLL_SECONDS)


class _NoQueue:
    async def enqueue_ingestion(self, document_id: uuid.UUID) -> None:  # pragma: no cover
        raise RuntimeError("read-only")


def _report_ingestion(view: DocumentRead) -> None:
    sys.stdout.write(
        f"Document {view.id}: {view.status.value} ({view.progress}%), "
        f"{view.chunks_count} chunks, {view.pages or 0} pages\n"
    )
    if view.status == DocumentStatus.FAILED:
        raise CliError(f"Ingestion failed: {view.error}")


# ---------------------------------------------------------------- load-mappings
async def load_mapping_file(settings: Settings, path: Path, *, replace: bool) -> LoadResult:
    if not await asyncio.to_thread(path.is_file):
        raise CliError(
            f"Mapping file not found: {path}. Put the verified CSV at data/mappings/ipc_bns.csv."
        )
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    try:
        rows = parse_mapping_csv(text)
    except MappingFileError as exc:
        raise CliError(str(exc)) from exc
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            return await load_mappings(session, rows, replace=replace)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------- entry point
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
        elif args.command == "ingest":
            view = asyncio.run(
                ingest_file(settings, args.file, build_act_metadata(args), wait=args.wait)
            )
            _report_ingestion(view)
        elif args.command == "load-mappings":
            path = args.file or settings.data_dir / "mappings" / "ipc_bns.csv"
            result = asyncio.run(load_mapping_file(settings, path, replace=args.replace))
            sys.stdout.write(
                f"Loaded {result.upserted} mappings from {path}"
                + (f" (deleted {result.deleted} existing)" if args.replace else "")
                + "\n"
            )
        elif args.command == "download-models":
            for name in download_models(settings):
                sys.stdout.write(f"Ready: {name}\n")
    except (CliError, AppError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

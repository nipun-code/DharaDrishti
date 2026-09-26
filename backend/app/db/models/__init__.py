"""ORM models. Importing this package registers every table on Base.metadata (used by Alembic)."""

from app.db.models.act import Act
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.enums import ActStatus, DocumentStatus, UserRole
from app.db.models.eval_run import EvalRun
from app.db.models.feedback import Feedback
from app.db.models.query_log import QueryLog
from app.db.models.section_mapping import SectionMapping
from app.db.models.user import User

__all__ = [
    "Act",
    "ActStatus",
    "Chunk",
    "Document",
    "DocumentStatus",
    "EvalRun",
    "Feedback",
    "QueryLog",
    "SectionMapping",
    "User",
    "UserRole",
]

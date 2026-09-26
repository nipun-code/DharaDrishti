from app.db.models import QueryLog
from app.repositories.base import BaseRepository


class QueryLogRepository(BaseRepository[QueryLog]):
    model = QueryLog

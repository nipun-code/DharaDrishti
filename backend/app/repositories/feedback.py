import uuid

from sqlalchemy import select

from app.db.models import Feedback
from app.repositories.base import BaseRepository


class FeedbackRepository(BaseRepository[Feedback]):
    model = Feedback

    async def get_for_user(self, query_log_id: uuid.UUID, user_id: uuid.UUID) -> Feedback | None:
        stmt = select(Feedback).where(
            Feedback.query_log_id == query_log_id, Feedback.user_id == user_id
        )
        return await self._session.scalar(stmt)

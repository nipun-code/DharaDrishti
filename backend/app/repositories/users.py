from sqlalchemy import select

from app.db.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        """`email` must already be normalized (lower-cased) by the caller."""
        return await self._session.scalar(select(User).where(User.email == email))

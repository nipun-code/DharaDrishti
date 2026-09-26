"""String enums stored as VARCHAR + CHECK constraint (simpler to migrate than native PG enums)."""

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class ActStatus(StrEnum):
    IN_FORCE = "in_force"
    REPEALED = "repealed"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentRead(BaseModel):
    """The API representation of an uploaded document."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    media_type: str
    byte_size: int = Field(ge=0)
    status: str
    chunk_count: int = Field(default=0, ge=0)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("status", mode="before")
    @classmethod
    def serialize_status(cls, value: object) -> object:
        """Accept both string statuses and ORM enum values."""
        return getattr(value, "value", value)

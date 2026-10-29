from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def strip_and_require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace characters")
        return value


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    document_id: UUID
    document_name: str
    excerpt: str
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    score: float

    @field_validator("heading_path", mode="before")
    @classmethod
    def normalize_heading_path(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(">") if part.strip()]
        return value


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer: str
    insufficient_evidence: bool
    sources: list[SourceRead] = Field(default_factory=list)

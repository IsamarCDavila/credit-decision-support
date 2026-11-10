from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict

UTCTimestamp = Annotated[datetime, AfterValidator(lambda value: value.astimezone(UTC))]


class CreateCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment: Literal["SME"]
    currency: Literal["USD"]
    cutoff: date


class CaseView(CreateCase):
    id: UUID
    created_at: UTCTimestamp
    current_evaluation_id: UUID | None


class AuditEvent(BaseModel):
    id: UUID
    sequence: int
    actor_id: str
    kind: str
    payload: dict[str, Any]
    previous_hash: str | None
    event_hash: str
    created_at: UTCTimestamp


class AuditPage(BaseModel):
    events: list[AuditEvent]
    next_after_sequence: int | None


class Health(BaseModel):
    status: Literal["ok", "ready"]


class Error(BaseModel):
    detail: str

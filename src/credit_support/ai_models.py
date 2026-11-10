from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

FieldKey = Literal[
    "annual_revenue", "ebitda", "total_debt", "debt_service", "available_cash_flow", "obligations"
]
ProviderName = Literal["mock", "openai"]
WorkflowName = Literal["multi_agent", "generalist"]
Section = Literal["overview", "financials", "policy", "limitations"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(StrictModel):
    key: FieldKey
    source_id: str
    raw_value: str


class ExtractionProposal(StrictModel):
    observations: list[Observation]
    missing_keys: list[FieldKey]


class DraftSelection(StrictModel):
    claim_ids: list[str]
    section_order: list[Section]


class GeneralistProposal(StrictModel):
    extraction: ExtractionProposal
    draft: DraftSelection


class AIRequest(StrictModel):
    source_evaluation_id: UUID
    provider: ProviderName = "mock"
    workflow: WorkflowName = "multi_agent"


class ClaimCard(StrictModel):
    id: str
    section: Section
    text_en: str
    text_es: str
    fact_ids: list[UUID]
    evidence_ids: list[UUID]
    calculation_ids: list[UUID]
    policy_fragment_ids: list[str]


class AIDraft(StrictModel):
    status: Literal["DRAFT_ONLY"]
    simulation: Literal[True]
    requires_human_review: Literal[True]
    marker_en: Literal["SIMULATION"]
    marker_es: Literal["SIMULACIÓN"]
    provider: ProviderName
    model: str
    workflow: WorkflowName
    section_order: list[Section]
    claims: list[ClaimCard]
    tool_trace: list[str]
    limitations_en: list[str]
    limitations_es: list[str]


class ModelCallView(StrictModel):
    id: UUID
    provider: str
    model: str
    stage: str
    status: str
    input_tokens: int | None
    output_tokens: int | None
    charged_usd: str | None
    reserved_usd: str
    accounted_usd: str
    cost_status: Literal["mock", "usage_based", "reserved"]
    prompt_version: str
    response_id: str | None


class BudgetView(StrictModel):
    limit_usd: str
    committed_or_reserved_usd: str
    openai_calls: int

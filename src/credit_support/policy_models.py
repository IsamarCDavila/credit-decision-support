from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["DSCR_MINIMUM"] = "DSCR_MINIMUM"
    formula: Literal["DSCR"] = "DSCR"
    operator: Literal["gte"] = "gte"
    threshold: str = Field(pattern=r"^(?:[0-9]{1,2}|100)(?:\.[0-9]{1,4})?$")

    @model_validator(mode="after")
    def bounded_threshold(self) -> "PolicyRule":
        if not Decimal("0") < Decimal(self.threshold) <= Decimal("100"):
            raise ValueError("Threshold must be within (0,100]")
        return self


class PolicySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{2,79}$")
    synthetic: Literal[True]
    segment: Literal["SME"]
    currency: Literal["USD"]
    accounting_basis: Literal["individual"]
    valid_from: date
    valid_to: date | None
    template_version: Literal["synthetic-policy-v1"] = "synthetic-policy-v1"
    rules: list[PolicyRule] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def valid_period(self) -> "PolicySpec":
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("Policy validity must be a nonempty half-open interval")
        return self


class PolicyCitation(BaseModel):
    policy_version: str
    fragment_id: str
    text_en: str
    text_es: str
    sha256: str


class PolicyView(BaseModel):
    specification: PolicySpec
    content_sha256: str
    fragments: list[PolicyCitation]


class RetrievalHit(BaseModel):
    policy_version: str
    fragment_id: str
    locale: Literal["en", "es"]
    text: str
    sha256: str
    score: float


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_evaluation_id: UUID


class CalculationView(BaseModel):
    id: UUID
    formula_id: str
    formula_version: str
    input_fact_ids: list[UUID]
    status: str
    value: str | None
    unrounded_value: str | None
    details: dict[str, Any]


class RuleResult(BaseModel):
    rule_id: str
    formula_id: str
    operator: str
    threshold: str
    status: Literal["PASS", "FAIL", "REQUIRES_REVIEW"]
    calculation_id: UUID
    policy_fragment_id: str


class PolicyCheckView(BaseModel):
    policy_version: str
    simulation: Literal[True]
    outcome: Literal["meets_rules", "exceptions", "insufficient_evidence"]
    rule_results: list[RuleResult]
    data_quality_exceptions: list[dict[str, str]]
    citations: list[PolicyCitation]

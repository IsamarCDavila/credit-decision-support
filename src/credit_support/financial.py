"""Deterministic DSCR with explicit input conventions and exact threshold comparison."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Literal
from uuid import UUID

FORMULA_VERSION = "dscr-v1"
MAX_AMOUNT = Decimal("999999999999999999.99")
MetricStatus = Literal["CALCULATED", "MISSING_INPUT", "INVALID_INPUT", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class FinancialFact:
    id: UUID
    key: str
    value: Decimal | None
    status: str
    currency: str | None
    unit: str
    period_start: date
    period_end: date


@dataclass(frozen=True)
class DSCR:
    status: MetricStatus
    reason: str
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    ratio: Decimal | None = None
    display: str | None = None

    def meets(self, threshold: Decimal) -> bool | None:
        if self.status != "CALCULATED" or self.numerator is None or self.denominator is None:
            return None
        if not threshold.is_finite() or not Decimal("0") < threshold <= Decimal("100"):
            raise ValueError("Synthetic threshold must be finite and within (0,100]")
        with localcontext(Context(prec=80)):
            return self.numerator >= threshold * self.denominator


def calculate_dscr(facts: list[FinancialFact]) -> DSCR:
    needed = ("available_cash_flow", "debt_service")
    selected = [fact for fact in facts if fact.key in needed]
    if len(selected) != 2 or {f.key for f in selected} != set(needed):
        return DSCR("MISSING_INPUT", "REQUIRED_FIELDS_UNAVAILABLE")
    if any(f.status == "invalid" for f in selected):
        return DSCR("INVALID_INPUT", "INVALID_SOURCE_AMOUNT")
    if any(f.status != "extracted" or f.value is None for f in selected):
        return DSCR("MISSING_INPUT", "UNVERIFIED_OR_MISSING_SOURCE")
    if any(f.currency != "USD" or f.unit != "USD" for f in selected):
        return DSCR("INVALID_INPUT", "UNSUPPORTED_UNIT_OR_CURRENCY")
    periods = {(f.period_start, f.period_end) for f in selected}
    if len(periods) != 1:
        return DSCR("INVALID_INPUT", "MISMATCHED_PERIODS")
    start, end = next(iter(periods))
    if start != date(start.year, 1, 1) or end != date(start.year, 12, 31):
        return DSCR("INVALID_INPUT", "FULL_CALENDAR_YEAR_REQUIRED")
    values = {f.key: f.value for f in selected}
    numerator, denominator = values[needed[0]], values[needed[1]]
    assert numerator is not None and denominator is not None
    for value in (numerator, denominator):
        if not value.is_finite() or value.copy_abs() > MAX_AMOUNT:
            return DSCR("INVALID_INPUT", "AMOUNT_OUT_OF_RANGE")
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            return DSCR("INVALID_INPUT", "SUBCENT_AMOUNT_UNSUPPORTED")
    if denominator < 0:
        return DSCR("INVALID_INPUT", "NEGATIVE_DEBT_SERVICE", numerator, denominator)
    if denominator == 0:
        return DSCR("NOT_APPLICABLE", "ZERO_DEBT_SERVICE", numerator, denominator)
    with localcontext(Context(prec=80)):
        ratio = numerator / denominator
        display = format(ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), ".4f")
    return DSCR("CALCULATED", "VALID_INPUTS", numerator, denominator, ratio, display)

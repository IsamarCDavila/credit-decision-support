from dataclasses import replace
from datetime import date
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from uuid import uuid4

import pytest

from credit_support.financial import FinancialFact, calculate_dscr


def inputs(cash="150000.00", debt="100000.00"):
    return [
        FinancialFact(
            uuid4(),
            key,
            Decimal(value),
            "extracted",
            "USD",
            "USD",
            date(2025, 1, 1),
            date(2025, 12, 31),
        )
        for key, value in (("available_cash_flow", cash), ("debt_service", debt))
    ]


@pytest.mark.parametrize(
    "cash,debt,status,display,passes",
    [
        ("150000.00", "100000.00", "CALCULATED", "1.5000", True),
        ("120000.00", "100000.00", "CALCULATED", "1.2000", True),
        ("119999.99", "100000.00", "CALCULATED", "1.2000", False),
        ("120000.01", "100000.00", "CALCULATED", "1.2000", True),
        ("-1.00", "100.00", "CALCULATED", "-0.0100", False),
        ("0.00", "100.00", "CALCULATED", "0.0000", False),
        ("100.00", "0.00", "NOT_APPLICABLE", None, None),
        ("100.00", "-1.00", "INVALID_INPUT", None, None),
        ("999999999999999999.99", "0.01", "CALCULATED", "99999999999999999999.0000", True),
    ],
)
def test_dscr_conventions_and_threshold(cash, debt, status, display, passes):
    result = calculate_dscr(inputs(cash, debt))
    assert result.status == status
    assert result.display == display
    assert result.meets(Decimal("1.20")) is passes
    if passes is not None:
        assert passes == (Fraction(cash) / Fraction(debt) >= Fraction("1.20"))


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"value": None, "status": "missing"}, "MISSING_INPUT"),
        ({"value": None, "status": "ambiguous"}, "MISSING_INPUT"),
        ({"status": "invalid"}, "INVALID_INPUT"),
        ({"currency": "EUR"}, "INVALID_INPUT"),
        ({"unit": "USD_thousands"}, "INVALID_INPUT"),
        ({"period_start": date(2024, 1, 1)}, "INVALID_INPUT"),
        ({"value": Decimal("NaN")}, "INVALID_INPUT"),
        ({"value": Decimal("Infinity")}, "INVALID_INPUT"),
        ({"value": Decimal("0.001")}, "INVALID_INPUT"),
    ],
)
def test_unusable_inputs_are_not_calculated(change, expected):
    facts = inputs()
    facts[0] = replace(facts[0], **change)
    result = calculate_dscr(facts)
    assert result.status == expected
    assert result.ratio is None and result.meets(Decimal("1.20")) is None


def test_context_independence_and_duplicate_fields():
    facts = inputs("1.00", "3.00")
    with localcontext() as context:
        context.prec = 4
        context.traps[Inexact] = True
        result = calculate_dscr(facts)
        assert result.display == "0.3333"
        assert not result.meets(Decimal("1.20"))
        assert context.prec == 4 and context.traps[Inexact]
    assert calculate_dscr([facts[0], facts[0]]).status == "MISSING_INPUT"

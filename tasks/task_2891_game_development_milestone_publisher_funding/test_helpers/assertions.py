"""Domain assertions for the funding, gate, holdback and waterfall arithmetic."""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

import pytest

from .constants import GATE_PROFILES, READINESS_WEIGHT_CONTENT, READINESS_WEIGHT_CRASH_FREE, READINESS_WEIGHT_FEATURE

THREE_FRACTIONAL_DIGIT_INSTANT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
CALENDAR_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def round_half_up(value) -> int:
    """PRD §2.5: "Rounding is always half up, never banker's rounding and never
    truncation."
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount: int, bps: int) -> int:
    """PRD §2.5: the product of an amount and a rate "is divided by 10000 and the
    result rounded half up to a whole number of cents"."""
    return round_half_up(Decimal(amount) * Decimal(bps) / Decimal(10000))


def round_half_up_2dp(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def expected_readiness_score(feature: float, crash_free: float, content: float) -> float:
    """PRD §3.4 weighted readiness score, rounded half up to two decimals."""
    total = (
        Decimal(str(feature)) * Decimal(str(READINESS_WEIGHT_FEATURE))
        + Decimal(str(crash_free)) * Decimal(str(READINESS_WEIGHT_CRASH_FREE))
        + Decimal(str(content)) * Decimal(str(READINESS_WEIGHT_CONTENT))
    )
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------- primitives
def assert_pct_equals(actual: Any, expected: float, label: str = "percentage") -> None:
    """Percentage-valued fields carry two decimals and are compared exactly."""
    assert actual is not None, f"{label} must be present"
    assert float(actual) == pytest.approx(float(expected), abs=1e-9), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_ratio_equals(actual: Any, expected: float, label: str = "ratio") -> None:
    """PRD §2.5: accepted_milestone_ratio is carried to four decimal places."""
    assert actual is not None, f"{label} must be present"
    assert float(actual) == pytest.approx(float(expected), abs=1e-9), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_decimal_places(raw_value: Any, label: str = "percentage") -> None:
    """The serialized figure must not carry more than two decimal places."""
    text = repr(raw_value) if not isinstance(raw_value, str) else raw_value
    if "." in text:
        fraction = text.split(".", 1)[1].rstrip("0")
        assert len(fraction) <= 2, f"{label}: {raw_value} carries more than two decimals"


def assert_integer_cents(value: Any, label: str = "amount") -> None:
    """PRD §2.5: "All monetary amounts in this system are integer counts of cents."
    """
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_instant_format(value: Any, label: str = "instant") -> None:
    """PRD §2.4: system instants are "ISO 8601 UTC with three fractional digits"."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert THREE_FRACTIONAL_DIGIT_INSTANT.match(value), (
        f"{label} must be ISO 8601 UTC with exactly three fractional digits, got {value!r}"
    )


def assert_calendar_date(value: Any, label: str = "date") -> None:
    assert isinstance(value, str) and CALENDAR_DATE.match(value), (
        f"{label} must be a plain YYYY-MM-DD date, got {value!r}"
    )


def assert_fields_equal(payload: Dict, expected: Dict, label: str = "resource") -> None:
    for key, value in expected.items():
        assert key in payload, f"{label} is missing field '{key}'"
        actual = payload[key]
        if isinstance(value, float):
            assert float(actual) == pytest.approx(value, abs=1e-9), (
                f"{label}.{key}: expected {value}, got {actual}"
            )
        else:
            assert actual == value, f"{label}.{key}: expected {value!r}, got {actual!r}"


def assert_absent(payload: Dict, field: str, label: str = "resource") -> None:
    assert field not in payload, f"{label} must not expose '{field}'"


def assert_common_fields(payload: Dict, label: str = "resource") -> None:
    """PRD §2.4 quartet: id, created_at, updated_at, version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in payload, f"{label} is missing '{field}'"
    assert isinstance(payload["version"], int) and payload["version"] >= 1


def assert_ids(rows: Iterable[Dict], expected_ids: Iterable[str], label: str = "rows") -> None:
    actual = [row["id"] for row in rows]
    assert set(actual) == set(expected_ids), (
        f"{label}: expected ids {sorted(set(expected_ids))}, got {sorted(set(actual))}"
    )


# ------------------------------------------------------------------- ledgers
LEDGER_FIELDS = (
    "uplift_funded_cents",
    "funding_pool_cents",
    "committed_cents",
    "available_funding_cents",
    "accepted_value_cents",
    "advance_disbursed_cents",
    "holdback_reserve_cents",
    "withheld_payment_cents",
    "advance_recouped_cents",
    "unrecouped_advance_cents",
    "royalties_paid_to_date_cents",
    "breach_count",
)


def assert_ledger(agreement: Dict, **expected) -> None:
    """Assert named funding-ledger fields and always re-check pool conservation."""
    for key, value in expected.items():
        assert key in agreement, f"agreement is missing ledger field '{key}'"
        if isinstance(value, float):
            assert float(agreement[key]) == pytest.approx(value, abs=1e-9), (
                f"agreement.{key}: expected {value}, got {agreement[key]}"
            )
        else:
            assert agreement[key] == value, (
                f"agreement.{key}: expected {value}, got {agreement[key]}"
            )
    assert_funding_pool_conservation(agreement)


def assert_funding_pool_conservation(agreement: Dict) -> None:
    """PRD §2.6: "`available_funding_cents` always equals `funding_pool_cents`
    minus `committed_cents`."
    """
    assert (
        agreement["available_funding_cents"]
        == agreement["funding_pool_cents"] - agreement["committed_cents"]
    ), (
        "funding-pool conservation broken: "
        f"available={agreement['available_funding_cents']}, "
        f"pool={agreement['funding_pool_cents']}, committed={agreement['committed_cents']}"
    )


def assert_payment_components(
    payment: Dict,
    scheduled: int,
    overrun: int,
    gross: int,
    holdback_bps: int,
    holdback: int,
    net: int,
) -> None:
    """Assert all five components of the PRD §3.6 four-step disbursement."""
    for field, value in (
        ("scheduled_amount_cents", scheduled),
        ("contractor_overrun_cents", overrun),
        ("gross_amount_cents", gross),
        ("holdback_bps", holdback_bps),
        ("holdback_cents", holdback),
        ("net_amount_cents", net),
    ):
        if field != "holdback_bps":
            assert_integer_cents(payment[field], f"payment.{field}")
        assert payment[field] == value, (
            f"payment.{field}: expected {value}, got {payment[field]}"
        )
    assert payment["gross_amount_cents"] == payment["scheduled_amount_cents"] - payment[
        "contractor_overrun_cents"
    ]
    assert payment["net_amount_cents"] == payment["gross_amount_cents"] - payment[
        "holdback_cents"
    ]


def assert_budget_summary(
    summary: Dict,
    milestone_id: str,
    budget: int,
    committed_basis: int,
    incurred_basis: int,
    available_committed: int,
    overrun: int,
) -> None:
    """Assert the six fields PRD §3.8 says the budget summary exposes."""
    assert_fields_equal(
        summary,
        {
            "milestone_id": milestone_id,
            "contractor_budget_cents": budget,
            "committed_basis_cents": committed_basis,
            "incurred_basis_cents": incurred_basis,
            "available_committed_cents": available_committed,
            "overrun_cents": overrun,
        },
        "budget summary",
    )


def assert_gate_bars_cleared(profile: str, feature: float, crash_free: float,
                             content: float, blockers: int,
                             relief: float = 0.0, cure_pending: bool = False) -> None:
    """Recompute the PRD §3.4 effective bars and assert the metrics clear them."""
    bars = GATE_PROFILES[profile]
    content_bar = Decimal(str(bars["content"])) - Decimal(str(relief))
    if cure_pending:
        content_bar += Decimal("5.00")
    content_bar = max(Decimal("0.00"), min(Decimal("100.00"), content_bar))
    feature_bar = Decimal(str(bars["feature"]))
    if profile != "GOLD" and Decimal(str(crash_free)) >= Decimal(str(bars["crash_free"])) + Decimal("0.50"):
        feature_bar -= Decimal("2.00")
    assert Decimal(str(feature)) >= feature_bar
    assert Decimal(str(crash_free)) >= Decimal(str(bars["crash_free"]))
    assert Decimal(str(content)) >= content_bar
    assert blockers <= bars["blockers"]

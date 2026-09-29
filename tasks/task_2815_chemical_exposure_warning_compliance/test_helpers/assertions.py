"""Domain assertion helpers.

Two things matter here.  First, instant comparison: the API is free to render a
timestamp with or without its three fractional digits from one field to the
next, so every comparison against a literal instant goes through
:func:`assert_instant` which compares the parsed moments rather than the strings.
Second, numeric comparison: the PRD pins a decimal width for every derived
number, so the helpers below compare with a tolerance one order of magnitude
finer than that width instead of demanding exact float equality.
"""

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import Row

_MILLIS_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ─── Instants ─────────────────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant with or without fractional seconds."""
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"Expected a UTC instant ending in Z, got {value!r}"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000000")[:6]
        body = f"{head}.{frac}"
        parsed = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S.%f")
    else:
        parsed = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
    return parsed.replace(tzinfo=timezone.utc)


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Assert two instants name the same moment, ignoring rendering width."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instants_equal(actual: Any, other: Any, label: str = "timestamp") -> None:
    """Assert two instants read from the API name the same moment."""
    assert actual is not None and other is not None, (
        f"{label}: cannot compare {actual!r} with {other!r}"
    )
    assert parse_instant(actual) == parse_instant(other), (
        f"{label}: {actual} and {other} are different moments"
    )


def assert_millis_timestamp(value: Any, label: str = "timestamp") -> None:
    """Assert an instant is rendered with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _MILLIS_INSTANT_RE.match(value), (
        f"{label} must be an ISO 8601 UTC instant with exactly three "
        f"fractional digits, got {value!r}"
    )


def assert_iso_timestamp(value: Any, label: str = "timestamp") -> None:
    """Assert an instant is a well-formed ISO 8601 UTC timestamp."""
    assert is_iso8601_timestamp(value), (
        f"{label} is not an ISO 8601 UTC timestamp: {value!r}"
    )


def instant_plus_seconds(value: str, seconds: int) -> str:
    """Render the instant ``seconds`` after ``value`` with millisecond width."""
    from datetime import timedelta

    moment = parse_instant(value) + timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def instant_plus_days(value: str, days: int) -> str:
    """Render the instant ``days`` after ``value``."""
    return instant_plus_seconds(value, days * 86400)


# ─── Structural shape ─────────────────────────────────────────────────────────

def assert_common_fields(row: Row, expected_version: Optional[int] = None) -> None:
    """Assert the five fields every stored entity carries."""
    assert is_valid_uuid(row.get("id")), (
        f"id must be a bare UUID with no prefix, got {row.get('id')!r}"
    )
    assert_iso_timestamp(row.get("created_at"), "created_at")
    assert_iso_timestamp(row.get("updated_at"), "updated_at")
    assert isinstance(row.get("version"), int), (
        f"version must be an integer, got {row.get('version')!r}"
    )
    assert row["version"] >= 1, f"version starts at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_created_row(row: Row) -> None:
    """A freshly created row is at version 1 with equal creation stamps."""
    assert_common_fields(row, expected_version=1)
    assert_instants_equal(row["created_at"], row["updated_at"], "created_at/updated_at")


def assert_fields_null(row: Row, field_names: Iterable[str]) -> None:
    for name in field_names:
        assert name in row, f"Expected field {name!r} to be present"
        assert row[name] is None, f"Expected {name} to be null, got {row[name]!r}"


# ─── Numbers ──────────────────────────────────────────────────────────────────

def assert_close(actual: Any, expected: float, decimals: int, label: str) -> None:
    """Compare a rounded decimal against its pinned expectation."""
    assert actual is not None, f"{label} is null, expected {expected}"
    tolerance = 0.1 ** (decimals + 1)
    assert actual == pytest.approx(expected, abs=tolerance), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_concentration(actual: Any, expected: float, label: str = "concentration") -> None:
    """Concentrations carry four decimal places."""
    assert_close(actual, expected, 4, label)


def assert_exposure(actual: Any, expected: float, label: str = "daily_exposure_ug") -> None:
    """Daily exposure and chemical load carry three decimal places."""
    assert_close(actual, expected, 3, label)


def assert_load(actual: Any, expected: float, label: str = "total_listed_chemical_load_ug") -> None:
    assert_close(actual, expected, 3, label)


def assert_margin(actual: Any, expected: float, label: str = "margin_ratio") -> None:
    """Margin ratios and mitigation factors carry four decimal places."""
    assert_close(actual, expected, 4, label)


def assert_cents(actual: Any, expected: int, label: str = "amount_cents") -> None:
    """Money is an integer number of cents; no fractional cent may appear."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_decimal_width(actual: Any, decimals: int, label: str) -> None:
    """Assert a number carries no more precision than the PRD allows."""
    assert actual is not None, f"{label} is null"
    assert round(float(actual), decimals) == pytest.approx(float(actual), abs=1e-12), (
        f"{label} carries more than {decimals} decimal places: {actual}"
    )


# ─── Domain rows ──────────────────────────────────────────────────────────────

def assert_posture(product: Row, expected: str) -> None:
    assert product.get("compliance_posture") == expected, (
        f"Expected compliance_posture {expected}, got "
        f"{product.get('compliance_posture')!r}"
    )


def assert_lifecycle(product: Row, expected: str) -> None:
    assert product.get("lifecycle_state") == expected, (
        f"Expected lifecycle_state {expected}, got "
        f"{product.get('lifecycle_state')!r}"
    )


def assert_status(row: Row, expected: str, label: str = "status") -> None:
    assert row.get("status") == expected, (
        f"Expected {label} {expected}, got {row.get('status')!r}"
    )


def assert_assessment_verdict(
    assessment: Row,
    daily_exposure_ug: float,
    margin_ratio: Optional[float],
    result: str,
    contribution_count: int,
) -> None:
    """Assert all four computed numbers of an exposure assessment at once."""
    assert_exposure(assessment.get("daily_exposure_ug"), daily_exposure_ug)
    if margin_ratio is None:
        assert assessment.get("margin_ratio") is None, (
            f"Expected a null margin_ratio, got {assessment.get('margin_ratio')!r}"
        )
    else:
        assert_margin(assessment.get("margin_ratio"), margin_ratio)
    assert assessment.get("result") == result, (
        f"Expected result {result}, got {assessment.get('result')!r}"
    )
    assert assessment.get("contribution_count") == contribution_count, (
        f"Expected contribution_count {contribution_count}, got "
        f"{assessment.get('contribution_count')!r}"
    )


def assert_money_waterfall(
    settlement: Row,
    violation_days: int,
    base_penalty_cents: int,
    mitigation_factor: float,
    adjusted_penalty_cents: int,
    fee_cap_cents: int,
    allowed_fees_cents: int,
    state_share_cents: int,
    noticing_party_share_cents: int,
    total_settlement_cents: int,
) -> None:
    """Assert every stage of the pinned penalty/cap/fees waterfall."""
    assert settlement.get("violation_days") == violation_days, (
        f"Expected violation_days {violation_days}, got "
        f"{settlement.get('violation_days')!r}"
    )
    assert_cents(settlement.get("base_penalty_cents"), base_penalty_cents,
                 "base_penalty_cents")
    assert_margin(settlement.get("mitigation_factor"), mitigation_factor,
                  "mitigation_factor")
    assert_cents(settlement.get("adjusted_penalty_cents"), adjusted_penalty_cents,
                 "adjusted_penalty_cents")
    assert_cents(settlement.get("fee_cap_cents"), fee_cap_cents, "fee_cap_cents")
    assert_cents(settlement.get("allowed_fees_cents"), allowed_fees_cents,
                 "allowed_fees_cents")
    assert_cents(settlement.get("state_share_cents"), state_share_cents,
                 "state_share_cents")
    assert_cents(settlement.get("noticing_party_share_cents"),
                 noticing_party_share_cents, "noticing_party_share_cents")
    assert_cents(settlement.get("total_settlement_cents"), total_settlement_cents,
                 "total_settlement_cents")


def assert_shares_reconcile(settlement: Row) -> None:
    """The two shares always partition the adjusted penalty exactly."""
    assert (
        settlement["state_share_cents"] + settlement["noticing_party_share_cents"]
        == settlement["adjusted_penalty_cents"]
    ), (
        "state_share_cents + noticing_party_share_cents must equal "
        f"adjusted_penalty_cents: {settlement['state_share_cents']} + "
        f"{settlement['noticing_party_share_cents']} != "
        f"{settlement['adjusted_penalty_cents']}"
    )


def assert_warning_content(
    determination: Row,
    warning_type: str,
    symbol_required: bool,
    named_chemicals: Sequence[str],
    website_url: Optional[str],
    warning_text: Optional[str],
    required_channels: Sequence[str],
) -> None:
    """Assert the seven content fields a determination derives."""
    assert determination.get("warning_type") == warning_type, (
        f"Expected warning_type {warning_type}, got "
        f"{determination.get('warning_type')!r}"
    )
    assert determination.get("symbol_required") is symbol_required, (
        f"Expected symbol_required {symbol_required}, got "
        f"{determination.get('symbol_required')!r}"
    )
    assert determination.get("named_chemicals") == list(named_chemicals), (
        f"Expected named_chemicals {list(named_chemicals)}, got "
        f"{determination.get('named_chemicals')!r}"
    )
    assert determination.get("website_url") == website_url, (
        f"Expected website_url {website_url!r}, got "
        f"{determination.get('website_url')!r}"
    )
    assert determination.get("warning_text") == warning_text, (
        f"warning_text must match byte for byte.\n"
        f"  expected: {warning_text!r}\n"
        f"  actual:   {determination.get('warning_text')!r}"
    )
    assert determination.get("required_channels") == list(required_channels), (
        f"Expected required_channels {list(required_channels)} in the pinned "
        f"order, got {determination.get('required_channels')!r}"
    )


def assert_defense_components(
    summary: Row,
    warning_evidence: float,
    assessment_evidence: float,
    warranty_evidence: float,
    recordkeeping_evidence: float,
) -> None:
    assert_close(summary.get("warning_evidence"), warning_evidence, 2,
                 "warning_evidence")
    assert_close(summary.get("assessment_evidence"), assessment_evidence, 2,
                 "assessment_evidence")
    assert_close(summary.get("warranty_evidence"), warranty_evidence, 2,
                 "warranty_evidence")
    assert_close(summary.get("recordkeeping_evidence"), recordkeeping_evidence, 2,
                 "recordkeeping_evidence")


def assert_defense_counts(
    summary: Row,
    required_channel_count: int,
    covered_channel_count: int,
    verified_channel_count: int,
    final_assessment_count: int,
    verified_material_count: int,
    active_component_count: int,
) -> None:
    expectations = {
        "required_channel_count": required_channel_count,
        "covered_channel_count": covered_channel_count,
        "verified_channel_count": verified_channel_count,
        "final_assessment_count": final_assessment_count,
        "verified_material_count": verified_material_count,
        "active_component_count": active_component_count,
    }
    for name, expected in expectations.items():
        assert summary.get(name) == expected, (
            f"Expected {name} {expected}, got {summary.get(name)!r}"
        )

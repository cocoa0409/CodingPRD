"""
Domain assertion helpers.

Two families live here. Shape assertions check that a returned resource carries
the fields the contract declares, with the right kinds of value. Invariant
assertions re-check the two conserved identities — the service line's unit pool
and the family's ledger — from whatever representation the caller has in hand.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CASE_WEIGHT_DECIMALS,
    FPL_PERCENT_DECIMALS,
    UTILIZATION_RATIO_DECIMALS,
)

# ─── Audit-field shape ────────────────────────────────────────────────

MUTABLE_ENTITIES = (
    "Child",
    "Referral",
    "ServiceCoordinator",
    "Assessment",
    "IFSP",
    "IFSPService",
    "Provider",
    "ProviderAuthorization",
    "ServiceVisit",
    "CostShare",
    "TransitionPlan",
)


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the four audit fields carried by every mutable resource."""
    assert is_valid_uuid(row.get("id", "")), f"id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at", "")), (
        f"created_at is not an ISO 8601 UTC timestamp: {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at", "")), (
        f"updated_at is not an ISO 8601 UTC timestamp: {row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int), (
        f"version must be an integer, got {row.get('version')!r}"
    )
    assert row["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_append_only_row(row: Dict[str, Any]) -> None:
    """Assert an append-only register row: ``id`` and ``created_at`` only."""
    assert is_valid_uuid(row.get("id", "")), f"id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at", "")), (
        f"created_at is not an ISO 8601 UTC timestamp: {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, (
        "An append-only register row must have no updated_at field"
    )
    assert "version" not in row, (
        "An append-only register row must have no version field"
    )


def assert_three_fractional_digits(timestamp: str) -> None:
    """Assert a server-minted timestamp carries exactly three fractional digits."""
    assert isinstance(timestamp, str), f"Not a timestamp: {timestamp!r}"
    assert timestamp.endswith("Z"), f"Timestamp must be UTC with a Z suffix: {timestamp!r}"
    assert "." in timestamp, f"Timestamp must carry fractional digits: {timestamp!r}"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"Timestamp must carry exactly three fractional digits: {timestamp!r}"
    )


# ─── Instant comparison ───────────────────────────────────────────────

def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Reduce an ISO 8601 UTC instant to a comparable canonical form.

    Three fractional digits are tolerated on input, so a server that echoes
    ``2026-03-24T14:00:00.000Z`` for a submitted ``2026-03-24T14:00:00Z`` is
    reporting the same instant. Comparisons of instants must go through here.
    """
    if value is None:
        return None
    assert isinstance(value, str), f"Not an instant: {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, fraction = text.split(".", 1)
        fraction = (fraction + "000")[:3]
        if fraction == "000":
            text = head
        else:
            text = f"{head}.{fraction}"
    return text + "Z"


def assert_instant_equals(actual: Optional[str], expected: Optional[str]) -> None:
    """Assert two UTC instants denote the same moment regardless of precision."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected instant {expected!r}, got {actual!r}"
    )


# ─── Rounding precision ───────────────────────────────────────────────

def assert_decimal_places(value: Any, places: int, field: str) -> None:
    """Assert a stored ratio carries at most the declared number of decimals."""
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    assert round(float(value), places) == pytest.approx(float(value)), (
        f"{field} must be stored to {places} decimal places, got {value!r}"
    )


def assert_fpl_percent(value: Any, expected: float) -> None:
    assert_decimal_places(value, FPL_PERCENT_DECIMALS, "fpl_percent")
    assert float(value) == pytest.approx(expected, abs=0.01), (
        f"Expected fpl_percent {expected}, got {value}"
    )


def assert_case_weight(value: Any, expected: float) -> None:
    assert_decimal_places(value, CASE_WEIGHT_DECIMALS, "case_weight_points")
    assert float(value) == pytest.approx(expected, abs=0.01), (
        f"Expected case_weight_points {expected}, got {value}"
    )


def assert_utilization_ratio(value: Any, expected: float) -> None:
    assert_decimal_places(value, UTILIZATION_RATIO_DECIMALS, "utilization_ratio")
    assert float(value) == pytest.approx(expected, abs=0.00005), (
        f"Expected utilization_ratio {expected}, got {value}"
    )


def assert_cents(value: Any, expected: int, field: str = "amount") -> None:
    """Assert a monetary field is an integer number of cents with an exact value."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"Expected {field} {expected}, got {value}"


# ─── Conserved quantities ─────────────────────────────────────────────

def assert_unit_pool_invariant(service_line: Dict[str, Any]) -> None:
    """units_committed + units_pool_remaining == planned_units_total."""
    committed = service_line["units_committed"]
    remaining = service_line["units_pool_remaining"]
    planned = service_line["planned_units_total"]
    assert committed + remaining == planned, (
        f"Unit pool broken: {committed} committed + {remaining} remaining "
        f"!= {planned} planned"
    )
    assert 0 <= remaining <= planned, (
        f"units_pool_remaining {remaining} must lie between 0 and {planned}"
    )


def assert_unit_pool(
    service_line: Dict[str, Any],
    units_committed: int,
    units_pool_remaining: int,
    planned_units_total: Optional[int] = None,
) -> None:
    """Assert both halves of the pool and then the identity that binds them."""
    assert service_line["units_committed"] == units_committed, (
        f"Expected units_committed {units_committed}, "
        f"got {service_line['units_committed']}"
    )
    assert service_line["units_pool_remaining"] == units_pool_remaining, (
        f"Expected units_pool_remaining {units_pool_remaining}, "
        f"got {service_line['units_pool_remaining']}"
    )
    if planned_units_total is not None:
        assert service_line["planned_units_total"] == planned_units_total
    assert_unit_pool_invariant(service_line)


def assert_ledger_invariant(cost_share: Dict[str, Any]) -> None:
    """total_assessed_cents == family_balance_cents + family_waived_cents."""
    assessed = cost_share["total_assessed_cents"]
    balance = cost_share["family_balance_cents"]
    waived = cost_share["family_waived_cents"]
    assert assessed == balance + waived, (
        f"Family ledger broken: {assessed} assessed != {balance} balance "
        f"+ {waived} waived"
    )
    assert balance >= 0, f"family_balance_cents must not be negative, got {balance}"
    assert waived >= 0, f"family_waived_cents must not be negative, got {waived}"


def assert_ledger(
    cost_share: Dict[str, Any],
    total_assessed_cents: int,
    family_balance_cents: int,
    family_waived_cents: int,
) -> None:
    """Assert all three ledger components and then the identity."""
    assert_cents(
        cost_share["total_assessed_cents"], total_assessed_cents, "total_assessed_cents"
    )
    assert_cents(
        cost_share["family_balance_cents"], family_balance_cents, "family_balance_cents"
    )
    assert_cents(
        cost_share["family_waived_cents"], family_waived_cents, "family_waived_cents"
    )
    assert_ledger_invariant(cost_share)


def assert_authorization_units(
    authorization: Dict[str, Any],
    units_consumed: Optional[int] = None,
    units_released: Optional[int] = None,
    units_remaining: Optional[int] = None,
) -> None:
    """
    Assert the authorization counters, including the arithmetic that binds them:
    units_remaining is authorized_units minus consumed minus released.
    """
    if units_consumed is not None:
        assert authorization["units_consumed"] == units_consumed, (
            f"Expected units_consumed {units_consumed}, "
            f"got {authorization['units_consumed']}"
        )
    if units_released is not None:
        assert authorization["units_released"] == units_released, (
            f"Expected units_released {units_released}, "
            f"got {authorization['units_released']}"
        )
    if units_remaining is not None:
        assert authorization["units_remaining"] == units_remaining, (
            f"Expected units_remaining {units_remaining}, "
            f"got {authorization['units_remaining']}"
        )
    assert (
        authorization["units_remaining"]
        == authorization["authorized_units"]
        - authorization["units_consumed"]
        - authorization["units_released"]
    ), (
        "units_remaining must equal authorized_units - units_consumed "
        f"- units_released, got {authorization}"
    )


# ─── Caseload standard ────────────────────────────────────────────────

def assert_caseload_summary(
    summary: Dict[str, Any],
    coordinator_id: Optional[str] = None,
    active_case_count: Optional[int] = None,
    weighted_caseload_points: Optional[float] = None,
    max_weighted_caseload_points: Optional[float] = None,
    utilization_ratio: Optional[float] = None,
    caseload_posture: Optional[str] = None,
    headroom_points: Optional[float] = None,
) -> None:
    """Assert the computed caseload read field by field."""
    if coordinator_id is not None:
        assert summary["coordinator_id"] == coordinator_id
    if active_case_count is not None:
        assert summary["active_case_count"] == active_case_count, (
            f"Expected active_case_count {active_case_count}, "
            f"got {summary['active_case_count']}"
        )
    if weighted_caseload_points is not None:
        assert_decimal_places(
            summary["weighted_caseload_points"],
            CASE_WEIGHT_DECIMALS,
            "weighted_caseload_points",
        )
        assert float(summary["weighted_caseload_points"]) == pytest.approx(
            weighted_caseload_points, abs=0.01
        ), (
            f"Expected weighted_caseload_points {weighted_caseload_points}, "
            f"got {summary['weighted_caseload_points']}"
        )
    if max_weighted_caseload_points is not None:
        assert float(summary["max_weighted_caseload_points"]) == pytest.approx(
            max_weighted_caseload_points, abs=0.01
        )
    if utilization_ratio is not None:
        assert_utilization_ratio(summary["utilization_ratio"], utilization_ratio)
    if caseload_posture is not None:
        assert summary["caseload_posture"] == caseload_posture, (
            f"Expected caseload_posture {caseload_posture!r}, "
            f"got {summary['caseload_posture']!r}"
        )
    if headroom_points is not None:
        assert float(summary["headroom_points"]) == pytest.approx(
            headroom_points, abs=0.01
        ), (
            f"Expected headroom_points {headroom_points}, "
            f"got {summary['headroom_points']}"
        )


# ─── Timeline ─────────────────────────────────────────────────────────

def assert_timeline(
    compliance: Dict[str, Any],
    statutory_deadline_date: Optional[str] = None,
    stop_date: Optional[str] = None,
    gross_elapsed_days: Optional[int] = None,
    excluded_delay_days: Optional[int] = None,
    net_elapsed_days: Optional[int] = None,
    initial_timeline_status: Optional[str] = None,
    monthly_contact_status: Optional[str] = None,
    last_qualifying_contact_date: Any = "__unchecked__",
) -> None:
    """Assert the computed statutory picture, then the net-of-delay arithmetic."""
    if statutory_deadline_date is not None:
        assert compliance["statutory_deadline_date"] == statutory_deadline_date
    if stop_date is not None:
        assert compliance["stop_date"] == stop_date, (
            f"Expected stop_date {stop_date}, got {compliance['stop_date']}"
        )
    if gross_elapsed_days is not None:
        assert compliance["gross_elapsed_days"] == gross_elapsed_days, (
            f"Expected gross_elapsed_days {gross_elapsed_days}, "
            f"got {compliance['gross_elapsed_days']}"
        )
    if excluded_delay_days is not None:
        assert compliance["excluded_delay_days"] == excluded_delay_days, (
            f"Expected excluded_delay_days {excluded_delay_days}, "
            f"got {compliance['excluded_delay_days']}"
        )
    if net_elapsed_days is not None:
        assert compliance["net_elapsed_days"] == net_elapsed_days, (
            f"Expected net_elapsed_days {net_elapsed_days}, "
            f"got {compliance['net_elapsed_days']}"
        )
    if initial_timeline_status is not None:
        assert compliance["initial_timeline_status"] == initial_timeline_status, (
            f"Expected initial_timeline_status {initial_timeline_status!r}, "
            f"got {compliance['initial_timeline_status']!r}"
        )
    if monthly_contact_status is not None:
        assert compliance["monthly_contact_status"] == monthly_contact_status
    if last_qualifying_contact_date != "__unchecked__":
        assert compliance["last_qualifying_contact_date"] == last_qualifying_contact_date
    assert compliance["net_elapsed_days"] == max(
        0, compliance["gross_elapsed_days"] - compliance["excluded_delay_days"]
    ), (
        "net_elapsed_days must be the gross count minus the excluded total, "
        f"floored at zero: {compliance}"
    )

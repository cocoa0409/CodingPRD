"""Domain assertion helpers.

Every helper takes an already-unwrapped ``data`` payload — the validators of the
runner return that payload directly, so nothing here indexes ``["data"]`` again.
"""

from decimal import Decimal
from typing import Any, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    ADMIN_FEE_RATE_DECIMALS,
    DIVERSION_RATE_DECIMALS,
    WEIGHTED_AVERAGE_SECONDS_DECIMALS,
)
from .types import JsonDict, JsonList


# ── Envelope-level common fields (PRD §2.4) ───────────────────────────────────
def assert_common_fields(entity: JsonDict, versioned: bool = True) -> None:
    """Assert the identity/timestamp fields every resource carries.

    ``versioned=False`` is for the two immutable resources — a show-up curve and
    a wait-time observation — which expose only ``id`` and ``created_at`` and on
    which no ``updated_at`` or ``version`` field may appear at all.
    """
    assert is_valid_uuid(entity.get("id", "")), f"id is not a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"created_at is not an ISO 8601 instant: {entity.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(entity.get("updated_at", "")), (
            f"updated_at is not an ISO 8601 instant: {entity.get('updated_at')!r}"
        )
        assert isinstance(entity.get("version"), int), "version must be an integer"
        assert entity["version"] >= 1, "version starts at 1"
    else:
        assert "updated_at" not in entity, "an immutable resource has no updated_at"
        assert "version" not in entity, "an immutable resource has no version"


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two ISO 8601 instants on their canonical form."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_nulls(entity: JsonDict, fields: Sequence[str]) -> None:
    for field in fields:
        assert field in entity, f"expected field {field} to be present"
        assert entity[field] is None, f"expected {field} to be null, got {entity[field]!r}"


# ── Fixed-precision decimal strings (PRD §2.6) ────────────────────────────────
def assert_decimal_string(value: Any, places: int, label: str = "value") -> None:
    """A fixed-precision ratio is transported as a string with exactly N decimals."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert "." in value, f"{label} must carry a decimal point: {value!r}"
    assert len(value.split(".", 1)[1]) == places, (
        f"{label} must carry exactly {places} decimals: {value!r}"
    )
    Decimal(value)


def assert_admin_fee_rate(value: Any, expected: str) -> None:
    assert_decimal_string(value, ADMIN_FEE_RATE_DECIMALS, "admin_fee_rate")
    assert value == expected, f"admin_fee_rate: expected {expected!r}, got {value!r}"


def assert_weighted_average_seconds(value: Any, expected: str) -> None:
    assert_decimal_string(
        value, WEIGHTED_AVERAGE_SECONDS_DECIMALS, "weighted_average_seconds"
    )
    assert value == expected, (
        f"weighted_average_seconds: expected {expected!r}, got {value!r}"
    )


def assert_diversion_rate(value: Any, expected: str) -> None:
    assert_decimal_string(value, DIVERSION_RATE_DECIMALS, "diversion_rate")
    assert value == expected, f"diversion_rate: expected {expected!r}, got {value!r}"


def assert_cents(value: Any, expected: int, label: str = "amount") -> None:
    """Money is an integer count of cents, never a float and never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"{label}: expected {expected}, got {value}"


# ── Checkpoint (PRD §3.1, §2.9, §2.10) ────────────────────────────────────────
def assert_new_checkpoint_defaults(checkpoint: JsonDict, total_lane_positions: int) -> None:
    """A freshly created checkpoint starts NORMAL with every counter at zero."""
    assert checkpoint["posture"] == "NORMAL"
    assert checkpoint["available_lane_positions"] == total_lane_positions
    for field in (
        "open_lane_count",
        "secondary_slots_in_use",
        "consecutive_breach_count_standard",
        "consecutive_breach_count_expedited",
        "diverted_pax_total",
        "leo_referral_count",
        "denied_entry_count",
        "cleared_referral_count",
    ):
        assert checkpoint[field] == 0, f"{field} must start at 0, got {checkpoint[field]!r}"


def assert_position_ledger(
    checkpoint: JsonDict, open_lanes_required_counts: Sequence[int]
) -> None:
    """available_lane_positions == total_lane_positions - Σ required over OPEN lanes."""
    consumed = sum(open_lanes_required_counts)
    expected = checkpoint["total_lane_positions"] - consumed
    assert checkpoint["available_lane_positions"] == expected, (
        f"available_lane_positions should be {expected} "
        f"({checkpoint['total_lane_positions']} - {consumed}), "
        f"got {checkpoint['available_lane_positions']}"
    )
    assert checkpoint["open_lane_count"] == len(open_lanes_required_counts), (
        f"open_lane_count should be {len(open_lanes_required_counts)}, "
        f"got {checkpoint['open_lane_count']}"
    )


def assert_posture(checkpoint: JsonDict, expected: str) -> None:
    assert checkpoint["posture"] == expected, (
        f"posture: expected {expected}, got {checkpoint['posture']}"
    )


# ── Lane (PRD §3.1, §3.6) ─────────────────────────────────────────────────────
def assert_lane_snapshot(
    lane: JsonDict,
    lane_state: str,
    equipment_state: str,
    paused_reason_code: Any = "__unchecked__",
) -> None:
    assert lane["lane_state"] == lane_state, (
        f"lane_state: expected {lane_state}, got {lane['lane_state']}"
    )
    assert lane["equipment_state"] == equipment_state, (
        f"equipment_state: expected {equipment_state}, got {lane['equipment_state']}"
    )
    if paused_reason_code != "__unchecked__":
        assert lane["paused_reason_code"] == paused_reason_code, (
            f"paused_reason_code: expected {paused_reason_code!r}, "
            f"got {lane['paused_reason_code']!r}"
        )


# ── Officer (PRD §2.9, §3.7) ──────────────────────────────────────────────────
def assert_officer_ledger(
    officer: JsonDict,
    committed_duty_minutes: int,
    approved_detail_minutes: Optional[int] = None,
    duty_status: Optional[str] = None,
) -> None:
    assert officer["committed_duty_minutes"] == committed_duty_minutes, (
        f"committed_duty_minutes: expected {committed_duty_minutes}, "
        f"got {officer['committed_duty_minutes']}"
    )
    if approved_detail_minutes is not None:
        assert officer["approved_detail_minutes"] == approved_detail_minutes, (
            f"approved_detail_minutes: expected {approved_detail_minutes}, "
            f"got {officer['approved_detail_minutes']}"
        )
    if duty_status is not None:
        assert officer["duty_status"] == duty_status, (
            f"duty_status: expected {duty_status}, got {officer['duty_status']}"
        )


def assert_duty_ledger(
    ledger: JsonDict,
    variant: str,
    worked_minutes: int,
    total_minutes: int,
    regular_minutes: int,
    overtime_minutes: int,
    cap_headroom_minutes: int,
    approved_detail_minutes: int = 0,
) -> None:
    assert ledger["variant"] == variant
    assert ledger["worked_minutes"] == worked_minutes, (
        f"worked_minutes: expected {worked_minutes}, got {ledger['worked_minutes']}"
    )
    assert ledger["approved_detail_minutes"] == approved_detail_minutes
    assert ledger["total_minutes"] == total_minutes
    assert ledger["regular_minutes"] == regular_minutes
    assert ledger["overtime_minutes"] == overtime_minutes
    assert ledger["cap_headroom_minutes"] == cap_headroom_minutes


# ── Staffing plan cost (PRD §3.3) ─────────────────────────────────────────────
def assert_plan_cost(
    priced: JsonDict,
    subtotal_cents: int,
    admin_fee_rate: str,
    admin_fee_cents: int,
    total_cost_cents: int,
    planned_regular_minutes: Optional[int] = None,
    planned_overtime_minutes: Optional[int] = None,
    base_cost_cents: Optional[int] = None,
    overtime_cost_cents: Optional[int] = None,
    detail_cost_cents: Any = "__unchecked__",
) -> None:
    """Assert the eight-step cost result, fee tier keyed on the subtotal alone."""
    assert_cents(priced["subtotal_cents"], subtotal_cents, "subtotal_cents")
    assert_admin_fee_rate(priced["admin_fee_rate"], admin_fee_rate)
    assert_cents(priced["admin_fee_cents"], admin_fee_cents, "admin_fee_cents")
    assert_cents(priced["total_cost_cents"], total_cost_cents, "total_cost_cents")
    assert total_cost_cents == subtotal_cents + admin_fee_cents, (
        "total_cost_cents must be subtotal_cents plus admin_fee_cents"
    )
    if planned_regular_minutes is not None:
        assert priced["planned_regular_minutes"] == planned_regular_minutes
    if planned_overtime_minutes is not None:
        assert priced["planned_overtime_minutes"] == planned_overtime_minutes
    if base_cost_cents is not None:
        assert_cents(priced["base_cost_cents"], base_cost_cents, "base_cost_cents")
    if overtime_cost_cents is not None:
        assert_cents(
            priced["overtime_cost_cents"], overtime_cost_cents, "overtime_cost_cents"
        )
    if detail_cost_cents != "__unchecked__":
        if detail_cost_cents is None:
            assert priced["detail_cost_cents"] is None, (
                f"detail_cost_cents: expected null, got {priced['detail_cost_cents']!r}"
            )
        else:
            assert_cents(
                priced["detail_cost_cents"], detail_cost_cents, "detail_cost_cents"
            )


# ── Wait publication (PRD §3.8) ───────────────────────────────────────────────
def assert_publication(
    publication: JsonDict,
    published_wait_minutes: Optional[int],
    weighted_average_seconds: Optional[str],
    sample_count: int,
    threshold_minutes: Optional[int] = None,
    breached: Optional[bool] = None,
    window_start_utc: Optional[str] = None,
    window_end_utc: Optional[str] = None,
) -> None:
    assert publication["sample_count"] == sample_count, (
        f"sample_count: expected {sample_count}, got {publication['sample_count']}"
    )
    assert publication["published_wait_minutes"] == published_wait_minutes, (
        f"published_wait_minutes: expected {published_wait_minutes!r}, "
        f"got {publication['published_wait_minutes']!r}"
    )
    if weighted_average_seconds is None:
        assert publication["weighted_average_seconds"] is None, (
            f"weighted_average_seconds should be null, "
            f"got {publication['weighted_average_seconds']!r}"
        )
    else:
        assert_weighted_average_seconds(
            publication["weighted_average_seconds"], weighted_average_seconds
        )
    if threshold_minutes is not None:
        assert publication["threshold_minutes"] == threshold_minutes
    if breached is not None:
        assert publication["breached"] is breached, (
            f"breached: expected {breached}, got {publication['breached']!r}"
        )
    if window_start_utc is not None:
        assert_instant(publication["window_start_utc"], window_start_utc, "window_start_utc")
    if window_end_utc is not None:
        assert_instant(publication["window_end_utc"], window_end_utc, "window_end_utc")


# ── Forecast and lane requirement (PRD §3.2) ──────────────────────────────────
def assert_forecast(
    band: JsonDict,
    forecast_pax_count: int,
    forecast_variant: str,
    required_standard_lanes: Optional[int] = None,
    required_expedited_lanes: Optional[int] = None,
    unmet_standard_demand: Optional[int] = None,
    unmet_expedited_demand: Optional[int] = None,
    forecast_computed_at_utc: Optional[str] = None,
) -> None:
    assert band["forecast_pax_count"] == forecast_pax_count, (
        f"forecast_pax_count: expected {forecast_pax_count}, "
        f"got {band['forecast_pax_count']}"
    )
    assert band["forecast_variant"] == forecast_variant
    if required_standard_lanes is not None:
        assert band["required_standard_lanes"] == required_standard_lanes, (
            f"required_standard_lanes: expected {required_standard_lanes}, "
            f"got {band['required_standard_lanes']}"
        )
    if required_expedited_lanes is not None:
        assert band["required_expedited_lanes"] == required_expedited_lanes, (
            f"required_expedited_lanes: expected {required_expedited_lanes}, "
            f"got {band['required_expedited_lanes']}"
        )
    if unmet_standard_demand is not None:
        assert band["unmet_standard_demand"] == unmet_standard_demand
    if unmet_expedited_demand is not None:
        assert band["unmet_expedited_demand"] == unmet_expedited_demand
    if forecast_computed_at_utc is not None:
        assert_instant(
            band["forecast_computed_at_utc"],
            forecast_computed_at_utc,
            "forecast_computed_at_utc",
        )


# ── Collections (PRD §2.3, §2.5) ──────────────────────────────────────────────
def assert_list_meta(
    meta: JsonDict,
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']!r}"
        )


def assert_ids_in_order(rows: JsonList, expected_ids: Sequence[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"row order: expected {list(expected_ids)}, got {actual}"
    )


def assert_field_sequence(rows: JsonList, field: str, expected: Sequence[Any]) -> None:
    actual = [row[field] for row in rows]
    assert actual == list(expected), (
        f"{field} sequence: expected {list(expected)}, got {actual}"
    )


def assert_no_pagination_fields(meta: JsonDict) -> None:
    """Single-resource reads carry no pagination fields (PRD §2.3)."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single-resource meta must not carry {field}"


# ── Referrals and tickets (PRD §3.8, §3.9) ────────────────────────────────────
def assert_secondary_slots(checkpoint: JsonDict, in_use: int) -> None:
    assert checkpoint["secondary_slots_in_use"] == in_use, (
        f"secondary_slots_in_use: expected {in_use}, "
        f"got {checkpoint['secondary_slots_in_use']}"
    )


def assert_referral_counters(
    checkpoint: JsonDict,
    cleared_referral_count: Optional[int] = None,
    leo_referral_count: Optional[int] = None,
    denied_entry_count: Optional[int] = None,
    diverted_pax_total: Optional[int] = None,
) -> None:
    if cleared_referral_count is not None:
        assert checkpoint["cleared_referral_count"] == cleared_referral_count
    if leo_referral_count is not None:
        assert checkpoint["leo_referral_count"] == leo_referral_count
    if denied_entry_count is not None:
        assert checkpoint["denied_entry_count"] == denied_entry_count
    if diverted_pax_total is not None:
        assert checkpoint["diverted_pax_total"] == diverted_pax_total, (
            f"diverted_pax_total: expected {diverted_pax_total}, "
            f"got {checkpoint['diverted_pax_total']}"
        )


def assert_breach_counters(
    checkpoint: JsonDict,
    standard: Optional[int] = None,
    expedited: Optional[int] = None,
) -> None:
    if standard is not None:
        assert checkpoint["consecutive_breach_count_standard"] == standard, (
            f"consecutive_breach_count_standard: expected {standard}, "
            f"got {checkpoint['consecutive_breach_count_standard']}"
        )
    if expedited is not None:
        assert checkpoint["consecutive_breach_count_expedited"] == expedited, (
            f"consecutive_breach_count_expedited: expected {expedited}, "
            f"got {checkpoint['consecutive_breach_count_expedited']}"
        )

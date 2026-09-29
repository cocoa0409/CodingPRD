"""Entity assertions and domain invariant checkers for the Store Operations API."""

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    FEE_TIER_MID_MAX_MINUTES,
    FEE_TIER_SURCHARGE_CENTS,
    MICRO_PER_MILE,
    WAIVER_HALF_THRESHOLD_CENTS,
    WAIVER_FULL_THRESHOLD_CENTS,
)

# --- Generic shape helpers ----------------------------------------------------

MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")


def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource except the motor-vehicle-record pull carries id, created_at,
    updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_append_only_common_fields(data: Dict[str, Any]) -> None:
    """The motor-vehicle-record pull is append-only: id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an append-only pull carries no updated_at"
    assert "version" not in data, "an append-only pull carries no version"


def assert_iso_millis(value: str, field: str = "timestamp") -> None:
    """Instants are ISO 8601 UTC with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{field} must be a string, got {type(value)}"
    assert is_iso8601_timestamp(value), f"{field} must be an ISO 8601 UTC instant, got {value!r}"
    assert value.endswith("Z"), f"{field} must be expressed in UTC and end with Z, got {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"{field} must carry exactly three fractional-second digits, got {value!r}"
    )


def assert_cents(value: Any, field: str) -> None:
    """Money is an integer count of cents — never a string and never a float."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer count of cents, got {value!r} ({type(value).__name__})"
    )


def assert_two_decimal_miles(value: Any, field: str) -> None:
    """Mileage carries exactly two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must carry at most two decimal places, got {value!r}"
    )


# --- Pure re-implementations of the published formulas ------------------------
# These exist so a test can state an expected value in terms of the published
# rule rather than a magic number, and so boundary tests can be written in one
# place. They never replace a literal the test already knows.


def round_half_up(value: float) -> int:
    """Round a fractional cent amount half up to a whole number of cents: a value
    ending in exactly one half rounds away from zero."""
    return int(math.floor(float(value) + 0.5))


def round_half_up_2dp(value: float) -> float:
    """Round half up to two decimal places, as mileage requires."""
    return math.floor(float(value) * 100 + 0.5) / 100.0


def expected_grid_miles(
    addr_lat: int, addr_lon: int, store_lat: int, store_lon: int
) -> float:
    """Grid mileage: the two absolute coordinate deltas added, then divided by
    15000 micro-degrees per mile and rounded half up to two decimal places."""
    total = abs(addr_lat - store_lat) + abs(addr_lon - store_lon)
    return round_half_up_2dp(total / MICRO_PER_MILE)


def expected_drive_minutes(
    grid_miles: float,
    base_drive_minutes: int,
    minutes_per_mile: int,
    peak: bool = False,
    crosses_barrier: bool = False,
    peak_surcharge_minutes: int = 0,
    barrier_surcharge_minutes: int = 0,
) -> int:
    """Base allowance, plus the mileage term rounded UP to the next whole minute,
    plus the GREATER of the peak and barrier components."""
    mileage_term = math.ceil(round(grid_miles * minutes_per_mile, 6))
    peak_component = peak_surcharge_minutes if peak else 0
    barrier_component = barrier_surcharge_minutes if crosses_barrier else 0
    return base_drive_minutes + mileage_term + max(peak_component, barrier_component)


def expected_fee_tier(drive_time_estimate_minutes: int) -> str:
    """15 minutes or less is BASE, above 15 through 25 is MID, above 25 is FAR."""
    if drive_time_estimate_minutes <= 15:
        return "BASE"
    if drive_time_estimate_minutes <= FEE_TIER_MID_MAX_MINUTES:
        return "MID"
    return "FAR"


def expected_waiver_pct(food_subtotal_cents: int) -> int:
    """Picked from the food subtotal alone — the tip never counts."""
    if food_subtotal_cents >= WAIVER_FULL_THRESHOLD_CENTS:
        return 100
    if food_subtotal_cents >= WAIVER_HALF_THRESHOLD_CENTS:
        return 50
    return 0


def expected_order_pricing(
    drive_time_estimate_minutes: int,
    store_delivery_fee_cents: int,
    food_subtotal_cents: int,
    tip_cents: int,
) -> Dict[str, Any]:
    """The whole five-step pricing pipeline, in its pinned order: tier, surcharged
    base, waiver from the food subtotal, charged fee, total."""
    tier = expected_fee_tier(drive_time_estimate_minutes)
    base = store_delivery_fee_cents + FEE_TIER_SURCHARGE_CENTS[tier]
    waiver = expected_waiver_pct(food_subtotal_cents)
    fee = round_half_up(base * (100 - waiver) / 100)
    return {
        "fee_tier": tier,
        "base_delivery_fee_cents": base,
        "fee_waiver_pct": waiver,
        "delivery_fee_cents": fee,
        "total_charge_cents": food_subtotal_cents + fee + tip_cents,
    }


def expected_route_minutes(
    stop_miles: List[float], minutes_per_mile: int, handoff_minutes_per_stop: int
) -> int:
    """Outbound legs each rounded up individually, plus a flat handoff at each
    door, plus a homeward leg that repeats the last stop's outbound leg."""
    if not stop_miles:
        return 0
    outbound = sum(math.ceil(round(m * minutes_per_mile, 6)) for m in stop_miles)
    handoff = handoff_minutes_per_stop * len(stop_miles)
    homeward = math.ceil(round(stop_miles[-1] * minutes_per_mile, 6))
    return outbound + handoff + homeward


def expected_stop_reimbursement_cents(
    stop_miles: List[float],
    per_delivery_cents: int,
    tier1_cap_miles: float,
    tier1_per_mile_cents: int,
    tier2_per_mile_cents: int,
    min_reimbursement_per_stop_cents: int,
) -> List[int]:
    """The mileage waterfall, stop by stop in sequence order. The tier-1 allowance
    is consumed cumulatively across the whole route; each stop's raw subtotal is
    rounded half up, then floored to the per-stop minimum, and only then added to
    the running total."""
    cumulative = 0.0
    per_stop: List[int] = []
    for miles in stop_miles:
        remaining = max(tier1_cap_miles - cumulative, 0.0)
        tier1_miles = min(miles, remaining)
        tier2_miles = miles - tier1_miles
        raw_mileage = tier1_miles * tier1_per_mile_cents + tier2_miles * tier2_per_mile_cents
        raw_subtotal = raw_mileage + per_delivery_cents
        rounded = round_half_up(round(raw_subtotal, 6))
        per_stop.append(max(rounded, min_reimbursement_per_stop_cents))
        cumulative += miles
    return per_stop


def expected_route_reimbursement_cents(stop_miles: List[float], *schedule, **kwargs) -> int:
    """The whole-route figure: the per-stop amounts summed after each has been
    rounded and floored."""
    return sum(expected_stop_reimbursement_cents(stop_miles, *schedule, **kwargs))


def expected_reimbursement_from_model(
    stop_miles: List[float], cost_model: Dict[str, Any]
) -> int:
    """The whole-route figure read straight off a published reimbursement schedule."""
    return expected_route_reimbursement_cents(
        stop_miles,
        cost_model["per_delivery_cents"],
        cost_model["tier1_cap_miles"],
        cost_model["tier1_per_mile_cents"],
        cost_model["tier2_per_mile_cents"],
        cost_model["min_reimbursement_per_stop_cents"],
    )


def expected_stops_from_model(
    stop_miles: List[float], cost_model: Dict[str, Any]
) -> List[int]:
    """The per-stop amounts read straight off a published reimbursement schedule."""
    return expected_stop_reimbursement_cents(
        stop_miles,
        cost_model["per_delivery_cents"],
        cost_model["tier1_cap_miles"],
        cost_model["tier1_per_mile_cents"],
        cost_model["tier2_per_mile_cents"],
        cost_model["min_reimbursement_per_stop_cents"],
    )


# --- Per-resource assertions --------------------------------------------------

SERVICE_POSTURES = ("OPEN", "CARRYOUT_ONLY", "CLOSED")
ZONE_VERSION_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED")
ZONE_STATES = ("IN_ZONE", "EDGE", "OUT_OF_ZONE")
DISPUTE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "GRANTED", "DENIED", "WITHDRAWN")
QUALIFICATION_STATUSES = ("APPLICANT", "PENDING_CHECKS", "QUALIFIED", "SUSPENDED", "DISQUALIFIED")
VEHICLE_CLASSES = ("CAR", "SUV", "SCOOTER")
INSURANCE_STATUSES = ("NONE", "VERIFIED", "REJECTED")
MVR_RESULTS = ("CLEAR", "MINOR_VIOLATIONS", "FAILED")
CASH_POSTURES = ("CLEAR", "DROP_REQUIRED")
FULFILLMENT_STATUSES = (
    "PLACED", "ZONE_HELD", "ZONE_CLEARED", "IN_PRODUCTION", "READY", "ASSIGNED",
    "EN_ROUTE", "DELIVERED", "REMAKE_QUEUED", "CLOSED", "DECLINED_OUT_OF_AREA",
    "CARRYOUT_REDIRECTED",
)
SETTLEMENT_STATUSES = (
    "UNDISCLOSED", "DISCLOSED", "CHARGED", "ADJUSTED", "CLOSED_SETTLED", "VOIDED",
)
FEE_TIERS = ("BASE", "MID", "FAR")
DISPATCH_STATUSES = (
    "DRAFT", "STACKED", "LOCKED", "EN_ROUTE", "RETURNED", "SETTLED", "RECALLED", "CANCELLED",
)
STOP_STATUSES = ("PENDING", "DELIVERED", "RELEASED", "REMADE")
LINE_TYPES = ("PROVISIONAL_STOP", "ACTUAL_STOP", "CLAWBACK")
LINE_BASES = ("ESTIMATED", "ACTUAL", "NONE")
LINE_STATUSES = ("PROVISIONAL", "ACCRUED", "SUPERSEDED", "VOIDED")
COMPLAINT_STATUSES = ("OPEN", "REMEDY_PROPOSED", "REMEDY_ISSUED", "DISMISSED")
COMPLAINT_CATEGORIES = ("LATE", "FEE_DISCLOSURE", "QUALITY", "DRIVER_CONDUCT")


def assert_store(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["store_number"], str) and 1 <= len(data["store_number"]) <= 8
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["latitude_micro"], int)
    assert isinstance(data["longitude_micro"], int)
    assert isinstance(data["promise_minutes"], int) and data["promise_minutes"] >= 1
    for field in (
        "delivery_fee_cents",
        "cash_limit_cents",
        "cash_collected_total_cents",
        "safe_deposit_total_cents",
    ):
        assert_cents(data[field], field)
        assert data[field] >= 0, f"{field} must be at least 0"
    assert isinstance(data["hot_bag_count"], int) and data["hot_bag_count"] >= 1
    assert isinstance(data["max_stacked_stops"], int) and data["max_stacked_stops"] >= 1
    assert isinstance(data["handoff_minutes_per_stop"], int) and data["handoff_minutes_per_stop"] >= 0
    assert (
        isinstance(data["dispatch_reset_buffer_minutes"], int)
        and data["dispatch_reset_buffer_minutes"] >= 0
    )
    assert data["service_posture"] in SERVICE_POSTURES
    assert isinstance(data["unassigned_order_count"], int) and data["unassigned_order_count"] >= 0
    assert data["active_zone_version_number"] is None or isinstance(
        data["active_zone_version_number"], int
    )


def assert_zone_version(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert data["status"] in ZONE_VERSION_STATUSES
    assert isinstance(data["polygon"], list) and len(data["polygon"]) >= 3, (
        "a stored ring carries at least three vertices"
    )
    for vertex in data["polygon"]:
        assert isinstance(vertex["latitude_micro"], int)
        assert isinstance(vertex["longitude_micro"], int)
    assert_iso_millis(data["effective_from"], "effective_from")
    assert_iso_millis(data["effective_to"], "effective_to")
    assert data["effective_to"] > data["effective_from"]
    assert isinstance(data["max_drive_time_minutes"], int) and data["max_drive_time_minutes"] >= 1
    assert isinstance(data["base_drive_minutes"], int) and data["base_drive_minutes"] >= 0
    assert isinstance(data["minutes_per_mile"], int) and data["minutes_per_mile"] >= 1
    assert isinstance(data["peak_surcharge_minutes"], int) and data["peak_surcharge_minutes"] >= 0
    assert (
        isinstance(data["barrier_surcharge_minutes"], int)
        and data["barrier_surcharge_minutes"] >= 0
    )
    assert data["supersedes_zone_version_id"] is None or is_valid_uuid(
        data["supersedes_zone_version_id"]
    )
    if data["status"] == "DRAFT":
        assert data["activated_at"] is None, "a draft version has not been activated"


def assert_service_address(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["line1"], str) and len(data["line1"]) > 0
    assert isinstance(data["latitude_micro"], int)
    assert isinstance(data["longitude_micro"], int)
    assert isinstance(data["crosses_barrier"], bool)
    assert_two_decimal_miles(data["grid_miles"], "grid_miles")
    assert data["grid_miles"] >= 0
    assert isinstance(data["drive_time_estimate_minutes"], int)
    assert data["zone_state"] in ZONE_STATES
    assert data["effective_zone_state"] in ZONE_STATES
    assert data["override_state"] is None or data["override_state"] in ZONE_STATES
    assert (
        isinstance(data["evaluated_zone_version_number"], int)
        and data["evaluated_zone_version_number"] >= 1
    )
    assert_iso_millis(data["evaluated_at"], "evaluated_at")


def assert_address_dispute(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["service_address_id"])
    assert data["claimed_state"] == "IN_ZONE"
    assert isinstance(data["evidence_note"], str)
    assert data["status"] in DISPUTE_STATUSES
    assert isinstance(data["review_round_count"], int) and 0 <= data["review_round_count"] <= 2
    assert data["resolution"] is None or data["resolution"] in ("GRANTED", "DENIED")


def assert_driver(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert data["vehicle_class"] in VEHICLE_CLASSES
    assert data["qualification_status"] in QUALIFICATION_STATUSES
    assert data["insurance_status"] in INSURANCE_STATUSES
    assert isinstance(data["mvr_points_latest"], int) and 0 <= data["mvr_points_latest"] <= 20
    assert_cents(data["cash_on_hand_cents"], "cash_on_hand_cents")
    assert data["cash_posture"] in CASH_POSTURES
    assert_cents(data["reimbursement_accrued_cents"], "reimbursement_accrued_cents")


def assert_mvr_check(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data)
    assert is_valid_uuid(data["driver_id"])
    assert data["result"] in MVR_RESULTS
    assert isinstance(data["violation_points"], int) and 0 <= data["violation_points"] <= 20
    assert_iso_millis(data["checked_on"], "checked_on")
    assert isinstance(data["recorded_by_user_id"], str) and len(data["recorded_by_user_id"]) > 0


def assert_insurance_verification(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["driver_id"])
    assert isinstance(data["policy_number"], str) and len(data["policy_number"]) > 0
    assert_iso_millis(data["coverage_from"], "coverage_from")
    assert_iso_millis(data["coverage_to"], "coverage_to")
    assert data["coverage_to"] > data["coverage_from"]
    assert_cents(data["liability_limit_cents"], "liability_limit_cents")
    assert data["liability_limit_cents"] >= 0
    assert data["status"] in ("VERIFIED", "REJECTED", "SUPERSEDED")


def assert_vehicle_cost_model(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert data["vehicle_class"] in VEHICLE_CLASSES
    for field in (
        "per_delivery_cents",
        "tier1_per_mile_cents",
        "tier2_per_mile_cents",
        "min_reimbursement_per_stop_cents",
    ):
        assert_cents(data[field], field)
        assert data[field] >= 0, f"{field} must be at least 0"
    assert_two_decimal_miles(data["tier1_cap_miles"], "tier1_cap_miles")
    assert data["tier1_cap_miles"] > 0, "tier1_cap_miles must be strictly greater than 0"
    assert_iso_millis(data["effective_from"], "effective_from")
    assert data["status"] in ("ACTIVE", "RETIRED")
    if data["status"] == "ACTIVE":
        assert data["retired_at"] is None


def assert_safe_drop(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["driver_id"])
    assert_cents(data["amount_cents"], "amount_cents")
    assert data["amount_cents"] >= 1, "a drop moves at least 1 cent"
    assert isinstance(data["envelope_number"], str) and len(data["envelope_number"]) > 0
    assert data["status"] in ("RECORDED", "VOIDED")
    if data["status"] == "RECORDED":
        assert data["voided_reason"] is None and data["voided_at"] is None


def assert_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["service_address_id"])
    assert isinstance(data["customer_name"], str) and len(data["customer_name"]) > 0
    assert isinstance(data["customer_phone"], str) and len(data["customer_phone"]) > 0
    for field in (
        "food_subtotal_cents",
        "tip_cents",
        "base_delivery_fee_cents",
        "delivery_fee_cents",
        "total_charge_cents",
    ):
        assert_cents(data[field], field)
        assert data[field] >= 0, f"{field} must be at least 0"
    assert data["payment_method"] in ("CASH", "CARD")
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    assert data["settlement_status"] in SETTLEMENT_STATUSES
    assert data["fee_tier"] in FEE_TIERS
    assert data["fee_waiver_pct"] in (0, 50, 100)
    assert isinstance(data["promise_minutes_snapshot"], int) and data["promise_minutes_snapshot"] >= 1
    assert_iso_millis(data["placed_at"], "placed_at")
    assert data["total_charge_cents"] == (
        data["food_subtotal_cents"] + data["delivery_fee_cents"] + data["tip_cents"]
    ), "total_charge_cents is the food subtotal plus the charged delivery fee plus the tip"


def assert_dispatch(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["driver_id"])
    assert_iso_millis(data["planned_depart_at"], "planned_depart_at")
    assert data["status"] in DISPATCH_STATUSES
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0
    assert isinstance(data["committed_hot_bag_slots"], int) and data["committed_hot_bag_slots"] >= 0
    if data["route_minutes"] is not None:
        assert isinstance(data["route_minutes"], int) and data["route_minutes"] >= 0
    if data["estimated_reimbursement_cents"] is not None:
        assert_cents(data["estimated_reimbursement_cents"], "estimated_reimbursement_cents")
    if data["actual_reimbursement_cents"] is not None:
        assert_cents(data["actual_reimbursement_cents"], "actual_reimbursement_cents")
    if data["reimbursement_variance_cents"] is not None:
        assert_cents(data["reimbursement_variance_cents"], "reimbursement_variance_cents")


def assert_dispatch_stop(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["dispatch_id"])
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["status"] in STOP_STATUSES
    assert data["hot_bag_slots"] in (1, 2)
    assert_two_decimal_miles(data["planned_miles"], "planned_miles")
    assert isinstance(data["planned_drive_minutes"], int) and data["planned_drive_minutes"] >= 0
    if data["actual_miles"] is not None:
        assert_two_decimal_miles(data["actual_miles"], "actual_miles")
        assert data["actual_miles"] >= 0
    assert_cents(data["cash_collected_cents"], "cash_collected_cents")


def assert_reimbursement_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["dispatch_id"])
    assert is_valid_uuid(data["driver_id"])
    assert data["line_type"] in LINE_TYPES
    assert data["basis"] in LINE_BASES
    assert data["status"] in LINE_STATUSES
    assert_cents(data["amount_cents"], "amount_cents")
    assert isinstance(data["sequence_snapshot"], int) and data["sequence_snapshot"] >= 0
    if data["line_type"] == "CLAWBACK":
        assert data["basis"] == "NONE"
        assert data["sequence_snapshot"] == 0
        assert data["amount_cents"] < 0, "only a clawback line carries a negative amount"
    else:
        assert data["amount_cents"] >= 0, "only a clawback line carries a negative amount"


def assert_complaint(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["category"] in COMPLAINT_CATEGORIES
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert data["status"] in COMPLAINT_STATUSES
    if data["proposed_remedy_cents"] is not None:
        assert_cents(data["proposed_remedy_cents"], "proposed_remedy_cents")
        assert data["proposed_remedy_cents"] >= 0
    assert isinstance(data["driver_chargeable"], bool)
    assert_cents(data["clawback_cents"], "clawback_cents")
    assert isinstance(data["logged_by_user_id"], str) and len(data["logged_by_user_id"]) > 0


# --- Domain invariants --------------------------------------------------------


def assert_cash_conservation(reconciliation: Dict[str, Any]) -> None:
    """A store's collected total always equals the safe-deposit total plus the
    combined cash on hand of its drivers."""
    for field in (
        "cash_collected_total_cents",
        "safe_deposit_total_cents",
        "driver_cash_on_hand_total_cents",
    ):
        assert_cents(reconciliation[field], field)
    left = reconciliation["cash_collected_total_cents"]
    right = (
        reconciliation["safe_deposit_total_cents"]
        + reconciliation["driver_cash_on_hand_total_cents"]
    )
    assert left == right, (
        f"cash conservation broken: collected {left} != safe {reconciliation['safe_deposit_total_cents']} "
        f"+ on hand {reconciliation['driver_cash_on_hand_total_cents']}"
    )
    assert isinstance(reconciliation["reconciled"], bool)
    assert reconciliation["reconciled"] is (left == right), (
        "reconciled is true exactly when the collected total equals the safe total plus cash on hand"
    )


def assert_order_to_door(data: Dict[str, Any]) -> None:
    """The net figure is the gross minus both hold accumulators, clamped at 0."""
    gross = data.get("order_to_door_gross_minutes")
    net = data.get("order_to_door_net_minutes")
    if gross is None or net is None:
        return
    expected_net = max(
        gross - data.get("zone_hold_minutes", 0) - data.get("remake_hold_minutes", 0), 0
    )
    assert net == expected_net, (
        f"order_to_door_net_minutes should be {expected_net} "
        f"(gross {gross} minus holds), got {net}"
    )
    assert net >= 0, "the net figure never falls below 0"


# --- Instant arithmetic -------------------------------------------------------

_ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant in either the second or the millisecond form."""
    normalised = value.replace("Z", "+0000")
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(normalised, fmt)
        except ValueError:
            continue
    raise AssertionError(f"unparseable instant {value!r}")


def format_instant(moment: datetime) -> str:
    """Render an instant in the shorter ``...Z`` form the API accepts on input."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def instant_plus(value: str, *, minutes: int = 0, seconds: int = 0, hours: int = 0) -> str:
    """Advance an instant by whole minutes, seconds or hours."""
    return format_instant(
        parse_instant(value) + timedelta(minutes=minutes, seconds=seconds, hours=hours)
    )


def whole_minutes_between(earlier: str, later: str) -> int:
    """The whole-second difference between two instants, divided by 60 and
    truncated downward, so a partly elapsed minute is not yet counted."""
    delta = parse_instant(later) - parse_instant(earlier)
    return int(delta.total_seconds()) // 60


# --- Remedy formulas ----------------------------------------------------------


def expected_late_remedy_cents(
    food_subtotal_cents: int,
    order_to_door_gross_minutes: int,
    promise_minutes_snapshot: int,
    delivery_fee_cents: int,
) -> int:
    """The raw late remedy before the ticket cap: a food percentage picked from the
    overage, plus the whole delivery fee once the overage reaches 20 minutes."""
    overage = order_to_door_gross_minutes - promise_minutes_snapshot
    if overage >= 20:
        percentage, fee_refund = 100, delivery_fee_cents
    elif overage >= 10:
        percentage, fee_refund = 50, 0
    elif overage >= 1:
        percentage, fee_refund = 20, 0
    else:
        percentage, fee_refund = 0, 0
    return round_half_up(food_subtotal_cents * percentage / 100) + fee_refund


def expected_remedy(order: Dict[str, Any], category: str) -> Tuple[int, str]:
    """The proposed remedy and its recorded basis for one order and one category.

    The category selects the formula and the ticket total caps every branch last.
    """
    if category == "LATE":
        raw = expected_late_remedy_cents(
            order["food_subtotal_cents"],
            order["order_to_door_gross_minutes"],
            order["promise_minutes_snapshot"],
            order["delivery_fee_cents"],
        )
        basis = "LATE_TIER"
    elif category == "FEE_DISCLOSURE":
        penalty = 0 if order.get("fee_disclosure_accurate") else 500
        raw = order["delivery_fee_cents"] + penalty
        basis = "FEE_REFUND"
    elif category == "QUALITY":
        raw = round_half_up(order["food_subtotal_cents"] * 50 / 100)
        basis = "QUALITY_HALF"
    elif category == "DRIVER_CONDUCT":
        raw = 0
        basis = "CONDUCT_ZERO"
    else:
        raise AssertionError(f"unknown complaint category {category!r}")
    return min(raw, order["total_charge_cents"]), basis

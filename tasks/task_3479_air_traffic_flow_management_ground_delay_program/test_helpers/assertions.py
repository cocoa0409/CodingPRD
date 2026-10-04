"""Domain assertions and expected-value computers.

Structural assertions wrap the shared helpers with this contract's vocabulary:
instants compare on their canonical form, mutable resources carry id /
created_at / updated_at / version, and the four append-only record types carry
only id / created_at.

The expected-value computers mirror the PRD's arithmetic - slot geometry from
the rate, the capacity-forecast multiplier product, whole-minute delay floors -
so a test states what the contract computes instead of re-deriving it inline.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    GA_MIN_RESERVED,
    GA_QUOTA_PCT,
    GDP_RATE_DIVISOR,
    IMPACT_STEP_BY_EVENT_TYPE,
    MIN_CAPACITY_FLOOR_PCT,
)


# ── Instants ───────────────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def render_instant(moment: datetime) -> str:
    """Render a UTC moment the way the contract's datetime inputs are written."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment, on canonical form."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: str, label: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant rendered with a Z suffix."""
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"{label}: must be rendered in UTC with a Z suffix: {value!r}"


# ── Envelope and common fields ─────────────────────────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the meta block carries a prefixed request id and a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "meta.api_request_timestamp")


def assert_mutable_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert id, created_at, updated_at and version are present and well formed."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data["created_at"], f"{label}.created_at")
    assert_instant_format(data["updated_at"], f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and not isinstance(data.get("version"), bool), (
        f"{label}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_append_only_common_fields(data: Dict[str, Any], label: str = "record") -> None:
    """Assert an append-only record carries ONLY id and created_at of the common set."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data["created_at"], f"{label}.created_at")
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_list_page(rows: Any, meta: Dict[str, Any]) -> None:
    """Assert the pagination block is self-consistent with the returned page."""
    assert isinstance(rows, list), f"list data must be an array, got {type(rows).__name__}"
    assert meta["total_count"] >= 0
    assert meta["limit"] >= 1
    assert meta["offset"] >= 0
    assert len(rows) <= meta["limit"]
    assert meta["has_more"] == (meta["offset"] + len(rows) < meta["total_count"])


# ── Per-entity shape assertions ────────────────────────────────────────────

def assert_facility(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "facility")
    assert isinstance(data["ident"], str) and data["ident"]
    assert data["facility_type"] in ("AIRPORT", "EN_ROUTE_SECTOR")
    assert isinstance(data["base_acceptance_rate"], int)
    assert data["status"] in ("OPERATIONAL", "DEGRADED", "OUTAGE")


def assert_operator(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "operator")
    assert isinstance(data["name"], str) and data["name"]
    assert data["operator_type"] in (
        "SCHEDULED_CARRIER", "GENERAL_AVIATION", "UNSCHEDULED_CHARTER",
    )
    assert isinstance(data["cdm_member"], bool)
    assert isinstance(data["cumulative_delay_minutes"], int)
    assert data["cumulative_delay_minutes"] >= 0


def assert_constraint_event(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "constraint_event")
    assert data["event_type"] in ("WEATHER", "STAFFING", "EQUIPMENT")
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    assert_instant(data["window_start"], data["window_start"])
    assert parse_instant(data["window_end"]) > parse_instant(data["window_start"])
    assert isinstance(data["extension_count"], int) and data["extension_count"] >= 0
    assert data["status"] in ("REPORTED", "CONFIRMED", "CLEARED")
    assert isinstance(data["facility_id"], str)


def assert_capacity_forecast(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "capacity_forecast")
    assert data["variant"] in ("PLANNING", "OPERATIONAL")
    assert data["status"] in ("DRAFT", "PUBLISHED", "STALE")
    assert isinstance(data["predicted_acceptance_rate"], int)
    assert data["predicted_acceptance_rate"] >= 1, "a facility never forecasts below 1/hour"
    assert isinstance(data["included_event_ids"], list)
    assert isinstance(data["facility_id"], str)
    if data["status"] == "DRAFT":
        assert data.get("published_at") is None
    else:
        assert_instant_format(data["published_at"], "capacity_forecast.published_at")


def assert_tmi(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "tmi")
    assert data["tmi_type"] in (
        "GROUND_DELAY_PROGRAM", "GROUND_STOP", "AIRSPACE_FLOW_PROGRAM", "REROUTE",
    )
    assert data["status"] in (
        "PROPOSED", "PUBLISHED", "ACTIVE", "REVISING", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["controlled_rate"], int)
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["facility_id"], str)
    assert parse_instant(data["program_end"]) > parse_instant(data["program_start"])
    if data["status"] in ("ACTIVE", "REVISING", "COMPLETED"):
        assert_instant_format(data["activated_at"], "tmi.activated_at")


def assert_tmi_revision(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "tmi_revision")
    assert isinstance(data["tmi_id"], str)
    assert isinstance(data["revision_index"], int) and data["revision_index"] >= 1
    assert data["origin"] in ("MANUAL", "SYSTEM_AUTO_DOWNGRADE")
    assert isinstance(data["reason"], str)
    assert isinstance(data["applied"], bool)
    # rate fields are null when only the window changed, and vice versa
    assert (data["previous_controlled_rate"] is None) == (data["new_controlled_rate"] is None)
    assert (data["previous_program_end"] is None) == (data["new_program_end"] is None)
    if data["applied"]:
        assert_instant_format(data["applied_at"], "tmi_revision.applied_at")
    else:
        assert data.get("applied_at") is None


def assert_flight(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "flight")
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["designator"], str) and data["designator"]
    assert isinstance(data["origin"], str)
    assert isinstance(data["arrival_facility_id"], str)
    assert_instant_format(data["scheduled_arrival"], "flight.scheduled_arrival")
    assert_instant_format(data["estimated_arrival"], "flight.estimated_arrival")
    assert_instant_format(data["last_eta_reported_at"], "flight.last_eta_reported_at")
    assert data["ops_status"] in ("SCHEDULED", "AIRBORNE", "LANDED", "CANCELLED")
    assert data["control_status"] in ("UNCONTROLLED", "SLOTTED")
    assert isinstance(data["is_overflow"], bool)
    assert isinstance(data["provisional_delay_minutes"], int)
    assert data["provisional_delay_minutes"] >= 0
    if data["control_status"] == "UNCONTROLLED" and not data["is_overflow"]:
        assert data.get("controlled_arrival") is None
    if data["is_overflow"]:
        assert data.get("controlled_arrival") is not None, "overflow carries a virtual CTA"
    assert data.get("final_delay_minutes") is None or isinstance(data["final_delay_minutes"], int)


def assert_arrival_slot(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "arrival_slot")
    assert isinstance(data["tmi_id"], str)
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 0
    assert_instant_format(data["slot_time"], "arrival_slot.slot_time")
    assert isinstance(data["is_ga_reserved"], bool)
    assert data["status"] in ("OPEN", "ASSIGNED", "RELEASED")
    if data["status"] == "ASSIGNED":
        assert isinstance(data.get("assigned_flight_id"), str)
    else:
        assert data.get("assigned_flight_id") is None


def assert_slot_transaction(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "slot_transaction")
    assert isinstance(data["tmi_id"], str)
    assert isinstance(data["flight_id"], str)
    assert isinstance(data["operator_id"], str)
    assert data["transaction_type"] in (
        "INITIAL_ASSIGNMENT", "SUBSTITUTION_SWAP", "COMPRESSION_MOVE",
        "RELEASE", "GA_ASSIGNMENT", "REVISION_MOVE", "REVERSAL",
    )
    assert isinstance(data["delay_delta_minutes"], int)
    if data["transaction_type"] == "INITIAL_ASSIGNMENT":
        assert data.get("from_slot_time") is None
    if data["transaction_type"] in ("RELEASE", "REVERSAL"):
        assert data.get("to_slot_time") is None


def assert_compression_run(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "compression_run")
    assert isinstance(data["tmi_id"], str)
    assert isinstance(data["released_slot_count"], int) and data["released_slot_count"] >= 0
    assert isinstance(data["moves_made"], int) and data["moves_made"] >= 0
    assert isinstance(data["passes_executed"], int) and data["passes_executed"] >= 1
    assert isinstance(data["promoted_ga_request_ids"], list)
    assert isinstance(data["remaining_open_slots"], int) and data["remaining_open_slots"] >= 0


def assert_ga_request(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "ga_request")
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["tmi_id"], str)
    assert data["priority_class"] in ("HIGH_PRIORITY", "STANDARD")
    assert data["status"] in ("REQUESTED", "ACCOMMODATED", "WAITLISTED", "DENIED", "EXPIRED")
    assert parse_instant(data["requested_window_end"]) > parse_instant(
        data["requested_window_start"]
    )
    if data["status"] == "ACCOMMODATED":
        assert isinstance(data.get("accommodated_flight_id"), str)
        assert_instant_format(
            data["accommodated_slot_time"], "ga_request.accommodated_slot_time"
        )
    else:
        assert data.get("accommodated_flight_id") is None
        assert data.get("accommodated_slot_time") is None


def assert_reroute_assignment(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "reroute_assignment")
    assert isinstance(data["tmi_id"], str)
    assert isinstance(data["flight_id"], str)
    assert isinstance(data["via_sector_id"], str)
    assert isinstance(data["assigned_route"], str) and data["assigned_route"]
    # the bucket is the flight's ETA truncated to the hour
    bucket = parse_instant(data["hourly_bucket"])
    assert bucket.minute == 0 and bucket.second == 0 and bucket.microsecond == 0


def assert_delay_ledger(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "delay_ledger")
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["tmi_id"], str)
    for field in (
        "flight_count", "attributed_delay_minutes", "reversed_delay_minutes",
        "fair_share_minutes", "deviation_minutes",
    ):
        assert isinstance(data[field], int) and not isinstance(data[field], bool), (
            f"delay_ledger.{field} must be an integer, got {data[field]!r}"
        )
    assert data["flight_count"] >= 0
    # deviation is defined as the signed gap between attributed and fair share
    assert data["deviation_minutes"] == (
        data["attributed_delay_minutes"] - data["fair_share_minutes"]
    ), (
        f"deviation_minutes {data['deviation_minutes']} != attributed "
        f"{data['attributed_delay_minutes']} - fair_share {data['fair_share_minutes']}"
    )


# ── Expected-value computers (the PRD's arithmetic, stated once) ───────────

def slot_interval_seconds(controlled_rate: int) -> int:
    """The exact spacing between consecutive slots of a ground delay program."""
    return GDP_RATE_DIVISOR // controlled_rate


def expected_slot_count(program_start: str, program_end: str, controlled_rate: int) -> int:
    """The whole number of slot intervals that fit in the half-open window."""
    seconds = (parse_instant(program_end) - parse_instant(program_start)).total_seconds()
    return int(seconds // slot_interval_seconds(controlled_rate))


def expected_slot_time(program_start: str, controlled_rate: int, slot_index: int) -> str:
    """Slot k sits at program_start + k intervals, exact to the second."""
    moment = parse_instant(program_start) + timedelta(
        seconds=slot_index * slot_interval_seconds(controlled_rate)
    )
    return render_instant(moment)


def expected_reserved_slots(slot_count: int) -> int:
    """max(GA_MIN_RESERVED, floor(slot_count * GA_QUOTA_PCT / 100))."""
    return max(GA_MIN_RESERVED, (slot_count * GA_QUOTA_PCT) // 100)


def expected_predicted_rate(
    base_acceptance_rate: int,
    factors: Iterable[float],
) -> int:
    """floor(base * max(product(factors), MIN_CAPACITY_FLOOR_PCT/100)), min 1.

    ``factors`` is the per-event (1 - step * severity * weight) list the variant
    admits; an empty iterable means no events entered the computation.
    """
    multiplier = 1.0
    for factor in factors:
        multiplier *= factor
    effective = max(multiplier, MIN_CAPACITY_FLOOR_PCT / 100)
    return max(1, int(base_acceptance_rate * effective // 1))


def event_factor(event_type: str, severity: int, weight: float = 1.0) -> float:
    """One event's multiplier factor: 1 - step * severity * weight."""
    return 1.0 - IMPACT_STEP_BY_EVENT_TYPE[event_type] * severity * weight


def expected_delay_minutes(controlled_arrival: str, scheduled_arrival: str) -> int:
    """Whole-minute floor of (CTA - scheduled), never below zero."""
    delta = (parse_instant(controlled_arrival) - parse_instant(scheduled_arrival)).total_seconds()
    return max(0, int(delta // 60))


def expected_hourly_bucket(estimated_arrival: str) -> str:
    """The reroute bucket: the ETA truncated to the hour."""
    moment = parse_instant(estimated_arrival).replace(minute=0, second=0, microsecond=0)
    return render_instant(moment)


def is_valid_gdp_rate(rate: int) -> bool:
    """The GDP rate shape: integer in [6, 60] dividing 3600 exactly."""
    from .constants import GDP_MAX_CONTROLLED_RATE, GDP_MIN_CONTROLLED_RATE

    return (
        isinstance(rate, int)
        and not isinstance(rate, bool)
        and GDP_MIN_CONTROLLED_RATE <= rate <= GDP_MAX_CONTROLLED_RATE
        and GDP_RATE_DIVISOR % rate == 0
    )


# ── Collection conveniences used across the recipes ────────────────────────

def assigned_slot_times(slots: List[Dict[str, Any]]) -> List[str]:
    """The multiset of slot_times currently ASSIGNED, in slot_index order."""
    return [s["slot_time"] for s in sorted(slots, key=lambda s: s["slot_index"])
            if s["status"] == "ASSIGNED"]


def transactions_of_type(
    transactions: List[Dict[str, Any]], transaction_type: str
) -> List[Dict[str, Any]]:
    return [t for t in transactions if t["transaction_type"] == transaction_type]


def sum_delay_deltas(transactions: List[Dict[str, Any]]) -> int:
    return sum(t["delay_delta_minutes"] for t in transactions)


def ledger_for(ledgers: List[Dict[str, Any]], operator_id: str) -> Dict[str, Any]:
    """The single ledger row of one operator in a program's ledger list."""
    matches = [l for l in ledgers if l["operator_id"] == operator_id]
    assert len(matches) == 1, f"expected exactly one ledger for {operator_id}, got {len(matches)}"
    return matches[0]

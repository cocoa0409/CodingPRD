"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str):
    """PRD states all window rules over instants; the string representation of
    user-supplied timestamps is unspecified, so compare the denoted instants."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{actual!r} and {expected!r} denote different instants"
    )

MISSION_STATUSES = [
    "MANIFEST_OPEN", "MANIFEST_LOCKED", "RANGE_SCHEDULED",
    "LAUNCHED", "COMPLETED", "SCRUBBED",
]
CONTRACT_STATUSES = ["DRAFT", "SIGNED", "MANIFESTED", "FULFILLED", "EXPIRED"]
PAYLOAD_STATUSES = ["REGISTERED", "MANIFESTED", "DEPLOYED"]
ASSIGNMENT_STATUSES = ["PROVISIONAL", "CONFIRMED", "INTEGRATED", "DEPLOYED", "REMOVED"]
LICENSE_STATUSES = ["SUBMITTED", "GRANTED", "DENIED", "REVOKED", "EXPIRED"]
SLOT_STATUSES = ["REQUESTED", "RESERVED", "CONFIRMED", "CONSUMED", "RELEASED"]
SEPARATION_STATUSES = ["PLANNED", "EXECUTED", "ANOMALOUS"]
ANOMALY_STATUSES = ["OPEN", "UNDER_INVESTIGATION", "ESCALATED", "RESOLVED"]
ORBITS = ["SSO", "LEO", "GTO"]
INTERFACES = ["RING_15", "RING_24", "CUBESAT"]


def _assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            "updated_at must be ISO 8601"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            "version must be a positive integer"
        )
    else:
        # Append-only records (PRD §2.5): updated_at and version are absent.
        assert "updated_at" not in data, "append-only record must not carry updated_at"
        assert "version" not in data, "append-only record must not carry version"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["default_rebookings"], int)


def assert_mission(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["mission_name"], str) and data["mission_name"]
    assert data["target_orbit"] in ORBITS
    assert is_iso8601_timestamp(data["window_open_utc"])
    assert is_iso8601_timestamp(data["window_close_utc"])
    assert data["mass_capacity_kg"] > 0
    assert data["volume_capacity_m3"] > 0
    assert data["committed_mass_kg"] >= 0
    assert data["committed_volume_m3"] >= 0
    assert data["firm_mass_kg"] >= 0
    assert isinstance(data["integration_revenue_cents"], int)
    assert isinstance(data["revenue_estimate_cents"], int)
    assert data["status"] in MISSION_STATUSES


def assert_dispenser_port(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["mission_id"])
    assert isinstance(data["port_code"], str) and data["port_code"]
    assert isinstance(data["stack_position"], int)
    assert data["max_mass_kg"] > 0
    assert isinstance(data["supported_interface_classes"], list)
    assert len(data["supported_interface_classes"]) > 0
    for iface in data["supported_interface_classes"]:
        assert iface in INTERFACES


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["pricing_mode"] in ("MARGINAL", "FLAT")
    assert is_iso8601_timestamp(data["window_open_utc"])
    assert is_iso8601_timestamp(data["window_close_utc"])
    assert isinstance(data["rebookings_remaining"], int)
    assert isinstance(data["quoted_price_cents"], int)
    assert isinstance(data["total_rebooking_fees_cents"], int)
    assert isinstance(data["rebook_eligible"], bool)
    assert data["status"] in CONTRACT_STATUSES


def assert_payload(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["payload_name"], str) and data["payload_name"]
    assert data["mass_kg"] > 0
    assert data["volume_m3"] > 0
    assert data["interface_class"] in INTERFACES
    assert data["required_orbit"] in ORBITS
    assert data["status"] in PAYLOAD_STATUSES


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["mission_id"])
    assert is_valid_uuid(data["payload_id"])
    assert is_valid_uuid(data["dispenser_port_id"])
    assert isinstance(data["integration_fee_cents"], int)
    assert data["status"] in ASSIGNMENT_STATUSES


def assert_license(data: dict):
    _assert_common_fields(data)
    assert data["subject_type"] in ("MISSION", "CUSTOMER")
    assert data["kind"] in ("LAUNCH_AUTHORIZATION", "PAYLOAD_OPERATOR")
    assert isinstance(data["debris_score"], int) and 0 <= data["debris_score"] <= 100
    assert isinstance(data["spectrum_score"], int) and 0 <= data["spectrum_score"] <= 100
    assert isinstance(data["operator_history_score"], int)
    assert 0 <= data["operator_history_score"] <= 100
    assert isinstance(data["composite_score"], int)
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["status"] in LICENSE_STATUSES


def assert_range_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["mission_id"])
    assert data["range_code"] in ("CCAFS", "VAFB")
    assert is_iso8601_timestamp(data["window_open_utc"])
    assert is_iso8601_timestamp(data["window_close_utc"])
    assert data["status"] in SLOT_STATUSES


def assert_separation_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["mission_id"])
    assert is_valid_uuid(data["assignment_id"])
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 0
    assert isinstance(data["offset_seconds"], int) and data["offset_seconds"] >= 0
    assert data["status"] in SEPARATION_STATUSES


def assert_anomaly(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["mission_id"])
    assert data["category"] in ("SEPARATION", "PAYLOAD_TELEMETRY")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ANOMALY_STATUSES


def assert_verification(data: dict):
    """Append-only (PRD §2.5): id + created_at only, plus domain fields."""
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["assignment_id"])
    assert data["check_type"] in ("MECHANICAL", "ELECTRICAL")
    assert data["outcome"] in ("PASSED", "FAILED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_safety_review(data: dict):
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["assignment_id"])
    assert data["decision"] in ("APPROVE", "REJECT")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_exclusion_window(data: dict):
    _assert_common_fields(data, with_version=False)
    assert data["scope_type"] in ("RANGE", "ORBIT")
    assert data["kind"] in ("WEATHER", "COLA")
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])


def assert_delay_event(data: dict):
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["mission_id"])
    assert is_iso8601_timestamp(data["previous_window_open_utc"])
    assert is_iso8601_timestamp(data["previous_window_close_utc"])
    assert is_iso8601_timestamp(data["new_window_open_utc"])
    assert is_iso8601_timestamp(data["new_window_close_utc"])
    assert isinstance(data["reason_code"], str)
    assert isinstance(data["slot_released"], bool)
    assert isinstance(data["assignments_removed_count"], int)
    assert data["assignments_removed_count"] >= 0

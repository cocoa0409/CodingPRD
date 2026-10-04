"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_audit_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


# --- Per-entity assertions -------------------------------------------------

def assert_property(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert isinstance(data["unit_capacity"], int)
    assert isinstance(data["temp_budget_cents_per_day"], int)
    assert isinstance(data["budget_committed_cents"], int)
    assert data["budget_committed_cents"] >= 0


def assert_building(data: dict):
    _assert_audit_fields(data)
    assert data["network_design"] in ("POINT_TO_POINT", "FIELD_MESH", "HUB_RELAY")
    assert isinstance(data["wifi_rssi_dbm"], int)
    assert isinstance(data["connectivity_ok"], bool)


def assert_unit(data: dict):
    _assert_audit_fields(data)
    assert data["occupancy_status"] in ("VACANT", "OCCUPIED", "NOTICE", "NOTICE_ENDED")
    assert data["hvac_mode"] in ("VACANT_AUTO", "OCCUPIED")
    assert isinstance(data["target_setpoint_c"], (int, float))
    assert isinstance(data["unauthorized_entry_detected"], bool)


def assert_device(data: dict):
    _assert_audit_fields(data)
    assert data["device_type"] in (
        "SMART_LOCK", "THERMOSTAT", "LEAK_SENSOR", "COMMUNITY_ACCESS", "HUB"
    )
    assert data["firmware_version"] in ("LATEST", "OLD", "CRITICAL")
    assert data["status"] in (
        "PROVISIONED", "ONLINE", "UNREACHABLE", "DECOMMISSIONED"
    )
    assert data["lock_state"] in ("LOCKED", "UNLOCKED")
    assert isinstance(data["battery_pct"], int)
    assert 0 <= data["battery_pct"] <= 100
    assert isinstance(data["battery_replacements"], int)


def assert_device_alert(data: dict):
    _assert_audit_fields(data)
    assert data["alert_type"] in ("OFFLINE", "LOW_BATTERY", "UNAUTHORIZED_ENTRY")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED")
    assert data["severity"] in ("MEDIUM", "HIGH")


def assert_work_order(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("OPEN", "ASSIGNED", "CLOSED")
    assert isinstance(data["battery_replaced"], bool)


def assert_resident(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in (
        "PENDING_CREDENTIAL", "ACTIVE", "DEACTIVATING", "REVOKED"
    )
    assert data["portal_credential_status"] in ("NOT_ISSUED", "ACTIVE", "REVOKED")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_resident_status_event(data: dict):
    """Append-only audit record: id + created_at only, never updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, (
        "ResidentStatusEvent is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "ResidentStatusEvent is append-only and must not carry version"
    )
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["from_status"], str)
    assert isinstance(data["to_status"], str)


def assert_access_credential(data: dict):
    _assert_audit_fields(data)
    assert data["credential_type"] in ("RESIDENT", "GUEST", "TOUR")
    assert data["status"] in ("ISSUED", "ACTIVE", "EXPIRED", "REVOKED")
    assert is_iso8601_timestamp(data["valid_from"])


def assert_guest_pass(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert isinstance(data["guest_label"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])


def assert_tour_session(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in (
        "REQUESTED", "DENIED", "VERIFIED", "ACTIVE", "COMPLETED"
    )
    assert isinstance(data["verify_attempts"], int)
    assert data["verify_attempts"] >= 0
    assert isinstance(data["duration_minutes"], int)


def assert_maintenance_visit(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in (
        "REQUESTED", "NOTICE_CERTIFIED", "COMPLETED", "CANCELLED"
    )
    assert isinstance(data["is_emergency"], bool)
    assert isinstance(data["accrued_cost_cents"], int)
    assert_cost_precision(float(data["accrued_cost_cents"]), 0)
    assert isinstance(data["planned_hours"], (int, float))


def assert_installation_job(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")
    assert isinstance(data["requires_resident_coordination"], bool)
    assert isinstance(data["labor_hours"], (int, float))


# --- Domain invariant checkers --------------------------------------------

def assert_property_invariants(data: dict):
    """The committed budget is a non-negative exact-cent accumulator."""
    assert data["budget_committed_cents"] >= 0
    assert isinstance(data["budget_committed_cents"], int)
    assert isinstance(data["temp_budget_cents_per_day"], int)


def assert_credential_conservation(credentials: list, expected_total: int):
    """active + expired + revoked always equals the number of credential rows."""
    counts = {"ACTIVE": 0, "EXPIRED": 0, "REVOKED": 0, "ISSUED": 0}
    for cred in credentials:
        assert cred["status"] in counts, f"unexpected credential status {cred['status']}"
        counts[cred["status"]] += 1
    assert len(credentials) == expected_total, (
        f"Expected {expected_total} credential rows, got {len(credentials)}"
    )
    assert counts["ACTIVE"] + counts["EXPIRED"] + counts["REVOKED"] == expected_total, (
        f"active + expired + revoked ({counts}) must equal the row count "
        f"{expected_total}; live rows must be moved between buckets, never deleted"
    )
    return counts


def assert_approx(value, expected, abs_tol=0.01):
    assert value == pytest.approx(expected, abs=abs_tol), (
        f"Expected {expected}, got {value}"
    )
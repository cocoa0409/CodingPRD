"""Entity assertions and domain invariant checkers for the Defibrillator
Program API. Uses framework generic validators internally."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

_CAMPUS_POSTURES = ["OPERATIONAL", "DEGRADED", "CRITICAL"]
_DEVICE_POSTURES = ["READY", "DEGRADED", "OUT_OF_SERVICE"]
_DEVICE_STATUSES = [
    "REGISTERED", "INSTALLED", "IN_SERVICE",
    "POST_EVENT", "MAINTENANCE", "DECOMMISSIONED",
]
_CABINET_STATUSES = ["EMPTY", "OCCUPIED", "ALARM_OPEN"]
_INSTALL_DISPOSITIONS = ["ACTIVE", "CONSUMED_IN_EVENT", "EXPIRED_REMOVED", "REPLACED"]
_INSPECTION_OUTCOMES = ["SCHEDULED", "PASS", "FAIL", "OVERDUE"]
_RESPONDER_ROLES = ["LAY_RESPONDER", "MEDICAL_DIRECTOR", "PROGRAM_MANAGER", "INSPECTOR"]
_RESPONDER_STATUSES = ["ACTIVE", "SUSPENDED", "INACTIVE"]
_SESSION_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
_EVENT_STATUSES = ["OPEN", "RESPONDING", "RESOLVED", "CASE_REVIEW", "CLOSED"]
_REVIEW_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REOPENED"]
_ORDER_STATUSES = ["PENDING", "RECEIVED", "CANCELLED"]
_KINDS = ["PAD", "BATTERY"]
_SELFTEST_STATUSES = ["PASS", "FAIL", "UNKNOWN"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_campus(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["jurisdiction_registration_number"], str)
    assert isinstance(data["medical_director_id"], str)
    assert isinstance(data["response_time_target_seconds"], int)
    assert data["readiness_posture"] in _CAMPUS_POSTURES


def assert_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campus_id"], str)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["floor_area_sqm"], int)
    assert isinstance(data["avg_walk_speed_mps"], (int, float))
    assert isinstance(data["requires_elevator"], bool)
    assert isinstance(data["elevator_delay_seconds"], int)


def assert_device_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]
    assert isinstance(data["pad_shelf_life_months"], int)
    assert isinstance(data["battery_shelf_life_months"], int)
    assert isinstance(data["prescription_required"], bool)


def assert_cabinet(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_id"], str)
    assert isinstance(data["location_label"], str)
    assert isinstance(data["centroid_x_m"], (int, float))
    assert isinstance(data["centroid_y_m"], (int, float))
    assert data["status"] in _CABINET_STATUSES
    assert "installed_device_id" in data


def assert_device(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campus_id"], str)
    assert isinstance(data["device_model_id"], str)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["status"] in _DEVICE_STATUSES
    assert data["readiness_posture"] in _DEVICE_POSTURES
    assert data["last_selftest_status"] in _SELFTEST_STATUSES
    assert "cabinet_id" in data
    assert "current_pad_install_id" in data
    assert "current_battery_install_id" in data
    assert "last_inspection_at" in data


def assert_consumable_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campus_id"], str)
    assert isinstance(data["device_model_id"], str)
    assert data["kind"] in _KINDS
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["quantity_received"], int)
    assert isinstance(data["quantity_available"], int)
    assert data["quantity_available"] <= data["quantity_received"]


def assert_install(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["device_id"], str)
    assert isinstance(data["consumable_lot_id"], str)
    assert data["kind"] in _KINDS
    assert data["disposition"] in _INSTALL_DISPOSITIONS
    assert is_iso8601_timestamp(data.get("installed_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["device_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert is_iso8601_timestamp(data.get("scheduled_for", ""))
    assert data["outcome"] in _INSPECTION_OUTCOMES


def assert_self_test_report(data: dict):
    # Immutable telemetry: id + created_at only; no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "version" not in data, "SelfTestReport must not carry version"
    assert "updated_at" not in data, "SelfTestReport must not carry updated_at"
    assert isinstance(data["device_id"], str)
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert data["result"] in ["PASS", "FAIL"]


def assert_responder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campus_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["badge_number"], str) and data["badge_number"]
    assert data["responder_role"] in _RESPONDER_ROLES
    assert data["status"] in _RESPONDER_STATUSES
    assert "certified_through" in data


def assert_training_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campus_id"], str)
    assert isinstance(data["instructor_id"], str)
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["capacity"], int)
    assert isinstance(data["certification_months_granted"], int)
    assert data["status"] in _SESSION_STATUSES


def assert_emergency_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campus_id"], str)
    assert isinstance(data["cabinet_id"], str)
    assert isinstance(data["device_id"], str)
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert data["status"] in _EVENT_STATUSES


def assert_case_review(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["emergency_event_id"], str)
    assert isinstance(data["reviewer_id"], str)
    assert data["status"] in _REVIEW_STATUSES


def assert_replenishment_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campus_id"], str)
    assert data["kind"] in _KINDS
    assert isinstance(data["quantity"], int)
    assert data["status"] in _ORDER_STATUSES


def assert_device_posture_invariants(data: dict):
    """Posture ladder invariants that must hold on any device payload."""
    posture = data["readiness_posture"]
    status = data["status"]
    if status in ("POST_EVENT", "MAINTENANCE", "DECOMMISSIONED"):
        assert posture == "OUT_OF_SERVICE", (
            f"Device in {status} must be OUT_OF_SERVICE, got {posture}"
        )
    assert posture in _DEVICE_POSTURES


def assert_campus_posture_value(data: dict):
    assert data["readiness_posture"] in _CAMPUS_POSTURES

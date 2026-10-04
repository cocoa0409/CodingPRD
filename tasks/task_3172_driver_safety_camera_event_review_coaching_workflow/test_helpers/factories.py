"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_fleet_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["FLEET_NAME"],
        "incentive_budget_cents": TEST_DEFAULTS["FLEET_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_terminal_payload(fleet_id, **overrides) -> dict:
    defaults = {
        "fleet_id": fleet_id,
        "name": TEST_DEFAULTS["TERMINAL_NAME"],
        "region_code": TEST_DEFAULTS["TERMINAL_REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "employee_ref": TEST_DEFAULTS["DRIVER_EMPLOYEE_REF"],
        "name": TEST_DEFAULTS["DRIVER_NAME"],
        "hire_date": TEST_DEFAULTS["DRIVER_HIRE_DATE"],
        "inward_camera_consent": True,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "vin": TEST_DEFAULTS["VEHICLE_VIN"],
        "camera_unit_id": TEST_DEFAULTS["VEHICLE_CAMERA_UNIT_ID"],
        "bandwidth_tier": TEST_DEFAULTS["VEHICLE_BANDWIDTH_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_union_agreement_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "agreement_code": "CBA-2026-01",
        "inward_camera_allowed": False,
        "live_view_allowed": False,
        "audio_recording_allowed": False,
        "coaching_requires_steward_present": False,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_until": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_camera_policy_payload(fleet_id, **overrides) -> dict:
    defaults = {
        "fleet_id": fleet_id,
        "name": TEST_DEFAULTS["POLICY_NAME"],
        "retention_days_standard": TEST_DEFAULTS["POLICY_RETENTION_DAYS_STANDARD"],
        "retention_days_collision": TEST_DEFAULTS["POLICY_RETENTION_DAYS_COLLISION"],
        "daily_upload_cap_mb": TEST_DEFAULTS["POLICY_DAILY_UPLOAD_CAP_MB"],
        "inward_capture_enabled": True,
        "distraction_detection_enabled": True,
        "seatbelt_detection_enabled": True,
        "effective_from": TEST_DEFAULTS["POLICY_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_safety_event_payload(fleet_id, driver_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "fleet_id": fleet_id,
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "event_type": "HARSH_BRAKE",
        "severity": "LOW",
        "occurred_at": "2026-08-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_footage_clip_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "camera_angle": "FORWARD",
        "size_mb": 5,
        "captured_at": "2026-08-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def review_payload(action, expected_event_version, rationale="reviewed", **overrides) -> dict:
    defaults = {
        "action": action,
        "rationale": rationale,
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_manual_session_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "starts_at": "2026-09-02T10:00:00Z",
        "ends_at": "2026-09-02T11:00:00Z",
        "due_at": "2026-09-09T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def reassign_session_payload(**overrides) -> dict:
    defaults = {
        "starts_at": "2026-09-05T10:00:00Z",
        "ends_at": "2026-09-05T11:00:00Z",
        "due_at": "2026-09-12T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_litigation_hold_payload(fleet_id, **overrides) -> dict:
    defaults = {
        "fleet_id": fleet_id,
        "scope": "EVENT",
        "reason": "matter M-1",
    }
    defaults.update(overrides)
    return defaults


def create_exoneration_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_ref": "CLM-1",
    }
    defaults.update(overrides)
    return defaults


def decide_claim_payload(decision="EXONERATE", rationale="reviewed", **overrides) -> dict:
    defaults = {
        "decision": decision,
        "rationale": rationale,
    }
    defaults.update(overrides)
    return defaults


def compute_snapshot_payload(**overrides) -> dict:
    defaults = {
        "scope_type": "DRIVER",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-31T23:59:59Z",
        "finalize": False,
    }
    defaults.update(overrides)
    return defaults

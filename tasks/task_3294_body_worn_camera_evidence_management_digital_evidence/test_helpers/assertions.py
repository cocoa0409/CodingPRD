"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str) and len(data["timezone"]) > 0
    assert isinstance(data["storage_used_bytes"], int) and data["storage_used_bytes"] >= 0
    assert data["storage_posture"] in ["OK", "WARNING", "OVER_BUDGET"]


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["recording_triggers"], list) and len(data["recording_triggers"]) >= 1
    assert isinstance(data["tagging_required"], bool)
    assert isinstance(data["supervisor_review_rate_pct"], int)
    assert 0 <= data["supervisor_review_rate_pct"] <= 100
    assert isinstance(data["default_share_expiry_days"], int)
    assert 1 <= data["default_share_expiry_days"] <= 90
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED"]


def assert_budget_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year_start_month"], int)
    assert 1 <= data["fiscal_year_start_month"] <= 12
    assert isinstance(data["monthly_budget_cents"], int)
    assert isinstance(data["cost_per_gb_month_cents"], int)
    assert isinstance(data["alert_threshold_pct"], int)
    assert 1 <= data["alert_threshold_pct"] <= 99
    assert isinstance(data["effective_from_month"], str)
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_officer(data: dict):
    _assert_common(data)
    assert isinstance(data["badge_number"], str) and len(data["badge_number"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["rank"] in ["OFFICER", "CORPORAL", "SERGEANT", "LIEUTENANT"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "RETIRED"]
    assert isinstance(data["recordings_uploaded_count"], int)
    assert data["recordings_uploaded_count"] >= 0
    assert isinstance(data["pending_review_count"], int)
    assert data["pending_review_count"] >= 0


def assert_device(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert isinstance(data["model"], str) and len(data["model"]) > 0
    assert isinstance(data["battery_pct"], int) and 0 <= data["battery_pct"] <= 100
    assert data["assignment_status"] in ["UNASSIGNED", "ASSIGNED"]
    assert data["dock_status"] in ["DOCKED", "UNDOCKED"]
    assert data["health_status"] in ["HEALTHY", "RETIRED"]
    if data["assignment_status"] == "ASSIGNED":
        assert isinstance(data.get("assigned_officer_id"), str)
    else:
        assert data.get("assigned_officer_id") is None


def assert_recording(data: dict):
    _assert_common(data)
    assert isinstance(data["trigger_code"], str)
    assert isinstance(data["duration_seconds"], int) and 1 <= data["duration_seconds"] <= 14400
    assert isinstance(data["size_bytes"], int) and data["size_bytes"] >= 1
    assert is_iso8601_timestamp(data["recorded_at"])
    h = data["content_hash_sha256"]
    assert isinstance(h, str) and len(h) == 64
    if data.get("category") is not None:
        assert data["category"] in ["INCIDENT", "ARREST", "TRAFFIC_STOP", "TRAINING", "TEST"]
    assert data["upload_status"] in [
        "RECEIVED", "INTEGRITY_VERIFIED", "INTEGRITY_FAILED",
        "ACTIVE", "RETENTION_DUE", "PURGED",
    ]
    assert data["review_status"] in ["NOT_FLAGGED", "PENDING_REVIEW", "REVIEWED"]
    assert isinstance(data["integrity_check_count"], int)
    assert data["integrity_check_count"] >= 0
    assert isinstance(data["legal_hold_count"], int) and data["legal_hold_count"] >= 0


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["case_number"], str) and len(data["case_number"]) > 0
    assert isinstance(data["title"], str)
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "CLOSED", "ARCHIVED"]
    assert isinstance(data["lead_officer_id"], str)
    assert isinstance(data["evidence_count"], int) and data["evidence_count"] >= 0
    assert isinstance(data["total_evidence_bytes"], int) and data["total_evidence_bytes"] >= 0


def assert_evidence_link(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["recording_id"], str)
    assert isinstance(data["linked_by_officer_id"], str)
    assert data["status"] in ["LINKED", "UNLINKED"]


def assert_redaction_job(data: dict):
    _assert_common(data)
    assert isinstance(data["recording_id"], str)
    assert isinstance(data["request_reference"], str)
    assert isinstance(data["scope_face"], bool)
    assert isinstance(data["scope_audio"], bool)
    assert data["passes"] in ["SINGLE_PASS", "MULTI_PASS"]
    assert isinstance(data["estimated_minutes"], int) and data["estimated_minutes"] >= 1
    assert data["status"] in [
        "QUEUED", "IN_PROGRESS", "SUBMITTED", "APPROVED",
        "RELEASED", "RETURNED", "CANCELLED",
    ]


def assert_share_grant(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["recipient_role"] in ["PROSECUTOR", "DEFENSE"]
    assert isinstance(data["recipient_email"], str)
    assert isinstance(data["access_token"], str) and len(data["access_token"]) > 0
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["access_count"], int) and data["access_count"] >= 0
    assert data["status"] in ["ACTIVE", "REVOKED", "EXPIRED"]


def assert_legal_hold(data: dict):
    _assert_common(data)
    assert data["scope_type"] in ["RECORDING", "CASE"]
    assert isinstance(data["authority_reference"], str)
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_audit_log_entry(data: dict):
    # append-only: id + created_at only, no updated_at / version
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only log entries must not carry updated_at"
    assert "version" not in data, "append-only log entries must not carry version"
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["entity_type"], str)
    assert isinstance(data["entity_id"], str)


def assert_custody_event(data: dict):
    # append-only: id + created_at only, no updated_at / version
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "custody events must not carry updated_at"
    assert "version" not in data, "custody events must not carry version"
    assert isinstance(data["recording_id"], str)
    assert data["event_type"] in [
        "UPLOADED", "HASH_VERIFIED", "HASH_MISMATCH", "CASE_LINKED", "CASE_UNLINKED",
        "REDACTION_STARTED", "REDACTION_RELEASED", "SHARED", "ACCESSED",
        "HOLD_PLACED", "HOLD_RELEASED", "PURGE_EXECUTED",
    ]
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)

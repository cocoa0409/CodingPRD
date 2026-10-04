"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive integer"
    )


def assert_fleet(data: dict):
    _assert_common_fields(data, "Fleet")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["incentive_budget_cents"], int)
    assert data["posture"] in ["NORMAL", "INCIDENT_LOCKDOWN"]
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    assert isinstance(data["retention_used_mb"], int) and data["retention_used_mb"] >= 0


def assert_terminal(data: dict):
    _assert_common_fields(data, "Terminal")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert "safety_score_cached" in data


def assert_driver(data: dict):
    _assert_common_fields(data, "Driver")
    assert isinstance(data["employee_ref"], str) and len(data["employee_ref"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED", "COACHING_HOLD", "INACTIVE"]
    assert isinstance(data["confirmed_events_90d"], int) and data["confirmed_events_90d"] >= 0
    assert "safety_score_provisional" in data
    assert "safety_score_final" in data
    assert data.get("incentive_tier") in ["GOLD", "SILVER", "BRONZE", "NONE"]


def assert_vehicle(data: dict):
    _assert_common_fields(data, "Vehicle")
    assert isinstance(data["vin"], str) and len(data["vin"]) > 0
    assert data["bandwidth_tier"] in ["LOW", "STANDARD", "HIGH"]
    assert data["status"] in ["ACTIVE", "DECOMMISSIONED"]


def assert_union_agreement(data: dict):
    _assert_common_fields(data, "UnionAgreement")
    assert isinstance(data["agreement_code"], str) and len(data["agreement_code"]) > 0
    assert data["status"] in ["DRAFT", "RATIFIED", "EXPIRED"]


def assert_camera_policy(data: dict):
    _assert_common_fields(data, "CameraPolicy")
    assert isinstance(data["retention_days_standard"], int)
    assert isinstance(data["retention_days_collision"], int)
    assert isinstance(data["daily_upload_cap_mb"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "ARCHIVED"]


def assert_safety_event(data: dict):
    _assert_common_fields(data, "SafetyEvent")
    assert data["event_type"] in [
        "HARSH_BRAKE", "FOLLOWING_DISTANCE", "DISTRACTION", "SEAT_BELT", "COLLISION",
    ]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in [
        "DETECTED", "IN_REVIEW", "CONFIRMED", "DISMISSED", "RECLASSIFIED", "EXONERATED",
    ]
    assert isinstance(data["upload_priority_score"], int)
    assert isinstance(data["review_count"], int) and data["review_count"] >= 0


def assert_review_decision(data: dict):
    """ReviewDecision is append-only: carries only id + created_at among the
    common fields; updated_at and version are absent entirely."""
    assert is_valid_uuid(data.get("id", "")), "ReviewDecision.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ReviewDecision.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ReviewDecision must not carry updated_at"
    assert "version" not in data, "ReviewDecision must not carry version"
    assert data["action"] in ["CONFIRM", "DISMISS", "RECLASSIFY", "REOPEN"]
    assert isinstance(data["reviewer_id"], str) and len(data["reviewer_id"]) > 0


def assert_footage_clip(data: dict):
    _assert_common_fields(data, "FootageClip")
    assert data["camera_angle"] in ["FORWARD", "INWARD", "SIDE"]
    assert isinstance(data["size_mb"], int) and data["size_mb"] >= 1
    assert data["upload_status"] in ["QUEUED", "UPLOADING", "UPLOADED", "PURGED"]
    assert data["retention_class"] in ["STANDARD", "COLLISION", "LITIGATION_HOLD"]


def assert_coaching_session(data: dict):
    _assert_common_fields(data, "CoachingSession")
    assert data["status"] in ["ASSIGNED", "ACKNOWLEDGED", "OVERDUE", "COMPLETED", "CANCELLED"]
    assert isinstance(data["reassign_count"], int) and data["reassign_count"] >= 0
    assert "assigned_by" in data


def assert_escalation_case(data: dict):
    _assert_common_fields(data, "EscalationCase")
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "RESOLVED_ACTION", "RESOLVED_NO_ACTION"]
    assert isinstance(data["offense_count"], int) and data["offense_count"] >= 1
    assert data["window_days"] == 90


def assert_exoneration_claim(data: dict):
    _assert_common_fields(data, "ExonerationClaim")
    assert data["status"] in ["SUBMITTED", "EVIDENCE_REVIEW", "EXONERATED", "REJECTED"]
    assert isinstance(data["claim_ref"], str) and len(data["claim_ref"]) > 0


def assert_litigation_hold(data: dict):
    _assert_common_fields(data, "LitigationHold")
    assert data["scope"] in ["DRIVER", "EVENT"]
    assert data["status"] in ["ACTIVE", "RELEASED"]
    assert isinstance(data["placed_by"], str) and len(data["placed_by"]) > 0


def assert_score_snapshot(data: dict):
    _assert_common_fields(data, "SafetyScoreSnapshot")
    assert data["scope_type"] in ["DRIVER", "TERMINAL", "FLEET"]
    assert data["status"] in ["PROVISIONAL", "FINAL"]
    assert "score" in data


def assert_incentive_award(data: dict):
    _assert_common_fields(data, "IncentiveAward")
    assert data["tier"] in ["GOLD", "SILVER", "BRONZE", "NONE"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ["PROJECTED", "APPROVED", "PAID", "FORFEITED"]

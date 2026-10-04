"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_skeleton(data: dict):
    """Every top-level resource carries id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_account(data: dict):
    assert_common_skeleton(data)
    assert data["account_type"] in ("RIDER", "DRIVER")
    assert isinstance(data["home_region_code"], str) and data["home_region_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["status"] in (
        "ACTIVE", "UNDER_HOLD", "PENDING_DECISION", "RESTRICTED",
        "DEACTIVATED", "APPEAL_PENDING", "REINSTATED",
    )
    assert data["safety_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["risk_tier"] in ("TIER_LOW", "TIER_ELEVATED", "TIER_HIGH", "TIER_SEVERE")
    assert 0 <= data["risk_score"] <= 1000
    assert isinstance(data["standing_enforcement_count"], int)
    assert data["standing_enforcement_count"] >= 0
    assert isinstance(data["deactivation_count"], int)
    assert data["deactivation_count"] >= 0
    assert isinstance(data["prior_reinstatement_count"], int)
    assert data["prior_reinstatement_count"] >= 0
    assert isinstance(data["policy_generation_index"], int)


def assert_device_cluster(data: dict):
    assert_common_skeleton(data)
    assert isinstance(data["cluster_key"], str) and data["cluster_key"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["status"] in ("OPEN", "WATCHLIST", "BANNED")
    assert data["aggregate_cluster_risk"] >= 0
    assert isinstance(data["clustered_actor_incident_count"], int)
    assert data["clustered_actor_incident_count"] >= 0
    assert isinstance(data["cluster_risk_generation_index"], int)


def assert_account_device_link(data: dict):
    assert_common_skeleton(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["device_cluster_id"])
    assert isinstance(data["fingerprint_hash"], str) and data["fingerprint_hash"]
    assert is_iso8601_timestamp(data["first_seen_at"])
    assert is_iso8601_timestamp(data["last_seen_at"])
    assert data["link_status"] in ("LINKED", "DORMANT", "SEVERED")


def assert_trip(data: dict):
    assert_common_skeleton(data)
    assert is_valid_uuid(data["rider_account_id"])
    assert is_valid_uuid(data["driver_account_id"])
    assert data["status"] in ("REQUESTED", "COMPLETED_PENDING", "COMPLETED", "CANCELLED")
    if data["status"] in ("REQUESTED", "COMPLETED_PENDING"):
        assert data.get("completed_at") is None, "completed_at must be null before COMPLETED"
    elif data["status"] == "COMPLETED":
        assert is_iso8601_timestamp(data["completed_at"])


def assert_incident(data: dict):
    assert_common_skeleton(data)
    assert is_valid_uuid(data["account_id"])
    assert data["reporter_type"] in ("RIDER", "DRIVER", "THIRD_PARTY")
    assert data["incident_category"] in (
        "PHYSICAL_ASSAULT", "SEXUAL_MISCONDUCT", "HARASSMENT", "SAFETY_VIOLATION",
        "FRAUD_IDENTITY", "DISCRIMINATION", "PROPERTY_DAMAGE",
    )
    assert data["severity"] in ("S1", "S2", "S3", "S4")
    assert isinstance(data["derivative_severity_flagged"], bool)
    assert data["incident_status"] in (
        "OPEN", "INVESTIGATING", "PENDING_DECISION", "MANDATORY_REPORTED_BLOCKED",
        "DECIDED", "APPEAL_PENDING", "APPEAL_UPHELD", "APPEAL_OVERTURNED", "WITHDRAWN",
    )
    assert data["decision_category"] in (
        "PENDING", "NO_ACTION", "WARNING", "RESTRICTED", "DEACTIVATED",
    )
    assert 100 <= data["cluster_risk_multiplier_pct"] <= 300
    assert isinstance(data["prior_incident_count_at_intake"], int)


def assert_evidence(data: dict):
    assert_common_skeleton(data)
    assert is_valid_uuid(data["incident_id"])
    assert data["evidence_type"] in (
        "TRIP_DATA", "IN_APP_MESSAGE", "RATINGS_HISTORY", "LAW_ENFORCEMENT_CONTACT",
        "DEVICE_LINK", "EXTERNAL_RECORD",
    )
    assert data["evidence_weight"] in ("WEAK", "STANDARD", "STRONG", "DISPOSITIVE")
    assert data["evidence_status"] in ("PENDING", "INCLUDED", "EXCLUDED")
    assert is_iso8601_timestamp(data["recorded_at"])
    if data["evidence_status"] in ("PENDING", "INCLUDED"):
        assert data.get("exclusion_reason") is None


def assert_enforcement_action(data: dict):
    assert_common_skeleton(data)
    assert is_valid_uuid(data["account_id"])
    assert data["outcome"] in ("WARNING", "RESTRICTED", "DEACTIVATED")
    assert data["enforcement_status"] in (
        "DRAFT", "ACTIVE", "MANDATORY_REPORTED", "APPEAL_PENDING", "REVERTED", "EXPIRED",
    )
    assert isinstance(data["regulator_report_required"], bool)
    assert isinstance(data["rehabilitation_credit"], int)
    assert data["rehabilitation_credit"] >= 0
    assert isinstance(data["reinstatement_generation"], int)


def assert_regulator_report(data: dict):
    assert_common_skeleton(data)
    assert is_valid_uuid(data["incident_id"])
    assert data["report_channel"] in ("REGULATOR_PORTAL", "LAW_ENFORCEMENT")
    assert data["filing_basis"] in (
        "PENDING", "ROLLUP_THRESHOLD", "ALWAYS_LAW_ENFORCEMENT", "BLOCKED_WINDOW_TRIGGER",
    )
    assert data["report_status"] in ("BACKLOG", "BLOCKED", "FILED")
    assert isinstance(data["region_code"], str) and data["region_code"]


def assert_background_check(data: dict):
    assert_common_skeleton(data)
    assert is_valid_uuid(data["account_id"])
    assert data["check_kind"] in ("CONTINUOUS_MONITOR", "RESCREEN")
    assert data["check_status"] in ("SCHEDULED", "IN_REVIEW", "COMPLETED")
    assert data["adjudication"] in ("PENDING", "CLEAR", "ADVERSE", "INCONCLUSIVE")
    assert data["trigger_source"] in ("CONTINUOUS", "CADENCE")
    assert isinstance(data["monitor_generation"], int)


def assert_platform_policy(data: dict):
    assert_common_skeleton(data)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["sd_floor_severity"] in ("S1", "S2", "S3", "S4")
    assert isinstance(data["sd_floor_enabled"], bool)
    assert isinstance(data["escalation_enabled"], bool)
    assert isinstance(data["review_generation_index"], int)
    assert isinstance(data["knob_generation_index"], int)


def assert_incident_invariants(data: dict):
    """Domain invariants that must hold after any operation on an incident."""
    assert data["severity"] in ("S1", "S2", "S3", "S4")
    assert data["incident_status"] in (
        "OPEN", "INVESTIGATING", "PENDING_DECISION", "MANDATORY_REPORTED_BLOCKED",
        "DECIDED", "APPEAL_PENDING", "APPEAL_UPHELD", "APPEAL_OVERTURNED", "WITHDRAWN",
    )
    if data["incident_status"] in ("DECIDED", "APPEAL_UPHELD", "APPEAL_OVERTURNED"):
        assert data["decision_category"] != "PENDING", (
            "a decided incident must carry a committed decision category"
        )


def assert_account_invariants(data: dict):
    """Derived-field invariants that must hold after any account mutation."""
    assert 0 <= data["risk_score"] <= 1000
    if data["status"] == "APPEAL_PENDING":
        assert data["safety_posture"] == "FROZEN"
    elif data["status"] == "RESTRICTED" or data["standing_enforcement_count"] >= 1:
        assert data["safety_posture"] == "RESTRICTED"
    else:
        assert data["safety_posture"] == "OPEN"
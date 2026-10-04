"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_registered_entity(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("registration_functions"), list) and data["registration_functions"]
    assert data.get("compliance_status") in ("ACTIVE", "RESTRICTED")
    assert isinstance(data.get("applicable_standards"), list)
    assert isinstance(data.get("applicable_standard_count"), int)
    assert isinstance(data.get("open_violation_count"), int)
    assert isinstance(data.get("unresolved_appeal_count"), int)
    assert isinstance(data.get("enrollment_self_logging"), bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_engagement(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("entity_id", ""))
    assert data.get("engagement_type") in ("AUDIT", "SPOT_CHECK", "SELF_CERTIFICATION")
    assert isinstance(data.get("standard_ids"), list) and data["standard_ids"]
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data.get("status") in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data.get("coverage_fraction"), (int, float))
    assert isinstance(data.get("version"), int)


def assert_evidence_artifact(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert isinstance(data.get("standard_id"), str) and data["standard_id"]
    assert data.get("artifact_kind") in ("OPERATING_RECORD", "ACCESS_LOG", "MAINTENANCE_RECORD")
    assert is_iso8601_timestamp(data.get("coverage_start", ""))
    assert is_iso8601_timestamp(data.get("coverage_end", ""))
    assert data.get("status") in ("SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data.get("version"), int)


def assert_self_report(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("entity_id", ""))
    assert data.get("status") in ("RECEIVED", "TRIAGED", "CONFIRMED", "DISMISSED")
    assert isinstance(data.get("version"), int)


def assert_violation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("entity_id", ""))
    assert data.get("source_type") in ("AUDIT", "SPOT_CHECK", "SELF_REPORT", "SELF_LOG")
    assert data.get("violation_risk_factor") in ("MINIMAL", "MODERATE", "SERIOUS")
    assert data.get("severity_level") in ("LOWER", "MODERATE", "HIGH", "SEVERE")
    assert data.get("status") in (
        "OPEN", "MITIGATION_SUBMITTED", "MITIGATION_IN_PROGRESS",
        "MITIGATION_COMPLETE", "APPEALED", "CLOSED", "DISMISSED",
    )
    assert isinstance(data.get("version"), int)


def assert_mitigation_plan(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("violation_id", ""))
    assert data.get("status") in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "VERIFIED")
    assert isinstance(data.get("version"), int)


def assert_milestone(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data.get("title"), str) and data["title"]
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert data.get("status") in ("PENDING", "COMPLETED", "MISSED")
    assert isinstance(data.get("version"), int)


def assert_self_log_entry(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("entity_id", ""))
    assert data.get("status") in ("LOGGED", "REVIEWED_OK", "ESCALATED")
    assert isinstance(data.get("version"), int)


def assert_review_period(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ("OPEN", "REVIEWING", "CLOSED")
    assert isinstance(data.get("entry_count"), int)
    assert isinstance(data.get("reviewed_ok_count"), int)
    assert isinstance(data.get("escalated_count"), int)
    assert isinstance(data.get("version"), int)


def assert_cip_asset(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("entity_id", ""))
    assert data.get("impact_rating") in ("HIGH", "MEDIUM", "LOW")
    assert isinstance(data.get("is_bes_cyber_asset"), bool)
    assert data.get("status") in ("ACTIVE", "DECOMMISSIONED")
    assert isinstance(data.get("version"), int)


def assert_access_grant(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data.get("scope") in ("PHYSICAL", "ELECTRONIC")
    assert data.get("status") in ("ACTIVE", "REVOKED")
    assert isinstance(data.get("version"), int)


def assert_penalty(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("violation_id", ""))
    assert isinstance(data.get("amount"), (int, float))
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert data.get("status") in ("ASSESSED", "CONFIRMED", "SETTLED", "WAIVED")
    assert isinstance(data.get("version"), int)


def assert_appeal(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("violation_id", ""))
    assert data.get("status") in (
        "APPEAL_PENDING_REVIEW", "APPEAL_GRANTED", "APPEAL_DENIED",
        "FEDERAL_REVIEW_REQUESTED",
    )
    assert isinstance(data.get("version"), int)

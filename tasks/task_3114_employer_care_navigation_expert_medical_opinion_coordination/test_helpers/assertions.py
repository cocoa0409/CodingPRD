"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["pepm_fee_cents"], int)
    assert isinstance(data["avg_in_out_cost_delta_cents"], int)
    assert isinstance(data["emo_benefit_enabled"], bool)


def assert_member(data: dict):
    _assert_common(data)
    assert data["relationship"] in ("SELF", "SPOUSE", "CHILD")
    assert data["eligibility_status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["deductible_limit_cents"], int)
    assert isinstance(data["oop_max_cents"], int)
    assert isinstance(data["deductible_used_cents"], int)
    assert isinstance(data["oop_used_cents"], int)


def assert_coverage_window(data: dict):
    _assert_common(data)
    assert data["coverage_tier"] in (
        "EMPLOYEE_ONLY", "EMPLOYEE_SPOUSE", "EMPLOYEE_CHILDREN", "FAMILY")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["effective_start"], str)


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["specialty"], str)
    assert data["network_status"] in ("IN_NETWORK", "OUT_OF_NETWORK")


def assert_quality_snapshot(data: dict):
    _assert_common(data)
    assert isinstance(data["claims_volume"], int)
    assert "composite_quality_score" in data


def assert_consent(data: dict):
    _assert_common(data)
    assert data["scope"] in (
        "RECORD_RETRIEVAL", "APPOINTMENT_BOOKING", "EMO_REVIEW", "BILLING_ADVOCACY")
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")


def assert_navigation_case(data: dict):
    _assert_common(data)
    assert data["question_type"] in ("CLINICAL", "BENEFIT", "COST")
    assert data["routed_discipline"] in ("NURSE", "ADVOCATE", "PHYSICIAN")
    assert data["status"] in (
        "ROUTED", "IN_PROGRESS", "ESCALATED", "RESOLVED", "CLOSED")
    assert isinstance(data["escalation_count"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["slot_start"], str)
    assert isinstance(data["slot_end"], str)


def assert_record_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "RECEIVED", "FAILED", "CANCELLED")
    assert isinstance(data["retry_count"], int)


def assert_expert_opinion(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "INTAKE", "RECORDS_COLLECTION", "COMPILING", "READY_FOR_REVIEW",
        "IN_REVIEW", "CHANGES_REQUESTED", "RECOMMENDATION_SUBMITTED",
        "RECORDS_BLOCKED", "AUTH_BLOCKED", "DELIVERED", "WITHDRAWN")
    assert isinstance(data["recommendation_version"], int)
    assert isinstance(data["attached_received_count"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "ADJUDICATED", "VOID")
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["error_line_count"], int)


def assert_billing_case(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPENED", "ERROR_IDENTIFIED", "NEGOTIATING", "SETTLEMENT_PROPOSED",
        "RESOLVED_ACCEPTED", "RESOLVED_NO_CHANGE", "VOIDED", "CLOSED")
    assert isinstance(data["proposal_count"], int)


def assert_authorization(data: dict):
    _assert_common(data)
    assert data["service_code"] in (
        "EXPERT_MEDICAL_OPINION", "PROCEDURE", "IMAGING")
    assert data["status"] in (
        "REQUESTED", "APPROVED", "DENIED", "APPEALED", "DENIED_FINAL")
    assert isinstance(data["units"], int)

"""Entity assertions — field-shape checks used across the test suite."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_curriculum_level(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["track"] in ["IMPROV", "SKETCH", "STANDUP", "CONSERVATORY"]
    assert isinstance(data["sequence_index"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert isinstance(data["allows_placement_bypass"], bool)
    assert isinstance(data["showcase_required"], bool)


def assert_term(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["status"] in ["DRAFT", "SCHEDULING", "ENROLLMENT_OPEN", "IN_SESSION", "CLOSED"]


def assert_instructor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str)
    assert data["status"] in ["ACTIVE", "ON_LEAVE", "INACTIVE"]
    assert isinstance(data["max_weekly_hours"], int)


def assert_section(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "OPEN", "LOCKED", "RUNNING", "COMPLETED", "CANCELLED"]
    assert isinstance(data["capacity"], int)
    assert isinstance(data["enrolled_count"], int)
    assert isinstance(data["waitlist_count"], int)


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["is_alumni"], bool)
    assert isinstance(data["completed_level_codes"], list)
    assert isinstance(data["placement_credit_codes"], list)


def assert_placement_evaluation(data: dict):
    _assert_common_fields(data)
    assert data["decision"] in ["SUBMITTED", "UNDER_REVIEW", "GRANTED", "DENIED", "APPEALED"]
    assert data["variant"] in ["AUDITION_BYPASS", "PORTFOLIO_REVIEW"]
    assert isinstance(data["portfolio_score"], int)


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "REGISTERED", "CONFIRMED", "WAITLISTED", "DROPPED_EARLY",
        "DROPPED_LATE", "TRANSFERRED_OUT", "COMPLETED", "CREDITED",
    ]
    assert data["priority_tier"] in ["RETURNING", "NEW"]


def assert_showcase(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PLANNED", "SCHEDULED", "STAGED", "ARCHIVED", "CANCELLED"]
    assert isinstance(data["is_industry"], bool)
    assert isinstance(data["performer_enrollment_ids"], list)


def assert_venue_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["venue_name"], str)
    assert data["status"] in ["AVAILABLE", "RESERVED", "BOOKED", "RELEASED"]


def assert_cohort_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["FORMING", "AUDITIONING", "CASTED", "ACTIVE", "GRADUATED", "DISSOLVED"]
    assert data["kind"] in ["CONSERVATORY", "INTENSIVE"]
    assert isinstance(data["cohort_size"], int)
    assert isinstance(data["admitted_count"], int)


def assert_audition(data: dict):
    _assert_common_fields(data)
    assert data["outcome"] in ["SCHEDULED", "EVALUATED", "SELECTED", "WAITLISTED", "REJECTED"]
    assert data["target_kind"] in ["COHORT", "ENSEMBLE", "TOURING"]
    assert isinstance(data["rubric_scores"], dict)


def assert_ensemble_cast(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN_ROLES", "CASTING", "REHEARSING", "RUNNING", "CLOSED"]
    assert data["source_policy"] in ["PIPELINE_ONLY", "OPEN_CALL", "MIXED"]
    assert isinstance(data["principal_ids"], list)
    assert isinstance(data["understudy_ids"], list)


def assert_touring_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PROPOSED", "ACCEPTED", "DECLINED", "ON_TOUR", "RETURNED", "REPLACED"]
    assert isinstance(data["travel_committed"], bool)


def assert_scholarship(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["APPLIED", "AWARDED", "DENIED", "DISBURSED", "REVOKED"]
    assert data["kind"] in ["NEED_BASED", "DIVERSITY", "MERIT"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["disbursed_cents"], int)


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ISSUED", "PARTIALLY_PAID", "PAID", "REFUNDED", "TRANSFERRED", "VOID"]
    for f in ("base_amount_cents", "scholarship_applied_cents", "amount_due_cents",
              "paid_cents", "refunded_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"

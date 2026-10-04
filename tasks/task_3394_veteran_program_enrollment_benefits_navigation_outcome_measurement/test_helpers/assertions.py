"""Entity assertions and domain invariant checkers.

Per PRD section 2.4, most resources expose id, created_at, updated_at and a
version integer; Assessment and DonorReport carry only id and created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lean_fields(data: dict):
    """For Assessment and DonorReport: only id + created_at are carried."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lean resource must not carry updated_at"
    assert "version" not in data, "lean resource must not carry version"


def assert_member(data: dict):
    _assert_common_fields(data)
    assert data["member_type"] in ("VETERAN", "FAMILY_SUPPORT")
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED")
    assert data["engagement_status"] in ("INACTIVE", "ENGAGED", "GRADUATED")
    assert isinstance(data["total_monthly_compensation_cents"], int)


def assert_eligibility_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("UNDER_REVIEW", "PENDED", "VERIFIED", "DENIED", "SUPERSEDED")


def assert_external_service_record(data: dict):
    _assert_common_fields(data)
    assert data["service_category"] in (
        "MENTAL_HEALTH", "PHYSICAL_HEALTH", "CAREER", "INDEPENDENCE", "BENEFITS")
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_program_track(data: dict):
    _assert_common_fields(data)
    assert data["track_code"] in ("MENTAL_HEALTH", "PHYSICAL_HEALTH", "CAREER", "INDEPENDENCE")
    assert isinstance(data["active_enrollment_count"], int)


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("INTAKE", "ACTIVE", "SUSPENDED", "COMPLETED", "WITHDRAWN")


def assert_assessment(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["acuity_score"], int) and 0 <= data["acuity_score"] <= 100
    assert data["tier_result"] in ("STANDARD", "ENHANCED", "INTENSIVE")


def assert_benefits_claim(data: dict):
    _assert_common_fields(data)
    assert data["claim_type"] in ("DISABILITY_COMPENSATION", "HEALTHCARE_ACCESS")
    assert data["status"] in ("FILED", "DECIDED", "APPEAL_PENDING", "CLOSED")


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "DECIDED")


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert data["required_specialty"] in ("PTSD", "TBI", "SUBSTANCE_USE", "DEPRESSION")
    assert data["status"] in (
        "PENDING_MATCH", "MATCHED", "IN_TREATMENT", "DISCHARGED", "EXPIRED", "SUPERSEDED")


def assert_partner_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["current_census"], int)
    assert data["current_census"] <= data["capacity"]


def assert_employer_partner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["open_requisitions"], int)


def assert_placement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "ACTIVE", "MILESTONE_30", "MILESTONE_90", "MILESTONE_180", "RETAINED", "SEPARATED")


def assert_community_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["registered_count"], int)
    assert isinstance(data["accessibility_seats_used"], int)
    assert isinstance(data["travel_budget_remaining_cents"], int)


def assert_event_registration(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "CONFIRMED", "WAITLISTED", "CANCELLED", "ATTENDED", "NO_SHOW", "EXPIRED")
    assert isinstance(data["travel_award_cents"], int)


def assert_outcome_survey(data: dict):
    _assert_common_fields(data)
    assert data["wave"] in ("BASELINE", "EXIT", "FOLLOWUP_90")
    assert data["status"] in ("SCHEDULED", "OPEN", "SUBMITTED", "EXPIRED")


def assert_donor_report(data: dict):
    _assert_lean_fields(data)
    assert data["methodology"] in ("ITT", "COMPLETER")
    assert isinstance(data["cohort_size_total"], int)
    assert isinstance(data["per_track"], list)


def assert_travel_budget_conserved(event: dict, active_awards: list):
    """travel_budget_remaining_cents + sum(non-cancelled awards) == travel_budget_cents."""
    total = event["travel_budget_remaining_cents"] + sum(active_awards)
    assert total == event["travel_budget_cents"], (
        f"travel budget not conserved: remaining {event['travel_budget_remaining_cents']} "
        f"+ awards {sum(active_awards)} != budget {event['travel_budget_cents']}")

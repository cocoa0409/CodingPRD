"""Entity assertions and domain invariant checkers.

Each assert_<entity>(data) validates the envelope payload of that entity:
system-managed field formats, input field round-trips, and enum membership.
Computed fields that are legitimately null before their lifecycle point
(e.g. national_weighted_score before quorum, final award figures before
confirmation) are type-checked only when present and non-null.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def _assert_enum(data: dict, field: str, allowed, entity: str):
    assert data.get(field) in allowed, \
        f"{entity}.{field} must be one of {sorted(allowed)}, got {data.get(field)!r}"


def _assert_optional_iso8601(data: dict, field: str, entity: str):
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), \
            f"{entity}.{field} must be ISO 8601 when present, got {value!r}"


def _assert_optional_int(data: dict, field: str, entity: str):
    value = data.get(field)
    if value is not None:
        assert isinstance(value, int) and not isinstance(value, bool), \
            f"{entity}.{field} must be an integer when present, got {value!r}"


def _assert_optional_number(data: dict, field: str, entity: str):
    value = data.get(field)
    if value is not None:
        assert isinstance(value, (int, float)) and not isinstance(value, bool), \
            f"{entity}.{field} must be numeric when present, got {value!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

CYCLE_STATUSES = {
    "DRAFT", "OPEN", "CLOSED", "SCREENING", "AWARDS_FINALIZED", "COMPLETED",
}
APPLICATION_STATUSES = {
    "DRAFT", "CAMPUS_REVIEW", "NATIONAL_SCREENING", "HOST_REVIEW", "SELECTED",
    "ALTERNATE", "PLACEMENT", "GRANT_PENDING", "AWARDED", "NOT_SELECTED",
    "WITHDRAWN", "DECLINED", "PLACEMENT_FAILED",
}
PLACEMENT_ROUND_STATUSES = {"OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"}
GRANT_STATUSES = {
    "PROVISIONAL", "CONFIRMED", "ACTIVE", "SUSPENDED", "COMPLETED",
    "TERMINATED_EARLY",
}
VISA_STATUSES = {"ISSUED", "ACTIVE", "COMPLETED", "ENDED_EARLY"}
LEDGER_STATUSES = {
    "PENDING", "ACCRUING", "WAIVER_PENDING", "FULFILLED", "WAIVED",
    "NOT_REQUIRED",
}
REPORT_STATUSES = {"SUBMITTED", "ACCEPTED", "NEEDS_REVISION"}
INCIDENT_STATUSES = {"OPEN", "RESOLVED"}


def assert_cycle(data: dict):
    _assert_common_fields(data, "CompetitionCycle")
    assert isinstance(data["academic_year"], str) and data["academic_year"]
    _assert_optional_iso8601(data, "application_deadline", "CompetitionCycle")
    assert "application_deadline" in data and data["application_deadline"]
    _assert_enum(data, "status", CYCLE_STATUSES, "CompetitionCycle")


def assert_country_program(data: dict):
    _assert_common_fields(data, "CountryProgram")
    assert is_valid_uuid(data.get("cycle_id", "")), \
        "CountryProgram.cycle_id must be a valid UUID"
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    for field in (
        "slot_quota", "min_duration_months", "max_duration_months",
        "monthly_stipend_standard_cents", "monthly_stipend_high_cents",
        "dependent_allowance_monthly_cents", "travel_allowance_cents",
        "health_benefit_monthly_cents", "slots_remaining",
    ):
        assert isinstance(data.get(field), int) and not isinstance(data[field], bool), \
            f"CountryProgram.{field} must be an integer"
    assert data["slots_remaining"] >= 0, "slots_remaining never negative"
    assert data["min_duration_months"] <= data["max_duration_months"]
    _assert_enum(
        data, "language_requirement",
        {"NONE", "BASIC", "PROFICIENT"}, "CountryProgram",
    )


def assert_applicant(data: dict):
    _assert_common_fields(data, "Applicant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    _assert_enum(
        data, "applicant_type",
        {"ENROLLED_STUDENT", "INDEPENDENT"}, "Applicant",
    )
    if data["applicant_type"] == "ENROLLED_STUDENT":
        assert data.get("home_institution_name"), \
            "home_institution_name is required for ENROLLED_STUDENT"
    assert isinstance(data["citizenship_country_code"], str) \
        and len(data["citizenship_country_code"]) == 2


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    for field in ("applicant_id", "cycle_id", "country_program_id"):
        assert is_valid_uuid(data.get(field, "")), \
            f"Application.{field} must be a valid UUID"
    assert isinstance(data["project_title"], str) and data["project_title"]
    assert isinstance(data["project_summary"], str)
    assert isinstance(data["proposed_duration_months"], int)
    assert isinstance(data["dependents_count"], int) and data["dependents_count"] >= 0
    assert isinstance(data["is_follow_on"], bool)
    _assert_enum(data, "status", APPLICATION_STATUSES, "Application")
    _assert_optional_iso8601(data, "submitted_at", "Application")
    _assert_optional_int(data, "recommend_seq", "Application")
    _assert_optional_number(data, "national_weighted_score", "Application")
    _assert_optional_int(data, "placement_rounds_used", "Application")
    if data.get("recommend_seq") is not None:
        assert data["recommend_seq"] >= 1, "recommend_seq is 1-based"
    if data.get("national_weighted_score") is not None:
        score = data["national_weighted_score"]
        assert 0 <= score <= 100, "weighted score within the 0-100 score range"


def assert_review_score(data: dict):
    # Append-only record: ONLY id + created_at are system-managed;
    # updated_at and version are absent (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "ReviewScore.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "ReviewScore.created_at must be ISO 8601"
    assert "updated_at" not in data, "ReviewScore carries no updated_at"
    assert "version" not in data, "ReviewScore carries no version"
    assert is_valid_uuid(data.get("application_id", "")), \
        "ReviewScore.application_id must be a valid UUID"
    _assert_enum(data, "stage", {"CAMPUS", "NATIONAL"}, "ReviewScore")
    assert isinstance(data["reviewer_id"], str) and data["reviewer_id"]
    for field in ("feasibility_score", "country_fit_score", "language_score"):
        value = data[field]
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        assert 0 <= value <= 100, f"ReviewScore.{field} within 0-100"


def assert_placement_round(data: dict):
    _assert_common_fields(data, "PlacementRound")
    assert is_valid_uuid(data.get("application_id", "")), \
        "PlacementRound.application_id must be a valid UUID"
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["institution_name"], str) and data["institution_name"]
    _assert_enum(data, "institution_band", {"STANDARD", "HIGH"}, "PlacementRound")
    assert is_iso8601_timestamp(data["response_deadline"])
    _assert_enum(data, "status", PLACEMENT_ROUND_STATUSES, "PlacementRound")
    _assert_optional_iso8601(data, "responded_at", "PlacementRound")


def assert_grant(data: dict):
    _assert_common_fields(data, "Grant")
    assert is_valid_uuid(data.get("application_id", "")), \
        "Grant.application_id must be a valid UUID"
    _assert_enum(data, "status", GRANT_STATUSES, "Grant")
    if data.get("awarded_band") is not None:
        _assert_enum(data, "awarded_band", {"STANDARD", "HIGH"}, "Grant")
    for field in (
        "provisional_monthly_stipend_cents", "provisional_total_cents",
        "final_monthly_stipend_cents", "final_total_cents",
        "earned_cents", "repayment_cents", "reconciliation_adjustment_cents",
        "duration_months", "suspension_days_total", "compliance_strikes",
    ):
        _assert_optional_int(data, field, "Grant")
    assert data.get("provisional_monthly_stipend_cents") is not None, \
        "provisional award is quoted at grant creation"
    assert data.get("provisional_total_cents") is not None
    assert data.get("suspension_days_total", 0) >= 0
    assert data.get("compliance_strikes", 0) >= 0
    _assert_optional_iso8601(data, "start_date", "Grant")
    _assert_optional_iso8601(data, "end_date", "Grant")
    _assert_optional_iso8601(data, "orientation_completed_at", "Grant")
    _assert_optional_iso8601(data, "interim_report_due_date", "Grant")
    _assert_optional_iso8601(data, "final_report_due_date", "Grant")


def assert_visa_sponsorship(data: dict):
    _assert_common_fields(data, "VisaSponsorship")
    assert is_valid_uuid(data.get("grant_id", "")), \
        "VisaSponsorship.grant_id must be a valid UUID"
    number = data.get("sponsor_program_number", "")
    assert isinstance(number, str) and number.startswith("EV-"), \
        'sponsor_program_number is "EV-" plus a six-digit sequence'
    digits = number[3:]
    assert len(digits) == 6 and digits.isdigit(), \
        "sponsor_program_number carries a six-digit sequence"
    assert isinstance(data["subject_to_home_residency"], bool)
    assert is_iso8601_timestamp(data["orientation_completed_at"])
    _assert_enum(data, "status", VISA_STATUSES, "VisaSponsorship")


def assert_residency_ledger(data: dict):
    _assert_common_fields(data, "ResidencyLedger")
    assert is_valid_uuid(data.get("visa_sponsorship_id", "")), \
        "ResidencyLedger.visa_sponsorship_id must be a valid UUID"
    _assert_enum(data, "status", LEDGER_STATUSES, "ResidencyLedger")
    assert data["required_days"] == 730, "the two-year requirement is 730 days"
    assert isinstance(data["accrued_days"], int) and data["accrued_days"] >= 0
    _assert_optional_iso8601(data, "accrual_start_date", "ResidencyLedger")
    stays = data.get("stays")
    assert isinstance(stays, list), "stays is a list of {start_date, end_date, day_count}"
    total = 0
    for stay in stays:
        assert set(stay.keys()) >= {"start_date", "end_date", "day_count"}
        assert isinstance(stay["day_count"], int) and stay["day_count"] >= 1
        total += stay["day_count"]
    assert total == data["accrued_days"], \
        "accrued_days is the running sum across all recorded stays"


def assert_report(data: dict):
    _assert_common_fields(data, "Report")
    assert is_valid_uuid(data.get("grant_id", "")), \
        "Report.grant_id must be a valid UUID"
    _assert_enum(data, "report_type", {"INTERIM", "FINAL"}, "Report")
    assert isinstance(data["content"], str)
    _assert_enum(data, "status", REPORT_STATUSES, "Report")
    assert is_iso8601_timestamp(data["submitted_at"]), \
        "submitted_at is stamped from the logical clock at first submission"
    assert isinstance(data["late"], bool)


def assert_incident(data: dict):
    _assert_common_fields(data, "EmergencyIncident")
    assert is_valid_uuid(data.get("grant_id", "")), \
        "EmergencyIncident.grant_id must be a valid UUID"
    _assert_enum(
        data, "category",
        {"MEDICAL", "SECURITY", "NATURAL_DISASTER", "CIVIL_UNREST"},
        "EmergencyIncident",
    )
    assert isinstance(data["description"], str)
    _assert_enum(data, "status", INCIDENT_STATUSES, "EmergencyIncident")
    assert is_iso8601_timestamp(data["opened_at"])
    _assert_optional_iso8601(data, "resolved_at", "EmergencyIncident")
    if data.get("outcome") is not None:
        _assert_enum(data, "outcome", {"RESUME", "TERMINATE"}, "EmergencyIncident")
    _assert_optional_int(data, "suspension_days", "EmergencyIncident")


def assert_alumni_profile(data: dict):
    _assert_common_fields(data, "AlumniProfile")
    assert is_valid_uuid(data.get("applicant_id", "")), \
        "AlumniProfile.applicant_id must be a valid UUID"
    assert is_valid_uuid(data.get("grant_id", "")), \
        "AlumniProfile.grant_id must be a valid UUID"
    assert isinstance(data["terminated_early"], bool)
    assert isinstance(data["compliance_strikes"], int) \
        and data["compliance_strikes"] >= 0
    for field in ("engagement_index_provisional", "engagement_index_certified"):
        value = data[field]
        assert isinstance(value, int) and not isinstance(value, bool)
        assert 0 <= value <= 100, \
            f"{field} is clamped to the range 0 through 100"
    _assert_enum(data, "residency_status", LEDGER_STATUSES, "AlumniProfile")
    _assert_enum(
        data, "follow_on_eligible",
        {"ELIGIBLE", "INELIGIBLE"}, "AlumniProfile",
    )


# ---------------------------------------------------------------------------
# Domain invariant checkers (PRD §2.10 conservation invariants)
# ---------------------------------------------------------------------------

def assert_slot_conservation(program_data: dict, consuming_count: int):
    """Slot conservation: slot_quota always equals slots_remaining plus the
    number of that program's applications in slot-consuming states
    (SELECTED, PLACEMENT, GRANT_PENDING, AWARDED)."""
    quota = program_data["slot_quota"]
    remaining = program_data["slots_remaining"]
    assert quota == remaining + consuming_count, (
        f"slot conservation violated: quota {quota} != slots_remaining "
        f"{remaining} + consuming {consuming_count}"
    )


def assert_award_conservation(grant_data: dict):
    """Award conservation at early termination: earned + repayment +
    reconciliation adjustment sum exactly to final_total_cents."""
    earned = grant_data["earned_cents"]
    repayment = grant_data["repayment_cents"]
    adjustment = grant_data["reconciliation_adjustment_cents"]
    total = grant_data["final_total_cents"]
    assert earned is not None and repayment is not None and adjustment is not None, \
        "termination figures are computed at early termination"
    assert earned + repayment + adjustment == total, (
        f"award conservation violated: {earned} + {repayment} + {adjustment} "
        f"!= final_total_cents {total}"
    )


def assert_engagement_index_bounds(profile_data: dict):
    """Engagement indices are integer points clamped to 0..100."""
    for field in ("engagement_index_provisional", "engagement_index_certified"):
        value = profile_data[field]
        assert isinstance(value, int) and 0 <= value <= 100

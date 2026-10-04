"""Entity assertions and domain invariant checkers.

assert_<entity>(data) validates the fields the PRD guarantees on a resource
body. Invariant checkers assert cross-field rules that must hold after any
operation (seat accounting, allowance conservation, inspection conjunction).
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationStatus,
    AssignmentOpeningStatus,
    BackgroundCheckStatus,
    CompletionType,
    CountryProgramStatus,
    DentalStatus,
    EtReason,
    InterviewRecommendation,
    InterviewStatus,
    InvitationStatus,
    LegalLifecycle,
    LegalOverallStatus,
    MedicalClearanceStatus,
    ServiceEventSeverity,
    ServiceEventType,
    SitePlacementStatus,
    SuitabilityStatus,
    TrainingCohortStatus,
    TrainingEnrollmentStatus,
    VolunteerServiceStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an int >= 1"


def assert_applicant(data: dict):
    _assert_common(data, "Applicant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert is_iso8601_timestamp(data["date_of_birth"])
    assert isinstance(data["citizenship_country"], str) and data["citizenship_country"]
    assert isinstance(data["skills"], list)
    assert isinstance(data["languages"], list)


def assert_country_program(data: dict):
    _assert_common(data, "CountryProgram")
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["medical_support_tier"] in (1, 2, 3)
    assert isinstance(data["required_language"], str) and data["required_language"]
    assert 1.0 <= data["language_threshold_score"] <= 5.0
    assert isinstance(data["training_capacity"], int) and data["training_capacity"] >= 1
    assert data["status"] in {s.value for s in CountryProgramStatus}


def assert_assignment_opening(data: dict):
    _assert_common(data, "AssignmentOpening")
    assert is_valid_uuid(data["country_program_id"])
    assert isinstance(data["sector"], str) and data["sector"]
    assert isinstance(data["title"], str)
    assert isinstance(data["required_skills"], list)
    assert isinstance(data["preferred_skills"], list)
    assert isinstance(data["seats_total"], int) and data["seats_total"] >= 1
    assert isinstance(data["seats_provisional"], int) and data["seats_provisional"] >= 0
    assert isinstance(data["seats_committed"], int) and data["seats_committed"] >= 0
    assert is_iso8601_timestamp(data["departure_date"])
    assert is_iso8601_timestamp(data["invitation_issue_deadline"])
    assert data["status"] in {s.value for s in AssignmentOpeningStatus}


def assert_application(data: dict):
    _assert_common(data, "Application")
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["country_preference_ids"], list)
    assert isinstance(data["sector_preferences"], list)
    assert isinstance(data["statement"], str)
    assert data["status"] in {s.value for s in ApplicationStatus}


def assert_interview(data: dict):
    _assert_common(data, "Interview")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["interviewer_id"], str) and data["interviewer_id"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in {s.value for s in InterviewStatus}
    if data["status"] == InterviewStatus.COMPLETED.value:
        for dim in ("motivation_score", "adaptability_score",
                    "skill_competency_score", "cross_cultural_score"):
            assert 1.0 <= data[dim] <= 5.0, f"{dim} in [1.0, 5.0]"
        assert 1.0 <= data["overall_score"] <= 5.0
        assert data["recommendation"] in {r.value for r in InterviewRecommendation}


def assert_invitation(data: dict):
    _assert_common(data, "Invitation")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["assignment_opening_id"])
    assert is_valid_uuid(data["pinned_country_program_id"])
    assert data["pinned_country_medical_tier"] in (1, 2, 3)
    assert is_iso8601_timestamp(data["pinned_departure_date"])
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["acceptance_deadline"])
    assert isinstance(data["issued_by"], str) and data["issued_by"]
    assert data["status"] in {s.value for s in InvitationStatus}


def assert_medical_clearance(data: dict):
    _assert_common(data, "MedicalClearance")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["conditions"], list)
    for cond in data["conditions"]:
        assert isinstance(cond["condition_code"], str) and cond["condition_code"]
        assert cond["severity"] in (1, 2, 3)
        assert cond["required_support_tier"] in (1, 2, 3)
    assert data["dental_status"] in {s.value for s in DentalStatus}
    assert isinstance(data["deferral_count"], int) and data["deferral_count"] >= 0
    assert isinstance(data["max_tier_gap"], int)
    assert data["reviewed_by"] is None or isinstance(data["reviewed_by"], str)
    assert data["status"] in {s.value for s in MedicalClearanceStatus}


def assert_legal_clearance(data: dict):
    _assert_common(data, "LegalClearance")
    assert is_valid_uuid(data["application_id"])
    assert data["background_check_status"] in {s.value for s in BackgroundCheckStatus}
    assert data["background_adjudicated_by"] is None or isinstance(data["background_adjudicated_by"], str)
    assert data["suitability_status"] in {s.value for s in SuitabilityStatus}
    assert data["suitability_decided_by"] is None or isinstance(data["suitability_decided_by"], str)
    assert data["overall_status"] in {s.value for s in LegalOverallStatus}
    assert data["lifecycle"] in {s.value for s in LegalLifecycle}


def assert_training_cohort(data: dict):
    _assert_common(data, "TrainingCohort")
    assert is_valid_uuid(data["country_program_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["status"] in {s.value for s in TrainingCohortStatus}


def assert_training_enrollment(data: dict):
    _assert_common(data, "TrainingEnrollment")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["training_cohort_id"])
    assert isinstance(data["assessment_attempts"], int) and data["assessment_attempts"] >= 0
    for comp in ("language_score", "technical_score", "cultural_score"):
        assert data[comp] is None or 1.0 <= data[comp] <= 5.0
    assert data["status"] in {s.value for s in TrainingEnrollmentStatus}


def assert_volunteer_service(data: dict):
    _assert_common(data, "VolunteerService")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["assignment_opening_id"])
    assert is_valid_uuid(data["country_program_id"])
    assert is_iso8601_timestamp(data["service_start_date"])
    assert is_iso8601_timestamp(data["expected_completion_date"])
    assert data["actual_end_date"] is None or is_iso8601_timestamp(data["actual_end_date"])
    assert data["days_served"] is None or isinstance(data["days_served"], int)
    assert data["months_served"] is None or isinstance(data["months_served"], int)
    assert data["status"] in {s.value for s in VolunteerServiceStatus}


def assert_site_placement(data: dict):
    _assert_common(data, "SitePlacement")
    assert is_valid_uuid(data["volunteer_service_id"])
    assert isinstance(data["host_community_name"], str) and data["host_community_name"]
    assert isinstance(data["counterpart_org_name"], str) and data["counterpart_org_name"]
    for flag in ("counterpart_agreement_signed", "has_running_water",
                 "structurally_sound", "secure_locks", "inspection_passed"):
        assert isinstance(data[flag], bool)
    assert data["status"] in {s.value for s in SitePlacementStatus}


def assert_service_event(data: dict):
    # Append-only log: id + created_at only, NO updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "ServiceEvent.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "ServiceEvent.created_at must be ISO 8601"
    assert "updated_at" not in data, "ServiceEvent must not carry updated_at"
    assert "version" not in data, "ServiceEvent must not carry version"
    assert is_valid_uuid(data["volunteer_service_id"])
    assert data["event_type"] in {t.value for t in ServiceEventType}
    assert data["severity"] in {s.value for s in ServiceEventSeverity}
    assert isinstance(data["description"], str)
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_completion_record(data: dict):
    _assert_common(data, "CompletionRecord")
    assert is_valid_uuid(data["volunteer_service_id"])
    assert data["completion_type"] in {t.value for t in CompletionType}
    if data["completion_type"] == CompletionType.FULL.value:
        assert data["et_reason"] is None
    else:
        assert data["et_reason"] in {r.value for r in EtReason}
    assert isinstance(data["months_served"], int) and data["months_served"] >= 0
    for field in ("gross_accrued_cents", "allowance_paid_cents", "allowance_forfeited_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["nce_eligible"], bool)
    assert isinstance(data["nce_duration_months"], int)


# --- Domain invariant checkers ---


def assert_seat_accounting_invariants(opening: dict):
    """PRD seat accounting: counters non-negative and never above seats_total;
    status FILLED exactly when the committed count reaches seats_total
    (a non-terminal, non-cancelled opening)."""
    prov = opening["seats_provisional"]
    comm = opening["seats_committed"]
    total = opening["seats_total"]
    assert prov >= 0 and comm >= 0, "seat counters must be non-negative"
    assert prov + comm <= total, \
        f"seats_provisional({prov}) + seats_committed({comm}) must not exceed seats_total({total})"
    if opening["status"] == AssignmentOpeningStatus.FILLED.value:
        assert comm == total, "FILLED requires seats_committed == seats_total"
    if opening["status"] == AssignmentOpeningStatus.OPEN.value:
        assert comm < total, "an OPEN opening has seats_committed < seats_total"


def assert_completion_record_invariants(record: dict):
    """PRD readjustment conservation: paid + forfeited == gross, always."""
    paid = record["allowance_paid_cents"]
    forfeited = record["allowance_forfeited_cents"]
    gross = record["gross_accrued_cents"]
    assert paid + forfeited == gross, \
        f"paid({paid}) + forfeited({forfeited}) must equal gross({gross})"
    assert paid <= gross, "paid must never exceed gross"
    assert gross == record["months_served"] * 47500, \
        "gross accrual is months_served times the standard monthly rate"
    if record["nce_eligible"]:
        assert record["nce_duration_months"] == 12
    else:
        assert record["nce_duration_months"] == 0


def assert_legal_overall_consistency(clearance: dict):
    """PRD derived overall_status: VOID if lifecycle VOID; else DENIED on
    ADVERSE/UNFAVORABLE; else CLEARED on CLEAR+FAVORABLE; else PENDING."""
    if clearance["lifecycle"] == LegalLifecycle.VOID.value:
        expected = LegalOverallStatus.VOID.value
    elif (clearance["background_check_status"] == BackgroundCheckStatus.ADVERSE.value
          or clearance["suitability_status"] == SuitabilityStatus.UNFAVORABLE.value):
        expected = LegalOverallStatus.DENIED.value
    elif (clearance["background_check_status"] == BackgroundCheckStatus.CLEAR.value
          and clearance["suitability_status"] == SuitabilityStatus.FAVORABLE.value):
        expected = LegalOverallStatus.CLEARED.value
    else:
        expected = LegalOverallStatus.PENDING.value
    assert clearance["overall_status"] == expected, \
        f"overall_status {clearance['overall_status']} != derived {expected}"


def assert_inspection_conjunction(placement: dict):
    """PRD: inspection_passed is the AND of the three housing flags."""
    expected = (placement["has_running_water"]
                and placement["structurally_sound"]
                and placement["secure_locks"])
    assert placement["inspection_passed"] == expected

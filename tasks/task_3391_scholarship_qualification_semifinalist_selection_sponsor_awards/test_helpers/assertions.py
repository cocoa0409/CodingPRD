"""Entity assertions and domain invariant checkers.

Each assert_<entity>() checks the presence and shape of every field the PRD
assigns to that resource, tolerating the nullability the PRD declares (e.g.
selection_index is null until scoring). School is asserted against its reduced
field set (id + created_at only, per PRD §2.4).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CONFIRMING_INDEX_MAX,
    CONFIRMING_INDEX_MIN,
    GPA_MAX,
    GPA_MIN,
    SECTION_SCORE_MAX,
    SECTION_SCORE_MIN,
    SELECTION_INDEX_MAX,
    SELECTION_INDEX_MIN,
)
from .types import (
    ApplicationStatus,
    AwardCategory,
    CitizenshipStatus,
    CollegeStatus,
    CourseRigor,
    DisbursementStatus,
    EndorsementStatus,
    EnrollmentStatus,
    EntryStatus,
    ExamYearOfHs,
    FundingStatus,
    NoticeType,
    NotificationStatus,
    ProgramCycleStatus,
    RecipientStatus,
    RenewalStatus,
    ReportedEnrollment,
    SponsorAgreementStatus,
    StateAllocationStatus,
)

VALID_CYCLE_STATUSES = [s.value for s in ProgramCycleStatus]
VALID_ALLOCATION_STATUSES = [s.value for s in StateAllocationStatus]
VALID_CITIZENSHIP_STATUSES = [s.value for s in CitizenshipStatus]
VALID_ENROLLMENT_STATUSES = [s.value for s in EnrollmentStatus]
VALID_EXAM_YEARS = [s.value for s in ExamYearOfHs]
VALID_ENTRY_STATUSES = [s.value for s in EntryStatus]
VALID_COURSE_RIGORS = [s.value for s in CourseRigor]
VALID_ENDORSEMENT_STATUSES = [s.value for s in EndorsementStatus]
VALID_APPLICATION_STATUSES = [s.value for s in ApplicationStatus]
VALID_AGREEMENT_STATUSES = [s.value for s in SponsorAgreementStatus]
VALID_COLLEGE_STATUSES = [s.value for s in CollegeStatus]
VALID_AWARD_CATEGORIES = [s.value for s in AwardCategory]
VALID_RECIPIENT_STATUSES = [s.value for s in RecipientStatus]
VALID_FUNDING_STATUSES = [s.value for s in FundingStatus]
VALID_DISBURSEMENT_STATUSES = [s.value for s in DisbursementStatus]
VALID_REPORTED_ENROLLMENTS = [s.value for s in ReportedEnrollment]
VALID_RENEWAL_STATUSES = [s.value for s in RenewalStatus]
VALID_NOTICE_TYPES = [s.value for s in NoticeType]
VALID_NOTIFICATION_STATUSES = [s.value for s in NotificationStatus]


def _assert_common(data: dict):
    """Fields every versioned resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def _assert_nullable_iso(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), f"{field} must be null or ISO 8601"


def _assert_nullable_uuid(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_valid_uuid(value), f"{field} must be null or a UUID"


def assert_program_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["target_graduation_year"], int)
    assert isinstance(data["total_semifinalist_slots"], int) and data["total_semifinalist_slots"] >= 1
    assert isinstance(data["national_award_slots"], int) and data["national_award_slots"] >= 0
    assert isinstance(data["national_award_amount_cents"], int) and data["national_award_amount_cents"] > 0
    assert isinstance(data["confirming_floor"], int)
    assert CONFIRMING_INDEX_MIN <= data["confirming_floor"] <= CONFIRMING_INDEX_MAX
    for field in (
        "application_deadline",
        "semifinalist_embargo_until",
        "finalist_embargo_until",
        "award_embargo_until",
        "public_embargo_until",
    ):
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601"
    assert data["status"] in VALID_CYCLE_STATUSES
    assert isinstance(data["matching_run"], bool)


def assert_state_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) > 0
    assert isinstance(data["graduating_population"], int) and data["graduating_population"] >= 0
    assert data.get("quota_raw") is None or isinstance(data["quota_raw"], (int, float))
    assert data.get("slots_provisional") is None or isinstance(data["slots_provisional"], int)
    assert data.get("slots_final") is None or isinstance(data["slots_final"], int)
    assert data.get("threshold_selection_index") is None or isinstance(
        data["threshold_selection_index"], int
    )
    assert isinstance(data["selected_count"], int) and data["selected_count"] >= 0
    assert data["status"] in VALID_ALLOCATION_STATUSES


def assert_school(data: dict):
    """School is the PRD §2.4 exception: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "School must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "School must not carry version (PRD §2.4)"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["school_code"], str) and len(data["school_code"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) > 0


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_valid_uuid(data.get("school_id", "")), "school_id must be a UUID"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) > 0
    assert isinstance(data["graduation_year"], int)
    assert data["citizenship_status"] in VALID_CITIZENSHIP_STATUSES
    assert data["enrollment_status"] in VALID_ENROLLMENT_STATUSES
    _assert_nullable_uuid(data, "parent_sponsor_id")


def assert_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert data["exam_year_of_hs"] in VALID_EXAM_YEARS
    for field in ("reading_score", "writing_score", "math_score"):
        value = data.get(field)
        assert value is None or (
            isinstance(value, int) and SECTION_SCORE_MIN <= value <= SECTION_SCORE_MAX
        ), f"{field} must be null or within [{SECTION_SCORE_MIN}, {SECTION_SCORE_MAX}]"
    si = data.get("selection_index")
    assert si is None or (
        isinstance(si, int) and SELECTION_INDEX_MIN <= si <= SELECTION_INDEX_MAX
    ), f"selection_index must be null or within [{SELECTION_INDEX_MIN}, {SELECTION_INDEX_MAX}]"
    assert data["status"] in VALID_ENTRY_STATUSES
    _assert_nullable_iso(data, "scored_at")


def assert_finalist_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("entry_id", "")), "entry_id must be a UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    _assert_nullable_uuid(data, "first_choice_college_id")
    assert isinstance(data["gpa_scaled"], (int, float))
    assert GPA_MIN <= data["gpa_scaled"] <= GPA_MAX
    assert data["course_rigor"] in VALID_COURSE_RIGORS
    assert isinstance(data["confirming_selection_index"], int)
    assert CONFIRMING_INDEX_MIN <= data["confirming_selection_index"] <= CONFIRMING_INDEX_MAX
    assert data["endorsement_status"] in VALID_ENDORSEMENT_STATUSES
    _assert_nullable_uuid(data, "endorsed_by_school_id")
    assert data["status"] in VALID_APPLICATION_STATUSES
    assert data.get("return_reason") is None or isinstance(data["return_reason"], str)
    _assert_nullable_iso(data, "submitted_at")


def assert_corporate_sponsor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["sponsor_code"], str) and len(data["sponsor_code"]) > 0


def _assert_pool_ledger(data: dict):
    for field in (
        "pool_total_cents",
        "pool_committed_cents",
        "pool_paid_cents",
        "pool_available_reserved_cents",
        "pool_available_cash_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
    assert data["pool_total_cents"] > 0
    assert data["pool_committed_cents"] >= 0
    assert data["pool_paid_cents"] >= 0


def assert_sponsor_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    _assert_nullable_uuid(data, "supersedes_agreement_id")
    assert isinstance(data["award_amount_cents"], int) and data["award_amount_cents"] > 0
    assert isinstance(data["max_awards"], int) and data["max_awards"] >= 1
    assert isinstance(data["employee_children_only"], bool)
    assert data.get("min_selection_index") is None or isinstance(data["min_selection_index"], int)
    assert isinstance(data["effective_start_date"], str) and len(data["effective_start_date"]) > 0
    assert isinstance(data["effective_end_date"], str) and len(data["effective_end_date"]) > 0
    _assert_pool_ledger(data)
    assert data["status"] in VALID_AGREEMENT_STATUSES


def assert_college_institution(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["college_code"], str) and len(data["college_code"]) > 0
    assert isinstance(data["award_amount_cents"], int) and data["award_amount_cents"] > 0
    assert isinstance(data["renewable_years_total"], int) and data["renewable_years_total"] >= 2
    assert isinstance(data["terms_per_year"], int) and data["terms_per_year"] >= 1
    assert isinstance(data["max_awards"], int) and data["max_awards"] >= 1
    _assert_pool_ledger(data)
    assert data["status"] in VALID_COLLEGE_STATUSES


def assert_award(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    _assert_nullable_uuid(data, "agreement_id")
    _assert_nullable_uuid(data, "college_id")
    assert data["category"] in VALID_AWARD_CATEGORIES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["terms_total"], int) and data["terms_total"] >= 1
    assert isinstance(data["renewable_years_total"], int) and data["renewable_years_total"] >= 1
    assert isinstance(data["years_renewed"], int) and data["years_renewed"] >= 0
    assert data["recipient_status"] in VALID_RECIPIENT_STATUSES
    assert data["funding_status"] in VALID_FUNDING_STATUSES
    assert isinstance(data["selection_index_snapshot"], int)
    assert is_iso8601_timestamp(data["offered_logical_at"]), "offered_logical_at must be ISO 8601"
    assert is_iso8601_timestamp(data["acceptance_deadline"]), "acceptance_deadline must be ISO 8601"


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("award_id", "")), "award_id must be a UUID"
    assert isinstance(data["term_index"], int) and data["term_index"] >= 1
    assert isinstance(data["academic_year_index"], int) and data["academic_year_index"] >= 1
    assert isinstance(data["scheduled_date"], str) and len(data["scheduled_date"]) > 0
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in VALID_DISBURSEMENT_STATUSES
    _assert_nullable_iso(data, "released_logical_at")


def assert_renewal_verification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("award_id", "")), "award_id must be a UUID"
    assert isinstance(data["academic_year_index"], int) and data["academic_year_index"] >= 2
    assert data["reported_enrollment"] in VALID_REPORTED_ENROLLMENTS
    assert isinstance(data["reported_gpa"], (int, float))
    assert GPA_MIN <= data["reported_gpa"] <= GPA_MAX
    assert data["status"] in VALID_RENEWAL_STATUSES
    assert isinstance(data["submitted_by_college_id"], str) and len(data["submitted_by_college_id"]) > 0
    _assert_nullable_iso(data, "decided_logical_at")


def assert_notification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert data["notice_type"] in VALID_NOTICE_TYPES
    assert isinstance(data["sequence_number"], int) and 1 <= data["sequence_number"] <= 4
    assert is_iso8601_timestamp(data["embargo_until"]), "embargo_until must be ISO 8601"
    assert data["status"] in VALID_NOTIFICATION_STATUSES
    _assert_nullable_iso(data, "released_logical_at")


def assert_pool_ledger_consistent(pool: dict):
    """The pool ledger identities that must hold at every read (PRD §3.6):
    pool_available_reserved_cents = pool_total - committed - paid, and
    pool_available_cash_cents = pool_total - paid."""
    assert pool["pool_available_reserved_cents"] == (
        pool["pool_total_cents"] - pool["pool_committed_cents"] - pool["pool_paid_cents"]
    ), "reservation availability must equal total minus committed minus paid"
    assert pool["pool_available_cash_cents"] == (
        pool["pool_total_cents"] - pool["pool_paid_cents"]
    ), "cash availability must equal total minus paid"


def assert_award_invariants(award: dict):
    """Award-level invariants (PRD §3.7, §3.8)."""
    assert award["years_renewed"] <= max(award["renewable_years_total"] - 1, 0), (
        "years_renewed must stay within 0..renewable_years_total-1"
    )
    if award["category"] == "CORPORATE_SPONSORED":
        assert award["agreement_id"] is not None and award["college_id"] is None
    elif award["category"] == "COLLEGE_SPONSORED":
        assert award["college_id"] is not None and award["agreement_id"] is None
    else:
        assert award["agreement_id"] is None and award["college_id"] is None


__all__ = [
    "VALID_CYCLE_STATUSES",
    "VALID_ALLOCATION_STATUSES",
    "VALID_CITIZENSHIP_STATUSES",
    "VALID_ENROLLMENT_STATUSES",
    "VALID_EXAM_YEARS",
    "VALID_ENTRY_STATUSES",
    "VALID_COURSE_RIGORS",
    "VALID_ENDORSEMENT_STATUSES",
    "VALID_APPLICATION_STATUSES",
    "VALID_AGREEMENT_STATUSES",
    "VALID_COLLEGE_STATUSES",
    "VALID_AWARD_CATEGORIES",
    "VALID_RECIPIENT_STATUSES",
    "VALID_FUNDING_STATUSES",
    "VALID_DISBURSEMENT_STATUSES",
    "VALID_REPORTED_ENROLLMENTS",
    "VALID_RENEWAL_STATUSES",
    "VALID_NOTICE_TYPES",
    "VALID_NOTIFICATION_STATUSES",
    "assert_program_cycle",
    "assert_state_allocation",
    "assert_school",
    "assert_student",
    "assert_entry",
    "assert_finalist_application",
    "assert_corporate_sponsor",
    "assert_sponsor_agreement",
    "assert_college_institution",
    "assert_award",
    "assert_disbursement",
    "assert_renewal_verification",
    "assert_notification",
    "assert_pool_ledger_consistent",
    "assert_award_invariants",
]

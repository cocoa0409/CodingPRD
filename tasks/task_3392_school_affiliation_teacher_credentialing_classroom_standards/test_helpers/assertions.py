"""Entity assertions and domain invariant checkers.

``assert_<entity>(data)`` validates the wire shape of one resource against
the PRD's field definitions: presence, type, enum membership, and the
common-field rule of PRD section 2.4 (``ClassroomAudit`` and
``CECreditEntry`` must NOT carry ``updated_at``/``version``).

Invariant checkers recompute a rule from the PRD out of the payload itself
(directory visibility, audit verdict consistency) or out of the PRD's
published schedule (annual dues, renewal fee), so tests can compare the
server's computed fields against an independent derivation.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BASE_DUES_CENTS,
    MAX_DUES_CENTS,
    MIN_DUES_CENTS,
    PER_CLASSROOM_SURCHARGE_CENTS,
    RENEWAL_BASE_FEE_CENTS,
    RENEWAL_LATE_FEE_CENTS,
    TIER1_RATE_CENTS,
    TIER1_UP_TO,
    TIER2_RATE_CENTS,
    TIER2_UP_TO,
    TIER3_RATE_CENTS,
)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_AGE_LEVELS = {"INFANT_TODDLER", "EARLY_CHILDHOOD", "ELEMENTARY_I", "ELEMENTARY_II", "SECONDARY"}
_CATALOG_STATUSES = {"DRAFT", "ACTIVE", "RETIRED"}
_MEMBERSHIP_LEVELS = {"APPLICANT", "AFFILIATE", "MEMBER", "ACCREDITED"}
_STANDINGS = {"GOOD_STANDING", "PROBATION", "SUSPENDED", "REVOKED"}
_COMPLIANCE_OVERRIDES = {"NONE", "NONCOMPLIANT_LEAD"}
_AUDIT_VERDICTS = {"COMPLIANT", "NONCOMPLIANT"}
_FAILED_CHECKS = {"RATIO", "WORK_PERIOD", "MATERIALS", "MULTI_AGE"}
_PROGRAM_STATUSES = {"PROVISIONAL", "ACCREDITED", "PROBATION", "SUSPENDED"}
_LEARNER_STATUSES = {"ENROLLED", "IN_PRACTICUM", "PRACTICUM_COMPLETE", "CREDENTIALED"}
_PLACEMENT_STATUSES = {"ACTIVE", "HOURS_COMPLETE", "VERIFIED", "CANCELLED"}
_CREDENTIAL_STATUSES = {"ACTIVE", "LAPSED", "EXPIRED", "REVOKED"}
_APPLICATION_TYPES = {"AFFILIATION", "MEMBERSHIP", "ACCREDITATION"}
_APPLICATION_STATUSES = {"DRAFT", "UNDER_REVIEW", "RETURNED", "SUSPENDED", "APPROVED", "DENIED"}
_SELF_STUDY_STATUSES = {"DRAFT", "SUBMITTED", "RETURNED_FOR_REVISION", "ACCEPTED"}
_VISIT_STATUSES = {"SCHEDULED", "REPORT_FILED", "CANCELLED"}
_VISIT_VERDICTS = {"COMPLIANT", "IMPROVEMENT_REQUIRED", "NONCOMPLIANT"}
_PLAN_STATUSES = {"OPEN", "OVERDUE", "SUBMITTED", "VERIFIED"}
_PD_EVENT_STATUSES = {"SCHEDULED", "COMPLETED"}
_CE_ENTRY_STATUSES = {"ACTIVE", "VOID"}


# ---------------------------------------------------------------------------
# Numeric and date helpers
# ---------------------------------------------------------------------------
def round_half_up(value, places: int) -> Decimal:
    """Round half-up to ``places`` decimal places (PRD section 2.9 pins
    half-up rounding; Python's built-in round() is banker's rounding)."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def _assert_iso_date(value, field: str) -> None:
    assert isinstance(value, str) and _ISO_DATE_RE.match(value), (
        "{0} must be an ISO date string (YYYY-MM-DD), got {1!r}".format(field, value)
    )


def _assert_nullable_iso_date(value, field: str) -> None:
    if value is not None:
        _assert_iso_date(value, field)


def _assert_nullable_timestamp(value, field: str) -> None:
    if value is not None:
        assert is_iso8601_timestamp(value), "{0} must be ISO 8601, got {1!r}".format(field, value)


def _assert_number(value, field: str) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        "{0} must be numeric, got {1!r}".format(field, value)
    )


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), "{0}.id must be a valid UUID".format(entity)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "{0}.created_at must be ISO 8601".format(entity)
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "{0}.updated_at must be ISO 8601".format(entity)
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "{0}.version must be a positive integer".format(entity)
    )


def _assert_lean_common_fields(data: dict, entity: str) -> None:
    """PRD section 2.4: append-only resources carry ONLY id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "{0}.id must be a valid UUID".format(entity)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "{0}.created_at must be ISO 8601".format(entity)
    )
    assert "updated_at" not in data, "{0} must not carry updated_at".format(entity)
    assert "version" not in data, "{0} must not carry version".format(entity)


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
def assert_standards_catalog(data: dict) -> None:
    _assert_common_fields(data, "StandardsCatalog")
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert data["status"] in _CATALOG_STATUSES
    _assert_iso_date(data["effective_from"], "effective_from")
    for field in (
        "min_uninterrupted_work_minutes_by_level",
        "max_students_per_adult_by_level",
        "min_multi_age_span_years_by_level",
        "practicum_min_hours_by_level",
    ):
        assert isinstance(data[field], dict), "{0} must be an object".format(field)
        assert set(data[field].keys()) == _AGE_LEVELS, (
            "{0} must key every age level, got {1}".format(field, sorted(data[field].keys()))
        )
    _assert_number(data["materials_pass_threshold"], "materials_pass_threshold")
    _assert_number(data["ce_hours_required"], "ce_hours_required")
    for field in (
        "credential_validity_months",
        "renewal_window_months",
        "renewal_grace_months",
        "min_membership_months_before_accreditation",
        "consultant_travel_buffer_days",
        "plan_response_days",
    ):
        assert isinstance(data[field], int), "{0} must be an integer".format(field)


def assert_school(data: dict) -> None:
    _assert_common_fields(data, "School")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["uses_method_name"], bool)
    assert data.get("descriptor") is None or isinstance(data["descriptor"], str)
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["membership_level"] in _MEMBERSHIP_LEVELS
    assert data["standing"] in _STANDINGS
    _assert_nullable_iso_date(data.get("affiliated_since"), "affiliated_since")
    _assert_nullable_iso_date(data.get("member_since"), "member_since")
    _assert_nullable_iso_date(data.get("accredited_since"), "accredited_since")
    _assert_nullable_iso_date(data.get("dues_paid_through"), "dues_paid_through")
    assert data.get("pinned_catalog_id") is None or isinstance(data["pinned_catalog_id"], str)
    for field in ("dues_current", "brand_compliant", "directory_visible"):
        assert isinstance(data[field], bool), "{0} must be boolean".format(field)
    for field in ("total_enrollment", "compliant_classroom_count", "annual_dues_cents"):
        assert isinstance(data[field], int), "{0} must be an integer".format(field)


def assert_classroom(data: dict) -> None:
    _assert_common_fields(data, "Classroom")
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["age_level"] in _AGE_LEVELS
    assert isinstance(data["declared_age_span_years"], int)
    assert isinstance(data["enrolled_student_count"], int) and data["enrolled_student_count"] >= 0
    assert isinstance(data["assistant_count"], int) and data["assistant_count"] >= 0
    assert data.get("lead_credential_id") is None or isinstance(data["lead_credential_id"], str)
    assert data["compliance_override"] in _COMPLIANCE_OVERRIDES
    assert data.get("latest_audit_verdict") is None or data["latest_audit_verdict"] in _AUDIT_VERDICTS


def assert_classroom_audit(data: dict) -> None:
    _assert_lean_common_fields(data, "ClassroomAudit")
    assert isinstance(data["classroom_id"], str) and data["classroom_id"]
    assert data.get("visit_id") is None or isinstance(data["visit_id"], str)
    assert isinstance(data["catalog_id"], str) and data["catalog_id"]
    assert isinstance(data["auditor_consultant_id"], str) and data["auditor_consultant_id"]
    assert is_iso8601_timestamp(data["observed_at"]), "observed_at must be ISO 8601"
    assert isinstance(data["students_present"], int) and data["students_present"] >= 0
    assert isinstance(data["adults_present"], int) and data["adults_present"] >= 1
    assert isinstance(data["observed_uninterrupted_minutes"], int)
    assert data["observed_uninterrupted_minutes"] >= 0
    groups = data["materials_groups"]
    assert isinstance(groups, list) and len(groups) >= 1, "materials_groups must be non-empty"
    for group in groups:
        assert isinstance(group["domain"], str) and group["domain"]
        assert isinstance(group["required_count"], int) and group["required_count"] >= 0
        assert isinstance(group["present_count"], int) and group["present_count"] >= 0
    _assert_number(data["ratio_students_per_adult"], "ratio_students_per_adult")
    _assert_number(data["materials_score"], "materials_score")
    for field in ("ratio_pass", "work_period_pass", "materials_pass", "multi_age_pass"):
        assert isinstance(data[field], bool), "{0} must be boolean".format(field)
    assert data["verdict"] in _AUDIT_VERDICTS
    assert isinstance(data["failed_checks"], list)
    assert set(data["failed_checks"]) <= _FAILED_CHECKS


def assert_teacher_education_program(data: dict) -> None:
    _assert_common_fields(data, "TeacherEducationProgram")
    assert isinstance(data["name"], str) and data["name"]
    offered = data["age_levels_offered"]
    assert isinstance(offered, list) and len(offered) >= 1
    assert set(offered) <= _AGE_LEVELS
    assert isinstance(data["course_contact_hours_by_level"], dict)
    assert isinstance(data["practicum_hours_by_level"], dict)
    assert data["status"] in _PROGRAM_STATUSES


def assert_adult_learner(data: dict) -> None:
    _assert_common_fields(data, "AdultLearner")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["age_level"] in _AGE_LEVELS
    assert data["status"] in _LEARNER_STATUSES


def assert_practicum_placement(data: dict) -> None:
    _assert_common_fields(data, "PracticumPlacement")
    assert isinstance(data["learner_id"], str) and data["learner_id"]
    assert isinstance(data["host_school_id"], str) and data["host_school_id"]
    assert data.get("supervisor_credential_id") is None or isinstance(
        data["supervisor_credential_id"], str
    )
    assert data["age_level"] in _AGE_LEVELS
    _assert_iso_date(data["start_date"], "start_date")
    _assert_iso_date(data["end_date"], "end_date")
    assert isinstance(data["target_hours"], int) and data["target_hours"] >= 0
    assert isinstance(data["hours_logged"], int) and data["hours_logged"] >= 0
    assert data["status"] in _PLACEMENT_STATUSES


def assert_credential(data: dict) -> None:
    _assert_common_fields(data, "Credential")
    assert isinstance(data["learner_id"], str) and data["learner_id"]
    assert data["age_level"] in _AGE_LEVELS
    assert data["status"] in _CREDENTIAL_STATUSES
    assert is_iso8601_timestamp(data["issued_at"]), "issued_at must be ISO 8601"
    _assert_iso_date(data["cycle_start"], "cycle_start")
    assert is_iso8601_timestamp(data["expires_at"]), "expires_at must be ISO 8601"
    assert isinstance(data["renewed_count"], int) and data["renewed_count"] >= 0
    _assert_number(data["ce_hours_cycle_credited"], "ce_hours_cycle_credited")
    _assert_number(data["ce_hours_rolling_credited"], "ce_hours_rolling_credited")


def assert_school_application(data: dict) -> None:
    _assert_common_fields(data, "SchoolApplication")
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert data["type"] in _APPLICATION_TYPES
    assert data["status"] in _APPLICATION_STATUSES
    assert data.get("supporting_self_study_id") is None or isinstance(
        data["supporting_self_study_id"], str
    )
    _assert_nullable_timestamp(data.get("submitted_at"), "submitted_at")
    _assert_nullable_timestamp(data.get("decided_at"), "decided_at")
    assert data.get("reviewer_user_id") is None or isinstance(data["reviewer_user_id"], str)


def assert_self_study(data: dict) -> None:
    _assert_common_fields(data, "SelfStudy")
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert isinstance(data["narrative"], str)
    assert data["status"] in _SELF_STUDY_STATUSES
    assert isinstance(data["pinned_catalog_id"], str) and data["pinned_catalog_id"]
    assert isinstance(data["pinned_catalog_label"], str) and data["pinned_catalog_label"]
    _assert_nullable_timestamp(data.get("submitted_at"), "submitted_at")


def assert_verification_visit(data: dict) -> None:
    _assert_common_fields(data, "VerificationVisit")
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert isinstance(data["self_study_id"], str) and data["self_study_id"]
    assert isinstance(data["consultant_id"], str) and data["consultant_id"]
    _assert_iso_date(data["window_start"], "window_start")
    _assert_iso_date(data["window_end"], "window_end")
    assert data["status"] in _VISIT_STATUSES
    assert data.get("verdict") is None or data["verdict"] in _VISIT_VERDICTS
    assert isinstance(data["findings"], list)
    _assert_nullable_timestamp(data.get("report_filed_at"), "report_filed_at")


def assert_improvement_plan(data: dict) -> None:
    _assert_common_fields(data, "ImprovementPlan")
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert data.get("visit_id") is None or isinstance(data["visit_id"], str)
    assert isinstance(data["required_actions"], list)
    _assert_iso_date(data["due_date"], "due_date")
    assert data["status"] in _PLAN_STATUSES
    assert data.get("response_notes") is None or isinstance(data["response_notes"], str)
    _assert_nullable_timestamp(data.get("submitted_at"), "submitted_at")
    _assert_nullable_timestamp(data.get("verified_at"), "verified_at")


def assert_pd_event(data: dict) -> None:
    _assert_common_fields(data, "PDEvent")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert is_iso8601_timestamp(data["start_at"]), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data["end_at"]), "end_at must be ISO 8601"
    _assert_number(data["ce_hours"], "ce_hours")
    assert data["ce_hours"] > 0
    assert data["status"] in _PD_EVENT_STATUSES


def assert_ce_credit_entry(data: dict) -> None:
    _assert_lean_common_fields(data, "CECreditEntry")
    assert isinstance(data["credential_id"], str) and data["credential_id"]
    assert isinstance(data["pd_event_id"], str) and data["pd_event_id"]
    _assert_number(data["hours"], "hours")
    assert data["hours"] > 0
    assert is_iso8601_timestamp(data["earned_at"]), "earned_at must be ISO 8601"
    assert data["status"] in _CE_ENTRY_STATUSES


def assert_directory_verification(data: dict) -> None:
    """Parent-facing verification payload (PRD section 3.8): always carries
    school_id, display_name and listed; a listed school also exposes its
    membership_level, standing, accredited flag and brand_compliant flag."""
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["listed"], bool)
    if data["listed"]:
        assert data["membership_level"] in _MEMBERSHIP_LEVELS
        assert data["standing"] in _STANDINGS
        assert isinstance(data["accredited"], bool)
        assert isinstance(data["brand_compliant"], bool)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_school_invariants(data: dict) -> None:
    """directory_visible must equal the conjunction of the four gating
    fields (PRD section 3.8): level in {MEMBER, ACCREDITED} AND standing
    GOOD_STANDING AND brand_compliant AND dues_current."""
    expected = (
        data["membership_level"] in ("MEMBER", "ACCREDITED")
        and data["standing"] == "GOOD_STANDING"
        and data["brand_compliant"]
        and data["dues_current"]
    )
    assert data["directory_visible"] == expected, (
        "directory_visible {0} disagrees with the four gating fields "
        "(level={1}, standing={2}, brand_compliant={3}, dues_current={4})".format(
            data["directory_visible"],
            data["membership_level"],
            data["standing"],
            data["brand_compliant"],
            data["dues_current"],
        )
    )


def assert_audit_verdict_consistency(data: dict) -> None:
    """verdict is COMPLIANT exactly when all four checks pass, and
    failed_checks lists the failed components in the fixed order
    [RATIO, WORK_PERIOD, MATERIALS, MULTI_AGE] (PRD section 3.3)."""
    flags = {
        "RATIO": data["ratio_pass"],
        "WORK_PERIOD": data["work_period_pass"],
        "MATERIALS": data["materials_pass"],
        "MULTI_AGE": data["multi_age_pass"],
    }
    expected_failed = [name for name in ("RATIO", "WORK_PERIOD", "MATERIALS", "MULTI_AGE") if not flags[name]]
    expected_verdict = "COMPLIANT" if not expected_failed else "NONCOMPLIANT"
    assert data["verdict"] == expected_verdict, (
        "verdict {0} disagrees with pass flags {1}".format(data["verdict"], flags)
    )
    assert list(data["failed_checks"]) == expected_failed, (
        "failed_checks {0} != expected {1}".format(data["failed_checks"], expected_failed)
    )


def expected_annual_dues_cents(membership_level: str, total_enrollment: int, classroom_count: int) -> int:
    """The dues schedule of PRD section 3.2, recomputed: level base
    (APPLICANT quotes AFFILIATE) + marginal per-student fee (1500c for the
    first 100, 1200c for 101-300, 900c beyond 300) + 8000c per classroom,
    floored at 60000 before capping at 1500000."""
    base = BASE_DUES_CENTS[membership_level]
    tier1 = min(total_enrollment, TIER1_UP_TO) * TIER1_RATE_CENTS
    tier2 = max(0, min(total_enrollment, TIER2_UP_TO) - TIER1_UP_TO) * TIER2_RATE_CENTS
    tier3 = max(0, total_enrollment - TIER2_UP_TO) * TIER3_RATE_CENTS
    raw = base + tier1 + tier2 + tier3 + PER_CLASSROOM_SURCHARGE_CENTS * classroom_count
    return min(MAX_DUES_CENTS, max(MIN_DUES_CENTS, raw))


def expected_renewal_fee_cents(credential_status: str) -> int:
    """PRD section 3.5: 8500 cents, plus a 5000-cent late fee when LAPSED."""
    return RENEWAL_BASE_FEE_CENTS + (
        RENEWAL_LATE_FEE_CENTS if credential_status == "LAPSED" else 0
    )


def expected_materials_score(materials_groups: list) -> Decimal:
    """Per-group ratios rounded half-up to 2dp FIRST, then the exact
    arithmetic mean, stored at 4dp half-up (PRD section 2.9 / 3.3)."""
    per_group = [
        round_half_up(Decimal(g["present_count"]) / Decimal(g["required_count"]), 2)
        for g in materials_groups
    ]
    mean = sum(per_group) / Decimal(len(per_group))
    return round_half_up(mean, 4)


def expected_materials_pass(materials_groups: list, threshold) -> bool:
    """materials_pass compares the UNROUNDED mean of per-group rounded
    scores against the catalog threshold."""
    per_group = [
        round_half_up(Decimal(g["present_count"]) / Decimal(g["required_count"]), 2)
        for g in materials_groups
    ]
    mean = sum(per_group) / Decimal(len(per_group))
    return mean >= Decimal(str(threshold))

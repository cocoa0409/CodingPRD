"""Payload factories — one per creatable resource, input fields only.

Optional fields the PRD declares (parent_sponsor_id on Student,
first_choice_college_id on FinalistApplication, employee_children_only and
min_selection_index on SponsorAgreement, return_reason on review) are omitted
by default so the PRD's default/absence semantics stay observable; pass them
as overrides when a scenario needs them.
"""
import itertools

from .constants import TEST_DEFAULTS

_counters = itertools.count(1)


def _next() -> int:
    return next(_counters)


def create_program_cycle_payload(**overrides) -> dict:
    """Input fields of POST /api/program-cycles (PRD §3.1, §4)."""
    n = _next()
    defaults = {
        "name": f"Cycle {n}",
        "target_graduation_year": TEST_DEFAULTS["TARGET_GRADUATION_YEAR"],
        "total_semifinalist_slots": TEST_DEFAULTS["TOTAL_SEMIFINALIST_SLOTS"],
        "national_award_slots": TEST_DEFAULTS["NATIONAL_AWARD_SLOTS"],
        "national_award_amount_cents": TEST_DEFAULTS["NATIONAL_AWARD_AMOUNT_CENTS"],
        "confirming_floor": TEST_DEFAULTS["CONFIRMING_FLOOR"],
        "application_deadline": TEST_DEFAULTS["APPLICATION_DEADLINE"],
        "semifinalist_embargo_until": TEST_DEFAULTS["SEMIFINALIST_EMBARGO_UNTIL"],
        "finalist_embargo_until": TEST_DEFAULTS["FINALIST_EMBARGO_UNTIL"],
        "award_embargo_until": TEST_DEFAULTS["AWARD_EMBARGO_UNTIL"],
        "public_embargo_until": TEST_DEFAULTS["PUBLIC_EMBARGO_UNTIL"],
        "state_populations": [
            {
                "state_code": TEST_DEFAULTS["STATE_CODE"],
                "graduating_population": TEST_DEFAULTS["STATE_POPULATION"],
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_school_payload(**overrides) -> dict:
    """Input fields of POST /api/schools (PRD §3.3)."""
    n = _next()
    defaults = {
        "name": f"School {n}",
        "school_code": f"SCH-{n}",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(school_id, **overrides) -> dict:
    """Input fields of POST /api/students (PRD §3.3). parent_sponsor_id is
    optional and omitted unless overridden."""
    n = _next()
    defaults = {
        "full_name": f"Student {n}",
        "school_id": school_id,
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "graduation_year": TEST_DEFAULTS["TARGET_GRADUATION_YEAR"],
        "citizenship_status": "US_CITIZEN",
        "enrollment_status": "ENROLLED_FULL_TIME",
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(student_id, cycle_id, **overrides) -> dict:
    """Input fields of POST /api/entries (PRD §3.3)."""
    defaults = {
        "student_id": student_id,
        "cycle_id": cycle_id,
        "exam_year_of_hs": "THIRD_YEAR",
    }
    defaults.update(overrides)
    return defaults


def create_score_payload(**overrides) -> dict:
    """Input fields of POST /api/entries/{id}/score (PRD §3.4)."""
    defaults = {
        "reading_score": TEST_DEFAULTS["SCORE_READING"],
        "writing_score": TEST_DEFAULTS["SCORE_WRITING"],
        "math_score": TEST_DEFAULTS["SCORE_MATH"],
    }
    defaults.update(overrides)
    return defaults


def create_finalist_application_payload(entry_id, **overrides) -> dict:
    """Input fields of POST /api/finalist-applications (PRD §3.5).
    first_choice_college_id is optional and omitted unless overridden."""
    defaults = {
        "entry_id": entry_id,
        "gpa_scaled": TEST_DEFAULTS["GPA_SCALED"],
        "course_rigor": TEST_DEFAULTS["COURSE_RIGOR"],
        "confirming_selection_index": TEST_DEFAULTS["CONFIRMING_SELECTION_INDEX"],
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(decision, expected_finalist_application_version, **overrides) -> dict:
    """Input fields of POST /api/finalist-applications/{id}/review (PRD §3.5,
    OCC per §2.7). return_reason is carried only when supplied."""
    defaults = {
        "decision": decision,
        "expected_finalist_application_version": expected_finalist_application_version,
    }
    defaults.update(overrides)
    return defaults


def create_corporate_sponsor_payload(**overrides) -> dict:
    """Input fields of POST /api/corporate-sponsors (PRD §3.6)."""
    n = _next()
    defaults = {
        "legal_name": f"Sponsor {n} Corp",
        "sponsor_code": f"SP-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_agreement_payload(cycle_id, **overrides) -> dict:
    """Input fields of POST /api/corporate-sponsors/{id}/agreements (PRD §3.6).
    employee_children_only (default true) and min_selection_index (default
    null) are omitted unless overridden so the declared defaults apply."""
    defaults = {
        "cycle_id": cycle_id,
        "award_amount_cents": TEST_DEFAULTS["AGREEMENT_AWARD_AMOUNT_CENTS"],
        "max_awards": TEST_DEFAULTS["AGREEMENT_MAX_AWARDS"],
        "pool_total_cents": TEST_DEFAULTS["AGREEMENT_POOL_TOTAL_CENTS"],
        "effective_start_date": TEST_DEFAULTS["AGREEMENT_WINDOW_START"],
        "effective_end_date": TEST_DEFAULTS["AGREEMENT_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(expected_sponsor_agreement_version, **overrides) -> dict:
    """Input fields of POST /api/sponsor-agreements/{id}/amend (PRD §3.6, OCC
    per §2.7). Only the amendable fields supplied are carried."""
    defaults = {
        "expected_sponsor_agreement_version": expected_sponsor_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_college_institution_payload(**overrides) -> dict:
    """Input fields of POST /api/college-institutions (PRD §3.6)."""
    n = _next()
    defaults = {
        "legal_name": f"College {n} University",
        "college_code": f"COL-{n}",
        "award_amount_cents": TEST_DEFAULTS["COLLEGE_AWARD_AMOUNT_CENTS"],
        "renewable_years_total": TEST_DEFAULTS["COLLEGE_RENEWABLE_YEARS_TOTAL"],
        "terms_per_year": TEST_DEFAULTS["COLLEGE_TERMS_PER_YEAR"],
        "pool_total_cents": TEST_DEFAULTS["COLLEGE_POOL_TOTAL_CENTS"],
        "max_awards": TEST_DEFAULTS["COLLEGE_MAX_AWARDS"],
    }
    defaults.update(overrides)
    return defaults


def create_renewal_verification_payload(**overrides) -> dict:
    """Input fields of POST /api/awards/{id}/renewal-verifications (PRD §3.8)."""
    defaults = {
        "academic_year_index": TEST_DEFAULTS["RENEWAL_ACADEMIC_YEAR_INDEX"],
        "reported_enrollment": TEST_DEFAULTS["RENEWAL_REPORTED_ENROLLMENT"],
        "reported_gpa": TEST_DEFAULTS["RENEWAL_REPORTED_GPA"],
    }
    defaults.update(overrides)
    return defaults


def create_renewal_decision_payload(decision, **overrides) -> dict:
    """Input fields of POST /api/renewal-verifications/{id}/decision (PRD §3.8)."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601) -> dict:
    """Input fields of POST /api/_clock/set_current_utc (PRD §2.5)."""
    return {"to_iso8601": to_iso8601}


__all__ = [
    "create_program_cycle_payload",
    "create_school_payload",
    "create_student_payload",
    "create_entry_payload",
    "create_score_payload",
    "create_finalist_application_payload",
    "create_review_payload",
    "create_corporate_sponsor_payload",
    "create_sponsor_agreement_payload",
    "create_amendment_payload",
    "create_college_institution_payload",
    "create_renewal_verification_payload",
    "create_renewal_decision_payload",
    "create_clock_payload",
]

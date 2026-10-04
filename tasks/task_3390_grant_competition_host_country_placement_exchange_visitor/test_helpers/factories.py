"""Payload factories — one per creatable entity, input fields only.

Defaults follow the canonical base pipeline shared by the PRD examples:
a 2027-2028 cycle, a DE country program with quota 1 and STANDARD/HIGH
stipends, an INDEPENDENT applicant, a 10-month application with 0 dependents.
Every factory accepts **overrides so tests control exactly the fields the
rule under test varies.
"""
import uuid

from .constants import (
    DEFAULT_CYCLE_ACADEMIC_YEAR,
    DEFAULT_CYCLE_DEADLINE,
    DEFAULT_GRANT_DURATION_MONTHS,
    DEFAULT_GRANT_END_DATE,
    DEFAULT_GRANT_START_DATE,
    DEFAULT_OFFER_DEADLINE,
    ORIENTATION_COMPLETED_AT,
)


def _unique_email(prefix: str = "applicant") -> str:
    """Unique email per call — emails are unique across applicants, and a
    test registering several applicants must not collide."""
    return f"{prefix}.{uuid.uuid4().hex[:12]}@example.com"


# ---------------------------------------------------------------------------
# Competition cycle / country program
# ---------------------------------------------------------------------------

def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "academic_year": DEFAULT_CYCLE_ACADEMIC_YEAR,
        "application_deadline": DEFAULT_CYCLE_DEADLINE,
    }
    defaults.update(overrides)
    return defaults


def cycle_transition_payload(action: str) -> dict:
    """action in {OPEN, CLOSE, BEGIN_SCREENING, FINALIZE_AWARDS, COMPLETE}."""
    return {"action": action}


def create_country_program_payload(**overrides) -> dict:
    defaults = {
        "country_code": "DE",
        "slot_quota": 1,
        "min_duration_months": 6,
        "max_duration_months": 12,
        "monthly_stipend_standard_cents": 300000,
        "monthly_stipend_high_cents": 360000,
        "dependent_allowance_monthly_cents": 50000,
        "travel_allowance_cents": 150000,
        "health_benefit_monthly_cents": 20000,
        "language_requirement": "NONE",
    }
    defaults.update(overrides)
    return defaults


def patch_country_program_payload(**overrides) -> dict:
    """All fields optional on PATCH; pass only the ones to amend."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Applicant / application
# ---------------------------------------------------------------------------

def create_applicant_payload(**overrides) -> dict:
    """Defaults to INDEPENDENT (no home_institution_name required). For an
    ENROLLED_STUDENT pass home_institution_name — it is required exactly when
    applicant_type is ENROLLED_STUDENT."""
    defaults = {
        "full_name": "Test Applicant",
        "email": _unique_email(),
        "applicant_type": "INDEPENDENT",
        "citizenship_country_code": "US",
    }
    defaults.update(overrides)
    return defaults


def create_enrolled_applicant_payload(**overrides) -> dict:
    defaults = create_applicant_payload(
        applicant_type="ENROLLED_STUDENT",
        home_institution_name="State University",
    )
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, cycle_id, country_program_id,
                               **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "cycle_id": cycle_id,
        "country_program_id": country_program_id,
        "project_title": "Test Project",
        "project_summary": "Test project summary",
        "proposed_duration_months": DEFAULT_GRANT_DURATION_MONTHS,
        "dependents_count": 0,
    }
    defaults.update(overrides)
    return defaults


def patch_application_payload(expected_application_version, **overrides) -> dict:
    """OCC-guarded edit of a DRAFT application; expected_application_version
    is non-optional."""
    defaults = {"expected_application_version": expected_application_version}
    defaults.update(overrides)
    return defaults


def application_transition_payload(action: str, outcome=None,
                                   rationale=None) -> dict:
    """action in {SUBMIT, WITHDRAW, DECLINE, DECIDE}; outcome required for
    DECIDE (stage vocabulary: ENDORSE/REJECT campus, RECOMMEND/REJECT
    national, SELECT/ALTERNATE/REJECT host)."""
    payload = {"action": action}
    if outcome is not None:
        payload["outcome"] = outcome
    if rationale is not None:
        payload["rationale"] = rationale
    return payload


# ---------------------------------------------------------------------------
# Review scores
# ---------------------------------------------------------------------------

def create_score_payload(**overrides) -> dict:
    defaults = {
        "feasibility_score": 80,
        "country_fit_score": 80,
        "language_score": 80,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Placement rounds
# ---------------------------------------------------------------------------

def create_placement_round_payload(expected_application_version, **overrides) -> dict:
    """OCC-guarded; expected_application_version is non-optional."""
    defaults = {
        "institution_name": "Heidelberg Institute",
        "institution_band": "STANDARD",
        "response_deadline": DEFAULT_OFFER_DEADLINE,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def placement_round_transition_payload(action: str) -> dict:
    """action in {ACCEPT, DECLINE, EXPIRE}."""
    return {"action": action}


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

def confirm_grant_payload(**overrides) -> dict:
    defaults = {
        "start_date": DEFAULT_GRANT_START_DATE,
        "end_date": DEFAULT_GRANT_END_DATE,
    }
    defaults.update(overrides)
    return defaults


def grant_transition_payload(action: str, termination_reason=None) -> dict:
    """action in {ACTIVATE, COMPLETE, TERMINATE}; termination_reason optional
    on TERMINATE."""
    payload = {"action": action}
    if termination_reason is not None:
        payload["termination_reason"] = termination_reason
    return payload


# ---------------------------------------------------------------------------
# Visa sponsorship / residency ledger
# ---------------------------------------------------------------------------

def create_visa_sponsorship_payload(**overrides) -> dict:
    defaults = {
        "subject_to_home_residency": True,
        "orientation_completed_at": ORIENTATION_COMPLETED_AT,
    }
    defaults.update(overrides)
    return defaults


def create_stay_payload(start_date, end_date, **overrides) -> dict:
    """Dates are calendar dates (YYYY-MM-DD); day_count spans both endpoints
    inclusively."""
    defaults = {"start_date": start_date, "end_date": end_date}
    defaults.update(overrides)
    return defaults


def residency_transition_payload(action: str, waiver_reason=None) -> dict:
    """action in {REQUEST_WAIVER, APPROVE_WAIVER, DENY_WAIVER}."""
    payload = {"action": action}
    if waiver_reason is not None:
        payload["waiver_reason"] = waiver_reason
    return payload


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def create_report_payload(report_type="FINAL", **overrides) -> dict:
    defaults = {
        "report_type": report_type,
        "content": "Report body",
    }
    defaults.update(overrides)
    return defaults


def report_transition_payload(action: str, revision_note=None,
                              content=None) -> dict:
    """action in {ACCEPT, REQUEST_REVISION, RESUBMIT}; revision_note stored at
    REQUEST_REVISION; content replaces the body on RESUBMIT when supplied."""
    payload = {"action": action}
    if revision_note is not None:
        payload["revision_note"] = revision_note
    if content is not None:
        payload["content"] = content
    return payload


# ---------------------------------------------------------------------------
# Emergency incidents
# ---------------------------------------------------------------------------

def create_incident_payload(**overrides) -> dict:
    defaults = {
        "category": "MEDICAL",
        "description": "In-country emergency",
    }
    defaults.update(overrides)
    return defaults


def resolve_incident_payload(outcome: str) -> dict:
    """outcome in {RESUME, TERMINATE}."""
    return {"outcome": outcome}

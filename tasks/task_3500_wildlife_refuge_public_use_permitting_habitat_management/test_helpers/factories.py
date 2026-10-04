"""Payload factories — one per create/action payload, input fields only.

Computed and system fields are never supplied (a citation's points, a
permit's fees, etc. are server-computed per the PRD). Identity references
(applicant_ref, cooperator_ref) mint dashed UUIDs by default so each test
gets a fresh caller identity; override with a fixed string when a test needs
a known caller. Dates default to the standard fixture dates, all consistent
with the startup logical clock (2026-09-01).
"""
from uuid import uuid4

from .constants import (
    DETERMINATION_COMMENT_OPEN_DATE, DETERMINATION_COMMENT_CLOSE_DATE,
    PERMIT_START_DATE, PERMIT_END_DATE, CLOSURE_START_DATE, CLOSURE_END_DATE,
    PROGRAM_DATE, TREATMENT_WINDOW_START, TREATMENT_WINDOW_END,
    GRAZING_WINDOW_START, GRAZING_WINDOW_END, GRAZING_APPLICATION_DEADLINE,
)

__all__ = [
    "create_management_unit_payload", "create_determination_payload",
    "create_finalize_payload", "create_comment_payload",
    "create_adjudicate_payload",
    "create_permit_payload", "create_resubmit_payload", "create_pay_payload",
    "create_revoke_payload", "create_return_for_revision_payload",
    "create_treatment_payload", "create_closure_payload",
    "create_program_payload", "create_volunteer_payload",
    "create_assignment_payload", "create_grazing_offering_payload",
    "create_bid_payload", "create_assess_payload",
    "create_ledger_entry_payload", "create_citation_payload",
    "create_population_objective_payload", "create_survey_payload",
    "create_clock_payload",
]


def create_management_unit_payload(**overrides) -> dict:
    defaults = {"name": "North Marsh", "habitat_type": "WETLAND", "acreage": 1200}
    defaults.update(overrides)
    return defaults


def create_determination_payload(**overrides) -> dict:
    defaults = {
        "use_type": "RESEARCH",
        "title": "Research use compatibility",
        "comment_open_date": DETERMINATION_COMMENT_OPEN_DATE,
        "comment_close_date": DETERMINATION_COMMENT_CLOSE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_finalize_payload(**overrides) -> dict:
    defaults = {
        "finding": "COMPATIBLE",
        "rationale": "No material interference with refuge purposes.",
    }
    defaults.update(overrides)
    return defaults


def create_comment_payload(**overrides) -> dict:
    defaults = {"author_name": "Citizen A", "body": "Comment on the proposed use."}
    defaults.update(overrides)
    return defaults


def create_adjudicate_payload(**overrides) -> dict:
    defaults = {"disposition": "NOTED"}
    defaults.update(overrides)
    return defaults


def create_permit_payload(management_unit_id: str, determination_id: str,
                          **overrides) -> dict:
    """Permit application payload. applicant_ref defaults to a fresh dashed
    UUID — callers must send X-User-ID equal to applicant_ref (ownership
    anchor), so thread payload["applicant_ref"] into the applicant headers."""
    defaults = {
        "applicant_ref": f"applicant-{uuid4()}",
        "management_unit_id": management_unit_id,
        "determination_id": determination_id,
        "use_type": "RESEARCH",
        "crew_size": 4,
        "start_date": PERMIT_START_DATE,
        "end_date": PERMIT_END_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_resubmit_payload(**overrides) -> dict:
    """Resubmission input: optional crew_size / start_date / end_date / note.
    use_type and determination_id are immutable and never supplied."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_pay_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_revoke_payload(**overrides) -> dict:
    defaults = {"reason": "Permit revoked by the refuge."}
    defaults.update(overrides)
    return defaults


def create_return_for_revision_payload(**overrides) -> dict:
    defaults = {"note": "Revision requested."}
    defaults.update(overrides)
    return defaults


def create_treatment_payload(**overrides) -> dict:
    defaults = {
        "treatment_type": "INVASIVE_CONTROL",
        "window_start": TREATMENT_WINDOW_START,
        "window_end": TREATMENT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_closure_payload(**overrides) -> dict:
    defaults = {
        "closure_type": "MIGRATION",
        "scope": "FULL",
        "start_date": CLOSURE_START_DATE,
        "end_date": CLOSURE_END_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "title": "Owl Prowl",
        "program_date": PROGRAM_DATE,
        "min_volunteers": 1,
        "max_volunteers": 3,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    token = uuid4()
    defaults = {"full_name": "Vol One", "email": f"volunteer-{token}@example.com"}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(volunteer_id: str, **overrides) -> dict:
    defaults = {"volunteer_id": volunteer_id}
    defaults.update(overrides)
    return defaults


def create_grazing_offering_payload(**overrides) -> dict:
    defaults = {
        "description": "Winter grazing for reed control",
        "aum_cap": 100,
        "grazing_window_start": GRAZING_WINDOW_START,
        "grazing_window_end": GRAZING_WINDOW_END,
        "application_deadline": GRAZING_APPLICATION_DEADLINE,
        "min_stewardship_rating": 5,
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(cooperator_ref: str = None, **overrides) -> dict:
    """Cooperator bid payload. cooperator_ref defaults to a fresh dashed UUID —
    callers must send X-User-ID equal to cooperator_ref (ownership anchor)."""
    defaults = {
        "cooperator_ref": cooperator_ref or f"cooperator-{uuid4()}",
        "rate_cents_per_aum": 2000,
        "stewardship_rating": 7,
    }
    defaults.update(overrides)
    return defaults


def create_assess_payload(expected_agreement_version: int, **overrides) -> dict:
    """Period assessment payload; the OCC guard field is non-optional."""
    defaults = {
        "period_key": "2026-11",
        "aum_used": 3,
        "rate_cents_per_aum": 1001,
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(entry_type: str, amount_cents: int,
                                **overrides) -> dict:
    """Ledger entry payload. entry_type is PAYMENT (owning Cooperator) or
    REFUND (RefugeManager)."""
    defaults = {"type": entry_type, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_citation_payload(subject_permit_id: str = None,
                            subject_agreement_id: str = None,
                            expected_agreement_version=None,
                            **overrides) -> dict:
    """Citation payload: exactly one subject must be supplied. The OCC field
    expected_agreement_version is required iff the subject is an agreement
    (permit-subject citations carry no version field)."""
    if (subject_permit_id is None) == (subject_agreement_id is None):
        raise ValueError(
            "exactly one of subject_permit_id / subject_agreement_id is required")
    if subject_agreement_id is not None and expected_agreement_version is None:
        raise ValueError(
            "expected_agreement_version is required for agreement-subject citations")
    defaults = {"severity": "MAJOR", "note": "Violation observed on refuge."}
    if subject_permit_id is not None:
        defaults["subject_permit_id"] = subject_permit_id
    if subject_agreement_id is not None:
        defaults["subject_agreement_id"] = subject_agreement_id
        defaults["expected_agreement_version"] = expected_agreement_version
    defaults.update(overrides)
    return defaults


def create_population_objective_payload(**overrides) -> dict:
    defaults = {"species": "Sandhill Crane", "target_count": 1000}
    defaults.update(overrides)
    return defaults


def create_survey_payload(survey_count: int, **overrides) -> dict:
    defaults = {"survey_count": survey_count}
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults

"""Request payload builders.

Every literal here satisfies the PRD's declared format, length and range rules:
program codes are 4-12 characters of uppercase A-Z, digits and the hyphen;
department codes are 2-12 characters; term codes are 4-10 characters; section
and finding codes are uppercase and 1-20 characters; ``fte`` is a JSON number
above 0 and at or below 1.00 carried to two decimals; every money amount is a
JSON integer number of cents, never a string.

Instants are always full ISO-8601 UTC instants with a time component and a
trailing ``Z``, never date-only literals.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import REQUIRED_SECTION_CODES

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def unique_program_code(prefix: str = "PROG") -> str:
    """A 4-12 character code of uppercase A-Z, digits and the hyphen."""
    return f"{prefix}-{_next():04d}"[:12]


def unique_faculty_number(prefix: str = "FAC") -> str:
    """A 4-20 character HR number, unique within a program."""
    return f"{prefix}-{_next():05d}"


def unique_student_number(prefix: str = "S") -> str:
    """A 4-20 character registrar number, unique within a plan."""
    return f"{prefix}-{_next():05d}"


# --- §3.1 program registration ---------------------------------------------


def program_payload(
    code: Optional[str] = None,
    name: str = "Bachelor of Science in Chemistry",
    degree_level: str = "UNDERGRADUATE",
    department_code: str = "CHEM",
    host_capacity_per_day: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code if code is not None else unique_program_code("CHEM"),
        "name": name,
        "degree_level": degree_level,
        "department_code": department_code,
    }
    if host_capacity_per_day is not None:
        payload["host_capacity_per_day"] = host_capacity_per_day
    payload.update(overrides)
    return payload


def metric_snapshot_payload(
    term_code: str = "2026FA",
    term_index: int = 1,
    enrollment_headcount: int = 30,
    credit_hours: int = 300,
    direct_cost_cents: int = 12000000,
    completions_count: int = 4,
    market_demand_index: int = 42,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "term_code": term_code,
        "term_index": term_index,
        "enrollment_headcount": enrollment_headcount,
        "credit_hours": credit_hours,
        "direct_cost_cents": direct_cost_cents,
        "completions_count": completions_count,
        "market_demand_index": market_demand_index,
    }
    payload.update(overrides)
    return payload


def catalog_status_payload(
    target_catalog_status: str,
    suppression_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_catalog_status": target_catalog_status}
    if suppression_note is not None:
        payload["suppression_note"] = suppression_note
    payload.update(overrides)
    return payload


# --- §3.3 review cycles and self-studies -----------------------------------


def review_cycle_payload(
    cycle_year: int = 2026,
    self_study_due_at: str = "2026-09-01T00:00:00Z",
    required_section_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_year": cycle_year,
        "self_study_due_at": self_study_due_at,
        "required_section_codes": (
            list(REQUIRED_SECTION_CODES)
            if required_section_codes is None
            else required_section_codes
        ),
    }
    payload.update(overrides)
    return payload


def self_study_payload(
    narrative: str = "The program's self-study narrative for the review cycle.",
    section_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "narrative": narrative,
        "section_codes": (
            list(REQUIRED_SECTION_CODES) if section_codes is None else section_codes
        ),
    }
    payload.update(overrides)
    return payload


def self_study_patch_payload(**fields: Any) -> Dict[str, Any]:
    """A PATCH body carrying only the fields the caller names."""
    return dict(fields)


def self_study_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def self_study_submit_payload(
    attestation_note: str = "The chair attests the self-study is complete.",
) -> Dict[str, Any]:
    return {"action": "SUBMIT", "attestation_note": attestation_note}


def self_study_return_payload(
    revision_notes: str = "Section coverage needs rework before acceptance.",
) -> Dict[str, Any]:
    return {"action": "RETURN", "revision_notes": revision_notes}


def self_study_accept_payload() -> Dict[str, Any]:
    return {"action": "ACCEPT"}


def program_response_payload(
    response_concurrence: str = "CONCUR",
    response_text: str = "The program concurs with the reviewers' findings.",
    disputed_finding_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "response_concurrence": response_concurrence,
        "response_text": response_text,
    }
    if disputed_finding_codes is not None:
        payload["disputed_finding_codes"] = disputed_finding_codes
    payload.update(overrides)
    return payload


# --- §3.4 reviewer logistics -----------------------------------------------


def external_reviewer_payload(
    full_name: str = "Dr Alex Reviewer",
    institution: str = "Northern State University",
    specialty_code: str = "CHEM-ORG",
    conflict_program_codes: Optional[List[str]] = None,
    travel_buffer_hours: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "institution": institution,
        "specialty_code": specialty_code,
    }
    if conflict_program_codes is not None:
        payload["conflict_program_codes"] = conflict_program_codes
    if travel_buffer_hours is not None:
        payload["travel_buffer_hours"] = travel_buffer_hours
    payload.update(overrides)
    return payload


def reviewer_visit_payload(
    cycle_id: str,
    reviewer_id: str,
    window_start_at: str = "2026-08-20T09:00:00Z",
    window_end_at: str = "2026-08-22T17:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "reviewer_id": reviewer_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload


def reviewer_report_payload(
    recommendation: str = "DISCONTINUE",
    finding_codes: Optional[List[str]] = None,
    narrative: str = "The review team's findings on the program under review.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recommendation": recommendation,
        "finding_codes": (
            ["F-CURRICULUM", "F-ASSESSMENT"] if finding_codes is None else finding_codes
        ),
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


# --- §3.6 / §3.8 decision records ------------------------------------------


def decision_payload(
    outcome: str,
    expected_cycle_version: int,
    rationale: str = "The rationale for the provost's proposed outcome.",
    effective_term_index: int = 4,
    receiving_program_id: Optional[str] = None,
    improvement_target_score: Optional[float] = None,
    improvement_review_term_index: Optional[int] = None,
    improvement_milestones: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "rationale": rationale,
        "effective_term_index": effective_term_index,
        "expected_cycle_version": expected_cycle_version,
    }
    if receiving_program_id is not None:
        payload["receiving_program_id"] = receiving_program_id
    if improvement_target_score is not None:
        payload["improvement_target_score"] = improvement_target_score
    if improvement_review_term_index is not None:
        payload["improvement_review_term_index"] = improvement_review_term_index
    if improvement_milestones is not None:
        payload["improvement_milestones"] = improvement_milestones
    payload.update(overrides)
    return payload


def decision_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def ratify_payload(
    ratification_note: Optional[str] = "Ratified by the second provost.",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": "RATIFY"}
    if ratification_note is not None:
        payload["ratification_note"] = ratification_note
    return payload


def effectuate_payload() -> Dict[str, Any]:
    return {"action": "EFFECTUATE"}


def rescind_payload(
    rescission_reason: str = "New evidence overturned the ratified outcome.",
) -> Dict[str, Any]:
    return {"action": "RESCIND", "rescission_reason": rescission_reason}


def evaluate_improvement_payload() -> Dict[str, Any]:
    return {"action": "EVALUATE_IMPROVEMENT"}


# --- §3.7 agency notifications ---------------------------------------------


def agency_notification_payload(
    agency_type: str = "FEDERAL",
    agency_code: str = "FED-ED",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_type": agency_type,
        "agency_code": agency_code,
    }
    payload.update(overrides)
    return payload


def notification_send_payload(
    transmitted_reference: str = "TRANSMIT-0001",
) -> Dict[str, Any]:
    return {"action": "SEND", "transmitted_reference": transmitted_reference}


def notification_acknowledge_payload() -> Dict[str, Any]:
    return {"action": "ACKNOWLEDGE"}


def notification_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# --- §3.9 teach-out plans, guarantees, seat ledger -------------------------


def teach_out_plan_payload(
    decision_id: str,
    expected_program_version: int,
    last_admit_term_index: int = 3,
    first_teach_out_term_index: int = 4,
    final_award_term_index: int = 6,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision_id": decision_id,
        "last_admit_term_index": last_admit_term_index,
        "first_teach_out_term_index": first_teach_out_term_index,
        "final_award_term_index": final_award_term_index,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def plan_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def plan_return_payload(
    revision_notes: str = "The seat ledger needs more guaranteed sections.",
) -> Dict[str, Any]:
    return {"action": "RETURN", "revision_notes": revision_notes}


def course_guarantee_payload(
    course_code: str = "CHEM-101",
    term_index: int = 4,
    seats_guaranteed: int = 6,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "course_code": course_code,
        "term_index": term_index,
        "seats_guaranteed": seats_guaranteed,
    }
    payload.update(overrides)
    return payload


def seat_commit_payload(
    displaced_student_id: str, seat_count: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "COMMIT",
        "displaced_student_id": displaced_student_id,
        "seat_count": seat_count,
    }
    payload.update(overrides)
    return payload


def seat_release_payload(
    displaced_student_id: str, seat_count: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "RELEASE",
        "displaced_student_id": displaced_student_id,
        "seat_count": seat_count,
    }
    payload.update(overrides)
    return payload


def seat_substitute_payload(
    substitute_course_code: str = "CHEM-105",
    substitution_justification: str = "The substitute course covers the same outcomes.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "SUBSTITUTE",
        "substitute_course_code": substitute_course_code,
        "substitution_justification": substitution_justification,
    }
    payload.update(overrides)
    return payload


def seat_waive_payload(
    waived_reason_code: str = "NO-DEMAND", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": "WAIVE", "waived_reason_code": waived_reason_code}
    payload.update(overrides)
    return payload


# --- §3.10 displaced students ----------------------------------------------


def displaced_student_payload(
    student_number: Optional[str] = None,
    credits_remaining: int = 12,
    max_credits_per_term: int = 15,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_number": (
            student_number if student_number is not None else unique_student_number()
        ),
        "credits_remaining": credits_remaining,
        "max_credits_per_term": max_credits_per_term,
    }
    payload.update(overrides)
    return payload


def advising_payload(
    advised_credits_per_term: int = 9, plan_signed: bool = True, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "advised_credits_per_term": advised_credits_per_term,
        "plan_signed": plan_signed,
    }
    payload.update(overrides)
    return payload


def student_complete_payload(
    completion_term_index: int = 5, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "COMPLETE",
        "completion_term_index": completion_term_index,
    }
    payload.update(overrides)
    return payload


def student_withdraw_payload(
    withdrawal_reason_code: str = "TRANSFERRED", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "WITHDRAW",
        "withdrawal_reason_code": withdrawal_reason_code,
    }
    payload.update(overrides)
    return payload


# --- §3.11 faculty appointments -------------------------------------------


def faculty_appointment_payload(
    faculty_number: Optional[str] = None,
    tenure_status: str = "TENURED",
    fte: float = 1.00,
    annual_salary_cents: int = 12000000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "faculty_number": (
            faculty_number if faculty_number is not None else unique_faculty_number()
        ),
        "tenure_status": tenure_status,
        "fte": fte,
        "annual_salary_cents": annual_salary_cents,
    }
    payload.update(overrides)
    return payload


def appointment_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def retain_payload() -> Dict[str, Any]:
    return {"action": "RETAIN"}


def propose_reassignment_payload(
    reassigned_to_department_code: str = "PHYS",
) -> Dict[str, Any]:
    return {
        "action": "PROPOSE_REASSIGNMENT",
        "reassigned_to_department_code": reassigned_to_department_code,
    }


def withdraw_reassignment_payload() -> Dict[str, Any]:
    return {"action": "WITHDRAW_REASSIGNMENT"}


def confirm_reassignment_payload() -> Dict[str, Any]:
    return {"action": "CONFIRM_REASSIGNMENT"}


def issue_notice_payload(notice_days: int) -> Dict[str, Any]:
    return {"action": "ISSUE_NOTICE", "notice_days": notice_days}


def separate_payload() -> Dict[str, Any]:
    return {"action": "SEPARATE"}

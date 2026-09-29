"""Request-payload factories.

Every factory returns ONLY the input fields the PRD §4 endpoint table declares
for its endpoint — never a computed or system field.  All money-free numerics
cross the wire as JSON numbers (never strings) and all instants cross as full
ISO-8601 UTC instants (date + time + `Z`), per PRD §2.4 and §2.7.

Each factory builds its defaults dict first and then applies `**overrides` with
`dict.update`, so an override can never collide with a positional default.
"""
import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CANONICAL_COMPONENT_SCORES,
    CANONICAL_GRADE_COMPONENTS,
    DEFAULT_CLOCK_UTC,
    LADDER_KIND,
    SHA256_A,
    SHA256_B,
    SHA256_C,
    SHA256_D,
    TEST_DEFAULTS,
)

_counter = itertools.count(1)
_course_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic per-process suffix for codes and e-mail local parts."""
    return f"{next(_counter):04d}"


def unique_course_code(prefix: str = "CRS") -> str:
    """A fresh `course_code` matching PRD §3.2.

    §3.2: "a `course_code` matching two to six uppercase letters, a hyphen and
    three digits" — so the numeric part is EXACTLY three digits, not the
    four-digit `unique_suffix()`.
    """
    return f"{prefix}-{next(_course_counter) % 1000:03d}"


def _build(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str = DEFAULT_CLOCK_UTC, **overrides) -> Dict[str, Any]:
    return _build({"current_utc": current_utc}, overrides)


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------


def department_payload(**overrides) -> Dict[str, Any]:
    return _build(dict(TEST_DEFAULTS["DEPT_ENGL"]), overrides)


def hist_department_payload(**overrides) -> Dict[str, Any]:
    return _build(dict(TEST_DEFAULTS["DEPT_HIST"]), overrides)


def phil_department_payload(**overrides) -> Dict[str, Any]:
    return _build(dict(TEST_DEFAULTS["DEPT_PHIL"]), overrides)


def unique_department_payload(**overrides) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _build(
        {
            "code": f"DEP{suffix}",
            "name": f"Department {suffix}",
            "enrolled_student_count": 1000,
            "faculty_headcount": 4,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Faculty member and training
# ---------------------------------------------------------------------------


def faculty_member_payload(department_id: str, **overrides) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _build(
        {
            "department_id": department_id,
            "full_name": f"Faculty {suffix}",
            "email": f"faculty{suffix}@example.edu",
        },
        overrides,
    )


def training_completion_payload(
    module_code: str = TEST_DEFAULTS["TRAINING_MODULE_CODE"],
    completed_at: str = TEST_DEFAULTS["TRAINING_COMPLETED_AT"],
    **overrides,
) -> Dict[str, Any]:
    return _build({"module_code": module_code, "completed_at": completed_at}, overrides)


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


def student_payload(**overrides) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _build(
        {
            "full_name": f"Student {suffix}",
            "email": f"student{suffix}@example.edu",
            "program_code": "BA-ENG",
            # PRD §3.2: "a `class_year` from 1 to 8" — NOT a calendar year.
            "class_year": 3,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Course offering
# ---------------------------------------------------------------------------


def course_offering_payload(
    department_id: str, instructor_id: str, **overrides
) -> Dict[str, Any]:
    return _build(
        {
            "department_id": department_id,
            "instructor_id": instructor_id,
            "course_code": TEST_DEFAULTS["COURSE_CODE"],
            "term_code": TEST_DEFAULTS["TERM_CODE"],
            "grade_components": [dict(c) for c in CANONICAL_GRADE_COMPONENTS],
        },
        overrides,
    )


def unique_course_offering_payload(
    department_id: str, instructor_id: str, **overrides
) -> Dict[str, Any]:
    base = {
        "course_code": unique_course_code(),
        "term_code": TEST_DEFAULTS["TERM_CODE"],
        "grade_components": [dict(c) for c in CANONICAL_GRADE_COMPONENTS],
    }
    base.update(overrides)
    return course_offering_payload(department_id, instructor_id, **base)


def single_component_offering_payload(
    department_id: str, instructor_id: str, **overrides
) -> Dict[str, Any]:
    """One component weighted 100 — the simplest legal gradebook."""
    base = {
        "grade_components": [{"code": "FINAL", "max_points": 100, "weight_pct": 100}]
    }
    base.update(overrides)
    return unique_course_offering_payload(department_id, instructor_id, **base)


# ---------------------------------------------------------------------------
# Integrity report
# ---------------------------------------------------------------------------


def report_payload(offering_id: str, student_id: str, **overrides) -> Dict[str, Any]:
    return _build(
        {
            "offering_id": offering_id,
            "student_id": student_id,
            "alleged_violation_type": "PLAGIARISM",
            "narrative": TEST_DEFAULTS["NARRATIVE"],
            "incident_at": TEST_DEFAULTS["INCIDENT_AT"],
            "component_scores": [dict(s) for s in CANONICAL_COMPONENT_SCORES],
        },
        overrides,
    )


def triage_payload(decision: str, triage_note: str = "Reviewed.", **overrides):
    return _build({"decision": decision, "triage_note": triage_note}, overrides)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def evidence_payload(
    report_id: str,
    kind: str = "SIMILARITY_REPORT",
    sha256: str = SHA256_A,
    page_count: int = 4,
    similarity_pct: Optional[float] = 45.00,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "report_id": report_id,
        "kind": kind,
        "sha256": sha256,
        "page_count": page_count,
    }
    if similarity_pct is not None:
        defaults["similarity_pct"] = similarity_pct
    return _build(defaults, overrides)


def similarity_evidence_payload(report_id: str, **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "kind": "SIMILARITY_REPORT",
        "sha256": SHA256_A,
        "page_count": 4,
        "similarity_pct": 45.00,
    }
    base.update(overrides)
    return evidence_payload(report_id, **base)


def proctor_log_payload(report_id: str, **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "kind": "PROCTOR_LOG",
        "sha256": SHA256_B,
        "page_count": 1,
        "similarity_pct": None,
    }
    base.update(overrides)
    return evidence_payload(report_id, **base)


def witness_statement_payload(report_id: str, **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "kind": "WITNESS_STATEMENT",
        "sha256": SHA256_C,
        "page_count": 2,
        "similarity_pct": None,
    }
    base.update(overrides)
    return evidence_payload(report_id, **base)


def document_evidence_payload(report_id: str, **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "kind": "DOCUMENT",
        "sha256": SHA256_D,
        "page_count": 3,
        "similarity_pct": None,
    }
    base.update(overrides)
    return evidence_payload(report_id, **base)


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------


def case_payload(report_id: str, **overrides) -> Dict[str, Any]:
    return _build({"report_id": report_id}, overrides)


def legacy_import_payload(
    report_id: str,
    decided_at: str = "2024-03-01T00:00:00Z",
    responsibility_finding: str = "RESPONSIBLE",
    imposed_ladder_rank: int = 4,
    completed_at: str = "2024-06-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _build(
        {
            "report_id": report_id,
            "decided_at": decided_at,
            "responsibility_finding": responsibility_finding,
            "imposed_ladder_rank": imposed_ladder_rank,
            "completed_at": completed_at,
        },
        overrides,
    )


def pathway_payload(pathway: str, **overrides) -> Dict[str, Any]:
    return _build({"pathway": pathway}, overrides)


def dismiss_payload(
    dismiss_reason: str = "Allegation withdrawn by the reporting instructor.",
    **overrides,
) -> Dict[str, Any]:
    return _build({"dismiss_reason": dismiss_reason}, overrides)


# ---------------------------------------------------------------------------
# Informal pathway
# ---------------------------------------------------------------------------


def informal_resolution_payload(
    expected_case_version: int,
    proposed_ladder_rank: int,
    effective_from: str,
    kind: Optional[str] = None,
    grade_component_code: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """`expected_case_version` is non-optional here (PRD §2.8 OCC rule)."""
    defaults: Dict[str, Any] = {
        "expected_case_version": expected_case_version,
        "proposed_ladder_rank": proposed_ladder_rank,
        "kind": kind if kind is not None else LADDER_KIND[proposed_ladder_rank],
        "effective_from": effective_from,
    }
    if grade_component_code is not None:
        defaults["grade_component_code"] = grade_component_code
    return _build(defaults, overrides)


def informal_response_payload(response: str, **overrides) -> Dict[str, Any]:
    return _build({"response": response}, overrides)


# ---------------------------------------------------------------------------
# Transcript notation
# ---------------------------------------------------------------------------


def expungement_request_payload(
    request_statement: str = "Two years of clean standing since completion.",
    **overrides,
) -> Dict[str, Any]:
    return _build({"request_statement": request_statement}, overrides)


def expungement_decision_payload(
    decision: str, decision_reason: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"decision": decision}
    if decision_reason is not None:
        defaults["decision_reason"] = decision_reason
    return _build(defaults, overrides)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def notification_payload(
    kind: str, response_window_days: Optional[int] = None, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"kind": kind}
    if response_window_days is not None:
        defaults["response_window_days"] = response_window_days
    return _build(defaults, overrides)


# ---------------------------------------------------------------------------
# Advisor engagements
# ---------------------------------------------------------------------------


def advisor_engagement_payload(
    case_id: str,
    advisor_kind: str = "FACULTY_ADVISOR",
    advisor_full_name: Optional[str] = None,
    advisor_bar_licensed: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "case_id": case_id,
        "advisor_full_name": advisor_full_name
        if advisor_full_name is not None
        else f"Advisor {unique_suffix()}",
        "advisor_kind": advisor_kind,
    }
    if advisor_bar_licensed is not None:
        defaults["advisor_bar_licensed"] = advisor_bar_licensed
    return _build(defaults, overrides)


def attorney_engagement_payload(case_id: str, **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "advisor_kind": "ATTORNEY",
        "advisor_bar_licensed": True,
    }
    base.update(overrides)
    return advisor_engagement_payload(case_id, **base)


def review_payload(
    decision: str, decision_reason: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"decision": decision}
    if decision_reason is not None:
        defaults["decision_reason"] = decision_reason
    return _build(defaults, overrides)


# ---------------------------------------------------------------------------
# Case meetings
# ---------------------------------------------------------------------------


def case_meeting_payload(
    case_id: str,
    instructor_id: str,
    start_at: str,
    end_at: str,
    advisor_present: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "case_id": case_id,
        "instructor_id": instructor_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    if advisor_present is not None:
        defaults["advisor_present"] = advisor_present
    return _build(defaults, overrides)


def meeting_outcome_payload(outcome: str, **overrides) -> Dict[str, Any]:
    return _build({"outcome": outcome}, overrides)


# ---------------------------------------------------------------------------
# Hearing rooms
# ---------------------------------------------------------------------------


def hearing_room_payload(
    code: Optional[str] = None,
    seat_capacity: int = 12,
    buffer_minutes: Optional[int] = None,
    sessions_per_day_cap: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "code": code if code is not None else f"ROOM-{unique_suffix()}",
        "seat_capacity": seat_capacity,
    }
    if buffer_minutes is not None:
        defaults["buffer_minutes"] = buffer_minutes
    if sessions_per_day_cap is not None:
        defaults["sessions_per_day_cap"] = sessions_per_day_cap
    return _build(defaults, overrides)


# ---------------------------------------------------------------------------
# Hearing sessions
# ---------------------------------------------------------------------------


def hearing_session_payload(
    case_id: str,
    room_id: str,
    chair_id: str,
    panelist_ids: List[str],
    start_at: str,
    end_at: str,
    **overrides,
) -> Dict[str, Any]:
    return _build(
        {
            "case_id": case_id,
            "room_id": room_id,
            "chair_id": chair_id,
            "panelist_ids": list(panelist_ids),
            "start_at": start_at,
            "end_at": end_at,
        },
        overrides,
    )


def adjourn_payload(
    adjourn_reason: str = "Panel requested additional documentary evidence.",
    **overrides,
) -> Dict[str, Any]:
    return _build({"adjourn_reason": adjourn_reason}, overrides)


def cancel_payload(
    cancel_reason: str = "Room became unavailable.", **overrides
) -> Dict[str, Any]:
    return _build({"cancel_reason": cancel_reason}, overrides)


# ---------------------------------------------------------------------------
# Panel votes
# ---------------------------------------------------------------------------


def panel_vote_payload(
    session_id: str,
    panelist_id: str,
    verdict: str,
    severity_recommendation: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "session_id": session_id,
        "panelist_id": panelist_id,
        "verdict": verdict,
    }
    if severity_recommendation is not None:
        defaults["severity_recommendation"] = severity_recommendation
    return _build(defaults, overrides)


# ---------------------------------------------------------------------------
# Sanctions
# ---------------------------------------------------------------------------


def sanction_payload(
    case_id: str,
    expected_case_version: int,
    ladder_rank: int,
    effective_from: str,
    kind: Optional[str] = None,
    grade_component_code: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """`expected_case_version` is non-optional here (PRD §2.8 OCC rule)."""
    defaults: Dict[str, Any] = {
        "case_id": case_id,
        "expected_case_version": expected_case_version,
        "kind": kind if kind is not None else LADDER_KIND[ladder_rank],
        "ladder_rank": ladder_rank,
        "effective_from": effective_from,
    }
    if grade_component_code is not None:
        defaults["grade_component_code"] = grade_component_code
    return _build(defaults, overrides)


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------


def appeal_payload(
    case_id: str,
    grounds: str = "PROCEDURE",
    statement: str = TEST_DEFAULTS["APPEAL_STATEMENT"],
    **overrides,
) -> Dict[str, Any]:
    return _build(
        {"case_id": case_id, "grounds": grounds, "statement": statement}, overrides
    )


def screen_payload(
    decision: str, decision_reason: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"decision": decision}
    if decision_reason is not None:
        defaults["decision_reason"] = decision_reason
    return _build(defaults, overrides)


def appeal_decision_payload(
    outcome: str,
    decision_reason: str = "Reviewed the full hearing record.",
    reduced_ladder_rank: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "outcome": outcome,
        "decision_reason": decision_reason,
    }
    if reduced_ladder_rank is not None:
        defaults["reduced_ladder_rank"] = reduced_ladder_rank
    return _build(defaults, overrides)

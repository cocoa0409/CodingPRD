"""Request-payload factories.

Every factory returns a valid, contract-shaped payload with sensible defaults
and accepts keyword overrides.  Money and quantity members are emitted as JSON
numbers (never strings); dates are ``YYYY-MM-DD`` and instants are
``YYYY-MM-DDTHH:MM:SSZ``, exactly the shapes the contract declares.
"""
import itertools
from typing import Any, Dict, List, Optional

_counter = itertools.count(1)


def unique_suffix() -> int:
    return next(_counter)


# ─── District ─────────────────────────────────────────

def district_payload(**overrides: Any) -> Dict[str, Any]:
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "name": f"Ridgeview Unified {n}",
        "district_code": f"D-RIDGE-{n}",
        "state_code": "CA",
        "requires_district_fingerprint": True,
        "travel_reimbursement_enabled": True,
    }
    payload.update(overrides)
    return payload


# ─── Candidate ────────────────────────────────────────

def candidate_payload(**overrides: Any) -> Dict[str, Any]:
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "candidate_code": f"C-{1000 + n}",
        "full_name": f"Avery Chen {n}",
        "program_track": "SECONDARY",
        "home_grid_x": 2,
        "home_grid_y": 4,
    }
    payload.update(overrides)
    return payload


def readiness_evaluate_payload(variant: Optional[str] = None,
                               **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if variant is not None:
        payload["variant"] = variant
    payload.update(overrides)
    return payload


def licensure_payload(decision: str = "RECOMMENDED",
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def licensure_denial_payload(denial_reason: str = "Clinical practice incomplete.",
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": "DENIED",
        "denial_reason": denial_reason,
    }
    payload.update(overrides)
    return payload


def state_report_payload(reporting_cycle: str = "2026-FALL",
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reporting_cycle": reporting_cycle}
    payload.update(overrides)
    return payload


# ─── Readiness items ──────────────────────────────────

def exam_item_payload(candidate_id: str, exam_score: int = 245,
                      issued_on: str = "2026-01-15",
                      expires_on: Optional[str] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """A content exam: exam scores never expire, so ``expires_on`` is omitted."""
    payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "item_type": "CONTENT_EXAM",
        "exam_score": exam_score,
        "issued_on": issued_on,
    }
    if expires_on is not None:
        payload["expires_on"] = expires_on
    payload.update(overrides)
    return payload


def clearance_item_payload(candidate_id: str,
                           clearance_scope: str = "DISTRICT_FINGERPRINT",
                           issued_on: str = "2026-05-01",
                           expires_on: Optional[str] = "2027-05-01",
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "item_type": "BACKGROUND_CLEARANCE",
        "clearance_scope": clearance_scope,
        "issued_on": issued_on,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


def coursework_item_payload(candidate_id: str, credits: float = 18,
                            issued_on: str = "2026-05-20",
                            expires_on: Optional[str] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """A coursework block: blocks never expire, so ``expires_on`` is omitted."""
    payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "item_type": "COURSEWORK_BLOCK",
        "credits": credits,
        "issued_on": issued_on,
    }
    if expires_on is not None:
        payload["expires_on"] = expires_on
    payload.update(overrides)
    return payload


def verify_item_payload(decision: str = "VERIFIED",
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def reject_item_payload(rejection_note: str = "Issuer could not be confirmed.",
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": "REJECTED",
        "rejection_note": rejection_note,
    }
    payload.update(overrides)
    return payload


# ─── Partnership agreement ────────────────────────────

def agreement_payload(district_id: str, term: str = "FALL_2026",
                      window_start: str = "2026-08-01",
                      window_end: str = "2027-01-31",
                      placement_cap: int = 1,
                      stipend_rate_cents_per_week: int = 12345,
                      allowed_subjects: Optional[List[str]] = None,
                      allowed_grade_bands: Optional[List[str]] = None,
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "district_id": district_id,
        "term": term,
        "window_start": window_start,
        "window_end": window_end,
        "placement_cap": placement_cap,
        "stipend_rate_cents_per_week": stipend_rate_cents_per_week,
        "allowed_subjects": allowed_subjects if allowed_subjects is not None
        else ["MATH", "ELA"],
        "allowed_grade_bands": allowed_grade_bands if allowed_grade_bands is not None
        else ["MG_5_9", "HS_9_12"],
    }
    payload.update(overrides)
    return payload


def suspend_payload(suspension_reason: str = "District compliance review.",
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"suspension_reason": suspension_reason}
    payload.update(overrides)
    return payload


def terminate_payload(suspension_reason: str = "District exited the partnership.",
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"suspension_reason": suspension_reason}
    payload.update(overrides)
    return payload


# ─── Cooperating teacher ──────────────────────────────

def teacher_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "district_id": district_id,
        "full_name": f"Tina Ortiz {n}",
        "site_name": f"Ridge High {n}",
        "site_grid_x": 10,
        "site_grid_y": 10,
        "subject_endorsement": "MATH",
        "grade_band": "HS_9_12",
        "years_experience": 9,
        "consecutive_terms_hosted": 2,
        "max_concurrent_candidates": 1,
    }
    payload.update(overrides)
    return payload


def training_completion_payload(training_completed_on: str = "2026-06-01",
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"training_completed_on": training_completed_on}
    payload.update(overrides)
    return payload


def disqualify_payload(
        disqualification_reason: str = "Substantiated misconduct finding.",
        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disqualification_reason": disqualification_reason}
    payload.update(overrides)
    return payload


# ─── University supervisor ────────────────────────────

def supervisor_payload(**overrides: Any) -> Dict[str, Any]:
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "full_name": f"Dr. Sam Reyes {n}",
        "employment_type": "FULL_TIME",
        "primary_subject": "MATH",
        "covered_grade_bands": ["MG_5_9", "HS_9_12"],
        "home_grid_x": 0,
        "home_grid_y": 0,
        "max_travel_miles": 60,
    }
    payload.update(overrides)
    return payload


def supervisor_update_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ─── Placement request ────────────────────────────────

def placement_request_payload(candidate_id: str,
                              preferred_district_id: Optional[str] = None,
                              term: str = "FALL_2026",
                              requested_subject: str = "MATH",
                              requested_grade_band: str = "HS_9_12",
                              max_commute_miles: int = 30,
                              term_start_date: str = "2026-09-01",
                              weeks_scheduled: int = 14,
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "term": term,
        "requested_subject": requested_subject,
        "requested_grade_band": requested_grade_band,
        "max_commute_miles": max_commute_miles,
        "term_start_date": term_start_date,
        "weeks_scheduled": weeks_scheduled,
    }
    if preferred_district_id is not None:
        payload["preferred_district_id"] = preferred_district_id
    payload.update(overrides)
    return payload


def reroute_payload(expected_request_version: int,
                    exclude_current_teacher: bool = True,
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_request_version": expected_request_version,
        "exclude_current_teacher": exclude_current_teacher,
    }
    payload.update(overrides)
    return payload


# ─── Placement lifecycle ──────────────────────────────

def removal_request_payload(
        removal_reason: str = "CANDIDATE_PERFORMANCE",
        removal_narrative: str = "Repeated unmet professional dispositions targets.",
        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "removal_reason": removal_reason,
        "removal_narrative": removal_narrative,
    }
    payload.update(overrides)
    return payload


def removal_decision_payload(decision: str = "UPHELD",
                             decision_note: str = "Removal upheld.",
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "decision_note": decision_note}
    payload.update(overrides)
    return payload


def complete_placement_payload(**overrides: Any) -> Dict[str, Any]:
    """Completion takes no settled figures: the settlement date is the clock's."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def stipend_transition_payload(target_status: str,
                               note: str = "Routine stipend transition.",
                               **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_status": target_status, "note": note}
    payload.update(overrides)
    return payload


# ─── Observation cycle ────────────────────────────────

def observation_cycle_payload(placement_id: str, sequence_no: int = 1,
                              cycle_type: str = "FORMATIVE",
                              window_start: str = "2026-09-14T00:00:00Z",
                              window_end: str = "2026-09-19T00:00:00Z",
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "sequence_no": sequence_no,
        "cycle_type": cycle_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def cycle_complete_payload(observed_at: str, rubric_score: float = 3.5,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "observed_at": observed_at,
        "rubric_score": rubric_score,
    }
    payload.update(overrides)
    return payload


def cycle_reschedule_payload(window_start: str, window_end: str,
                             resolution_note: str = "Moved at the site's request.",
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "window_start": window_start,
        "window_end": window_end,
        "resolution_note": resolution_note,
    }
    payload.update(overrides)
    return payload


# ─── Performance assessment ───────────────────────────

def assessment_payload(placement_id: str,
                       window_opens_at: str = "2026-11-01T00:00:00Z",
                       window_closes_at: str = "2026-12-01T00:00:00Z",
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "window_opens_at": window_opens_at,
        "window_closes_at": window_closes_at,
    }
    payload.update(overrides)
    return payload


def assessment_submit_payload(artifact_reference: str = "portfolio-v1",
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"artifact_reference": artifact_reference}
    payload.update(overrides)
    return payload


def assessment_score_payload(decision: str = "SCORE",
                             task_planning: Optional[float] = 4.0,
                             task_instruction: Optional[float] = 3.5,
                             task_assessment: Optional[float] = 3.0,
                             task_professionalism: Optional[float] = 3.0,
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if task_planning is not None:
        payload["task_planning"] = task_planning
    if task_instruction is not None:
        payload["task_instruction"] = task_instruction
    if task_assessment is not None:
        payload["task_assessment"] = task_assessment
    if task_professionalism is not None:
        payload["task_professionalism"] = task_professionalism
    payload.update(overrides)
    return payload


def assessment_return_payload(
        returned_feedback: str = "Expand the assessment-of-learning commentary.",
        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": "RETURN",
        "returned_feedback": returned_feedback,
    }
    payload.update(overrides)
    return payload

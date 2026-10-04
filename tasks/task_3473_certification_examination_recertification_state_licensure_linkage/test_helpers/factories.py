"""Payload factories — one per entity, input fields only (PRD §4 payloads).

Each factory returns a plain dict suitable for the matching ApiClient method;
`**overrides` win over the defaults so tests can steer exactly the fields a
claim exercises.
"""
import itertools

from .constants import (
    DEFAULT_LEVEL_PAYLOAD,
    DEFAULT_POLICY_PAYLOAD,
    DEFAULT_COMPLETION_DATE,
    DEFAULT_SCHEDULED_START,
    DEFAULT_SCHEDULED_END,
    DEFAULT_PSYCHOMOTOR_EXAM_DATE,
    DEFAULT_DIRECTOR_USER_ID,
)

_name_counter = itertools.count(1)
_course_counter = itertools.count(1)
_item_counter = itertools.count(1)


def _unique_email() -> str:
    return f"candidate-{next(_name_counter)}@example.com"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def create_level_payload(**overrides) -> dict:
    """LevelDefinition create payload (PRD §3.1). Defaults to the standard EMT."""
    payload = dict(DEFAULT_LEVEL_PAYLOAD)
    payload.update(overrides)
    return payload


def create_state_policy_payload(**overrides) -> dict:
    """StateAdoptionPolicy create payload (PRD §3.1)."""
    payload = dict(DEFAULT_POLICY_PAYLOAD)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Candidates / programs / completion records
# ---------------------------------------------------------------------------
def create_candidate_payload(**overrides) -> dict:
    payload = {"full_name": "Test Candidate", "email": _unique_email()}
    payload.update(overrides)
    return payload


def create_education_program_payload(level_id, **overrides) -> dict:
    payload = {
        "name": "County EMT Academy",
        "level_id": level_id,
        "director_user_id": DEFAULT_DIRECTOR_USER_ID,
    }
    payload.update(overrides)
    return payload


def accreditation_event_payload(to_status, effective_date, reason="Recorded event", **overrides) -> dict:
    payload = {"to_status": to_status, "effective_date": effective_date, "reason": reason}
    payload.update(overrides)
    return payload


def create_completion_record_payload(candidate_id, program_id, **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "program_id": program_id,
        "completion_date": DEFAULT_COMPLETION_DATE,
    }
    payload.update(overrides)
    return payload


def decision_payload(outcome, **overrides) -> dict:
    """Generic {outcome[, reason]} decision body (completion / exam app /
    psychomotor / recert / reentry / license decisions)."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Exam applications / attempts
# ---------------------------------------------------------------------------
def create_exam_application_payload(level_id, completion_record_id, **overrides) -> dict:
    payload = {"level_id": level_id, "completion_record_id": completion_record_id}
    payload.update(overrides)
    return payload


def resubmit_application_payload(**overrides) -> dict:
    """Optional completion_record_id swap on resubmit (PRD §3.4)."""
    return dict(overrides)


def schedule_attempt_payload(att_id, scheduled_start=DEFAULT_SCHEDULED_START,
                             scheduled_end=DEFAULT_SCHEDULED_END, **overrides) -> dict:
    payload = {
        "att_id": att_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def cat_response_items(correct_count, total=None, difficulty_b=0.5,
                       item_prefix="q") -> list:
    """Build `total` CAT item dicts, the first `correct_count` marked correct.

    All items share `difficulty_b` (weighted accuracy then equals the plain
    correct fraction, which keeps expected theta arithmetic simple).
    """
    total = correct_count if total is None else total
    items = []
    for i in range(total):
        items.append({
            "item_id": f"{item_prefix}{next(_item_counter)}",
            "difficulty_b": difficulty_b,
            "correct": i < correct_count,
        })
    return items


def cat_pass_responses(n=8, difficulty_b=0.5) -> dict:
    """All-correct delivery: theta 1.0 -> band exits PASS at CAT_MIN_ITEMS."""
    return {"responses": cat_response_items(n, n, difficulty_b)}


def cat_fail_responses(n=6, difficulty_b=0.5) -> dict:
    """All-wrong delivery: theta 0.0 -> band exits FAIL at CAT_MIN_ITEMS."""
    return {"responses": cat_response_items(0, n, difficulty_b)}


def cat_responses_payload(correct_count, total=None, difficulty_b=0.5) -> dict:
    return {"responses": cat_response_items(correct_count, total, difficulty_b)}


# ---------------------------------------------------------------------------
# Remedial education / psychomotor
# ---------------------------------------------------------------------------
def create_remedial_record_payload(candidate_id, level_id, **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "level_id": level_id,
        "hours": 20,
        "completed_date": DEFAULT_COMPLETION_DATE,
        "provider_name": "RemedialCE",
    }
    payload.update(overrides)
    return payload


def passing_stations(*station_codes) -> list:
    codes = station_codes or ("AIRWAY",)
    return [{"station_code": code, "passed": True} for code in codes]


def create_psychomotor_payload(candidate_id, level_id, completion_record_id,
                               **overrides) -> dict:
    """STATE-administered by default (no program_id, no segregation entanglement)."""
    payload = {
        "candidate_id": candidate_id,
        "level_id": level_id,
        "administered_by": "STATE",
        "completion_record_id": completion_record_id,
        "exam_date": DEFAULT_PSYCHOMOTOR_EXAM_DATE,
        "stations": passing_stations("AIRWAY"),
        "documentation_attached": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Certification issuance
# ---------------------------------------------------------------------------
def issue_certification_payload(candidate_id, level_id, exam_application_id,
                                attempt_id, psychomotor_id, **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "level_id": level_id,
        "exam_application_id": exam_application_id,
        "attempt_id": attempt_id,
        "psychomotor_id": psychomotor_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recertification
# ---------------------------------------------------------------------------
def create_recert_application_payload(certification_id, model, expected_certification_version,
                                      **overrides) -> dict:
    payload = {
        "certification_id": certification_id,
        "model": model,
        "expected_certification_version": expected_certification_version,
    }
    payload.update(overrides)
    return payload


def ce_entry_payload(component, hours, delivery_method, course_date,
                     provider_name, **overrides) -> dict:
    """CECreditEntry payload; course_code auto-uniques unless overridden."""
    payload = {
        "component": component,
        "hours": hours,
        "delivery_method": delivery_method,
        "course_code": f"C{next(_course_counter)}",
        "course_date": course_date,
        "provider_name": provider_name,
    }
    payload.update(overrides)
    return payload


def audit_outcome_payload(entry_verdicts) -> dict:
    """entry_verdicts: [{"entry_id": ..., "verdict": "VERIFIED"|"REJECTED"[, "reason": ...]}]"""
    return {"entry_verdicts": entry_verdicts}


def audit_verdict(entry_id, verdict, reason=None) -> dict:
    v = {"entry_id": entry_id, "verdict": verdict}
    if reason is not None:
        v["reason"] = reason
    return v


# ---------------------------------------------------------------------------
# Reentry
# ---------------------------------------------------------------------------
def create_reentry_application_payload(certification_id, **overrides) -> dict:
    payload = {"certification_id": certification_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# State licensure
# ---------------------------------------------------------------------------
def create_license_application_payload(state_code, level_id, **overrides) -> dict:
    """Optional keys per path: certification_id (+ expected_certification_version)
    for NREMT, state_exam_record_id for STATE_EXAM, jurisprudence_completed."""
    payload = {"state_code": state_code, "level_id": level_id}
    payload.update(overrides)
    return payload


def license_respond_payload(response_note="Additional information attached", **overrides) -> dict:
    payload = {"response_note": response_note}
    payload.update(overrides)
    return payload


def create_state_exam_record_payload(candidate_id, state_code, level_id, **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "state_code": state_code,
        "level_id": level_id,
        "exam_date": DEFAULT_PSYCHOMOTOR_EXAM_DATE,
        "score": 85.0,
        "passing_score": 70.0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Disciplinary cases
# ---------------------------------------------------------------------------
def create_disciplinary_case_payload(subject_candidate_id, violation_type, **overrides) -> dict:
    payload = {
        "subject_candidate_id": subject_candidate_id,
        "violation_type": violation_type,
        "description": "Allegation under review",
    }
    payload.update(overrides)
    return payload


def case_response_payload(response_text="Response to the allegations", **overrides) -> dict:
    payload = {"response_text": response_text}
    payload.update(overrides)
    return payload


def case_decide_payload(sanction_type, findings, expected_case_version, **overrides) -> dict:
    payload = {
        "sanction_type": sanction_type,
        "findings": findings,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def case_appeal_payload(appeal_grounds="Procedural challenge", **overrides) -> dict:
    payload = {"appeal_grounds": appeal_grounds}
    payload.update(overrides)
    return payload


def appeal_decision_payload(outcome, rationale="Appeal reviewed", **overrides) -> dict:
    payload = {"outcome": outcome, "rationale": rationale}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}

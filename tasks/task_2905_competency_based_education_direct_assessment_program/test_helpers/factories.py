"""Payload factories — one per entity, carrying only the fields a client sends.

Monetary amounts are always JSON numbers of whole cents. Every instant is a full
ISO 8601 UTC instant with three fractional digits, never a date-only literal.
"""
from typing import Any, Dict, List, Optional

from .constants import SINGLE_DIMENSION_RUBRIC, TEST_DEFAULTS


def create_program_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": TEST_DEFAULTS["PROGRAM_CODE"],
        "title": TEST_DEFAULTS["PROGRAM_TITLE"],
    }
    payload.update(overrides)
    return payload


def create_competency_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "code": TEST_DEFAULTS["COMPETENCY_CODE"],
        "title": TEST_DEFAULTS["COMPETENCY_TITLE"],
        "unit_value": TEST_DEFAULTS["COMPETENCY_UNIT_VALUE"],
        "level": TEST_DEFAULTS["COMPETENCY_LEVEL"],
    }
    payload.update(overrides)
    return payload


def create_blueprint_payload(
    competency_id: str,
    expected_competency_version: int,
    dimensions: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "competency_id": competency_id,
        "expected_competency_version": expected_competency_version,
        "dimensions": [dict(d) for d in (dimensions or SINGLE_DIMENSION_RUBRIC)],
        "passing_rule": "WEIGHTED_ONLY",
        "required_evaluator_count": 1,
        "effective_from_utc": TEST_DEFAULTS["TERM_START_UTC"],
    }
    payload.update(overrides)
    return payload


def create_student_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "full_name": TEST_DEFAULTS["STUDENT_NAME"],
        "email": TEST_DEFAULTS["STUDENT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_subscription_term_payload(student_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "term_start_utc": TEST_DEFAULTS["TERM_START_UTC"],
        "term_end_utc": TEST_DEFAULTS["TERM_END_UTC"],
        "tuition_cents": TEST_DEFAULTS["TUITION_CENTS"],
    }
    payload.update(overrides)
    return payload


def close_term_payload(outcome: str, effective_utc: str, **overrides: Any
                       ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome, "effective_utc": effective_utc}
    payload.update(overrides)
    return payload


def withdraw_student_payload(effective_utc: str, reason: str = "personal",
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"effective_utc": effective_utc, "reason": reason}
    payload.update(overrides)
    return payload


def create_mentor_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": TEST_DEFAULTS["MENTOR_NAME"],
        "email": TEST_DEFAULTS["MENTOR_EMAIL"],
        "max_caseload": TEST_DEFAULTS["MENTOR_MAX_CASELOAD"],
        "cadence_days": TEST_DEFAULTS["MENTOR_CADENCE_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_mentor_assignment_payload(
    student_id: str, expected_student_version: int,
    mentor_id: Optional[str] = None, **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "expected_student_version": expected_student_version,
    }
    if mentor_id is not None:
        payload["mentor_id"] = mentor_id
    payload.update(overrides)
    return payload


def create_evaluator_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": TEST_DEFAULTS["EVALUATOR_NAME"],
        "email": TEST_DEFAULTS["EVALUATOR_EMAIL"],
        "certification_level": TEST_DEFAULTS["EVALUATOR_CERTIFICATION_LEVEL"],
    }
    payload.update(overrides)
    return payload


def create_attempt_payload(student_id: str, competency_id: str, **overrides: Any
                           ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "competency_id": competency_id,
    }
    payload.update(overrides)
    return payload


def submit_attempt_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "artifact_hash": TEST_DEFAULTS["ARTIFACT_HASH"],
        "integrity_attestation_accepted": True,
        "client_fingerprint": TEST_DEFAULTS["CLIENT_FINGERPRINT"],
    }
    payload.update(overrides)
    return payload


def record_score_payload(
    evaluator_id: str, dimension_scores: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evaluator_id": evaluator_id,
        "dimension_scores": [dict(d) for d in (
            dimension_scores or [{"code": "D1", "score": 90}]
        )],
    }
    payload.update(overrides)
    return payload


def create_integrity_case_payload(attempt_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "attempt_id": attempt_id,
        "signal_type": "THIRD_PARTY_REPORT",
        "severity": "MEDIUM",
    }
    payload.update(overrides)
    return payload


def resolve_case_payload(outcome: str, sanction: str = "NONE", **overrides: Any
                         ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome, "sanction": sanction}
    payload.update(overrides)
    return payload


def create_sap_review_payload(student_id: str, term_id: str, **overrides: Any
                              ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"student_id": student_id, "term_id": term_id}
    payload.update(overrides)
    return payload


def create_aid_disbursement_payload(
    student_id: str, term_id: str, expected_term_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "term_id": term_id,
        "scheduled_amount_cents": TEST_DEFAULTS["AID_SCHEDULED_CENTS"],
        "expected_term_version": expected_term_version,
    }
    payload.update(overrides)
    return payload


def create_transcript_record_payload(student_id: str, purpose: str = "TRANSFER",
                                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"student_id": student_id, "purpose": purpose}
    payload.update(overrides)
    return payload


def rubric_dimension(code: str, weight: float, max_score: float,
                     critical: bool = False) -> Dict[str, Any]:
    return {"code": code, "weight": weight, "max_score": max_score,
            "critical": critical}


def dimension_score(code: str, score: float) -> Dict[str, Any]:
    return {"code": code, "score": score}

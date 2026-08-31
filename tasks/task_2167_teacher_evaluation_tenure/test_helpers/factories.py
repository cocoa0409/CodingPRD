"""Payload factories — one per resource, request-input fields only."""

from .constants import SCHOOL_YEAR

_EMP_SEQ = {"n": 0}


def next_employee_number(prefix: str = "E") -> str:
    """District employee numbers must be unique across all educators."""
    _EMP_SEQ["n"] += 1
    return f"{prefix}-{1000 + _EMP_SEQ['n']}"


def evaluation_policy_payload(**overrides) -> dict:
    """Only school_year is required; every other field takes its declared default."""
    payload = {"school_year": SCHOOL_YEAR}
    payload.update(overrides)
    return payload


def school_payload(**overrides) -> dict:
    payload = {
        "name": "Lincoln High",
        "code": "LHS",
        "level": "HIGH",
        "evaluation_budget_allocated_cents": 100000,
    }
    payload.update(overrides)
    return payload


def educator_payload(school_id: str, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "employee_number": next_employee_number(),
        "full_name": "Dana Reed",
        "service_start_date": "2024-08-15",
    }
    payload.update(overrides)
    return payload


def evaluator_payload(**overrides) -> dict:
    payload = {"full_name": "Pat Ortiz"}
    payload.update(overrides)
    return payload


def calibration_review_payload(evaluator_id: str, **overrides) -> dict:
    payload = {
        "evaluator_id": evaluator_id,
        "anchor_lesson_code": "ANCH-1",
        "anchor_score": 3.00,
        "evaluator_score": 3.10,
    }
    payload.update(overrides)
    return payload


def evaluation_cycle_payload(educator_id: str, policy_id: str, **overrides) -> dict:
    payload = {
        "educator_id": educator_id,
        "policy_id": policy_id,
        "school_year": SCHOOL_YEAR,
    }
    payload.update(overrides)
    return payload


def observation_payload(cycle_id: str, evaluator_id: str, **overrides) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "evaluator_id": evaluator_id,
        "observation_type": "FORMAL",
        "scheduled_start": "2026-09-10T09:00:00Z",
        "scheduled_end": "2026-09-10T10:00:00Z",
        "announced": True,
    }
    payload.update(overrides)
    return payload


def rubric_score_payload(domain_code: str, raw_score: int,
                         expected_observation_version: int, **overrides) -> dict:
    payload = {
        "domain_code": domain_code,
        "raw_score": raw_score,
        "expected_observation_version": expected_observation_version,
    }
    payload.update(overrides)
    return payload


def evidence_artifact_payload(**overrides) -> dict:
    payload = {"artifact_type": "LESSON_PLAN", "title": "Unit 3 plan"}
    payload.update(overrides)
    return payload


def growth_measure_payload(cycle_id: str, expected_cycle_version: int, **overrides) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "measure_code": "STATE_ASSESSMENT",
        "index_value": 3.00,
        "coverage_pct": 100,
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


def appeal_payload(cycle_id: str, **overrides) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "grounds": "PROCEDURAL",
        "statement": "The required pre-conference never happened",
    }
    payload.update(overrides)
    return payload


def grievance_payload(appeal_id: str, **overrides) -> dict:
    payload = {"appeal_id": appeal_id, "article_code": "ART_12_EVALUATION"}
    payload.update(overrides)
    return payload

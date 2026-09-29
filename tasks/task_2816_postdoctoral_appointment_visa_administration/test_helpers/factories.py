"""Payload factories — one per write operation, client-supplied fields only.

Monetary amounts are always emitted as JSON numbers, never as strings.
"""

import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short unique token for fields that must not collide across records."""
    return f"{next(_counter):05d}"


def unique_email(local: str = "scholar") -> str:
    """An institutional address; `email` must be unique across scholar records."""
    return f"{local}.{unique_suffix()}@example.edu"


# ─── Registries ───────────────────────────────────────────────────────────

def create_postdoc_payload(**overrides) -> dict:
    """Register a prospective scholar. The four optional flags are omitted so
    that their declared defaults apply unless a test overrides them."""
    payload = {
        "full_name": f"Test Scholar {unique_suffix()}",
        "email": unique_email(),
        "citizenship_country": "US",
        "requires_sponsorship": False,
        "phd_award_date": TEST_DEFAULTS["PHD_AWARD_DATE"],
    }
    payload.update(overrides)
    return payload


def create_faculty_mentor_payload(**overrides) -> dict:
    payload = {
        "full_name": f"Test Mentor {unique_suffix()}",
        "department": "Molecular Biology",
        "mentor_training_valid_through": TEST_DEFAULTS["MENTOR_TRAINING_VALID_THROUGH"],
    }
    payload.update(overrides)
    return payload


def create_funding_source_payload(**overrides) -> dict:
    payload = {
        "sponsor_name": f"Sponsor {unique_suffix()}",
        "funding_type": "FEDERAL_GRANT",
        "salary_floor_policy": "NIH_SCALE",
        "award_start_date": TEST_DEFAULTS["AWARD_START_DATE"],
        "award_end_date": TEST_DEFAULTS["AWARD_END_DATE"],
        "annual_budget_usd": TEST_DEFAULTS["AWARD_BUDGET_USD"],
    }
    payload.update(overrides)
    return payload


def create_laboratory_payload(**overrides) -> dict:
    payload = {
        "name": f"Laboratory {unique_suffix()}",
        "biosafety_level": "BSL1",
        "bench_capacity": TEST_DEFAULTS["BENCH_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def verification_payload(decision: str = "VERIFY") -> dict:
    return {"decision": decision}


# ─── Appointments ─────────────────────────────────────────────────────────

def create_appointment_payload(postdoc_id: str, mentor_id: str,
                               funding_source_id: str, **overrides) -> dict:
    payload = {
        "postdoc_id": postdoc_id,
        "mentor_id": mentor_id,
        "funding_source_id": funding_source_id,
        "title_classification": "POSTDOC_ASSOCIATE",
        "employment_class": "EMPLOYEE",
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "annual_salary_usd": TEST_DEFAULTS["ANNUAL_SALARY_USD"],
    }
    payload.update(overrides)
    return payload


def salary_exception_payload(expected_appointment_version: int,
                             exception_floor_usd: float,
                             justification: str = "Documented compensation exception.") -> dict:
    return {
        "expected_appointment_version": expected_appointment_version,
        "exception_floor_usd": exception_floor_usd,
        "justification": justification,
    }


def accept_offer_payload(processing_track: str = None) -> dict:
    return {} if processing_track is None else {"processing_track": processing_track}


def withdraw_payload(withdraw_reason: str = "CANDIDATE_DECLINED") -> dict:
    return {"withdraw_reason": withdraw_reason}


# ─── Sponsorship pipeline ─────────────────────────────────────────────────

def submit_petition_payload(processing_track: str = None) -> dict:
    return {} if processing_track is None else {"processing_track": processing_track}


def adjudication_payload(outcome: str, decision_note: str = None) -> dict:
    payload = {"outcome": outcome}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


# ─── Funder mandates ──────────────────────────────────────────────────────

def submit_document_payload(content_summary: str = "Mentoring commitments for the term.",
                            postdoc_acknowledged: bool = None) -> dict:
    payload = {"content_summary": content_summary}
    if postdoc_acknowledged is not None:
        payload["postdoc_acknowledged"] = postdoc_acknowledged
    return payload


def review_document_payload(decision: str, reviewer_note: str = None) -> dict:
    payload = {"decision": decision}
    if reviewer_note is not None:
        payload["reviewer_note"] = reviewer_note
    return payload


# ─── Research security ────────────────────────────────────────────────────

def screening_decision_payload(restricted_party_hit: bool = False,
                               controlled_technology_flag: bool = False) -> dict:
    return {
        "restricted_party_hit": restricted_party_hit,
        "controlled_technology_flag": controlled_technology_flag,
    }


def create_lab_access_grant_payload(appointment_id: str, laboratory_id: str,
                                    expected_appointment_version: int = None,
                                    **overrides) -> dict:
    payload = {
        "appointment_id": appointment_id,
        "laboratory_id": laboratory_id,
        "bench_seats": 1,
        "access_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "access_end_date": TEST_DEFAULTS["TERM_END_DATE"],
    }
    if expected_appointment_version is not None:
        payload["expected_appointment_version"] = expected_appointment_version
    payload.update(overrides)
    return payload


# ─── Reappointment, grievance and exit ────────────────────────────────────

def recommendation_payload(recommendation: str,
                           mentor_recommendation_note: str = "Written recommendation.") -> dict:
    return {
        "recommendation": recommendation,
        "mentor_recommendation_note": mentor_recommendation_note,
    }


def finalize_payload(decision: str) -> dict:
    return {"decision": decision}


def create_grievance_payload(reappointment_review_id: str,
                             category: str = "PROCEDURAL",
                             narrative: str = "The scholar's written statement.") -> dict:
    return {
        "reappointment_review_id": reappointment_review_id,
        "category": category,
        "narrative": narrative,
    }


def grievance_resolution_payload(outcome: str,
                                 resolution_note: str = "The officer's rationale.") -> dict:
    return {"outcome": outcome, "resolution_note": resolution_note}


def initiate_exit_payload(exit_reason: str = "TERM_COMPLETION") -> dict:
    return {"exit_reason": exit_reason}


def ip_assignment_payload(ip_disclosure_count: int = 0) -> dict:
    return {"ip_disclosure_count": ip_disclosure_count}

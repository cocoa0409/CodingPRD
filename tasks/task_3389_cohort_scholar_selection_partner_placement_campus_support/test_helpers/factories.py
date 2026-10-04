"""Payload factories — one per writable endpoint, input fields only (PRD §4).

Optional fields are omitted from the payload entirely when not supplied, so
factories never impose a client-side default the PRD leaves to the server
(e.g. first_generation is only sent when explicitly passed).
"""
from .constants import (
    DEFAULT_CITY_CODE,
    DEFAULT_CITY_NAME,
    DEFAULT_COHORT_SIZE,
    DEFAULT_COLLEGE_NAME,
    DEFAULT_CYCLE,
    DEFAULT_MENTOR_NAME,
    DEFAULT_PARTNER_NAME,
    DEFAULT_TUITION_CENTS,
    WINDOW_CLOSES,
    WINDOW_OPENS,
)


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_city_program_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULT_CITY_CODE,
        "name": DEFAULT_CITY_NAME,
        "admissions_cycle": DEFAULT_CYCLE,
        "nomination_window_opens_at": WINDOW_OPENS,
        "nomination_window_closes_at": WINDOW_CLOSES,
    }
    defaults.update(overrides)
    return defaults


def create_nominating_partner_payload(city_program_id: str, **overrides) -> dict:
    defaults = {
        "city_program_id": city_program_id,
        "name": DEFAULT_PARTNER_NAME,
        "kind": "HIGH_SCHOOL",
        "nomination_quota": 20,
    }
    defaults.update(overrides)
    return defaults


def create_nominee_payload(city_program_id: str, full_name: str, **overrides) -> dict:
    """nominator_id / first_generation are sent only when explicitly passed:
    a Nominator caller omits nominator_id (server sets it from X-User-ID);
    a ProgramAdmin caller must supply it."""
    payload = {"city_program_id": city_program_id, "full_name": full_name}
    payload.update(overrides)
    return payload


def decision_payload(decision: str) -> dict:
    return {"decision": decision}


def create_evaluation_payload(
    nominee_id: str,
    round_number: int,
    leadership: int,
    teamwork: int,
    group_presence: int,
) -> dict:
    return {
        "nominee_id": nominee_id,
        "round_number": round_number,
        "leadership": leadership,
        "teamwork": teamwork,
        "group_presence": group_presence,
    }


def create_partner_college_payload(**overrides) -> dict:
    defaults = {"name": DEFAULT_COLLEGE_NAME}
    defaults.update(overrides)
    return defaults


def create_mentor_payload(partner_college_id: str, **overrides) -> dict:
    defaults = {"partner_college_id": partner_college_id, "full_name": DEFAULT_MENTOR_NAME}
    defaults.update(overrides)
    return defaults


def create_partner_agreement_payload(
    partner_college_id: str,
    expected_college_version,
    admissions_cycle: str = DEFAULT_CYCLE,
    cohort_size: int = DEFAULT_COHORT_SIZE,
    tuition_annual_cents: int = DEFAULT_TUITION_CENTS,
    **overrides,
) -> dict:
    payload = {
        "partner_college_id": partner_college_id,
        "admissions_cycle": admissions_cycle,
        "cohort_size": cohort_size,
        "tuition_annual_cents": tuition_annual_cents,
        "expected_college_version": expected_college_version,
    }
    payload.update(overrides)
    return payload


def create_cohort_payload(agreement_id: str, city_program_id: str, mentor_id: str) -> dict:
    return {
        "agreement_id": agreement_id,
        "city_program_id": city_program_id,
        "mentor_id": mentor_id,
    }


def create_offer_payload(nominee_id: str, cohort_id: str) -> dict:
    return {"nominee_id": nominee_id, "cohort_id": cohort_id}


def lifecycle_payload(to_enrollment_status=None, to_standing=None) -> dict:
    """At least one of the two target fields is required (PRD §3.7); each is
    included only when supplied."""
    payload = {}
    if to_enrollment_status is not None:
        payload["to_enrollment_status"] = to_enrollment_status
    if to_standing is not None:
        payload["to_standing"] = to_standing
    return payload


def create_cohort_meeting_payload(
    cohort_id: str,
    kind: str,
    starts_at: str,
    ends_at: str,
    scholar_id=None,
    include_scholar_id: bool = False,
) -> dict:
    """scholar_id is included only when include_scholar_id is True, so the
    COHORT-with-scholar_id shape violation can be expressed explicitly."""
    payload = {
        "cohort_id": cohort_id,
        "kind": kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    if include_scholar_id:
        payload["scholar_id"] = scholar_id
    return payload


def create_internship_payload(
    scholar_id: str,
    employer_name: str,
    starts_on: str,
    ends_on: str,
) -> dict:
    return {
        "scholar_id": scholar_id,
        "employer_name": employer_name,
        "starts_on": starts_on,
        "ends_on": ends_on,
    }


def internship_transition_payload(to_status: str) -> dict:
    return {"to_status": to_status}


def renewal_review_payload(decision: str) -> dict:
    return {"decision": decision}

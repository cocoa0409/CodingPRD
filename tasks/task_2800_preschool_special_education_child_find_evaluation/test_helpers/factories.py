"""Payload factories: valid-by-default request bodies with per-test overrides.

Every numeric field is emitted as a JSON number and every timestamp in the
three-fractional-digit ISO 8601 UTC form the API documents for its window inputs.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    INITIAL_LOGICAL_CLOCK,
    date_of_birth_for_age,
    plus_minutes,
    ts,
)

_counter = itertools.count(1)


def unique_suffix() -> int:
    """A per-process monotonically increasing discriminator for unique names."""
    return next(_counter)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``...`` removes the key entirely."""
    for key, value in overrides.items():
        if value is ...:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ------------------------------------------------------------------------- child
def child_payload(**overrides: Any) -> Dict[str, Any]:
    """A registrable child, 33 completed months old at the initial logical clock."""
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "first_name": f"Ada{n}",
        "last_name": f"Lovelace{n}",
        "date_of_birth": date_of_birth_for_age(33, "2026-08-01"),
        "guardian_full_name": f"Guardian {n}",
        "district_of_residence": "DIST-01",
    }
    return _merge(payload, overrides)


def child_payload_for_age(age_months: int, on_date: str = "2026-08-01", **overrides: Any):
    """A child whose age in completed months on ``on_date`` is exactly ``age_months``."""
    return child_payload(
        date_of_birth=date_of_birth_for_age(age_months, on_date), **overrides
    )


def part_c_child_payload(age_months: int = 33, on_date: str = "2026-08-01", **overrides: Any):
    """An early-intervention child, which requires an explicit ``part_c_exit_date``."""
    dob = date_of_birth_for_age(age_months, on_date)
    payload = child_payload(
        date_of_birth=dob,
        part_c_enrolled=True,
        part_c_exit_date="2026-11-01",
    )
    return _merge(payload, overrides)


# --------------------------------------------------------------- community site
def community_site_payload(**overrides: Any) -> Dict[str, Any]:
    """A placement destination that is also approved to host screening events."""
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "name": f"Sunnyside Preschool {n}",
        "region_code": "REG-NORTH",
        "licensed_capacity": 40,
        "iep_seat_capacity": 4,
        "languages_supported": ["en"],
        "screening_host_approved": True,
        "status": "ACTIVE",
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------- provider
def provider_payload(**overrides: Any) -> Dict[str, Any]:
    """An ACTIVE provider with the district's default ceilings left implicit."""
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "full_name": f"Provider {n}",
        "discipline": "SLP",
        "home_region_code": "REG-NORTH",
    }
    return _merge(payload, overrides)


def chair_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """A chair-eligible provider (SCHOOL_PSYCHOLOGIST)."""
    return provider_payload(discipline="SCHOOL_PSYCHOLOGIST", **overrides)


def interpreter_provider_payload(
    languages: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """An interpreter with one open assignment unless overridden."""
    payload = provider_payload(
        discipline="INTERPRETER",
        languages=languages if languages is not None else ["es"],
        max_weekly_interpreter_assignments=1,
    )
    return _merge(payload, overrides)


def provider_update_payload(**overrides: Any) -> Dict[str, Any]:
    """A provider amendment; every field the amendment endpoint accepts is optional."""
    return dict(overrides)


# --------------------------------------------------------------- screening event
def screening_event_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    """A two-hour event with twenty-minute appointments, so six fit in the window."""
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "event_label": f"Child Find Day {n}",
        "window_start_utc": ts("2026-08-10T09:00:00Z"),
        "window_end_utc": ts("2026-08-10T11:00:00Z"),
        "slot_capacity": 6,
        "slot_length_minutes": 20,
        "interpreter_languages": [],
    }
    return _merge(payload, overrides)


def event_status_payload(target_status: str) -> Dict[str, Any]:
    return {"target_status": target_status}


def slot_booking_payload(
    child_id: str,
    expected_screening_event_version: int,
    slot_start_utc: str = "2026-08-10T09:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "child_id": child_id,
        "slot_start_utc": ts(slot_start_utc),
        "expected_screening_event_version": expected_screening_event_version,
    }
    return _merge(payload, overrides)


def slot_outcome_payload(
    attendance: str, screening_result: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"attendance": attendance}
    if screening_result is not None:
        payload["screening_result"] = screening_result
    return _merge(payload, overrides)


# ---------------------------------------------------------------------- referral
def referral_payload(child_id: str, **overrides: Any) -> Dict[str, Any]:
    """A parent self-referral, which needs no referring physician identifier."""
    payload: Dict[str, Any] = {"child_id": child_id, "source": "PARENT"}
    return _merge(payload, overrides)


def pediatrician_referral_payload(child_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = referral_payload(
        child_id, source="PEDIATRICIAN", referring_provider_npi="1234567890"
    )
    return _merge(payload, overrides)


# ---------------------------------------------------------------- consent notice
def consent_request_payload(**overrides: Any) -> Dict[str, Any]:
    """An English-language notice, which needs no interpreter of record."""
    payload: Dict[str, Any] = {
        "notice_language_code": "en",
        "notice_delivery_method": "MAIL",
    }
    return _merge(payload, overrides)


def interpreted_consent_request_payload(
    interpreter_provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    """An English notice for a non-English family, carried by an interpreter."""
    payload = consent_request_payload(
        interpreter_provider_id=interpreter_provider_id,
        interpreter_modality="IN_PERSON",
    )
    return _merge(payload, overrides)


def consent_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    return _merge(payload, overrides)


# --------------------------------------------------------------- evaluation case
def evaluation_case_payload(chair_provider_id: str, **overrides: Any) -> Dict[str, Any]:
    """A case pinned to the inclusive play-based weighting variant."""
    payload: Dict[str, Any] = {
        "chair_provider_id": chair_provider_id,
        "assessment_protocol": "PLAY_BASED",
    }
    return _merge(payload, overrides)


# ------------------------------------------------------------- domain assessment
def domain_assessment_payload(
    evaluator_provider_id: str,
    domain: str = "COGNITIVE",
    method: str = "STANDARDIZED",
    window_start_utc: str = "2026-08-05T09:00:00Z",
    window_minutes: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evaluator_provider_id": evaluator_provider_id,
        "domain": domain,
        "method": method,
        "window_start_utc": ts(window_start_utc),
        "window_end_utc": plus_minutes(window_start_utc, window_minutes),
    }
    return _merge(payload, overrides)


def assessment_completion_payload(
    age_equivalent_months: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"age_equivalent_months": age_equivalent_months}
    return _merge(payload, overrides)


def assessment_invalidation_payload(
    invalidation_reason: str = "Administration compromised", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"invalidation_reason": invalidation_reason}
    return _merge(payload, overrides)


# ------------------------------------------------------------------ report / plan
def report_payload(
    report_narrative_summary: str = "Multidisciplinary findings across all five domains.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"report_narrative_summary": report_narrative_summary}
    return _merge(payload, overrides)


def revision_request_payload(
    revision_note: str = "Expand the adaptive-domain narrative.", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"revision_note": revision_note}
    return _merge(payload, overrides)


def eligible_determination_payload(
    expected_evaluation_case_version: int,
    setting: str = "ITINERANT_ONLY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "eligibility_decision": "ELIGIBLE",
        "expected_evaluation_case_version": expected_evaluation_case_version,
        "disability_category": "DEVELOPMENTAL_DELAY",
        "setting": setting,
    }
    return _merge(payload, overrides)


def not_eligible_determination_payload(
    expected_evaluation_case_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "eligibility_decision": "NOT_ELIGIBLE",
        "expected_evaluation_case_version": expected_evaluation_case_version,
    }
    return _merge(payload, overrides)


# ------------------------------------------------------------------ service lines
def service_line_payload(
    discipline: str = "SLP",
    weekly_minutes: int = 100,
    delivery_model: str = "DIRECT",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "discipline": discipline,
        "weekly_minutes": weekly_minutes,
        "delivery_model": delivery_model,
    }
    return _merge(payload, overrides)


def staffing_payload(
    provider_id: str, expected_provider_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "provider_id": provider_id,
        "expected_provider_version": expected_provider_version,
    }
    return _merge(payload, overrides)


def unstaffing_payload(unstaff_reason: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if unstaff_reason is not None:
        payload["unstaff_reason"] = unstaff_reason
    return _merge(payload, overrides)


# ------------------------------------------------------ service consent / transition
def consent_submission_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "notice_language_code": "en",
        "notice_delivery_method": "MAIL",
    }
    return _merge(payload, overrides)


def transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _merge(payload, overrides)


# ------------------------------------------------------------------ logical clock
def clock_payload(current_utc: str = INITIAL_LOGICAL_CLOCK) -> Dict[str, Any]:
    return {"current_utc": current_utc}

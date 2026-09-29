"""Payload factories — one per write operation, carrying only input fields.

Every monetary amount is an integer number of cents, sent as a JSON number.
"""
from typing import Any, Dict, List, Optional

from .constants import DOMAIN_KEYS


def domain_scores(
    adl: int = 2,
    cognition: int = 2,
    medical_complexity: int = 2,
    social_support: int = 2,
    safety: int = 2,
    finances: int = 2,
) -> Dict[str, int]:
    """The six-key `domain_scores` object, every value an integer 0..5."""
    return {
        "adl": adl,
        "cognition": cognition,
        "medical_complexity": medical_complexity,
        "social_support": social_support,
        "safety": safety,
        "finances": finances,
    }


def uniform_domain_scores(value: int) -> Dict[str, int]:
    """`domain_scores` with the same integer in all six domains."""
    return {key: value for key in DOMAIN_KEYS}


# ------------------------------------------------------------------ client ---
def create_client_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Margarethe Oyelaran",
        "residence_setting": "PRIVATE_HOME",
    }
    payload.update(overrides)
    return payload


def client_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


def capacity_determination_payload(
    capacity_status: str = "DIMINISHED_DOCUMENTED",
    basis: str = "Neuropsychological evaluation dated 2026-07-20",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"capacity_status": capacity_status, "basis": basis}
    payload.update(overrides)
    return payload


def retainer_deposit_payload(
    amount_cents: int = 60_000,
    received_at: str = "2026-08-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "received_at": received_at,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ care manager ---
def create_care_manager_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Dana Whitfield",
        "credential": "CMC",
        "hourly_rate_cents": 22_500,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ vendor ---
def create_vendor_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Northgate Home Care",
        "vendor_type": "HOME_CARE",
        "has_referral_relationship": False,
    }
    payload.update(overrides)
    return payload


def update_vendor_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------- family contact ---
def create_family_contact_payload(client_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "full_name": "Lena Oyelaran",
        "contact_role": "POA_HEALTHCARE",
    }
    payload.update(overrides)
    return payload


def family_report_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "report_period_start": "2026-08-01",
        "report_period_end": "2026-08-31",
        "summary": "Monthly coordination summary for the long-distance family.",
    }
    payload.update(overrides)
    return payload


# -------------------------------------------------------------- assessment ---
def create_assessment_payload(
    client_id: str,
    care_manager_id: str,
    scores: Optional[Dict[str, int]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "care_manager_id": care_manager_id,
        "domain_scores": scores if scores is not None else domain_scores(),
    }
    payload.update(overrides)
    return payload


def assessment_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- care plan --
def create_care_plan_payload(
    client_id: str,
    source_assessment_id: str,
    expected_client_version: int,
    goals: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "source_assessment_id": source_assessment_id,
        "expected_client_version": expected_client_version,
        "goals": goals if goals is not None else ["Maintain safe ambulation at home"],
    }
    payload.update(overrides)
    return payload


def care_plan_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ------------------------------------------------- service authorization -----
def create_service_authorization_payload(
    care_plan_id: str,
    vendor_id: str,
    expected_care_plan_version: int,
    coverage_start: str = "2026-08-16T08:00:00Z",
    coverage_end: str = "2026-08-16T16:00:00Z",
    concurrent_caregivers: int = 1,
    hourly_cost_cents: int = 4_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "care_plan_id": care_plan_id,
        "vendor_id": vendor_id,
        "expected_care_plan_version": expected_care_plan_version,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "concurrent_caregivers": concurrent_caregivers,
        "hourly_cost_cents": hourly_cost_cents,
    }
    payload.update(overrides)
    return payload


def authorization_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


def coi_event_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ------------------------------------------------------- family conference ---
def create_family_conference_payload(
    client_id: str,
    invited_contact_ids: List[str],
    scheduled_start: str = "2026-08-20T14:00:00Z",
    scheduled_end: str = "2026-08-20T15:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "invited_contact_ids": list(invited_contact_ids),
    }
    payload.update(overrides)
    return payload


def conference_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ------------------------------------------------------ conference decision --
def create_conference_decision_payload(
    family_conference_id: str,
    decided_by_contact_id: str,
    decision_type: str = "VENDOR_ENGAGEMENT",
    decision_text: str = "The family engages Northgate Home Care for daytime coverage.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "family_conference_id": family_conference_id,
        "decided_by_contact_id": decided_by_contact_id,
        "decision_type": decision_type,
        "decision_text": decision_text,
    }
    payload.update(overrides)
    return payload


def decision_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------- crisis episode --
def create_crisis_episode_payload(
    client_id: str, trigger_type: str = "FALL", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"client_id": client_id, "trigger_type": trigger_type}
    payload.update(overrides)
    return payload


def crisis_episode_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- time entry --
def create_time_entry_payload(
    client_id: str,
    care_manager_id: str,
    start_at: str,
    end_at: str,
    service_type: str = "CARE_COORDINATION",
    service_location_id: str = "CLIENT_HOME",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "care_manager_id": care_manager_id,
        "service_type": service_type,
        "start_at": start_at,
        "end_at": end_at,
        "service_location_id": service_location_id,
    }
    payload.update(overrides)
    return payload


def time_entry_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ invoice --
def create_invoice_payload(
    client_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def invoice_state_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


def invoice_payment_payload(
    amount_cents: int,
    received_at: str = "2026-08-20T12:00:00Z",
    method: str = "ACH",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "received_at": received_at,
        "method": method,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ logical clock --
def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}

"""Payload factories — one per creation/action endpoint, input fields only
(PRD §3 narratives; §4 routing table).

The accident-case default is the canonical 60-point fixture: HIGHWAY, one
fatality (40), no injuries, no damage, public transport (20) -> statutory 60,
risk-adjusted 50.0, suggested_mode FULL_GO_TEAM. report_number is globally
unique (PRD §3.1), so the default draws from a per-process counter — pass an
explicit report_number when a test needs a specific value.
"""
import itertools

from .constants import (
    DEFAULT_BENCH_ID,
    DEFAULT_CHAIRMAN_USER_ID,
    DEFAULT_MEETING_WINDOW_END,
    DEFAULT_MEETING_WINDOW_START,
    DEFAULT_ROOM_ID,
    DEFAULT_SESSION_WINDOW_END,
    DEFAULT_SESSION_WINDOW_START,
    DEFAULT_SITTING_MEMBER_IDS,
)

_report_number_counter = itertools.count(1)
_legal_name_counter = itertools.count(1)


def _next_report_number() -> str:
    return f"NTSB-2026-{next(_report_number_counter):04d}"


# --- accident cases & launch decisions (PRD §3.1, §3.2) ----------------------

def create_accident_case_payload(**overrides) -> dict:
    defaults = {
        "report_number": _next_report_number(),
        "category": "HIGHWAY",
        "occurred_at": "2026-08-31T14:22:00Z",
        "location_state": "VA",
        "fatalities_count": 1,
        "injuries_count": 0,
        "damage_estimate_cents": 0,
        "is_public_transport": True,
    }
    defaults.update(overrides)
    return defaults


def propose_launch_decision_payload(mode, expected_accident_case_version, **overrides) -> dict:
    """mode + OCC version; overrides may add rationale and/or severity overrides
    (fatalities_count, injuries_count, damage_estimate_cents, is_public_transport)."""
    payload = {
        "mode": mode,
        "expected_accident_case_version": expected_accident_case_version,
    }
    payload.update(overrides)
    return payload


def adopt_launch_decision_payload(iic_user_id=None, **overrides) -> dict:
    """iic_user_id is required exactly when the decision's mode is FULL_GO_TEAM
    and must be absent for LIMITED/DECLINED (PRD §3.2)."""
    payload = {}
    if iic_user_id is not None:
        payload["iic_user_id"] = iic_user_id
    payload.update(overrides)
    return payload


def reconsider_launch_decision_payload(**overrides) -> dict:
    """Optional rationale and/or severity overrides (PRD §3.2)."""
    return dict(overrides)


# --- investigations (PRD §3.5) -------------------------------------------------

def advance_phase_payload(to_phase, **overrides) -> dict:
    payload = {"to_phase": to_phase}
    payload.update(overrides)
    return payload


# --- party system (PRD §3.3, §3.4) --------------------------------------------

def create_party_organization_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Test Organization {next(_legal_name_counter)}",
        "org_type": "OPERATOR",
    }
    defaults.update(overrides)
    return defaults


def create_party_designation_payload(investigation_id, organization_id, **overrides) -> dict:
    payload = {"investigation_id": investigation_id, "organization_id": organization_id}
    payload.update(overrides)
    return payload


def expel_party_designation_payload(**overrides) -> dict:
    """Optional free-text reason (PRD §3.4)."""
    return dict(overrides)


def create_seat_payload(group_id, **overrides) -> dict:
    payload = {"group_id": group_id}
    payload.update(overrides)
    return payload


def conduct_violation_payload(
    violation_kind="PREMATURE_PUBLIC_STATEMENT",
    detail="Conduct violation recorded by the IIC.",
    **overrides,
) -> dict:
    payload = {"violation_kind": violation_kind, "detail": detail}
    payload.update(overrides)
    return payload


# --- investigative groups & factual reports (PRD §3.3, §3.5) -------------------

def create_group_payload(
    investigation_id,
    specialty="OPERATIONS",
    chairman_user_id=DEFAULT_CHAIRMAN_USER_ID,
    **overrides,
) -> dict:
    payload = {
        "investigation_id": investigation_id,
        "specialty": specialty,
        "chairman_user_id": chairman_user_id,
    }
    payload.update(overrides)
    return payload


def factual_report_payload(
    report_kind="GROUP_FACTUAL",
    content="Factual record: field examination results.",
    recorder_id=None,
    **overrides,
) -> dict:
    """recorder_id is required iff report_kind == RECORDER_TRANSCRIPT and must be
    absent otherwise (PRD §3.5)."""
    payload = {"report_kind": report_kind, "content": content}
    if recorder_id is not None:
        payload["recorder_id"] = recorder_id
    payload.update(overrides)
    return payload


# --- recorder packages & readout sessions (PRD §3.6) ----------------------------

def create_recorder_payload(
    investigation_id,
    recorder_type="CVR",
    condition="INTACT",
    **overrides,
) -> dict:
    payload = {
        "investigation_id": investigation_id,
        "recorder_type": recorder_type,
        "condition": condition,
    }
    payload.update(overrides)
    return payload


def readout_session_payload(
    bench_id=DEFAULT_BENCH_ID,
    window_start_utc=DEFAULT_SESSION_WINDOW_START,
    window_end_utc=DEFAULT_SESSION_WINDOW_END,
    **overrides,
) -> dict:
    payload = {
        "bench_id": bench_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    payload.update(overrides)
    return payload


# --- safety recommendations (PRD §3.7) ------------------------------------------

def create_safety_recommendation_payload(
    investigation_id,
    addressee_org_id,
    recommendation_text="Require quarterly brake-line inspection intervals.",
    **overrides,
) -> dict:
    payload = {
        "investigation_id": investigation_id,
        "addressee_org_id": addressee_org_id,
        "recommendation_text": recommendation_text,
    }
    payload.update(overrides)
    return payload


def recommendation_response_payload(
    response_text="We will implement the recommendation.", **overrides
) -> dict:
    payload = {"response_text": response_text}
    payload.update(overrides)
    return payload


def classify_response_payload(classification="ACCEPTABLE", **overrides) -> dict:
    payload = {"classification": classification}
    payload.update(overrides)
    return payload


def close_recommendation_payload(outcome="CLOSED_ACCEPTABLE", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --- board meetings (PRD §3.8) ---------------------------------------------------

def create_board_meeting_payload(
    investigation_id,
    room_id=DEFAULT_ROOM_ID,
    window_start_utc=DEFAULT_MEETING_WINDOW_START,
    window_end_utc=DEFAULT_MEETING_WINDOW_END,
    sitting_member_ids=None,
    **overrides,
) -> dict:
    payload = {
        "investigation_id": investigation_id,
        "room_id": room_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "sitting_member_ids": list(
            sitting_member_ids if sitting_member_ids is not None else DEFAULT_SITTING_MEMBER_IDS
        ),
    }
    payload.update(overrides)
    return payload


def vote_payload(position, expected_meeting_version, dissent_text=None, **overrides) -> dict:
    """dissent_text is permitted only alongside a REJECT position (PRD §3.8)."""
    payload = {
        "position": position,
        "expected_meeting_version": expected_meeting_version,
    }
    if dissent_text is not None:
        payload["dissent_text"] = dissent_text
    payload.update(overrides)
    return payload


__all__ = [
    "create_accident_case_payload",
    "propose_launch_decision_payload",
    "adopt_launch_decision_payload",
    "reconsider_launch_decision_payload",
    "advance_phase_payload",
    "create_party_organization_payload",
    "create_party_designation_payload",
    "expel_party_designation_payload",
    "create_seat_payload",
    "conduct_violation_payload",
    "create_group_payload",
    "factual_report_payload",
    "create_recorder_payload",
    "readout_session_payload",
    "create_safety_recommendation_payload",
    "recommendation_response_payload",
    "classify_response_payload",
    "close_recommendation_payload",
    "create_board_meeting_payload",
    "vote_payload",
]

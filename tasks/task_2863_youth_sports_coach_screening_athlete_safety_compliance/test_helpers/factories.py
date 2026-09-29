"""Request-payload builders for the SafeSport compliance platform.

Every builder returns a plain dict that already satisfies the shape rules of
PRD 3, so a test only has to override the one or two fields whose value carries
the rule it is exercising.  Two conventions matter and are held everywhere:

* money is an integer number of cents, never a string and never a fraction,
  because PRD 2.7 represents money exclusively as integer cents;
* every field PRD declares as an instant is emitted as a full ISO 8601 instant
  with a UTC designator.  Only ``date_of_birth`` is a calendar date.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

from .constants import ALLEGATION_CATEGORIES, CLOCK_EPOCH, DEFAULT_PASS_SCORE

_counter = itertools.count(1)


def _seq() -> int:
    """Monotonic suffix so uniqueness-constrained fields never collide by accident."""
    return next(_counter)


def unique_email(prefix: str = "coach") -> str:
    """An email that is unique across the governing body (PRD 3.1)."""
    return f"{prefix}.{_seq()}@example.org"


def unique_course_code(prefix: str = "SS") -> str:
    """A globally unique course code of uppercase letters, digits and hyphens (PRD 3.4)."""
    return f"{prefix}-CORE-{_seq():04d}"


# ----------------------------------------------------------------------
# Clubs (PRD 3.1)
# ----------------------------------------------------------------------
def club_payload(**overrides: Any) -> Dict[str, Any]:
    """Charter payload for a club that runs minor-athlete programs."""
    payload: Dict[str, Any] = {
        "name": f"Riverside Youth Athletics {_seq()}",
        "state_code": "OR",
        "minor_athlete_program": True,
        "roster_size_attested": 20,
        "initial_escrow_cents": 5_000_000,
    }
    payload.update(overrides)
    return payload


def escrow_funding_payload(amount_cents: int = 1_000_000, **overrides: Any) -> Dict[str, Any]:
    """Escrow top-up payload; ``amount_cents`` is a positive whole number of cents."""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Members (PRD 3.1)
# ----------------------------------------------------------------------
def member_payload(club_id: str, **overrides: Any) -> Dict[str, Any]:
    """Registration payload for an adult volunteer with no minor-athlete contact."""
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "full_name": f"Dana Whitfield {_seq()}",
        "email": unique_email(),
        "role_type": "VOLUNTEER",
        "has_minor_athlete_contact": False,
        "date_of_birth": "1988-04-17",
        "jurisdiction_codes": ["OR"],
    }
    payload.update(overrides)
    return payload


def renewal_payload(**overrides: Any) -> Dict[str, Any]:
    """Membership renewal payload; the attestation must be signed (PRD 3.5)."""
    payload: Dict[str, Any] = {"attestation_signed": True}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Screening orders (PRD 3.2, PRD 3.3)
# ----------------------------------------------------------------------
def screening_order_payload(
    expected_club_version: int, expedited: bool = False, **overrides: Any
) -> Dict[str, Any]:
    """Screening-order payload carrying the mandatory club version pin (PRD 2.6)."""
    payload: Dict[str, Any] = {
        "expected_club_version": expected_club_version,
        "expedited": expedited,
    }
    payload.update(overrides)
    return payload


def vendor_result_payload(
    vendor_disposition: str = "NO_RECORD", **overrides: Any
) -> Dict[str, Any]:
    """Vendor return payload (PRD 3.3)."""
    payload: Dict[str, Any] = {"vendor_disposition": vendor_disposition}
    payload.update(overrides)
    return payload


def adjudication_payload(
    disposition: str = "CLEAR", rationale: str = "No disqualifying record found.", **overrides: Any
) -> Dict[str, Any]:
    """Adjudication payload; a written rationale accompanies every disposition (PRD 3.3)."""
    payload: Dict[str, Any] = {"disposition": disposition, "rationale": rationale}
    payload.update(overrides)
    return payload


def void_payload(reason: str = "Duplicate submission by club staff.", **overrides: Any) -> Dict[str, Any]:
    """Void payload; the free-text reason is retained as ``void_reason`` (PRD 3.3)."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Training (PRD 3.4)
# ----------------------------------------------------------------------
def course_payload(
    required_for_tiers: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Course-publication payload with a one-year validity period."""
    payload: Dict[str, Any] = {
        "code": unique_course_code(),
        "title": "Abuse Prevention Core",
        "validity_days": 365,
        "delivery_mode": "ONLINE",
        "required_for_tiers": list(required_for_tiers or ["TIER_1", "TIER_2", "TIER_3"]),
        "pass_score": DEFAULT_PASS_SCORE,
    }
    payload.update(overrides)
    return payload


def training_assignment_payload(
    member_id: str,
    course_code: str,
    due_at: str = "2026-12-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Training-assignment payload; ``due_at`` is a full instant, not a bare date."""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "course_code": course_code,
        "due_at": due_at,
    }
    payload.update(overrides)
    return payload


def training_completion_payload(score: int = 95, **overrides: Any) -> Dict[str, Any]:
    """Completion payload; the score must reach the course's pass mark (PRD 3.4)."""
    payload: Dict[str, Any] = {"score": score}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Coach placements (PRD 3.6)
# ----------------------------------------------------------------------
def coach_assignment_payload(
    member_id: str,
    club_id: str,
    season_start: str = "2026-08-01T00:00:00Z",
    season_end: str = "2027-06-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Placement payload over the half-open season interval [season_start, season_end)."""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "club_id": club_id,
        "team_name": f"Under-14 Blue {_seq()}",
        "season_start": season_start,
        "season_end": season_end,
    }
    payload.update(overrides)
    return payload


def activation_payload(expected_member_version: int, **overrides: Any) -> Dict[str, Any]:
    """Activation payload carrying the member version pin (PRD 2.6)."""
    payload: Dict[str, Any] = {"expected_member_version": expected_member_version}
    payload.update(overrides)
    return payload


def electronic_comm_payload(
    channel_kind: str = "TEAM_PLATFORM",
    parent_copy_required: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """Electronic-communication authorization payload (PRD 3.6)."""
    payload: Dict[str, Any] = {
        "channel_kind": channel_kind,
        "parent_copy_required": parent_copy_required,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Travel and lodging (PRD 3.7)
# ----------------------------------------------------------------------
def adult_room_stay_payload(
    member_id: str,
    trip_label: str = "Spring Invitational",
    room_number: str = "204",
    check_in: str = "2026-09-10T15:00:00Z",
    check_out: str = "2026-09-12T11:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Booking for an adult member: member_id set, minor_athlete_age null (PRD 3.7)."""
    payload: Dict[str, Any] = {
        "occupant_kind": "ADULT_MEMBER",
        "member_id": member_id,
        "minor_athlete_age": None,
        "trip_label": trip_label,
        "room_number": room_number,
        "check_in": check_in,
        "check_out": check_out,
    }
    payload.update(overrides)
    return payload


def minor_room_stay_payload(
    minor_athlete_age: int = 14,
    trip_label: str = "Spring Invitational",
    room_number: str = "204",
    check_in: str = "2026-09-10T15:00:00Z",
    check_out: str = "2026-09-12T11:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Booking for a minor athlete: member_id null, age set (PRD 3.7)."""
    payload: Dict[str, Any] = {
        "occupant_kind": "MINOR_ATHLETE",
        "member_id": None,
        "minor_athlete_age": minor_athlete_age,
        "trip_label": trip_label,
        "room_number": room_number,
        "check_in": check_in,
        "check_out": check_out,
    }
    payload.update(overrides)
    return payload


def cancel_payload(reason: str = "Trip roster changed.", **overrides: Any) -> Dict[str, Any]:
    """Cancellation payload; the reason is retained as ``cancel_reason`` (PRD 3.7)."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Investigating bodies, cases, measures (PRD 3.8)
# ----------------------------------------------------------------------
def investigating_body_payload(
    scope_categories: Optional[List[str]] = None,
    intake_status: str = "ACCEPTING",
    max_open_cases: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    """Registration payload for an independent investigating body."""
    payload: Dict[str, Any] = {
        "name": f"Independent Review Panel {_seq()}",
        "scope_categories": list(scope_categories or ALLEGATION_CATEGORIES),
        "intake_status": intake_status,
        "max_open_cases": max_open_cases,
    }
    payload.update(overrides)
    return payload


def case_payload(
    club_id: str,
    reported_member_id: str,
    allegation_category: str = ALLEGATION_CATEGORIES[0],
    occurred_at: str = CLOCK_EPOCH,
    reporter_kind: str = "MANDATORY_REPORTER",
    **overrides: Any,
) -> Dict[str, Any]:
    """Incident-report payload; ``occurred_at`` is a full instant (PRD 3.8)."""
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "reported_member_id": reported_member_id,
        "allegation_category": allegation_category,
        "reporter_kind": reporter_kind,
        "narrative": (
            "A parent reported that the named individual was alone with a minor "
            "athlete in a locked equipment room after practice."
        ),
        "occurred_at": occurred_at,
    }
    payload.update(overrides)
    return payload


def route_payload(investigating_body_id: str, **overrides: Any) -> Dict[str, Any]:
    """Routing payload naming the body with jurisdiction (PRD 3.8)."""
    payload: Dict[str, Any] = {"investigating_body_id": investigating_body_id}
    payload.update(overrides)
    return payload


def administrative_closure_payload(
    closure_reason: str = "NO_JURISDICTION", **overrides: Any
) -> Dict[str, Any]:
    """Closure payload from intake, which carries no outcome at all (PRD 3.8)."""
    payload: Dict[str, Any] = {"closure_reason": closure_reason}
    payload.update(overrides)
    return payload


def investigation_closure_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    """Closure payload from routed, where the outcome is required (PRD 3.8)."""
    payload: Dict[str, Any] = {
        "closure_reason": "INVESTIGATION_COMPLETE",
        "outcome": outcome,
    }
    payload.update(overrides)
    return payload


def interim_measure_payload(
    member_id: str,
    expected_member_version: int,
    measure_kind: str = "NO_CONTACT_DIRECTIVE",
    effective_from: str = CLOCK_EPOCH,
    effective_to: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Interim-measure payload with the inclusive window and member version pin."""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "measure_kind": measure_kind,
        "effective_from": effective_from,
        "expected_member_version": expected_member_version,
    }
    if effective_to is not None:
        payload["effective_to"] = effective_to
    payload.update(overrides)
    return payload


def lift_payload(reason: str = "Investigation found no ongoing risk.", **overrides: Any) -> Dict[str, Any]:
    """Lift payload; the reason is retained as ``lift_reason`` (PRD 3.8)."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def convert_permanent_payload(
    rationale: str = "Panel found the allegation substantiated on the record.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Conversion payload; a written rationale is required (PRD 3.8)."""
    payload: Dict[str, Any] = {"rationale": rationale}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Compliance audits and findings (PRD 3.9)
# ----------------------------------------------------------------------
def club_audit_payload(
    club_id: str,
    sampled_member_ids: Optional[List[str]] = None,
    score_variant: str = "SELF_ATTESTED",
    audit_period_start: str = "2026-01-01T00:00:00Z",
    audit_period_end: str = "2026-07-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Audit-opening payload; an empty sample is explicitly legal (PRD 3.9)."""
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "audit_period_start": audit_period_start,
        "audit_period_end": audit_period_end,
        "score_variant": score_variant,
        "sampled_member_ids": list(sampled_member_ids or []),
    }
    payload.update(overrides)
    return payload


def finding_payload(
    finding_code: str = "RECORDS_INCOMPLETE",
    severity: str = "MINOR",
    member_id: Optional[str] = None,
    is_repeat: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Finding payload; ``member_id`` is omitted for an organization-level finding."""
    payload: Dict[str, Any] = {
        "finding_code": finding_code,
        "severity": severity,
        "is_repeat": is_repeat,
    }
    if member_id is not None:
        payload["member_id"] = member_id
    payload.update(overrides)
    return payload


def finding_decision_payload(
    decision: str, note: str = "Corrective action attached.", **overrides: Any
) -> Dict[str, Any]:
    """Finding-decision payload; the note lands in evidence_note or decision_note."""
    payload: Dict[str, Any] = {"decision": decision, "note": note}
    payload.update(overrides)
    return payload


def audit_closure_payload(resolution: str, **overrides: Any) -> Dict[str, Any]:
    """Audit-closure payload; resolution is CLOSE_COMPLIANT or SANCTION (PRD 3.9)."""
    payload: Dict[str, Any] = {"resolution": resolution}
    payload.update(overrides)
    return payload

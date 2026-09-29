"""Request-payload factories.

Every factory returns a fresh dictionary built from a valid baseline and applies
keyword overrides on top, so a test can change exactly the field under
examination. Monetary amounts are emitted as JSON numbers with at most two
decimal places and percentages as decimal fractions, as the PRD requires;
instants carry three fractional digits while ``start_date``, ``end_date`` and
``due_date`` are plain ``YYYY-MM-DD`` calendar dates.
"""

import itertools
from typing import Any, Dict, List, Optional

_event_code_counter = itertools.count(1)
_venue_name_counter = itertools.count(1)

# The tiered cancellation ladder the sourcing scenarios negotiate. The array
# always contains a tier whose days_before_arrival_min is 0.
CANONICAL_CANCELLATION_SCHEDULE: List[Dict[str, Any]] = [
    {"days_before_arrival_min": 181, "fee_pct": 0.25},
    {"days_before_arrival_min": 91, "fee_pct": 0.50},
    {"days_before_arrival_min": 31, "fee_pct": 0.75},
    {"days_before_arrival_min": 0, "fee_pct": 1.00},
]


def next_event_code(prefix: str = "EVT-2822") -> str:
    """A fresh globally unique sourcing code."""
    return f"{prefix}-{next(_event_code_counter):04d}"


def next_venue_name(prefix: str = "Harborline Grand") -> str:
    return f"{prefix} {next(_venue_name_counter):02d}"


def clock_payload(current_utc: str) -> Dict[str, Any]:
    """Body for the logical-clock endpoint."""
    return {"current_utc": current_utc}


def rate_benchmark_payload(**overrides: Any) -> Dict[str, Any]:
    """A published benchmark for the TIER_1 / USER_CONFERENCE pair."""
    payload: Dict[str, Any] = {
        "destination_tier": "TIER_1",
        "program_type": "USER_CONFERENCE",
        "benchmark_adr_usd": 260.00,
        "benchmark_service_charge_pct": 0.24,
        "benchmark_tax_pct": 0.156,
    }
    payload.update(overrides)
    return payload


def venue_payload(**overrides: Any) -> Dict[str, Any]:
    """A TIER_1 venue large enough for the canonical meeting requirement."""
    payload: Dict[str, Any] = {
        "name": "Harborline Grand",
        "city": "Lisbon",
        "country": "PT",
        "destination_tier": "TIER_1",
        "guest_rooms_total": 420,
        "largest_space_sqft": 14000,
        "preferred_supplier_status": "PREFERRED",
    }
    payload.update(overrides)
    return payload


def second_venue_payload(**overrides: Any) -> Dict[str, Any]:
    """A second TIER_1 venue, used whenever a scenario needs two bidders."""
    payload: Dict[str, Any] = {
        "name": "Cascade Bay Resort",
        "city": "Porto",
        "country": "PT",
        "destination_tier": "TIER_1",
        "guest_rooms_total": 380,
        "largest_space_sqft": 16000,
        "preferred_supplier_status": "PREFERRED",
    }
    payload.update(overrides)
    return payload


def event_payload(**overrides: Any) -> Dict[str, Any]:
    """The canonical four-day user conference requirement."""
    payload: Dict[str, Any] = {
        "event_code": next_event_code(),
        "name": "Global User Conference 2027",
        "program_type": "USER_CONFERENCE",
        "start_date": "2027-03-15",
        "end_date": "2027-03-18",
        "peak_attendees": 200,
        "requested_room_nights": 600,
        "largest_meeting_space_sqft": 12000,
        "budget_ceiling_usd": 500000.00,
        "preferred_program_only": False,
    }
    payload.update(overrides)
    return payload


def shortlist_entry_payload(venue_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "venue_id": venue_id,
        "rank_seq": 1,
        "inspection_required": False,
    }
    payload.update(overrides)
    return payload


def eliminate_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"elimination_reason": "Rate above programme benchmark."}
    payload.update(overrides)
    return payload


def site_inspection_payload(entry_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shortlist_entry_id": entry_id,
        "inspector_user_id": "insp-dana",
        "window_start": "2026-09-10T09:00:00.000Z",
        "window_end": "2026-09-10T13:00:00.000Z",
        "travel_buffer_minutes": 90,
    }
    payload.update(overrides)
    return payload


def complete_inspection_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"findings_score": 4}
    payload.update(overrides)
    return payload


def cancel_inspection_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancel_reason": "Inspector travel restriction."}
    payload.update(overrides)
    return payload


def rfp_payload(**overrides: Any) -> Dict[str, Any]:
    """A round-1 solicitation whose deadline sits after the sourcing clock and
    before the event's arrival date."""
    payload: Dict[str, Any] = {
        "round_number": 1,
        "response_due_at": "2026-09-30T17:00:00.000Z",
        "standard_response_version": "V2",
        "instructions": "Answer every line of the standard grid.",
    }
    payload.update(overrides)
    return payload


def proposal_submission_payload(**overrides: Any) -> Dict[str, Any]:
    """The canonical standardized bid grid.

    A NET rate of 249.00 over 600 offered nights with a 45:1 comp ratio, priced
    against a 260.00 benchmark ADR.
    """
    payload: Dict[str, Any] = {
        "room_rate_usd": 249.00,
        "rate_type": "NET",
        "commission_pct": 0.10,
        "room_nights_offered": 600,
        "comp_room_ratio": 45,
        "resort_fee_usd_per_night": 18.00,
        "service_charge_pct": 0.24,
        "tax_pct": 0.156,
        "av_estimate_usd": 22000.00,
        "fnb_minimum_usd": 145000.00,
        "concession_credit_usd": 25000.00,
        "attrition_allowance_pct": 0.20,
        "cancellation_schedule": [dict(t) for t in CANONICAL_CANCELLATION_SCHEDULE],
        "force_majeure_scope": "STANDARD",
        "rebooking_credit_pct": 0.60,
    }
    payload.update(overrides)
    return payload


def evaluate_payload(basis: str = "CONTRACTED_BASIS") -> Dict[str, Any]:
    return {"basis": basis}


def counter_payload(
    expected_proposal_version: int,
    term_category: str = "RATE",
    proposed_numeric_value: Optional[float] = 235.00,
    proposed_text_value: Optional[str] = None,
    planner_note: Optional[str] = "Bring the rate to 235.00.",
) -> Dict[str, Any]:
    """A counter on one negotiated term.

    Numeric categories carry ``proposed_numeric_value``; the two text categories
    carry ``proposed_text_value`` instead.
    """
    payload: Dict[str, Any] = {
        "expected_proposal_version": expected_proposal_version,
        "term_category": term_category,
    }
    if proposed_numeric_value is not None:
        payload["proposed_numeric_value"] = proposed_numeric_value
    if proposed_text_value is not None:
        payload["proposed_text_value"] = proposed_text_value
    if planner_note is not None:
        payload["planner_note"] = planner_note
    return payload


def revision_payload(counter_id: str, accepted: bool = True, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"counter_id": counter_id, "accepted": accepted}
    payload.update(overrides)
    return payload


def award_payload(
    proposal_id: str, expected_event_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "proposal_id": proposal_id,
        "expected_event_version": expected_event_version,
        "award_note": "Best total cost after negotiation.",
    }
    payload.update(overrides)
    return payload


def decision_payload(decision: str = "APPROVED", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "decision_note": "Within delegation.",
    }
    payload.update(overrides)
    return payload


def sign_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"planner_signatory_name": "Anita Vale"}
    payload.update(overrides)
    return payload


def countersign_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"venue_signatory_name": "Rui Costa"}
    payload.update(overrides)
    return payload


def terminate_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "termination_reason": "Programme cancelled by the business sponsor."
    }
    payload.update(overrides)
    return payload


def pay_installment_payload(paid_amount_usd: float, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "paid_amount_usd": paid_amount_usd,
        "payment_reference": "WIRE-2026-0001",
    }
    payload.update(overrides)
    return payload


def post_event_report_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "actual_room_nights": 540,
        "actual_fnb_usd": 152000.00,
        "actual_av_usd": 21000.00,
        "notes": "Group ran slightly under the contracted block.",
    }
    payload.update(overrides)
    return payload


def performance_review_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "review_source": "EXTERNAL",
        "service_score": 5,
        "value_score": 5,
        "av_quality_score": 4,
        "responsiveness_score": 5,
        "comment": "Imported programme-history scorecard.",
    }
    payload.update(overrides)
    return payload


def preferred_status_payload(status: str) -> Dict[str, Any]:
    return {"preferred_supplier_status": status}

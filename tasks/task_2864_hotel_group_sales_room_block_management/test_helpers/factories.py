"""Request-payload factories, one per creatable resource.

Money and room counts are emitted as JSON integers and percentages as JSON
fractions, exactly as PRD 2.6 requires. Instant-typed fields carry a full
ISO-8601 UTC instant; date-typed fields carry a ``YYYY-MM-DD`` string
(PRD 2.4).
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from . import constants as C
from .types import (
    AttritionBasis,
    ChargeCategory,
    ForceMajeureClause,
    MarketSegment,
    ReservationSource,
    SpaceCode,
)


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------


def dates_between(arrival: str, departure: str) -> List[str]:
    """The half-open stay range of PRD 2.4, as YYYY-MM-DD strings."""
    start = date.fromisoformat(arrival)
    end = date.fromisoformat(departure)
    out: List[str] = []
    cursor = start
    while cursor < end:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def shift_date(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------
# GroupAccount (PRD 3.1)
# --------------------------------------------------------------------------


def account_payload(
    *,
    name: str = "Northwind Manufacturing",
    market_segment: str = MarketSegment.CORPORATE,
    billing_contact_email: str = "ap@northwind.example",
    credit_hold: Optional[bool] = None,
) -> Dict[str, Any]:
    return _clean({
        "name": name,
        "market_segment": market_segment,
        "billing_contact_email": billing_contact_email,
        "credit_hold": credit_hold,
    })


# --------------------------------------------------------------------------
# InventoryDay (PRD 2.9)
# --------------------------------------------------------------------------


def inventory_day_payload(
    stay_date: str,
    *,
    total_rooms: int = C.INV_TOTAL_ROOMS,
    group_ceiling_rooms: int = C.INV_GROUP_CEILING_ROOMS,
    transient_demand_rooms: int = C.INV_TRANSIENT_DEMAND_ROOMS,
    transient_adr_cents: int = C.INV_TRANSIENT_ADR_CENTS,
    historical_pickup_rooms: int = C.INV_HISTORICAL_PICKUP_ROOMS,
    historical_adr_cents: int = C.INV_HISTORICAL_ADR_CENTS,
) -> Dict[str, Any]:
    return {
        "stay_date": stay_date,
        "total_rooms": total_rooms,
        "group_ceiling_rooms": group_ceiling_rooms,
        "transient_demand_rooms": transient_demand_rooms,
        "transient_adr_cents": transient_adr_cents,
        "historical_pickup_rooms": historical_pickup_rooms,
        "historical_adr_cents": historical_adr_cents,
    }


# --------------------------------------------------------------------------
# ConcessionPackage (PRD 3.1)
# --------------------------------------------------------------------------


def package_payload(
    *,
    name: str = "Corporate Standard",
    room_rate_discount_pct: float = 0.0725,
    comp_room_ratio: int = 40,
    rebate_per_room_night_cents: int = 750,
    banquet_discount_pct: float = 0.10,
    av_discount_pct: float = 0.15,
    parking_discount_pct: float = 0.05,
    min_peak_rooms: int = 4,
    min_total_room_nights: int = 12,
    max_discount_stack_pct: float = 0.45,
) -> Dict[str, Any]:
    """The 'Corporate Standard' package: stack 0.0725 + 0.10 + 0.15 + 0.05."""
    return {
        "name": name,
        "room_rate_discount_pct": room_rate_discount_pct,
        "comp_room_ratio": comp_room_ratio,
        "rebate_per_room_night_cents": rebate_per_room_night_cents,
        "banquet_discount_pct": banquet_discount_pct,
        "av_discount_pct": av_discount_pct,
        "parking_discount_pct": parking_discount_pct,
        "min_peak_rooms": min_peak_rooms,
        "min_total_room_nights": min_total_room_nights,
        "max_discount_stack_pct": max_discount_stack_pct,
    }


def small_meetings_package_payload(**overrides: Any) -> Dict[str, Any]:
    """A package with floors low enough for a one-room programme."""
    payload = package_payload(
        name="Small Meetings",
        room_rate_discount_pct=0.05,
        comp_room_ratio=5,
        rebate_per_room_night_cents=500,
        banquet_discount_pct=0.05,
        av_discount_pct=0.10,
        parking_discount_pct=0.02,
        min_peak_rooms=1,
        min_total_room_nights=1,
        max_discount_stack_pct=0.30,
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Lead (PRD 3.2)
# --------------------------------------------------------------------------


def lead_payload(
    account_id: str,
    *,
    program_name: str = "Northwind Sales Kickoff",
    arrival_date: str = C.ARRIVAL_DATE,
    departure_date: str = C.DEPARTURE_DATE,
    peak_rooms: int = 4,
    total_requested_room_nights: int = 12,
    meeting_space_sqft_needed: int = 100,
    decision_deadline_at: str = "2026-09-15T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "account_id": account_id,
        "program_name": program_name,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "peak_rooms": peak_rooms,
        "total_requested_room_nights": total_requested_room_nights,
        "meeting_space_sqft_needed": meeting_space_sqft_needed,
        "decision_deadline_at": decision_deadline_at,
    }


# --------------------------------------------------------------------------
# FunctionSpaceHold (PRD 3.2)
# --------------------------------------------------------------------------


def function_space_hold_payload(
    lead_id: str,
    *,
    space_code: str = SpaceCode.GRAND_BALLROOM,
    start_at: str = "2026-11-09T09:00:00Z",
    end_at: str = "2026-11-09T12:00:00Z",
    attendee_count: int = 120,
) -> Dict[str, Any]:
    return {
        "lead_id": lead_id,
        "space_code": space_code,
        "start_at": start_at,
        "end_at": end_at,
        "attendee_count": attendee_count,
    }


# --------------------------------------------------------------------------
# DisplacementAnalysis (PRD 3.3)
# --------------------------------------------------------------------------


def displacement_analysis_payload(
    lead_id: str, *, analysis_variant: str = "FORECAST_BASED"
) -> Dict[str, Any]:
    return {"lead_id": lead_id, "analysis_variant": analysis_variant}


def decide_payload(
    *,
    decision: str = "APPROVE",
    expected_lead_version: int,
    override_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return _clean({
        "decision": decision,
        "expected_lead_version": expected_lead_version,
        "override_reason": override_reason,
    })


# --------------------------------------------------------------------------
# RateQuote (PRD 3.4)
# --------------------------------------------------------------------------


def rate_quote_payload(
    lead_id: str,
    concession_package_id: str,
    expected_lead_version: int,
    *,
    base_rate_cents: int = 23950,
    quoted_peak_rooms: int = 4,
    quoted_room_nights: int = 12,
    expires_at: str = "2026-10-01T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "lead_id": lead_id,
        "concession_package_id": concession_package_id,
        "base_rate_cents": base_rate_cents,
        "quoted_peak_rooms": quoted_peak_rooms,
        "quoted_room_nights": quoted_room_nights,
        "expires_at": expires_at,
        "expected_lead_version": expected_lead_version,
    }


def counter_payload(
    *, countered_base_rate_cents: int = 22000, counter_note: Optional[str] = None
) -> Dict[str, Any]:
    return _clean({
        "countered_base_rate_cents": countered_base_rate_cents,
        "counter_note": counter_note,
    })


def revise_payload(
    *,
    base_rate_cents: int = 22000,
    quoted_peak_rooms: int = 4,
    quoted_room_nights: int = 12,
    expires_at: str = "2026-10-01T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "base_rate_cents": base_rate_cents,
        "quoted_peak_rooms": quoted_peak_rooms,
        "quoted_room_nights": quoted_room_nights,
        "expires_at": expires_at,
    }


# --------------------------------------------------------------------------
# GroupContract (PRD 3.5)
# --------------------------------------------------------------------------


def allotment_plan(*pairs: Any) -> List[Dict[str, Any]]:
    """Build a nightly_allotments plan from (stay_date, rooms) pairs."""
    return [{"stay_date": day, "rooms": rooms} for day, rooms in pairs]


def flat_allotment_plan(stay_dates: List[str], rooms: int) -> List[Dict[str, Any]]:
    return [{"stay_date": day, "rooms": rooms} for day in stay_dates]


def contract_payload(
    quote_id: str,
    *,
    attrition_threshold_pct: float = 0.75,
    attrition_basis: str = AttritionBasis.ROOM_NIGHTS,
    force_majeure_clause: str = ForceMajeureClause.STANDARD,
    cutoff_days_before_arrival: int = C.CUTOFF_DAYS_BEFORE_ARRIVAL,
    contracted_room_nights: int = 12,
    contracted_peak_rooms: int = 4,
    nightly_allotments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """The canonical 4/4/4 contract of the golden path."""
    if nightly_allotments is None:
        nightly_allotments = flat_allotment_plan(C.STAY_DATES, 4)
    return {
        "quote_id": quote_id,
        "attrition_threshold_pct": attrition_threshold_pct,
        "attrition_basis": attrition_basis,
        "force_majeure_clause": force_majeure_clause,
        "cutoff_days_before_arrival": cutoff_days_before_arrival,
        "contracted_room_nights": contracted_room_nights,
        "contracted_peak_rooms": contracted_peak_rooms,
        "nightly_allotments": nightly_allotments,
    }


def sign_payload(*, signature_name: str = "R. Buyer") -> Dict[str, Any]:
    return {"signature_name": signature_name}


def cancel_contract_payload(
    *, cancellation_reason: str = "CLIENT_CANCEL", note: Optional[str] = None
) -> Dict[str, Any]:
    return _clean({"cancellation_reason": cancellation_reason, "note": note})


# --------------------------------------------------------------------------
# RoomBlock (PRD 3.6)
# --------------------------------------------------------------------------


def sub_block_payload(
    parent_block_id: str,
    expected_parent_block_version: int,
    *,
    name: str = "SUB-A",
    nightly_allotments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if nightly_allotments is None:
        nightly_allotments = flat_allotment_plan(C.STAY_DATES[:2], 2)
    return {
        "parent_block_id": parent_block_id,
        "name": name,
        "nightly_allotments": nightly_allotments,
        "expected_parent_block_version": expected_parent_block_version,
    }


def waive_attrition_payload(
    *, waiver_reason: str = "Client rebooked 2027 in exchange for the shortfall"
) -> Dict[str, Any]:
    return {"waiver_reason": waiver_reason}


# --------------------------------------------------------------------------
# Reservation (PRD 3.6)
# --------------------------------------------------------------------------


def reservation_payload(
    block_id: str,
    *,
    guest_name: str = "Delegate One",
    arrival_date: str = C.ARRIVAL_DATE,
    departure_date: str = C.DEPARTURE_DATE,
    source: str = ReservationSource.ROOMING_LIST,
) -> Dict[str, Any]:
    return {
        "block_id": block_id,
        "guest_name": guest_name,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "source": source,
    }


def advance_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


def cancel_reservation_payload(
    *, disposition_reason: str = "Traveller withdrew"
) -> Dict[str, Any]:
    return {"disposition_reason": disposition_reason}


# --------------------------------------------------------------------------
# AncillaryCharge (PRD 3.8)
# --------------------------------------------------------------------------


def ancillary_charge_payload(
    contract_id: str,
    *,
    category: str = ChargeCategory.BANQUET,
    gross_amount_cents: int = 500000,
) -> Dict[str, Any]:
    return {
        "contract_id": contract_id,
        "category": category,
        "gross_amount_cents": gross_amount_cents,
    }


# --------------------------------------------------------------------------
# Reconciliation (PRD 3.9)
# --------------------------------------------------------------------------


def reconciliation_payload(expected_contract_version: int) -> Dict[str, Any]:
    return {"expected_contract_version": expected_contract_version}

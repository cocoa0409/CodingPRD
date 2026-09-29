"""Payload factories -- one per resource, input fields only.

Money values are emitted as JSON numbers (never strings); instants carry a
trailing ``Z``; dates are bare ``YYYY-MM-DD`` calendar days.
"""
from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "PLANNER_ORG_NAME": "Continental Dental Assembly",
    "PLANNER_EMAIL": "meetings@cda.org",
    "HOTEL_NAME": "Harborview Grand",
    "HOTEL_ROOMS": 600,
    "HOTEL_WALK_BLOCKS": 2,
    "HALL_NAME": "Grand Hall A",
    "HALL_SQFT": 250_000,
    "HALL_CAPACITY": 12_000,
    "HALL_TURNAROUND_HOURS": 48,
    "EVENT_NAME": "CDA Annual 2028",
    "ARRIVAL_DATE": "2028-04-10",
    "DEPARTURE_DATE": "2028-04-12",
    "PEAK_ROOMS": 1000,
    "TOTAL_ROOM_NIGHTS": 1800,
    "ATTENDANCE": 8000,
    "EXHIBIT_SQFT": 200_000,
    "RATE_CEILING": 219.00,
    "FISCAL_YEAR": 2028,
    "BUDGET_AMOUNT": 500_000.00,
    "RATIONALE": "Citywide block clears the coverage floor with a healthy payback",
}

# The PRD names these bureau service pledges explicitly.
SERVICE_COMMITMENT_CODES: List[str] = [
    "HOUSING_BUREAU",
    "SHUTTLE_NETWORK",
    "VOLUNTEER_CORPS",
    "WELCOME_SIGNAGE",
]


def create_meeting_planner_payload(**overrides) -> dict:
    payload = {
        "org_name": DEFAULTS["PLANNER_ORG_NAME"],
        "contact_email": DEFAULTS["PLANNER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_hotel_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["HOTEL_NAME"],
        "committable_rooms": DEFAULTS["HOTEL_ROOMS"],
        "walk_distance_blocks": DEFAULTS["HOTEL_WALK_BLOCKS"],
    }
    payload.update(overrides)
    return payload


def create_center_hall_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["HALL_NAME"],
        "exhibit_sqft": DEFAULTS["HALL_SQFT"],
        "capacity_persons": DEFAULTS["HALL_CAPACITY"],
        "turnaround_hours": DEFAULTS["HALL_TURNAROUND_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_incentive_fund_payload(**overrides) -> dict:
    payload = {
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "budget_amount": DEFAULTS["BUDGET_AMOUNT"],
    }
    payload.update(overrides)
    return payload


def create_lodging_tax_receipt_payload(**overrides) -> dict:
    payload = {"amount": 50_000.00, "received_at": "2027-03-01T00:00:00Z"}
    payload.update(overrides)
    return payload


def create_opportunity_payload(planner_id: str, **overrides) -> dict:
    payload = {
        "planner_id": planner_id,
        "event_name": DEFAULTS["EVENT_NAME"],
        "arrival_date": DEFAULTS["ARRIVAL_DATE"],
        "departure_date": DEFAULTS["DEPARTURE_DATE"],
        "peak_rooms_requested": DEFAULTS["PEAK_ROOMS"],
        "total_room_nights_requested": DEFAULTS["TOTAL_ROOM_NIGHTS"],
        "attendance_estimate": DEFAULTS["ATTENDANCE"],
        "exhibit_sqft_requested": DEFAULTS["EXHIBIT_SQFT"],
        "rate_ceiling_amount": DEFAULTS["RATE_CEILING"],
    }
    payload.update(overrides)
    return payload


def create_space_hold_payload(opportunity_id: str, center_hall_id: str, **overrides) -> dict:
    payload = {
        "opportunity_id": opportunity_id,
        "center_hall_id": center_hall_id,
        "move_in_start": "2028-04-08T00:00:00Z",
        "move_out_end": "2028-04-13T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_room_block_commitment_payload(
    opportunity_id: str, hotel_id: str, expected_opportunity_version: int, **overrides
) -> dict:
    payload = {
        "opportunity_id": opportunity_id,
        "hotel_id": hotel_id,
        "rooms_peak_invited": 500,
        "expected_opportunity_version": expected_opportunity_version,
    }
    payload.update(overrides)
    return payload


def offer_payload(**overrides) -> dict:
    payload = {
        "rooms_peak_offered": 500,
        "rate_offered_amount": 214.33,
        "cutoff_days_before_arrival": 30,
    }
    payload.update(overrides)
    return payload


def withdraw_payload(withdraw_reason: str = "PROPERTY_SOLD_OUT", **overrides) -> dict:
    payload = {"withdraw_reason": withdraw_reason}
    payload.update(overrides)
    return payload


def pickup_record_payload(night_date: str, rooms_picked_up: int, rate_charged_amount: float, **overrides) -> dict:
    payload = {
        "night_date": night_date,
        "rooms_picked_up": rooms_picked_up,
        "rate_charged_amount": rate_charged_amount,
    }
    payload.update(overrides)
    return payload


def create_bid_package_payload(opportunity_id: str, expected_opportunity_version: int, **overrides) -> dict:
    payload = {
        "opportunity_id": opportunity_id,
        "expected_opportunity_version": expected_opportunity_version,
    }
    payload.update(overrides)
    return payload


def support_letter_payload(letter_type: str = "MAYOR", organization_name: Optional[str] = None, **overrides) -> dict:
    payload = {
        "organization_name": organization_name or f"{letter_type.title()} Backer",
        "letter_type": letter_type,
    }
    payload.update(overrides)
    return payload


def request_incentive_payload(incentive_request_amount: float, **overrides) -> dict:
    payload = {
        "incentive_request_amount": incentive_request_amount,
        "service_commitment_codes": ["HOUSING_BUREAU", "SHUTTLE_NETWORK"],
    }
    payload.update(overrides)
    return payload


def incentive_decision_payload(
    fund_id: str,
    decision: str,
    approved_amount: float,
    expected_fund_version: int,
    **overrides,
) -> dict:
    payload = {
        "fund_id": fund_id,
        "decision": decision,
        "approved_amount": approved_amount,
        "rationale": DEFAULTS["RATIONALE"],
        "expected_fund_version": expected_fund_version,
    }
    payload.update(overrides)
    return payload


def submit_payload(response_due_at: str, **overrides) -> dict:
    payload = {"response_due_at": response_due_at}
    payload.update(overrides)
    return payload


def planner_response_payload(response: str, **overrides) -> dict:
    payload = {"response": response}
    payload.update(overrides)
    return payload


def estimate_payload(opportunity_id: str, variant: str, **overrides) -> dict:
    payload = {"opportunity_id": opportunity_id, "variant": variant}
    payload.update(overrides)
    return payload


def create_servicing_order_payload(opportunity_id: str, **overrides) -> dict:
    payload = {
        "opportunity_id": opportunity_id,
        "category": "HOUSING",
        "requested_units": 10,
        "window_start": "2028-04-09T00:00:00Z",
        "window_end": "2028-04-13T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_board_report_payload(period_start: str, period_end: str, **overrides) -> dict:
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload

"""Payload factories — one per write endpoint, input fields only.

Every money value is emitted as a JSON number in whole cents, never as a
string.  Every instant is emitted as a full ISO 8601 UTC timestamp with exactly
three fractional-second digits; only production_date, window_start_date and
window_end_date are plain YYYY-MM-DD calendar dates, because those are the only
date-only inputs the PRD declares.
"""

from typing import Any, Dict, List

from .constants import MEAT_FOUR_RUNGS


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def create_store_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_number": "0412",
        "name": "Fresh Market 0412",
        "region_code": "MID-ATL",
    }
    payload.update(overrides)
    return payload


def create_food_bank_partner_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Mid-Atlantic Food Bank",
        "contact_email": "ops@mafb.example",
        "service_region_code": "MID-ATL",
        "accepted_department_codes": ["PRODUCE"],
    }
    payload.update(overrides)
    return payload


def create_markdown_ladder_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "MEAT-STD-2026",
        "department_code": "MEAT",
        "rungs": [dict(rung) for rung in MEAT_FOUR_RUNGS],
    }
    payload.update(overrides)
    return payload


def create_department_payload(
    store_id: str, markdown_ladder_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_id": store_id,
        "markdown_ladder_id": markdown_ladder_id,
        "code": "MEAT",
        "shelf_life_days_default": 10,
    }
    payload.update(overrides)
    return payload


def create_item_payload(department_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "upc": "000111222333",
        "description": "Ribeye Steak 12oz",
        "base_retail_cents": 599,
        "unit_cost_cents": 420,
        "daily_forecast_units": 4.00,
    }
    payload.update(overrides)
    return payload


def update_item_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def update_store_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def update_food_bank_partner_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def update_department_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Lots, markdowns, labels, sales, scans
# --------------------------------------------------------------------------


def create_lot_payload(item_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_id": item_id,
        "production_date": "2026-08-05",
        "quantity_original": 24,
    }
    payload.update(overrides)
    return payload


def create_markdown_payload(expected_lot_version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_lot_version": expected_lot_version}
    payload.update(overrides)
    return payload


def void_markdown_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def post_sale_payload(quantity_units: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"quantity_units": quantity_units}
    payload.update(overrides)
    return payload


def withdraw_lot_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def create_scan_price_check_payload(
    scanned_price_cents: int, register_lane_code: str = "L03", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "register_lane_code": register_lane_code,
        "scanned_price_cents": scanned_price_cents,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Donation
# --------------------------------------------------------------------------


def create_donation_pickup_payload(
    store_id: str,
    partner_id: str,
    dock_door_code: str = "D1",
    scheduled_window_start: str = "2026-08-12T14:00:00.000Z",
    scheduled_window_end: str = "2026-08-12T16:00:00.000Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_id": store_id,
        "partner_id": partner_id,
        "dock_door_code": dock_door_code,
        "scheduled_window_start": scheduled_window_start,
        "scheduled_window_end": scheduled_window_end,
    }
    payload.update(overrides)
    return payload


def create_donation_assignment_payload(
    lot_id: str, quantity_units: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"lot_id": lot_id, "quantity_units": quantity_units}
    payload.update(overrides)
    return payload


def cancel_donation_pickup_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Shrink
# --------------------------------------------------------------------------


def create_shrink_event_payload(
    lot_id: str, quantity_units: int, cause_code: str = "SPOILAGE", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lot_id": lot_id,
        "cause_code": cause_code,
        "quantity_units": quantity_units,
    }
    payload.update(overrides)
    return payload


def dispute_shrink_event_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def resubmit_shrink_event_payload(quantity_units: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"quantity_units": quantity_units}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Compliance
# --------------------------------------------------------------------------


def create_compliance_audit_payload(
    department_id: str, window_start_at: str, window_end_at: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload


def escalate_compliance_audit_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def remediate_audit_finding_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Ordering and reporting
# --------------------------------------------------------------------------


def create_order_recommendation_payload(
    item_id: str,
    window_start_date: str,
    window_end_date: str,
    expected_item_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_id": item_id,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "expected_item_version": expected_item_version,
    }
    payload.update(overrides)
    return payload


def window_params(window_start_date: str, window_end_date: str) -> Dict[str, str]:
    return {
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
    }


def ladder_rungs(*triples) -> List[Dict[str, Any]]:
    """Build a rung array from (days_remaining_max, discount_pct, approval) triples."""
    return [
        {
            "days_remaining_max": days,
            "discount_pct": pct,
            "requires_manager_approval": approval,
        }
        for days, pct, approval in triples
    ]

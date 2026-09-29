"""Request-payload factories.

Each builder returns only the input fields the endpoint accepts, with sane defaults
that any override can replace. Money is always a JSON integer count of cents, dates
are ``YYYY-MM-DD`` strings and instants are ISO-8601 UTC with exactly three
fractional digits and a trailing ``Z``.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS
from .types import Payload

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so SKUs and PO numbers stay unique inside one test."""
    return f"{next(_counter):03d}"


DEFAULTS: Dict[str, Any] = {
    "material": {
        "name": "Yard Material",
        "offered_forms": ["BULK"],
        "seasonal_category": "MULCH",
        "density_lb_per_cubic_yard": TEST_DEFAULTS["MATERIAL_DENSITY_LB_PER_CUBIC_YARD"],
        "shrinkage_factor": TEST_DEFAULTS["MATERIAL_SHRINKAGE_FACTOR"],
        "moisture_pct": TEST_DEFAULTS["MATERIAL_MOISTURE_PCT"],
        "unit_bag_cubic_yards": TEST_DEFAULTS["UNIT_BAG_CUBIC_YARDS"],
        "prebuy_eligible": False,
    },
    "price_schedule": {
        "effective_from": TEST_DEFAULTS["PRICE_EFFECTIVE_FROM"],
        "bulk_price_per_cubic_yard_cents": TEST_DEFAULTS["BULK_PRICE_PER_CUBIC_YARD_CENTS"],
        "bagged_price_per_bag_cents": TEST_DEFAULTS["BAGGED_PRICE_PER_BAG_CENTS"],
        "seasonal_surcharge_pct": 0.0,
    },
    "inventory_lot": {
        "gross_cubic_yards": TEST_DEFAULTS["LOT_GROSS_CUBIC_YARDS"],
        "moisture_pct_at_intake": TEST_DEFAULTS["LOT_MOISTURE_PCT_AT_INTAKE"],
    },
    "contractor_account": {
        "business_name": "Contractor Account",
        "credit_limit_cents": TEST_DEFAULTS["GENEROUS_CREDIT_LIMIT_CENTS"],
        "po_required": False,
        "driveway_protection_required": False,
    },
    "delivery_truck": {
        "axle_class": "TANDEM",
        "max_payload_lb": TEST_DEFAULTS["TRUCK_MAX_PAYLOAD_LB"],
        "bed_capacity_cubic_yards": TEST_DEFAULTS["TRUCK_BED_CAPACITY_CUBIC_YARDS"],
        "min_driveway_access_class": "CLASS_A",
    },
}


def create_material_payload(**overrides: Any) -> Payload:
    payload: Payload = dict(DEFAULTS["material"])
    payload["sku"] = f"MAT-{unique_suffix()}"
    payload.update(overrides)
    return payload


def create_price_schedule_payload(
    material_id: str, expected_material_version: int, **overrides: Any
) -> Payload:
    payload: Payload = dict(DEFAULTS["price_schedule"])
    payload["material_id"] = material_id
    payload["expected_material_version"] = expected_material_version
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(material_id: str, **overrides: Any) -> Payload:
    payload: Payload = dict(DEFAULTS["inventory_lot"])
    payload["material_id"] = material_id
    payload.update(overrides)
    return payload


def create_moisture_reading_payload(
    current_moisture_pct: float, set_quarantine: bool = False, **overrides: Any
) -> Payload:
    payload: Payload = {
        "current_moisture_pct": current_moisture_pct,
        "set_quarantine": set_quarantine,
    }
    payload.update(overrides)
    return payload


def create_contractor_account_payload(**overrides: Any) -> Payload:
    payload: Payload = dict(DEFAULTS["contractor_account"])
    payload.update(overrides)
    return payload


def create_credit_adjustment_payload(
    new_credit_limit_cents: int, expected_contractor_account_version: int, **overrides: Any
) -> Payload:
    payload: Payload = {
        "new_credit_limit_cents": new_credit_limit_cents,
        "memo": "Credit line reset",
        "expected_contractor_account_version": expected_contractor_account_version,
    }
    payload.update(overrides)
    return payload


def create_job_purchase_order_payload(
    contractor_account_id: str, po_limit_cents: int, **overrides: Any
) -> Payload:
    payload: Payload = {
        "contractor_account_id": contractor_account_id,
        "po_number": f"PO-2026-{unique_suffix()}",
        "job_code": "JOB-ALPHA",
        "po_limit_cents": po_limit_cents,
    }
    payload.update(overrides)
    return payload


def create_prebuy_contract_payload(
    contractor_account_id: str,
    material_id: str,
    locked_price_per_cubic_yard_cents: int,
    contracted_cubic_yards: float,
    season_start_date: str,
    season_end_date: str,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "contractor_account_id": contractor_account_id,
        "material_id": material_id,
        "locked_price_per_cubic_yard_cents": locked_price_per_cubic_yard_cents,
        "contracted_cubic_yards": contracted_cubic_yards,
        "season_start_date": season_start_date,
        "season_end_date": season_end_date,
    }
    payload.update(overrides)
    return payload


def create_delivery_order_payload(
    contractor_account_id: str,
    driveway_access_class: str = "CLASS_A",
    delivery_distance_miles: float = 0.0,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "contractor_account_id": contractor_account_id,
        "fulfillment_mode": "DELIVERY",
        "delivery_address": TEST_DEFAULTS["DELIVERY_ADDRESS"],
        "driveway_access_class": driveway_access_class,
        "delivery_distance_miles": delivery_distance_miles,
    }
    payload.update(overrides)
    return payload


def create_will_call_order_payload(contractor_account_id: str, **overrides: Any) -> Payload:
    payload: Payload = {
        "contractor_account_id": contractor_account_id,
        "fulfillment_mode": "WILL_CALL",
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(
    material_order_id: str,
    material_id: str,
    form: str = "BULK",
    quantity: float = 10.0,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "material_order_id": material_order_id,
        "material_id": material_id,
        "form": form,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def create_delivery_truck_payload(**overrides: Any) -> Payload:
    payload: Payload = dict(DEFAULTS["delivery_truck"])
    payload["truck_code"] = f"TRK-{unique_suffix()}"
    payload.update(overrides)
    return payload


def create_delivery_load_payload(
    material_order_id: str,
    delivery_truck_id: str,
    planned_cubic_yards: float,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "material_order_id": material_order_id,
        "delivery_truck_id": delivery_truck_id,
        "planned_cubic_yards": planned_cubic_yards,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def deliver_payload(
    actual_net_cubic_yards: float,
    driveway_protection_used: bool = False,
    spillage_cubic_yards: Optional[float] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "actual_net_cubic_yards": actual_net_cubic_yards,
        "driveway_protection_used": driveway_protection_used,
    }
    if spillage_cubic_yards is not None:
        payload["spillage_cubic_yards"] = spillage_cubic_yards
    payload.update(overrides)
    return payload


def refuse_payload(refusal_reason: str = "CUSTOMER_REFUSED", **overrides: Any) -> Payload:
    payload: Payload = {"refusal_reason": refusal_reason}
    payload.update(overrides)
    return payload


def replan_payload(
    delivery_truck_id: str,
    planned_cubic_yards: float,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "delivery_truck_id": delivery_truck_id,
        "planned_cubic_yards": planned_cubic_yards,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_will_call_ticket_payload(
    material_order_id: str, requested_pickup_at: str, **overrides: Any
) -> Payload:
    payload: Payload = {
        "material_order_id": material_order_id,
        "requested_pickup_at": requested_pickup_at,
    }
    payload.update(overrides)
    return payload


def stage_next_payload(staging_window_start: str, staging_window_end: str, **overrides: Any) -> Payload:
    payload: Payload = {
        "staging_window_start": staging_window_start,
        "staging_window_end": staging_window_end,
    }
    payload.update(overrides)
    return payload


def safety_ack_payload(
    ppe_confirmed: bool = True, safety_briefing_code: str = "SB-2026-01", **overrides: Any
) -> Payload:
    payload: Payload = {
        "safety_briefing_code": safety_briefing_code,
        "ppe_confirmed": ppe_confirmed,
    }
    payload.update(overrides)
    return payload


def load_ticket_payload(
    loaded_cubic_yards: float, pallet_count: Optional[int] = None, **overrides: Any
) -> Payload:
    payload: Payload = {"loaded_cubic_yards": loaded_cubic_yards}
    if pallet_count is not None:
        payload["pallet_count"] = pallet_count
    payload.update(overrides)
    return payload


def create_claim_case_payload(
    material_order_id: str,
    claim_type: str,
    claimed_amount_cents: int,
    description: str = "Damage reported at the job site",
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "material_order_id": material_order_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
        "description": description,
    }
    payload.update(overrides)
    return payload


def decide_claim_payload(
    decision: str, approved_amount_cents: Optional[int] = None, denial_reason: Optional[str] = None
) -> Payload:
    payload: Payload = {"decision": decision}
    if approved_amount_cents is not None:
        payload["approved_amount_cents"] = approved_amount_cents
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


def receive_container_payload(returned_count: int) -> Payload:
    return {"returned_count": returned_count}


def settle_order_payload(paid_amount_cents: int) -> Payload:
    return {"paid_amount_cents": paid_amount_cents}


__all__: List[str] = [
    "DEFAULTS",
    "unique_suffix",
    "create_material_payload",
    "create_price_schedule_payload",
    "create_inventory_lot_payload",
    "create_moisture_reading_payload",
    "create_contractor_account_payload",
    "create_credit_adjustment_payload",
    "create_job_purchase_order_payload",
    "create_prebuy_contract_payload",
    "create_delivery_order_payload",
    "create_will_call_order_payload",
    "create_order_line_payload",
    "create_delivery_truck_payload",
    "create_delivery_load_payload",
    "deliver_payload",
    "refuse_payload",
    "replan_payload",
    "create_will_call_ticket_payload",
    "stage_next_payload",
    "safety_ack_payload",
    "load_ticket_payload",
    "create_claim_case_payload",
    "decide_claim_payload",
    "receive_container_payload",
    "settle_order_payload",
]

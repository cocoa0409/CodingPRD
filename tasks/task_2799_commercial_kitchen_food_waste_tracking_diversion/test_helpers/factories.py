"""Request-payload builders. Every field here is a client-supplied input."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def create_site_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": TEST_DEFAULTS["site_name"],
        "site_code": TEST_DEFAULTS["site_code"],
        "region_code": TEST_DEFAULTS["region_code"],
    }
    payload.update(overrides)
    return payload


def create_food_type_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": TEST_DEFAULTS["food_type_name"],
        "category": TEST_DEFAULTS["food_type_category"],
        "default_cost_per_kg_cents": TEST_DEFAULTS["default_cost_per_kg_cents"],
        "donation_eligible": True,
        "animal_feed_eligible": False,
        "compostable": True,
        "donation_shelf_life_hours": TEST_DEFAULTS["donation_shelf_life_hours"],
    }
    payload.update(overrides)
    return payload


def recipe_ingredient(
    ingredient_name: str,
    quantity_kg: float,
    unit_cost_cents_per_kg: int,
    trim_loss_pct: float = 0.0,
) -> Dict[str, Any]:
    return {
        "ingredient_name": ingredient_name,
        "quantity_kg": quantity_kg,
        "unit_cost_cents_per_kg": unit_cost_cents_per_kg,
        "trim_loss_pct": trim_loss_pct,
    }


def create_recipe_payload(ingredients: Optional[List[Dict[str, Any]]] = None, **overrides: Any) -> Dict[str, Any]:
    """The three-line worked example of the costing pass is the default ingredient array."""
    payload: Dict[str, Any] = {
        "recipe_code": "BRZ-CHK",
        "name": "Braised Chicken",
        "ingredients": ingredients
        if ingredients is not None
        else [
            recipe_ingredient("Chicken", 2.5, 1201, 0.20),
            recipe_ingredient("Stock", 1.5, 407, 0.0),
            recipe_ingredient("Aromatics", 0.5, 999, 0.0),
        ],
    }
    payload.update(overrides)
    return payload


def create_tracking_station_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "station_code": TEST_DEFAULTS["prep_station_code"],
        "station_kind": "PREP",
        "calibration_due_at": TEST_DEFAULTS["calibration_due_at"],
    }
    payload.update(overrides)
    return payload


def station_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status}
    payload.update(overrides)
    return payload


def create_shift_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "shift_date": TEST_DEFAULTS["shift_date"],
        "shift_code": TEST_DEFAULTS["shift_code"],
        "meals_served": TEST_DEFAULTS["meals_served"],
    }
    payload.update(overrides)
    return payload


def create_waste_entry_payload(
    station_id: str, shift_id: str, food_type_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "shift_id": shift_id,
        "food_type_id": food_type_id,
        "weight_grams": 1000,
        "loss_reason": "TRIM",
    }
    payload.update(overrides)
    return payload


def flag_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"flag_reason": "Weight looks implausible"}
    payload.update(overrides)
    return payload


def void_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"void_reason": "Tray weighed twice"}
    payload.update(overrides)
    return payload


def correction_payload(expected_entry_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_entry_version": expected_entry_version,
        "correction_note": "Corrected the mis-tapped weight",
    }
    payload.update(overrides)
    return payload


def create_baseline_period_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "start_date": "2026-08-01",
        "end_date": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def reject_baseline_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_note": "Meals figure looks understated"}
    payload.update(overrides)
    return payload


def create_reduction_target_payload(
    site_id: str, baseline_period_id: str, expected_site_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "baseline_period_id": baseline_period_id,
        "basis": "ABSOLUTE",
        "target_reduction_pct": 10.00,
        "window_start": "2026-08-02",
        "window_end": "2026-08-31",
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload


def create_hauler_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": TEST_DEFAULTS["hauler_name"],
        "channels": ["COMPOST"],
        "rate_cents_per_tonne": TEST_DEFAULTS["rate_cents_per_tonne"],
        "stop_fee_cents": TEST_DEFAULTS["stop_fee_cents"],
        "capacity_kg_per_pickup": TEST_DEFAULTS["capacity_kg_per_pickup"],
    }
    payload.update(overrides)
    return payload


def create_consignment_payload(site_id: str, hauler_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "hauler_id": hauler_id,
        "channel": "COMPOST",
        "pickup_window_start": "2026-08-01T14:00:00Z",
        "pickup_window_end": "2026-08-01T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def cancel_consignment_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancel_reason": "Truck broke down"}
    payload.update(overrides)
    return payload


def create_consignment_line_payload(
    consignment_id: str, waste_entry_id: str, allocated_weight_grams: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "consignment_id": consignment_id,
        "waste_entry_id": waste_entry_id,
        "allocated_weight_grams": allocated_weight_grams,
    }
    payload.update(overrides)
    return payload


def create_hauler_ticket_payload(consignment_id: str, gross_weight_grams: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "consignment_id": consignment_id,
        "ticket_number": "TN-1",
        "gross_weight_grams": gross_weight_grams,
        "ticket_date": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def dispute_ticket_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"dispute_note": "Gross weight disagrees with our scale"}
    payload.update(overrides)
    return payload


def resolve_alert_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolution_note": "Coached the line on portioning"}
    payload.update(overrides)
    return payload


def create_data_quality_scan_payload(site_id: str, scan_date: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"site_id": site_id, "scan_date": scan_date}
    payload.update(overrides)
    return payload


def resolve_finding_payload(resolution: str = "CONFIRMED", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolution": resolution}
    payload.update(overrides)
    return payload


def create_rollup_payload(site_ids: List[str], **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "site_ids": site_ids,
    }
    payload.update(overrides)
    return payload

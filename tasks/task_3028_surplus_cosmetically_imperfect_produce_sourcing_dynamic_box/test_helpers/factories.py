"""Payload factories — one per entity, input fields only.

Defaults are chosen so a single factory call produces a payload that is valid
against the PRD's declared enums and required fields.
"""
from .constants import DEFAULT_CLOCK

# Defaults used when a test does not care about a particular value.
DEFAULTS = {
    "LOT_WEIGHT_GRAMS": 100,
    "LOT_UNITS": 300,
    "LOT_COST_CENTS": 100,
    "HARVEST_DATE": "2026-09-01T00:00:00Z",
    "EXPIRY_DATE": "2026-09-20T00:00:00Z",
    "READY_DATE": "2026-09-05T00:00:00Z",
    "GTIN": "00012345678905",
}


def create_fulfillment_center_payload(**overrides) -> dict:
    defaults = {
        "code": "DEMO-NE",
        "name": "Demo Center",
        "region": "NE",
        "insulation_profile": "LIGHT",
        "max_concurrent_building_cycles": 5,
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {"name": "Supply Co", "region": "NE"}
    defaults.update(overrides)
    return defaults


def register_customer_payload(**overrides) -> dict:
    defaults = {
        "email": "sub@example.com",
        "full_name": "Sub Scriber",
        "service_region": "NE",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "cadence": "WEEKLY"}
    defaults.update(overrides)
    return defaults


def create_lot_payload(fulfillment_center_id, **overrides) -> dict:
    defaults = {
        "fulfillment_center_id": fulfillment_center_id,
        "product_name": "LOT",
        "category": "FRUIT",
        "procurement_grade": "SURPLUS",
        "unit_weight_grams": DEFAULTS["LOT_WEIGHT_GRAMS"],
        "quantity_available": DEFAULTS["LOT_UNITS"],
        "unit_cost_cents": DEFAULTS["LOT_COST_CENTS"],
        "harvest_date": DEFAULTS["HARVEST_DATE"],
        "expiry_date": DEFAULTS["EXPIRY_DATE"],
        "ready_date": DEFAULTS["READY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(supply_lot_id, supplier_id, **overrides) -> dict:
    defaults = {
        "supply_lot_id": supply_lot_id,
        "supplier_id": supplier_id,
        "bid_unit_cost_cents": DEFAULTS["LOT_COST_CENTS"],
        "quantity_offered": DEFAULTS["LOT_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(supply_lot_id, **overrides) -> dict:
    defaults = {
        "supply_lot_id": supply_lot_id,
        "retailer_label": "Conventional Co",
        "source_url": "https://ref.example.com/quote",
        "captured_at": "2026-08-30T00:00:00Z",
        "conventional_unit_price_cents": 500,
        "barcode_gtin": DEFAULTS["GTIN"],
        "grade_equivalent": True,
    }
    defaults.update(overrides)
    return defaults


def create_box_order_payload(customer_id, subscription_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "serving_cycle_index": 1,
        "cuisine_preference": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(box_build_item_id, **overrides) -> dict:
    defaults = {
        "box_build_item_id": box_build_item_id,
        "reason_code": "SPOILED",
        "photo_url": "https://cdn.example.com/evidence.jpg",
        "requested_credit_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601=DEFAULT_CLOCK) -> dict:
    return {"to_iso8601": to_iso8601}
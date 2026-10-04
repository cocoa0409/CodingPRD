"""Payload factories — one per entity, input fields only (PRD §3).

Each test runs against a freshly restarted server, so fixed literals are safe;
the `unique()` helper only disambiguates multiple resources inside one test.
"""
from .constants import AGREEMENT_WINDOW_END, AGREEMENT_WINDOW_START

_seq = {"n": 0}


def unique(prefix: str) -> str:
    """Monotonic unique code fragment for skus / lot_codes / batch_codes."""
    _seq["n"] += 1
    return f"{prefix}-{_seq['n']:04d}"


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Facility",
        "health_system_name": "Test Health System",
        "facility_type": "ACUTE_CARE",
        "ship_to_address": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": unique("SKU"),
        "name": "Test Product",
        "brand_type": "BRANDED",
        "category": "WOUND_CARE",
        "sterile": False,
        "device_class": "CLASS_I",
        "units_per_case": 1,
        "each_price_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "lot_code": unique("LOT"),
        "product_id": product_id,
        "quantity": 100,
        "manufacture_date": "2026-08-01",
        "expiry_date": "2027-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_sterilization_batch_payload(lot_ids: list, **overrides) -> dict:
    defaults = {
        "batch_code": unique("BAT"),
        "chamber_id": "CH-1",
        "scheduled_start": "2026-09-10T08:00:00Z",
        "scheduled_end": "2026-09-10T12:00:00Z",
        "lot_ids": lot_ids,
    }
    defaults.update(overrides)
    return defaults


def create_conversion_program_payload(facility_id: str, line_items: list, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "name": "Conversion Program",
        "target_categories": ["WOUND_CARE"],
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def create_tray_template_payload(facility_id: str, components: list, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "name": "Procedure Tray",
        "procedure_type": "GENERAL",
        "sterile_assembly": False,
        "components": components,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "committed_fill_rate_pct": 95.0,
        "deliveries_per_week": 5,
        "lum_commitment": False,
        "annual_commitment_cents": 100000000,
        "start_date": AGREEMENT_WINDOW_START,
        "end_date": AGREEMENT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(agreement_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "requested_delivery_date": "2026-09-15",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_rebate_claim_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "gpo_name": "GPO-A",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "eligible_purchase_cents": 250000,
        "private_label_share": 0.10,
        "compliant": True,
    }
    defaults.update(overrides)
    return defaults


def create_disruption_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "disrupted_quantity": 100,
        "reason": "RAW_MATERIAL_SHORTAGE",
        "severity": "HIGH",
        "expected_resolution_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults


def create_inventory_program_payload(facility_id: str, positions: list, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "program_type": "STOCKROOM_MANAGED",
        "positions": positions,
    }
    defaults.update(overrides)
    return defaults

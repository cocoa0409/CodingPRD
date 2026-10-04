"""Payload factories — one per creatable resource, input fields only.

Defaults track the standard fixture values used across the test design:
DOMESTIC factory (capacity 1000, 3 lines, rate 50, overhead 600), a
DUAL_SOURCE model with one IMPORT_ALLOWED thread line, ISO week 2026-W36.
"""

DEFAULTS = {
    "FACTORY_NAME": "Lawrence MA Plant",
    "WEEKLY_CAPACITY": 1000,
    "LINE_COUNT": 3,
    "LABOR_RATE": 50,
    "OVERHEAD": 600,
    "STYLE_CODE": "MSTD",
    "BASE_PRICE": 5000,
    "IMPORT_BASIS": 2000,
    "PLANNED_LINE_COST": 100,
    "SUPPLIER": "Fall River Mills",
    "LOT_QTY": 1000,
    "LOT_COST": 100,
    "ISO_WEEK": "2026-W36",
    "START_DAY": "2026-09-07",
    "END_DAY": "2026-09-11",
    "BUYER_REF": "cust-1",
    "ISSUER": "Fall River Mills",
    "VALID_FROM": "2026-08-01",
    "VALID_UNTIL": "2027-08-31",
}


def create_factory_payload(**overrides) -> dict:
    defaults = {
        "factory_name": DEFAULTS["FACTORY_NAME"],
        "location_type": "DOMESTIC",
        "weekly_capacity_units": DEFAULTS["WEEKLY_CAPACITY"],
        "line_count": DEFAULTS["LINE_COUNT"],
        "labor_rate_cents_per_minute": DEFAULTS["LABOR_RATE"],
        "overhead_cents_per_pair": DEFAULTS["OVERHEAD"],
    }
    defaults.update(overrides)
    return defaults


def bom_line(component_id, **overrides) -> dict:
    defaults = {
        "component_id": component_id,
        "quantity_per_pair": 1.0,
        "sourcing_requirement": "IMPORT_ALLOWED",
        "planned_unit_cost_cents": DEFAULTS["PLANNED_LINE_COST"],
        "planned_is_domestic": False,
    }
    defaults.update(overrides)
    return defaults


def create_model_payload(component_id=None, bom_lines=None, **overrides) -> dict:
    if bom_lines is None:
        assert component_id is not None, "pass component_id or bom_lines"
        bom_lines = [bom_line(component_id)]
    defaults = {
        "style_code": DEFAULTS["STYLE_CODE"],
        "production_policy": "DUAL_SOURCE",
        "base_price_cents": DEFAULTS["BASE_PRICE"],
        "import_cost_basis_cents": DEFAULTS["IMPORT_BASIS"],
        "bom_lines": bom_lines,
        "standard_stitching_minutes": 0,
        "standard_lasting_minutes": 0,
        "standard_assembly_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    defaults = {
        "component_name": "Bonded nylon thread",
        "component_type": "THREAD",
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(component_id, **overrides) -> dict:
    defaults = {
        "component_id": component_id,
        "supplier_name": DEFAULTS["SUPPLIER"],
        "is_domestic": True,
        "quantity_received": DEFAULTS["LOT_QTY"],
        "unit_cost_cents": DEFAULTS["LOT_COST"],
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(model_id, factory_id, **overrides) -> dict:
    defaults = {
        "model_id": model_id,
        "factory_id": factory_id,
        "run_type": "STOCK",
        "planned_units": 10,
        "line_index": 1,
        "start_day": DEFAULTS["START_DAY"],
        "end_day": DEFAULTS["END_DAY"],
        "iso_week": DEFAULTS["ISO_WEEK"],
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(stitching=0, lasting=0, assembly=0) -> dict:
    return {
        "actual_stitching_minutes": stitching,
        "actual_lasting_minutes": lasting,
        "actual_assembly_minutes": assembly,
    }


def create_report_payload(variant, expected_run_version) -> dict:
    return {"variant": variant, "expected_run_version": expected_run_version}


def create_order_payload(model_id, **overrides) -> dict:
    defaults = {
        "model_id": model_id,
        "buyer_ref": DEFAULTS["BUYER_REF"],
        "colorway": "STD",
        "size": "10",
        "quantity_units": 2,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(model_id, claim_type="MADE_IN_USA") -> dict:
    return {"model_id": model_id, "claim_type": claim_type}


def create_document_payload(doc_type, *, link_field, link_id, **overrides) -> dict:
    assert link_field in ("claim_id", "material_lot_id", "production_run_id")
    defaults = {
        "doc_type": doc_type,
        "issuer": DEFAULTS["ISSUER"],
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
        link_field: link_id,
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(factory_id, **overrides) -> dict:
    defaults = {"factory_id": factory_id, "full_name": "Ada Lovelace"}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(worker_id, operation, target_level=1) -> dict:
    return {"worker_id": worker_id, "operation": operation, "target_level": target_level}


def record_assessment_payload(score) -> dict:
    return {"score": score}


def create_allocation_payload(factory_id, **overrides) -> dict:
    defaults = {
        "factory_id": factory_id,
        "iso_week": DEFAULTS["ISO_WEEK"],
        "total_reserved_units": 100,
    }
    defaults.update(overrides)
    return defaults


def shift_allocation_payload(direction, units, expected_allocation_version) -> dict:
    return {
        "direction": direction,
        "units": units,
        "expected_allocation_version": expected_allocation_version,
    }


def create_contract_payload(model_id, factory_id, **overrides) -> dict:
    defaults = {
        "contract_number": "G-100",
        "model_id": model_id,
        "factory_id": factory_id,
        "awarded_units": 10,
        "fulfillment_start": "2026-10-01",
        "fulfillment_end": "2026-10-31",
    }
    defaults.update(overrides)
    return defaults

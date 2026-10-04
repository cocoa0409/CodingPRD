"""Payload factories — one per write operation, input fields only (PRD §3).

Defaults satisfy the happy-path preconditions: the default product passes the
brand floor (2400 >= round_half_up(2000 * 1.15) = 2300, msrp 4000 >= 2400),
the default chemistry passes the certification gate (carbon_equivalent
3.30 + (2.99 + 0.010)/3 = 4.30, sulfur 0.045, phosphorus 0.010, 2725F), the
default bake hits the SOYBEAN band midpoint (475F), and the default ship week
is strictly after the initial logical date 2026-09-01.

None values are dropped so optional fields (defect_type, severity, notes) are
absent unless requested. OCC version fields and FK ids are passed explicitly
by callers/fixtures; unique sku_code defaults avoid cross-entity collisions
when a test registers more than one product.
"""
import uuid


def _clean(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if v is not None}


def _unique_sku() -> str:
    return f"SKU-{uuid.uuid4().hex[:8].upper()}"


# ---- products (PRD §3.1) ----
def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku_code": _unique_sku(),
        "name": "Skillet 10.25in",
        "category": "SKILLET",
        "target_weight_oz": 128.0,
        "weight_tolerance_oz": 6.0,
        "target_diameter_in": 10.25,
        "diameter_tolerance_in": 0.125,
        "min_wall_thickness_in": 0.1875,
        "wholesale_price_cents": 2400,
        "msrp_cents": 4000,
        "import_landed_cost_cents": 2000,
        "peak_season_start_week": 44,
        "peak_season_end_week": 52,
    }
    defaults.update(overrides)
    return _clean(defaults)


# ---- production orders (PRD §3.2) ----
def create_production_order_payload(product_id=None, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "planned_quantity": 10,
        "scheduled_week": 40,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_order_completion_payload(**overrides) -> dict:
    defaults = {
        "labor_hours_actual": 40.0,
        "energy_kwh_actual": 900.0,
    }
    defaults.update(overrides)
    return _clean(defaults)


# ---- melt batches (PRD §3.3) ----
def create_melt_batch_payload(production_order_id=None,
                              expected_production_order_version=None,
                              **overrides) -> dict:
    defaults = {
        "production_order_id": production_order_id,
        "furnace_id": "FURNACE_A",
        "planned_tap_start": "2026-09-02T10:00:00Z",
        "planned_tap_end": "2026-09-02T12:00:00Z",
        "planned_iron_lbs": 2000,
        "planned_pig_iron_pct": 40,
        "planned_scrap_steel_pct": 40,
        "planned_returns_pct": 15,
        "planned_alloy_pct": 5,
        "expected_production_order_version": expected_production_order_version,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_charge_payload(**overrides) -> dict:
    defaults = {
        "pig_iron_lbs": 810,
        "scrap_steel_lbs": 790,
        "returns_lbs": 320,
        "alloy_lbs": 90,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_chemistry_readings_payload(**overrides) -> dict:
    # Defaults sit exactly on the inclusive CE upper bound and pass the gate.
    defaults = {
        "carbon_pct": 3.30,
        "silicon_pct": 2.99,
        "manganese_pct": 0.65,
        "sulfur_pct": 0.045,
        "phosphorus_pct": 0.010,
        "bath_temp_f": 2725,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_certify_chemistry_payload(decision="CERTIFY", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return _clean(defaults)


def create_tap_payload(**overrides) -> dict:
    defaults = {
        "tapped_temp_f": 2690,
        "tapped_lbs": 2010,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_pour_payload(mold_id=None, **overrides) -> dict:
    defaults = {
        "mold_id": mold_id,
        "unit_count": 1,
        "pour_weight_per_unit_oz": 128.0,
    }
    defaults.update(overrides)
    return _clean(defaults)


# ---- molds (PRD §3.4) ----
def create_mold_payload(production_order_id=None, **overrides) -> dict:
    defaults = {
        "production_order_id": production_order_id,
        "new_sand_pct": 20.0,
        "reclaimed_sand_pct": 80.0,
        "moisture_pct": 3.8,
        "clay_pct": 10.0,
        "sand_weight_lbs": 500,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_reclaim_payload(**overrides) -> dict:
    # Defaults: loss 0 lbs on a 500-lb mold (well inside the 12% bound).
    defaults = {
        "reclaimed_sand_lbs": 450.0,
        "dust_collected_lbs": 50.0,
    }
    defaults.update(overrides)
    return _clean(defaults)


# ---- casting inspection and defects (PRD §3.5) ----
def create_inspect_payload(outcome="PASS", **overrides) -> dict:
    # Default measurements match the default product's targets exactly.
    defaults = {
        "outcome": outcome,
        "measured_weight_oz": 128.0,
        "measured_diameter_in": 10.25,
        "measured_wall_thickness_in": 0.19,
        "defect_type": None,
        "severity": None,
        "notes": None,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_disposition_payload(disposition="SCRAP", **overrides) -> dict:
    defaults = {"disposition": disposition}
    defaults.update(overrides)
    return _clean(defaults)


# ---- seasoning batches (PRD §3.6) ----
def create_seasoning_batch_payload(production_order_id=None, unit_ids=None,
                                   **overrides) -> dict:
    defaults = {
        "production_order_id": production_order_id,
        "oil_type": "SOYBEAN",
        "coating_count": 1,
        "planned_bake_start": "2026-09-03T08:00:00Z",
        "planned_bake_end": "2026-09-03T10:00:00Z",
        "unit_ids": unit_ids,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_start_bake_payload(**overrides) -> dict:
    # 475F is the SOYBEAN band midpoint (450..500).
    defaults = {
        "actual_bake_temp_f": 475,
        "oil_lot_number": "LOT-2026-0901",
        "coa_reference": "COA-7781",
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_qa_release_payload(**overrides) -> dict:
    # 60 min at the SOYBEAN minimum gives duration_factor 2/3; with temp_factor
    # 1.0 the cure score is 87 (>= 70, releaseable).
    defaults = {
        "bake_duration_min": 60,
        "food_safety_verified": True,
        "decision": "RELEASE",
    }
    defaults.update(overrides)
    return _clean(defaults)


# ---- environmental permits and readings (PRD §3.7) ----
def create_environmental_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_type": "AIR_EMISSIONS",
        "limit_value": 100.0,
        "measurement_unit": "mg_m3",
        "compliance_period": "MONTHLY",
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_emissions_reading_payload(reading_value=None, **overrides) -> dict:
    defaults = {
        "reading_value": reading_value,
        "source": "MELT_FURNACE",
    }
    defaults.update(overrides)
    return _clean(defaults)


# ---- inventory / allocations / outlet sales (PRD §3.8) ----
def create_retail_allocation_payload(inventory_record_id=None,
                                     expected_inventory_version=None,
                                     **overrides) -> dict:
    # ship_week 2026-11-16 is a Monday strictly after the initial logical date.
    defaults = {
        "inventory_record_id": inventory_record_id,
        "channel": "RETAIL_CHAIN",
        "allocated_qty": 1,
        "ship_week": "2026-11-16",
        "expected_inventory_version": expected_inventory_version,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_outlet_sale_payload(product_id=None, **overrides) -> dict:
    # Default price sits exactly on the FACTORY_OUTLET floor:
    # round_half_up(4000 * 0.55) = 2200 (equality allowed).
    defaults = {
        "product_id": product_id,
        "channel": "FACTORY_OUTLET",
        "qty": 1,
        "unit_price_cents": 2200,
    }
    defaults.update(overrides)
    return _clean(defaults)


# ---- logical clock (PRD §2.4) ----
def create_clock_payload(to_iso8601=None, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return _clean(defaults)

"""Payload factories — one per entity, input fields only (PRD §3)."""


def supplier_payload(**overrides) -> dict:
    defaults = {"name": "Malabar Exports", "origin_country": "IN"}
    defaults.update(overrides)
    return defaults


def lot_payload(supplier_id, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "spice_code": "BLACK_PEPPER",
        "origin_region": "Malabar",
        "crop_year": 2025,
        "quantity_kg": 100,
        "flavor_intensity_units": 100.0,
        "moisture_pct": 8.0,
        "cost_per_kg_cents": 100,
        "allergen_profile": "NONE",
        "organic_certified": False,
    }
    defaults.update(overrides)
    return defaults


def test_payload(test_type="MICRO", measured_value=50000, lab_code="LAB-A",
                 **overrides) -> dict:
    defaults = {
        "test_type": test_type,
        "measured_value": measured_value,
        "lab_code": lab_code,
    }
    defaults.update(overrides)
    return defaults


def disposition_payload(action="ACCEPT", **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def formula_payload(product_code, **overrides) -> dict:
    defaults = {
        "product_code": product_code,
        "name": product_code,
        "brand_type": "BRANDED",
        "target_flavor_units": 100.0,
    }
    defaults.update(overrides)
    return defaults


def formula_line_payload(spice_code="BLACK_PEPPER", target_proportion_pct=100.0,
                         **overrides) -> dict:
    defaults = {
        "spice_code": spice_code,
        "target_proportion_pct": target_proportion_pct,
        "allergen_profile": "NONE",
        "organic_required": False,
        "min_lot_flavor_units": 50.0,
    }
    defaults.update(overrides)
    return defaults


def blend_run_payload(formula_id, selection_policy="COST_MIN", target_batch_kg=100,
                      **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "selection_policy": selection_policy,
        "target_batch_kg": target_batch_kg,
    }
    defaults.update(overrides)
    return defaults


def line_payload(name="Line-1", capacity_kg_per_shift=1000, **overrides) -> dict:
    defaults = {
        "name": name,
        "capacity_kg_per_shift": capacity_kg_per_shift,
        "supported_changeover_classes": ["NONE", "DRY_CLEAN", "WET_WASH",
                                         "FULL_SANITATION"],
    }
    defaults.update(overrides)
    return defaults


def production_run_payload(line_id, formula_id, blend_run_id, quantity_kg,
                           window_start, window_end, expected_line_version,
                           **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "formula_id": formula_id,
        "blend_run_id": blend_run_id,
        "quantity_kg": quantity_kg,
        "window_start": window_start,
        "window_end": window_end,
        "expected_line_version": expected_line_version,
    }
    defaults.update(overrides)
    return defaults


def recall_case_payload(trigger_type="LOT_SUSPECT", scope_policy="FINAL",
                        **overrides) -> dict:
    defaults = {"trigger_type": trigger_type, "scope_policy": scope_policy}
    defaults.update(overrides)
    return defaults


def agreement_payload(retailer_name="Riverbend Foods", product_codes=None,
                      annual_commitment_kg=500, **overrides) -> dict:
    defaults = {
        "retailer_name": retailer_name,
        "product_codes": product_codes if product_codes is not None else ["PL-1"],
        "annual_commitment_kg": annual_commitment_kg,
    }
    defaults.update(overrides)
    return defaults


def reservation_payload(line_id, window_start, window_end, reserved_kg_per_week,
                        **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "window_start": window_start,
        "window_end": window_end,
        "reserved_kg_per_week": reserved_kg_per_week,
    }
    defaults.update(overrides)
    return defaults

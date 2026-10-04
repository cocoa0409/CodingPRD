"""Payload factories — one per entity, input fields only (PRD §3)."""

# Canonical store fixtures used across the suite (PRD §3.1 input fields).
STORE_ALPHA = {
    "name": "Store Alpha",
    "region": "US-NE",
    "demographic_index": 80,
    "weekly_category_velocity_index": 90,
    "competitor_density_index": 20,
    "available_sqft": 100,
    "distance_miles_from_plant": 10,
}
STORE_BETA = {
    "name": "Store Beta",
    "region": "US-SW",
    "demographic_index": 90,
    "weekly_category_velocity_index": 80,
    "competitor_density_index": 10,
    "available_sqft": 100,
    "distance_miles_from_plant": 12,
}
STORE_GAMMA = {
    "name": "Store Gamma",
    "region": "US-MW",
    "demographic_index": 75,
    "weekly_category_velocity_index": 85,
    "competitor_density_index": 15,
    "available_sqft": 100,
    "distance_miles_from_plant": 20,
}
STORE_DELTA = {
    "name": "Store Delta",
    "region": "US-MW",
    "demographic_index": 60,
    "weekly_category_velocity_index": 70,
    "competitor_density_index": 25,
    "available_sqft": 80,
    "distance_miles_from_plant": 7,
}


def create_store_payload(**overrides) -> dict:
    defaults = dict(STORE_ALPHA)
    defaults.update(overrides)
    return defaults


def create_site_evaluation_payload(**overrides) -> dict:
    defaults = {
        "model_variant": "DEMOGRAPHIC_LED",
        "chiller_model": "STANDARD",
        "forecast_weekly_units": 200,
        "allocated_sqft": 16,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "allocated_sqft": 16,
        "max_capex_cents": 500000,
        "term_months": 60,
    }
    defaults.update(overrides)
    return defaults


def create_chiller_batch_payload(**overrides) -> dict:
    defaults = {
        "model": "STANDARD",
        "serial_prefix": "FP",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(store_id, agreement_id, chiller_id, expected_agreement_version, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "agreement_id": agreement_id,
        "chiller_id": chiller_id,
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def create_reading_payload(**overrides) -> dict:
    defaults = {
        "recorded_at": "2026-09-02T08:30:00Z",
        "temp_c": 2.5,
        "duration_minutes": 15,
    }
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(chiller_id, **overrides) -> dict:
    payload = {
        "chiller_id": chiller_id,
        "issue_summary": "store-reported issue",
    }
    payload.update(overrides)
    return payload


def create_dispatch_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-09-03T09:00:00Z",
        "window_end": "2026-09-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_resolve_payload(**overrides) -> dict:
    defaults = {"resolution_note": "repair completed"}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(store_id, lot_id, quantity_units, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "lot_id": lot_id,
        "quantity_units": quantity_units,
    }
    payload.update(overrides)
    return payload


def create_deliver_payload(accepted_units, rejected_units) -> dict:
    return {"accepted_units": accepted_units, "rejected_units": rejected_units}


def create_product_lot_payload(**overrides) -> dict:
    defaults = {
        "sku": "BEEF-5LB",
        "produced_at": "2026-09-01T00:00:00Z",
        "quantity_units": 500,
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(qc_passed=True) -> dict:
    return {"qc_passed": qc_passed}


def create_capacity_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Line expansion",
        "capacity_delta_units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_trial_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "Launch Demo",
        "start_date": "2026-09-10T00:00:00Z",
        "end_date": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_retire_remove_payload(removal_reason="UNDERPERFORMANCE_REMOVAL") -> dict:
    return {"mode": "REMOVE", "removal_reason": removal_reason}


def create_retire_relocate_payload(target_store_id, target_agreement_id) -> dict:
    return {
        "mode": "RELOCATE",
        "target_store_id": target_store_id,
        "target_agreement_id": target_agreement_id,
    }

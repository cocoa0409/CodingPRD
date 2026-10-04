"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PLANT_NAME": "Phoenix Can Plant",
    "PLANT_REGION": "US-SW",
    "WAREHOUSE_CAPACITY": 1_000_000,
    "CUSTOMER_NAME": "Desert Beverage Co",
    "CUSTOMER_REGION": "US-SW",
    "FILLING_LINES": 1,
    "COMMITTED_ANNUAL_UNITS": 12_000_000,
    "PASS_THROUGH_PCT": 0.9,
    "CONVERSION_COST": 1500,
    "START_DATE": "2026-01-01",
    "END_DATE": "2026-12-31",
    "LINE_NAME": "Line 1",
    "LINE_SPEED": 120_000,
    "BASE_SPOILAGE": 0.04,
    "SIZE_CODE": "12OZ",
    "SHAPE": "STANDARD",
    "METAL_LBS_PER_1000": 30.0,
    "SCHEDULED_QTY": 50_000,
    "GRAPHICS_CODE": "G1",
    "WINDOW_START": "2026-09-10T08:00:00Z",
    "WINDOW_END": "2026-09-10T16:00:00Z",
    "DECLARED_WEIGHT_LBS": 5000,
    "PICKUP_START": "2026-09-05T09:00:00Z",
    "PICKUP_END": "2026-09-05T10:00:00Z",
    "INCIDENT_NOTE": "quality note",
}


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PLANT_NAME"],
        "region": DEFAULTS["PLANT_REGION"],
        "warehouse_capacity_units": DEFAULTS["WAREHOUSE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "home_region": DEFAULTS["CUSTOMER_REGION"],
        "filling_lines_count": DEFAULTS["FILLING_LINES"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(plant_id, customer_id, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "customer_id": customer_id,
        "committed_annual_units": DEFAULTS["COMMITTED_ANNUAL_UNITS"],
        "pass_through_pct": DEFAULTS["PASS_THROUGH_PCT"],
        "conversion_cost_cents_per_1000": DEFAULTS["CONVERSION_COST"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def publish_index_payload(period, index_cents_per_lb) -> dict:
    return {"period": period, "index_cents_per_lb": index_cents_per_lb}


def create_line_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LINE_NAME"],
        "nominal_speed_cans_per_hour": DEFAULTS["LINE_SPEED"],
        "base_spoilage_pct": DEFAULTS["BASE_SPOILAGE"],
    }
    defaults.update(overrides)
    return defaults


def create_format_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "size_code": DEFAULTS["SIZE_CODE"],
        "shape": DEFAULTS["SHAPE"],
        "is_specialty": False,
        "metal_lbs_per_1000_units": DEFAULTS["METAL_LBS_PER_1000"],
        "tooling_investment_cents": 0,
        "min_volume_commitment_units": 0,
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(line_id, format_id, expected_agreement_version, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "format_id": format_id,
        "scheduled_qty": DEFAULTS["SCHEDULED_QTY"],
        "graphics_code": DEFAULTS["GRAPHICS_CODE"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(**overrides) -> dict:
    defaults = {"produced_qty": DEFAULTS["SCHEDULED_QTY"], "spoiled_qty": 0}
    defaults.update(overrides)
    return defaults


def create_forecast_payload(period, forecast_qty) -> dict:
    return {"period": period, "forecast_qty": forecast_qty}


def create_scrap_return_payload(plant_id, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "pickup_window_start": DEFAULTS["PICKUP_START"],
        "pickup_window_end": DEFAULTS["PICKUP_END"],
        "declared_weight_lbs": DEFAULTS["DECLARED_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def credit_scrap_payload(actual_weight_lbs, grade="UBC") -> dict:
    return {"actual_weight_lbs": actual_weight_lbs, "grade": grade}


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "severity": "MAJOR",
        "defect_class": "SEAM_INTEGRITY",
        "note": DEFAULTS["INCIDENT_NOTE"],
    }
    defaults.update(overrides)
    return defaults

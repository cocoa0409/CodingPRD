"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FACILITY_NAME": "F1",
    "FACILITY_CAPACITY": 2000,
    "DOUGH_CODE": "CXL",
    "SHELF_LIFE_HOURS": 36,
    "ORDER_CUTOFF": "13:00",
    "FLAT_TRANSFER_PRICE": 4.00,
    "CAFE_NAME": "C1",
    "OWNERSHIP": "FRANCHISE",
    "CREDIT_LIMIT": 90000,
    "PRODUCTION_DATE": "2026-09-10",
    "BUSINESS_DATE": "2026-09-10",
    "VEHICLE_CAPACITY": 500,
    "WINDOW_START": "03:00",
    "WINDOW_END": "04:00",
    "PLANNED_ARRIVAL": "2026-09-10T03:10:00Z",
    "PARTNER_NAME": "CityFood",
    "PROOF_MINUTES": 90,
}


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "effective_capacity_units": DEFAULTS["FACILITY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_dough_type_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["DOUGH_CODE"],
        "category": "CONVENTIONAL",
        "shelf_life_hours": DEFAULTS["SHELF_LIFE_HOURS"],
        "order_cutoff_local": DEFAULTS["ORDER_CUTOFF"],
        "substitution_allowed": False,
        "flat_transfer_price": DEFAULTS["FLAT_TRANSFER_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_cafe_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CAFE_NAME"],
        "facility_id": "",
        "ownership_type": DEFAULTS["OWNERSHIP"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def create_demand_adjustment_payload(**overrides) -> dict:
    defaults = {
        "cafe_id": "",
        "production_date": DEFAULTS["PRODUCTION_DATE"],
        "reason": "WEATHER",
        "demand_delta_pct": -20,
    }
    defaults.update(overrides)
    return defaults


def create_cafe_order_payload(**overrides) -> dict:
    defaults = {
        "cafe_id": "",
        "dough_type_id": "",
        "production_date": DEFAULTS["PRODUCTION_DATE"],
        "quantity": 100,
        "expected_cafe_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_production_plan_payload(**overrides) -> dict:
    defaults = {"production_date": DEFAULTS["PRODUCTION_DATE"]}
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "production_date": DEFAULTS["PRODUCTION_DATE"],
        "vehicle_capacity_units": DEFAULTS["VEHICLE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(**overrides) -> dict:
    defaults = {
        "seq": 1,
        "cafe_id": "",
        "planned_arrival": DEFAULTS["PLANNED_ARRIVAL"],
        "window_start_local": DEFAULTS["WINDOW_START"],
        "window_end_local": DEFAULTS["WINDOW_END"],
        "planned_units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(**overrides) -> dict:
    defaults = {"business_date": DEFAULTS["BUSINESS_DATE"]}
    defaults.update(overrides)
    return defaults


def create_bake_entry_payload(**overrides) -> dict:
    defaults = {
        "cafe_order_id": "",
        "quantity": 40,
        "proof_start_at": "2026-09-10T04:00:00Z",
        "proof_minutes": DEFAULTS["PROOF_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_donation_pickup_payload(**overrides) -> dict:
    defaults = {
        "schedule_id": "",
        "partner_name": DEFAULTS["PARTNER_NAME"],
        "unsold_conventional": 12,
        "unsold_artisan": 0,
    }
    defaults.update(overrides)
    return defaults


def create_billing_period_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-09-08",
        "period_end": "2026-09-14",
        "admin_pool_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_line_payload(**overrides) -> dict:
    defaults = {"cafe_id": "", "cafe_hours": 80}
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 1000}
    defaults.update(overrides)
    return defaults

"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _suffix() -> int:
    return next(_counter)


def create_location_payload(**overrides) -> dict:
    n = _suffix()
    defaults = {
        "location_code": f"LOC-{n:05d}",
        "city": f"City {n}",
        "geo_zone": "NORTH",
        "storage_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(**overrides) -> dict:
    n = _suffix()
    defaults = {
        "dealer_code": f"D-{n:05d}",
        "name": f"Dealer {n}",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(**overrides) -> dict:
    n = _suffix()
    defaults = {
        "unit_code": f"U-{n:05d}",
        "equipment_type": "TRUCK_10FT",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_profile_payload(**overrides) -> dict:
    n = _suffix()
    defaults = {
        "label": f"Vehicle {n}",
        "make": "Honda",
        "model": "Accord",
        "year": 2020,
        "curb_weight_lbs": 3300,
        "tow_capacity_lbs": 0,
        "hitch_class": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    n = _suffix()
    defaults = {
        "email": f"customer-{n}@example.com",
        "full_name": f"Customer {n}",
    }
    defaults.update(overrides)
    return defaults


def create_lane_rate_payload(**overrides) -> dict:
    defaults = {
        "equipment_type": "TRUCK_10FT",
        "season": "OFF_PEAK",
        "base_rate_cents": 5000,
        "reposition_surcharge_cents": 0,
        "commission_rate": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    defaults = {
        "equipment_type": "TRUCK_10FT",
        "rental_kind": "ONE_WAY",
        "pickup_date": "2026-11-10T10:00:00Z",
        "dropoff_date": "2026-11-11T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rental_agreement_payload(**overrides) -> dict:
    return dict(overrides)


def create_damage_protection_plan_payload(**overrides) -> dict:
    defaults = {"tier": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(**overrides) -> dict:
    defaults = {"claimed_amount_cents": 10000}
    defaults.update(overrides)
    return defaults


def create_reposition_task_payload(**overrides) -> dict:
    defaults = {"equipment_type": "TRUCK_10FT"}
    defaults.update(overrides)
    return defaults


def create_cross_sell_order_payload(**overrides) -> dict:
    defaults = {"line_items": [{"sku": "TAPE", "qty": 1}]}
    defaults.update(overrides)
    return defaults


def create_dealer_settlement_payload(**overrides) -> dict:
    defaults = {"period": "2026-Q4"}
    defaults.update(overrides)
    return defaults


def create_performance_review_payload(**overrides) -> dict:
    defaults = {"period": "2026-Q3", "scores": []}
    defaults.update(overrides)
    return defaults

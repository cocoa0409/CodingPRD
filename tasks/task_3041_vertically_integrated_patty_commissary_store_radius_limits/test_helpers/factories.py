"""Payload factories — caller-supplied fields only, per PRD section 4."""

import itertools

from .constants import (
    COMMISSARY_LAT,
    COMMISSARY_LNG,
    DEFAULT_DELIVERY_DAYS_MASK,
    DEFAULT_SPEC_PROFILE,
    MENU_HAMBURGER,
    STORE_LAT,
    STORE_LNG,
)

_counter = itertools.count(1)


def _tag() -> int:
    return next(_counter)


def create_supplier_payload(**overrides) -> dict:
    n = _tag()
    payload = {
        "supplier_code": f"RANCH-{n:04d}",
        "spec_profile": dict(DEFAULT_SPEC_PROFILE),
        "audit_frequency_days": 30,
    }
    payload.update(overrides)
    return payload


def create_commissary_payload(supplier_id: str, **overrides) -> dict:
    n = _tag()
    payload = {
        "name": f"Commissary {n}",
        "lat": COMMISSARY_LAT,
        "lng": COMMISSARY_LNG,
        "radius_limit_km": 500,
        "daily_patty_capacity": 100000,
        "daily_bun_capacity": 60000,
        "daily_produce_capacity": 40000,
        "delivery_days_mask": list(DEFAULT_DELIVERY_DAYS_MASK),
        "supplier_id": supplier_id,
    }
    payload.update(overrides)
    return payload


def create_store_payload(commissary_id: str, expected_commissary_version: int,
                         **overrides) -> dict:
    n = _tag()
    payload = {
        "commissary_id": commissary_id,
        "name": f"Store {n}",
        "lat": STORE_LAT,
        "lng": STORE_LNG,
        "expected_commissary_version": expected_commissary_version,
    }
    payload.update(overrides)
    return payload


def create_associate_payload(home_store_id: str, **overrides) -> dict:
    n = _tag()
    payload = {
        "full_name": f"Associate {n}",
        "hired_date": "2024-01-01T00:00:00Z",
        "home_store_id": home_store_id,
    }
    payload.update(overrides)
    return payload


def create_menu_item_payload(**overrides) -> dict:
    payload = dict(MENU_HAMBURGER)
    payload.update(overrides)
    return payload


def create_truck_payload(**overrides) -> dict:
    n = _tag()
    payload = {
        "plate": f"TRK-{n:04d}",
        "route_type": "PRIMARY",
        "cooler_capacity_cases": 30,
    }
    payload.update(overrides)
    return payload


def create_route_payload(commissary_id: str, truck_id: str, service_date: str,
                         store_ids: list, **overrides) -> dict:
    payload = {
        "commissary_id": commissary_id,
        "truck_id": truck_id,
        "service_date": service_date,
        "store_ids": list(store_ids),
    }
    payload.update(overrides)
    return payload


def create_batch_payload(store_id: str, expected_store_version: int,
                         delivery_date: str, patty_count: int = 10,
                         bun_count: int = 10, produce_units: int = 10,
                         **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "delivery_date": delivery_date,
        "patty_count": patty_count,
        "bun_count": bun_count,
        "produce_units": produce_units,
        "expected_store_version": expected_store_version,
    }
    payload.update(overrides)
    return payload


def create_order_line(menu_item_id: str, qty: int = 1,
                      modifier_codes: list = None) -> dict:
    return {
        "menu_item_id": menu_item_id,
        "qty": qty,
        "modifier_codes": list(modifier_codes or []),
    }


def create_order_payload(placed_by_associate_id: str, lines: list,
                         **overrides) -> dict:
    payload = {
        "placed_by_associate_id": placed_by_associate_id,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def create_shift_payload(associate_id: str, shift_start: str, shift_end: str,
                         **overrides) -> dict:
    payload = {
        "associate_id": associate_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
    }
    payload.update(overrides)
    return payload


def create_beef_delivery_payload(commissary_id: str, supplier_id: str,
                                 raw_beef_lbs: float = 500,
                                 transit_temp_celsius: float = 2.0,
                                 **overrides) -> dict:
    payload = {
        "commissary_id": commissary_id,
        "supplier_id": supplier_id,
        "shipped_at": "2026-09-01T06:00:00Z",
        "raw_beef_lbs": raw_beef_lbs,
        "transit_temp_celsius": transit_temp_celsius,
    }
    payload.update(overrides)
    return payload


def create_production_run_payload(patties_planned: int = 10,
                                  buns_planned: int = 10,
                                  produce_units_planned: int = 10,
                                  run_date: str = "2026-09-01T00:00:00Z",
                                  **overrides) -> dict:
    payload = {
        "run_date": run_date,
        "patties_planned": patties_planned,
        "buns_planned": buns_planned,
        "produce_units_planned": produce_units_planned,
    }
    payload.update(overrides)
    return payload

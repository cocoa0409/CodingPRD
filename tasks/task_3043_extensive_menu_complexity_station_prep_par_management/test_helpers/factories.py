"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "RESTAURANT_NAME": "Ridgeview",
    "RESTAURANT_CODE": "RIDGE",
    "WEEKLY_BAKERY_BUDGET_CENTS": 100000,
    "SERVICE_DATE": "2026-09-02T00:00:00Z",
}


def create_restaurant_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RESTAURANT_NAME"],
        "code": DEFAULTS["RESTAURANT_CODE"],
        "weekly_bakery_budget_cents": DEFAULTS["WEEKLY_BAKERY_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_menu_revision_payload(restaurant_id, **overrides) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "label": "2026-Fall",
        "effective_from": "2026-09-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_recipe_payload(menu_revision_id, **overrides) -> dict:
    defaults = {
        "menu_revision_id": menu_revision_id,
        "name": "Steak",
        "station_type": "GRILL",
    }
    defaults.update(overrides)
    return defaults


def create_prep_item_payload(**overrides) -> dict:
    defaults = {
        "name": "Diced Onions",
        "station_type": "SAUTE",
        "shelf_life_hours": 48,
        "min_batch_size": 10,
        "batch_unit": "OZ",
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(restaurant_id, **overrides) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "name": "Grill 1",
        "station_type": "GRILL",
        "rack_slot_capacity": 100,
    }
    defaults.update(overrides)
    return defaults


def create_station_par_payload(station_id, prep_item_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "prep_item_id": prep_item_id,
        "par_quantity": 20,
    }
    defaults.update(overrides)
    return defaults


def create_cook_payload(restaurant_id, **overrides) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "name": "Chris Cook",
        "certified_station_types": ["GRILL"],
    }
    defaults.update(overrides)
    return defaults


def create_demand_forecast_payload(restaurant_id, **overrides) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
        "expected_covers": 100,
        "item_mix": [],
    }
    defaults.update(overrides)
    return defaults


def create_prep_list_payload(restaurant_id, demand_forecast_id, **overrides) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "demand_forecast_id": demand_forecast_id,
    }
    defaults.update(overrides)
    return defaults


def create_prep_batch_payload(prep_list_id, prep_item_id, station_id,
                              **overrides) -> dict:
    defaults = {
        "prep_list_id": prep_list_id,
        "prep_item_id": prep_item_id,
        "station_id": station_id,
        "quantity": 20,
    }
    defaults.update(overrides)
    return defaults


def create_shift_assignment_payload(cook_id, station_id, **overrides) -> dict:
    defaults = {
        "cook_id": cook_id,
        "station_id": station_id,
        "shift_start": "2026-09-02T08:00:00Z",
        "shift_end": "2026-09-02T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bakery_order_payload(restaurant_id, **overrides) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "cheesecake_type": "ORIGINAL",
        "whole_cakes_ordered": 10,
    }
    defaults.update(overrides)
    return defaults


def create_waste_entry_payload(station_id, prep_batch_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "prep_batch_id": prep_batch_id,
        "quantity": 5,
        "reason": "OVER_PREP",
    }
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(restaurant_id, items, **overrides) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "table_ref": "T1",
        "items": items,
    }
    defaults.update(overrides)
    return defaults

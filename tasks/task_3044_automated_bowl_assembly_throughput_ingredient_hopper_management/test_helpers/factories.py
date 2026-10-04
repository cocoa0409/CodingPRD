"""Payload factories — one per creatable resource, input fields only."""

import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_restaurant_payload(**overrides) -> dict:
    payload = {"name": f"Restaurant {_seq()}", "city": "Los Angeles"}
    payload.update(overrides)
    return payload


def create_assembly_line_payload(restaurant_id, **overrides) -> dict:
    payload = {
        "restaurant_id": restaurant_id,
        "name": f"Auto Line {_seq()}",
        "line_type": "AUTOMATED",
        "service_rate_seconds_per_bowl": 45,
    }
    payload.update(overrides)
    return payload


def create_ingredient_payload(**overrides) -> dict:
    n = _seq()
    payload = {
        "sku": f"SKU-{n:04d}",
        "name": f"Ingredient {n}",
        "station_type": "BASE",
        "shelf_life_minutes": 240,
    }
    payload.update(overrides)
    return payload


def create_recipe_payload(restaurant_id, portion_spec, **overrides) -> dict:
    payload = {
        "restaurant_id": restaurant_id,
        "name": f"Harvest Bowl {_seq()}",
        "base_complexity": 0,
        "portion_spec": portion_spec,
    }
    payload.update(overrides)
    return payload


def create_hopper_payload(line_id, ingredient_id, **overrides) -> dict:
    payload = {
        "line_id": line_id,
        "ingredient_id": ingredient_id,
        "capacity_grams": 2000,
        "station_slot": 0,
        "calibration_coefficient": 1.0,
    }
    payload.update(overrides)
    return payload


def load_hopper_payload(load_grams, expected_hopper_version, **overrides) -> dict:
    payload = {
        "load_grams": load_grams,
        "expected_hopper_version": expected_hopper_version,
    }
    payload.update(overrides)
    return payload


def sensor_reading_payload(grams_reading) -> dict:
    return {"grams_reading": grams_reading}


def calibration_adjustment_payload(new_coefficient) -> dict:
    return {"new_coefficient": new_coefficient}


def create_refill_task_payload(hopper_id, mode="STANDARD", **overrides) -> dict:
    payload = {"hopper_id": hopper_id, "mode": mode}
    payload.update(overrides)
    return payload


def create_prep_batch_payload(restaurant_id, ingredient_id, **overrides) -> dict:
    payload = {
        "restaurant_id": restaurant_id,
        "ingredient_id": ingredient_id,
        "quantity_grams": 1000,
    }
    payload.update(overrides)
    return payload


def create_order_payload(restaurant_id, recipe_id, expected_recipe_version, **overrides) -> dict:
    payload = {
        "restaurant_id": restaurant_id,
        "recipe_id": recipe_id,
        "expected_recipe_version": expected_recipe_version,
    }
    payload.update(overrides)
    return payload


def submit_verification_payload(measurements) -> dict:
    return {"measurements": measurements}


def reroute_order_payload(target_route, **overrides) -> dict:
    payload = {"target_route": target_route}
    payload.update(overrides)
    return payload


def create_substitution_rule_payload(
    restaurant_id, from_ingredient_id, to_ingredient_id, effective_start, effective_end,
    **overrides,
) -> dict:
    payload = {
        "restaurant_id": restaurant_id,
        "from_ingredient_id": from_ingredient_id,
        "to_ingredient_id": to_ingredient_id,
        "effective_start": effective_start,
        "effective_end": effective_end,
    }
    payload.update(overrides)
    return payload


def create_sanitation_cycle_payload(line_id, scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "line_id": line_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_labor_assignment_payload(
    restaurant_id, staff_user_id, window_start, window_end, **overrides
) -> dict:
    payload = {
        "restaurant_id": restaurant_id,
        "staff_user_id": staff_user_id,
        "from_role": "MAKE_LINE",
        "to_role": "PREP",
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload

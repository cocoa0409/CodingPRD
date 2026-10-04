"""Composite setup helpers that walk the public API to a wanted state.

Every test runs against a freshly restarted server with an empty database, so
each helper builds its preconditions through PRD-declared endpoints only.
Setup calls use the lenient success reader so a failure surfaces as a clear
setup error rather than an assertion error.

Station-slot geometry (PRD §2.11): slot 0 = BASE, slot 1 = PROTEIN,
slots 2-5 = TOPPING, slot 6 = DRESSING.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .constants import TEST_DEFAULTS
from .test_users import (
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    QUALITY_LEAD_HEADERS,
    SHIFT_MANAGER_HEADERS,
    make_line_operator_headers,
)

BASE_CLOCK = TEST_DEFAULTS["CLOCK_DEFAULT"]


# ═══ Tier 1: basic resource creation ═══════════════════════════════════════


def set_clock(api: ApiClient, to_iso8601: str = BASE_CLOCK) -> Dict[str, Any]:
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), OPS_ADMIN_HEADERS))


def create_restaurant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_restaurant(f.create_restaurant_payload(**overrides), OPS_ADMIN_HEADERS))


def create_line(api: ApiClient, restaurant_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_assembly_line(f.create_assembly_line_payload(restaurant_id, **overrides), OPS_ADMIN_HEADERS)
    )


def create_ingredient(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_ingredient(f.create_ingredient_payload(**overrides), OPS_ADMIN_HEADERS))


def create_recipe(api: ApiClient, restaurant_id: str, portion_spec, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_recipe(f.create_recipe_payload(restaurant_id, portion_spec, **overrides), OPS_ADMIN_HEADERS)
    )


def create_hopper(api: ApiClient, line_id: str, ingredient_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_hopper(f.create_hopper_payload(line_id, ingredient_id, **overrides), OPS_ADMIN_HEADERS)
    )


def load_hopper(api: ApiClient, hopper: Dict[str, Any], load_grams, headers=None) -> Dict[str, Any]:
    """Load a hopper, OCC-checking against its current version."""
    return get_success_data(
        api.load_hopper(
            hopper["id"],
            f.load_hopper_payload(load_grams, hopper["version"]),
            headers or LINE_OPERATOR_HEADERS,
        )
    )


def read_hopper(api: ApiClient, hopper_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_hopper(hopper_id, headers or LINE_OPERATOR_HEADERS))


def read_line(api: ApiClient, line_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_assembly_line(line_id, headers or SHIFT_MANAGER_HEADERS))


def read_order(api: ApiClient, order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, headers or CUSTOMER_HEADERS))


def read_recipe(api: ApiClient, recipe_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_recipe(recipe_id, headers or CUSTOMER_HEADERS))


def read_batch(api: ApiClient, batch_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_prep_batch(batch_id, headers or PREP_COOK_HEADERS))


def create_prep_batch_ready(
    api: ApiClient, restaurant_id: str, ingredient_id: str, quantity_grams=1000
) -> Dict[str, Any]:
    """Register a prep batch and mark it READY (runs the allocation waterfall)."""
    batch = get_success_data(
        api.create_prep_batch(
            f.create_prep_batch_payload(restaurant_id, ingredient_id, quantity_grams=quantity_grams),
            PREP_COOK_HEADERS,
        )
    )
    return get_success_data(api.mark_prep_batch_ready(batch["id"], PREP_COOK_HEADERS))


# ═══ Tier 2: store-with-loaded-hopper composite ════════════════════════════


def setup_store_with_hopper(
    api: ApiClient,
    clock: str = BASE_CLOCK,
    line_type: str = "AUTOMATED",
    service_rate: int = 45,
    capacity_grams=2000,
    load_grams=1000,
    coefficient=1.0,
    target_grams=100,
    station_type: str = "BASE",
    station_slot: int = 0,
    shelf_life_minutes: int = 240,
    add_manual_line: bool = False,
    manual_rate: int = 120,
) -> Dict[str, Any]:
    """Clock pinned, restaurant, one line, one ingredient, a recipe with a
    single portion, and a hopper loaded to ``load_grams`` (IN_SERVICE)."""
    set_clock(api, clock)
    restaurant = create_restaurant(api)
    line = create_line(
        api, restaurant["id"], line_type=line_type, service_rate_seconds_per_bowl=service_rate
    )
    manual_line = None
    if add_manual_line:
        manual_line = create_line(
            api,
            restaurant["id"],
            name="Manual Line",
            line_type="MANUAL",
            service_rate_seconds_per_bowl=manual_rate,
        )
    ingredient = create_ingredient(api, station_type=station_type, shelf_life_minutes=shelf_life_minutes)
    recipe = create_recipe(
        api, restaurant["id"], [{"ingredient_id": ingredient["id"], "target_grams": target_grams}]
    )
    hopper = create_hopper(
        api,
        line["id"],
        ingredient["id"],
        capacity_grams=capacity_grams,
        station_slot=station_slot,
        calibration_coefficient=coefficient,
    )
    hopper = load_hopper(api, hopper, load_grams)
    return {
        "restaurant": restaurant,
        "line": line,
        "manual_line": manual_line,
        "ingredient": ingredient,
        "recipe": recipe,
        "hopper": hopper,
    }


def place_order(
    api: ApiClient,
    restaurant_id: str,
    recipe: Dict[str, Any],
    customizations=None,
    headers=None,
) -> Dict[str, Any]:
    """Place an order with the recipe's current version (OCC)."""
    payload = f.create_order_payload(restaurant_id, recipe["id"], recipe["version"])
    if customizations is not None:
        payload["customizations"] = customizations
    return get_success_data(api.create_order(payload, headers or CUSTOMER_HEADERS))


def assemble_and_verify(
    api: ApiClient,
    order_id: str,
    hopper_id: str,
    actual_grams,
    operator_id: str = "op_verifier_1",
) -> Dict[str, Any]:
    """Start assembly and submit a single-hopper measurement; returns the order."""
    headers = make_line_operator_headers(operator_id)
    get_success_data(api.start_order_assembly(order_id, headers))
    return get_success_data(
        api.submit_order_verification(
            order_id, f.submit_verification_payload([{"hopper_id": hopper_id, "actual_grams": actual_grams}]),
            headers,
        )
    )


# ═══ Tier 3: drift / quarantine accumulation ═══════════════════════════════


def drive_hopper_to_quarantine(
    api: ApiClient,
    restaurant_id: str,
    recipe: Dict[str, Any],
    hopper: Dict[str, Any],
    actual_grams=104.0,
    samples: int = 3,
    operator_id: str = "op_verifier_1",
) -> Dict[str, Any]:
    """Complete ``samples`` orders each verified at ``actual_grams`` so the
    hopper's drift crosses the quarantine threshold; returns the re-read hopper."""
    for _ in range(samples):
        order = place_order(api, restaurant_id, recipe)
        assemble_and_verify(api, order["id"], hopper["id"], actual_grams, operator_id)
    return read_hopper(api, hopper["id"])


# ═══ Tier 4: depletion cascade / refill pipeline ═══════════════════════════


def deplete_hopper(
    api: ApiClient, hopper_id: str, grams_reading, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.report_sensor_reading(
            hopper_id, f.sensor_reading_payload(grams_reading), headers or LINE_OPERATOR_HEADERS
        )
    )


def latest_refill_task(api: ApiClient, hopper_id: str, headers=None) -> Dict[str, Any]:
    data = get_success_data(
        api.list_hopper_refill_tasks(hopper_id, headers or LINE_OPERATOR_HEADERS)
    )
    assert data, "expected at least one refill task for the hopper"
    return data[0]


def deplete_and_get_refill_task(
    api: ApiClient, hopper_id: str, grams_reading, headers=None
) -> Dict[str, Any]:
    """Drive a hopper DEPLETED via sensor reading and return its auto-created task."""
    deplete_hopper(api, hopper_id, grams_reading, headers)
    return latest_refill_task(api, hopper_id, headers)

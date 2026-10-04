"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment, so each test has to build the
world it needs from scratch. These helpers do that walking through the public
API only — no direct data writes — and return the identifiers, headers and
observed versions the test then asserts against.

They are organised from the simplest to the most far-reaching:

  Tier 1  advancing the clock and creating individual resources
  Tier 2  building the store / ingredient / batch / menu hierarchy
  Tier 3  staffing deployments through publish and lock
  Tier 4  orders driven through their lifecycle to a chosen state
  Tier 5  day close and post-close probes

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .constants import (
    CHANNEL_IN_STORE,
    ROLE_GENERAL_MANAGER,
    ROLE_LINE_WORKER,
    ROLE_STORE_MANAGER,
)
from .test_users import (
    GENERAL_MANAGER_HEADERS,
    LINE_WORKER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    STORE_MANAGER_HEADERS,
    build_user_headers,
)

# The instant the clock reports on a fresh deployment.
BASE_CLOCK = "2026-09-01T00:00:00Z"

# A convenient mid-morning instant most scenarios anchor on.
MORNING = "2026-09-01T10:00:00Z"

# The ISO date that corresponds to the mid-morning anchor.
BUSINESS_DAY = "2026-09-01"


# ═══ Tier 1: clock and single-resource creation ════════════════════════════

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(
        api.set_clock(f.clock_payload(current_utc), PLATFORM_ADMIN_HEADERS)
    )


def create_store(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_store(f.store_payload(**overrides), PLATFORM_ADMIN_HEADERS))


def read_store(api: ApiClient, store_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_store(store_id, STORE_MANAGER_HEADERS))


def create_ingredient(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_ingredient(f.ingredient_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def read_ingredient(api: ApiClient, ingredient_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_ingredient(ingredient_id, STORE_MANAGER_HEADERS))


def cook_batch(
    api: ApiClient, ingredient_id: str, store_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_batch(
            ingredient_id, f.batch_payload(store_id, **overrides), STORE_MANAGER_HEADERS
        )
    )


def read_batch(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_batch(batch_id, STORE_MANAGER_HEADERS))


def create_menu_item(api: ApiClient, store_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_menu_item(store_id, f.menu_item_payload(**overrides), STORE_MANAGER_HEADERS)
    )


def read_menu_item(api: ApiClient, menu_item_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_menu_item(menu_item_id, STORE_MANAGER_HEADERS))


def add_recipe_component(
    api: ApiClient, menu_item_id: str, ingredient_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_recipe_component(
            menu_item_id,
            f.recipe_component_payload(ingredient_id, **overrides),
            STORE_MANAGER_HEADERS,
        )
    )


def create_marketplace_channel(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_marketplace_channel(
            f.marketplace_channel_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def open_window(
    api: ApiClient,
    store_id: str,
    interval_start: str = "2026-09-01T10:15:00Z",
    interval_end: str = "2026-09-01T10:30:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_production_window(
            store_id,
            f.production_window_payload(interval_start=interval_start, interval_end=interval_end),
            STORE_MANAGER_HEADERS,
        )
    )


def read_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_production_window(window_id, STORE_MANAGER_HEADERS))


def read_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, STORE_MANAGER_HEADERS))


# ═══ Tier 2: store with menu, stock and a window ═══════════════════════════

def store_with_bowl(
    api: ApiClient,
    *,
    chicken_grams: int = 10000,
    chicken_par: int = 5000,
    chicken_hold_minutes: int = 240,
    chicken_unit_cost: float = 2.1,
    bowl_standard_grams: int = 120,
    bowl_price_cents: int = 1095,
    with_window: bool = True,
    window_start: str = "2026-09-01T10:15:00Z",
    window_end: str = "2026-09-01T10:30:00Z",
    store_overrides: Optional[Dict[str, Any]] = None,
    cooked_at: str = "2026-09-01T09:00:00Z",
) -> Dict[str, Any]:
    """A store with one chicken ingredient, one cooked batch, one BOWL menu item
    carrying a single chicken recipe component, and (optionally) one open
    production window. Returns the identifiers a test asserts against."""
    store = create_store(api, **(store_overrides or {}))
    ingredient = create_ingredient(
        api,
        par_level_grams=chicken_par,
        hold_time_minutes=chicken_hold_minutes,
        unit_cost_cents_per_gram=chicken_unit_cost,
    )
    batch = cook_batch(
        api, ingredient["id"], store["id"], cooked_at=cooked_at, grams_cooked=chicken_grams
    )
    item = create_menu_item(api, store["id"], base_price_cents=bowl_price_cents)
    add_recipe_component(api, item["id"], ingredient["id"], standard_grams=bowl_standard_grams)
    window = open_window(api, store["id"], window_start, window_end) if with_window else None
    return {
        "store": store,
        "store_id": store["id"],
        "store_version": store["version"],
        "ingredient": ingredient,
        "ingredient_id": ingredient["id"],
        "batch": batch,
        "batch_id": batch["id"],
        "item": item,
        "item_id": item["id"],
        "window": window,
        "window_id": window["id"] if window else None,
    }


# ═══ Tier 3: staffing deployments ══════════════════════════════════════════

def create_deployment(
    api: ApiClient,
    store_id: str,
    expected_store_version: int,
    shift_date: str = BUSINESS_DAY,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_deployment(
            store_id,
            f.deployment_payload(shift_date, expected_store_version, **overrides),
            STORE_MANAGER_HEADERS,
        )
    )


def publish_deployment(
    api: ApiClient, store_id: str, deployment_id: str, publisher_id: str = "sm-pat"
) -> Dict[str, Any]:
    return get_success_data(
        api.publish_deployment(
            store_id, deployment_id, build_user_headers(publisher_id, ROLE_STORE_MANAGER)
        )
    )


def lock_deployment(
    api: ApiClient, store_id: str, deployment_id: str, locker_id: str = "gm-quinn"
) -> Dict[str, Any]:
    return get_success_data(
        api.lock_deployment(
            store_id, deployment_id, build_user_headers(locker_id, ROLE_GENERAL_MANAGER)
        )
    )


def locked_deployment(
    api: ApiClient,
    store_id: str,
    expected_store_version: int,
    shift_date: str = BUSINESS_DAY,
    publisher_id: str = "sm-pat",
    locker_id: str = "gm-quinn",
    **overrides: Any,
) -> Dict[str, Any]:
    """A staffing deployment carried all the way to LOCKED for ``shift_date``."""
    deployment = create_deployment(
        api, store_id, expected_store_version, shift_date=shift_date, **overrides
    )
    publish_deployment(api, store_id, deployment["id"], publisher_id)
    return lock_deployment(api, store_id, deployment["id"], locker_id)


def store_with_locked_deployment(
    api: ApiClient, *, shift_date: str = BUSINESS_DAY, **kwargs: Any
) -> Dict[str, Any]:
    """A stocked store with a window AND a locked deployment, ready for an order
    to be worked through production."""
    world = store_with_bowl(api, **kwargs)
    deployment = locked_deployment(
        api, world["store_id"], world["store_version"], shift_date=shift_date
    )
    world["deployment"] = deployment
    world["deployment_id"] = deployment["id"]
    return world


# ═══ Tier 4: orders driven through their lifecycle ═════════════════════════

def place_order(
    api: ApiClient,
    store_id: str,
    menu_item_id: str,
    *,
    channel: str = CHANNEL_IN_STORE,
    quantity: int = 1,
    headers: Optional[Dict[str, str]] = None,
    customizations: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Place an order that is expected to be accepted; returns the order."""
    if headers is None:
        headers = (
            LINE_WORKER_HEADERS if channel == CHANNEL_IN_STORE else STORE_MANAGER_HEADERS
        )
    lines = [
        f.order_line_payload(
            menu_item_id,
            quantity=quantity,
            customizations=customizations if customizations is not None else [],
        )
    ]
    return get_success_data(
        api.create_order(store_id, f.order_payload(channel, lines, **overrides), headers)
    )


def start_production(
    api: ApiClient, store_id: str, order_id: str, worker_id: str = "lw-1"
) -> Dict[str, Any]:
    return get_success_data(
        api.start_production(store_id, order_id, build_user_headers(worker_id, ROLE_LINE_WORKER))
    )


def verify_pass(
    api: ApiClient, store_id: str, order_id: str, menu_item_id: str, worker_id: str = "lw-1"
) -> Dict[str, Any]:
    """A verification pass in which every line matches."""
    return get_success_data(
        api.verify_accuracy(
            store_id,
            order_id,
            f.verification_payload([f.line_result(menu_item_id, True)]),
            build_user_headers(worker_id, ROLE_LINE_WORKER),
        )
    )


def verify_fail(
    api: ApiClient, store_id: str, order_id: str, menu_item_id: str, worker_id: str = "lw-1"
) -> Dict[str, Any]:
    """A verification pass in which every line mismatches."""
    return get_success_data(
        api.verify_accuracy(
            store_id,
            order_id,
            f.verification_payload([f.line_result(menu_item_id, False)]),
            build_user_headers(worker_id, ROLE_LINE_WORKER),
        )
    )


def mark_ready(
    api: ApiClient, store_id: str, order_id: str, worker_id: str = "lw-1"
) -> Dict[str, Any]:
    return get_success_data(
        api.mark_ready(store_id, order_id, build_user_headers(worker_id, ROLE_LINE_WORKER))
    )


def pickup(
    api: ApiClient, store_id: str, order_id: str, worker_id: str = "lw-1"
) -> Dict[str, Any]:
    return get_success_data(
        api.pickup_order(store_id, order_id, build_user_headers(worker_id, ROLE_LINE_WORKER))
    )


def cancel(api: ApiClient, store_id: str, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.cancel_order(store_id, order_id, STORE_MANAGER_HEADERS))


def order_in_production(
    api: ApiClient, world: Dict[str, Any], *, channel: str = CHANNEL_IN_STORE, quantity: int = 1
) -> Dict[str, Any]:
    """An order accepted and started, sitting IN_PRODUCTION with payment captured."""
    order = place_order(
        api, world["store_id"], world["item_id"], channel=channel, quantity=quantity
    )
    started = start_production(api, world["store_id"], order["id"])
    return started


def order_ready(
    api: ApiClient, world: Dict[str, Any], *, channel: str = CHANNEL_IN_STORE, quantity: int = 1
) -> Dict[str, Any]:
    """An order worked to READY: started, verified PASS, marked ready."""
    order = order_in_production(api, world, channel=channel, quantity=quantity)
    verify_pass(api, world["store_id"], order["id"], world["item_id"])
    return mark_ready(api, world["store_id"], order["id"])


def order_picked_up(
    api: ApiClient, world: Dict[str, Any], *, channel: str = CHANNEL_IN_STORE, quantity: int = 1
) -> Dict[str, Any]:
    """An order carried all the way to PICKED_UP."""
    order = order_ready(api, world, channel=channel, quantity=quantity)
    return pickup(api, world["store_id"], order["id"])


# ═══ Tier 5: waste and day close ═══════════════════════════════════════════

def record_waste(
    api: ApiClient,
    store_id: str,
    ingredient_batch_id: str,
    grams: int,
    reason: str,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_waste_event(
            store_id,
            f.waste_event_payload(ingredient_batch_id, grams, reason),
            LINE_WORKER_HEADERS,
        )
    )


def current_store_version(api: ApiClient, store_id: str) -> int:
    return read_store(api, store_id)["version"]


def close_day(
    api: ApiClient, store_id: str, closer_id: str = "gm-quinn"
) -> Dict[str, Any]:
    """Close the business day with the store's live version; returns the DayClose."""
    version = current_store_version(api, store_id)
    return get_success_data(
        api.close_day(
            store_id,
            f.day_close_payload(version),
            build_user_headers(closer_id, ROLE_GENERAL_MANAGER),
        )
    )


def read_day_close(api: ApiClient, day_close_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_day_close(day_close_id, GENERAL_MANAGER_HEADERS))

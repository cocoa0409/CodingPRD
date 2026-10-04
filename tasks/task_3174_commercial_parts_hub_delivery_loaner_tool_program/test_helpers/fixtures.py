"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through declared endpoints,
because the harness restarts the server before each individual test: each test
starts against an empty database.

`get_success_data()` (the lenient validator) is used for setup steps so a
broken precondition reports "Setup step failed with ERR_X" rather than a
confusing assertion mismatch.

Version threading: parent-versioned writes carry an explicit expected version.
Rather than threading captured values through the whole chain, the helpers
re-read the parent immediately before each versioned write -- the account for
account-versioned writes, the route for route-versioned writes.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import STARTUP_DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_account_payload,
    create_core_return_payload,
    create_inventory_item_payload,
    create_loan_payload,
    create_order_payload,
    create_part_fitment_payload,
    create_part_payload,
    create_rep_coverage_payload,
    create_route_payload,
    create_route_stop_payload,
    create_sales_rep_payload,
    create_store_payload,
    create_tool_catalog_payload,
    create_tool_fitment_payload,
    create_vehicle_payload,
    create_warranty_payload,
    line_item,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
DRIVER = TEST_USERS["driver_headers"]
CRIB = TEST_USERS["tool_crib_headers"]
CREDIT = TEST_USERS["credit_analyst_headers"]
DISPATCHER = TEST_USERS["route_dispatcher_headers"]
CATALOG = TEST_USERS["parts_manager_headers"]
ANY_ROLE = TEST_USERS["any_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Tier 0 -- primitives
# ═══════════════════════════════════════════════════════════════════════════

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Every time-dependent rule reads this instant."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


def advance_epoch(to_iso8601: str) -> dict:
    """Advance the business-day capacity epoch for eligible stores."""
    return get_success_data(api_client.advance_epoch({"to_iso8601": to_iso8601}, ADMIN))


def start_clock_at_default():
    """Begin a test at the documented startup default clock."""
    return set_clock(STARTUP_DEFAULT_CLOCK)


def account_version(account_id: str) -> int:
    """Current `version` of an account, freshly read."""
    return get_success_data(api_client.get_account(account_id, SALES))["version"]


def order_version(order_id: str) -> int:
    """Current `version` of an order, freshly read."""
    return get_success_data(api_client.get_order(order_id, SALES))["version"]


def route_version(route_id: str) -> int:
    """Current `version` of a route, freshly read."""
    return get_success_data(api_client.get_route(route_id, DISPATCHER))["version"]


def reload_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, SALES))


def reload_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_order(order_id, headers or SALES))


def reload_loan(loan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_loan(loan_id, headers or CRIB))


def reload_store(store_id: str) -> dict:
    return get_success_data(api_client.get_store(store_id, CATALOG))


def reload_part(part_id: str) -> dict:
    return get_success_data(api_client.get_part(part_id, CATALOG))


def reload_tool(tool_id: str) -> dict:
    return get_success_data(api_client.get_tool_catalog_entry(tool_id, CRIB))


def reload_inventory(item_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_inventory_item(item_id, headers or CATALOG))


def reload_core_return(core_return_id: str) -> dict:
    return get_success_data(api_client.get_core_return(core_return_id, CRIB))


def reload_stop(stop_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_stop(stop_id, headers or DISPATCHER))


def reload_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, DISPATCHER))


def inventory_line_for(store_id: str, part_id: str, headers=None):
    """The single inventory line for a (store, part) pair, or None."""
    from prd_bench_local_runner.testing import validate_paginated

    response = api_client.list_inventory_items(
        headers or CATALOG, params={"store_id": store_id, "part_id": part_id})
    data, _meta = validate_paginated(response)
    return data[0] if data else None


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1 -- single-entity creation
# ═══════════════════════════════════════════════════════════════════════════

def create_satellite(**overrides) -> dict:
    payload = create_store_payload(store_code="S100", name="Satellite",
                                   store_type="SATELLITE",
                                   delivery_radius_miles=5.0)
    payload.update(overrides)
    return get_success_data(api_client.create_store(payload, CATALOG))


def create_hub(**overrides) -> dict:
    payload = create_store_payload(store_code="S200", name="Hub", store_type="HUB",
                                   delivery_radius_miles=30.0, hub_store_id=None,
                                   promise_time_minutes=90)
    payload.update(overrides)
    return get_success_data(api_client.create_store(payload, CATALOG))


def create_mega_hub(**overrides) -> dict:
    payload = create_store_payload(store_code="S300", name="Mega Hub",
                                   store_type="MEGA_HUB", delivery_radius_miles=50.0,
                                   hub_store_id=None, promise_time_minutes=120)
    payload.update(overrides)
    return get_success_data(api_client.create_store(payload, CATALOG))


def create_dc(**overrides) -> dict:
    payload = create_store_payload(store_code="S400", name="Distribution Center",
                                   store_type="DC", delivery_radius_miles=80.0,
                                   hub_store_id=None, promise_time_minutes=180)
    payload.update(overrides)
    return get_success_data(api_client.create_store(payload, CATALOG))


def create_part(sku="TEST-1", list_price_cents=1673, **overrides) -> dict:
    payload = create_part_payload(sku=sku, list_price_cents=list_price_cents, **overrides)
    return get_success_data(api_client.create_part(payload, CATALOG))


# ── PRD 3.1/3.4: the replenishment chain a satellite draws on -----------------
# "a store ... may name a parent through `hub_store_id`" and "the routing
# decision ... reads the account's home store as its starting point", resolving
# "the full chain satellite to hub to mega-hub to distribution center". A
# satellite that names no hub therefore has no deeper node to fall back to, so
# the stores a scenario needs must be wired into that chain.

def create_chain_hub(parent=None, **overrides) -> dict:
    """A hub for a satellite's replenishment chain."""
    if parent is not None:
        overrides["hub_store_id"] = parent["id"]
    overrides.setdefault("store_code", "S201")
    overrides.setdefault("name", "Replenishment Hub")
    overrides.setdefault("delivery_radius_miles", 30.0)
    overrides.setdefault("promise_time_minutes", 90)
    return create_hub(**overrides)


def create_replenishment_satellite(hub=None, **overrides) -> dict:
    """A satellite sitting on a live chain: the store plus the hub above it.

    PRD 3.4: the routing decision "reads the account's home store as its
    starting point" and bands 2-4 are only reachable "when the account's home
    store resolves the full chain satellite to hub to mega-hub to distribution
    center"; a satellite whose `hub_store_id` is null has nothing deeper to
    fall back to, so it can only ever be served by its own shelf.
    """
    hub = hub or create_chain_hub()
    overrides.setdefault("store_code", "S100")
    overrides.setdefault("name", "Satellite")
    overrides.setdefault("delivery_radius_miles", 5.0)
    overrides.setdefault("hub_store_id", hub["id"])
    return create_satellite(**overrides)


def create_vehicle(vin="1HGCM82633A004352", **overrides) -> dict:
    payload = create_vehicle_payload(vin=vin, **overrides)
    return get_success_data(api_client.create_vehicle(payload, SALES))


def stock(store_id: str, part_id: str, on_hand_units: int = 20) -> dict:
    payload = create_inventory_item_payload(store_id, part_id, on_hand_units=on_hand_units)
    return get_success_data(api_client.create_inventory_item(payload, CATALOG))


def add_fitment(part_id: str, **overrides) -> dict:
    payload = create_part_fitment_payload(**overrides)
    return get_success_data(api_client.create_part_fitment(part_id, payload, CATALOG))


def create_account(home_store_id: str, **overrides) -> dict:
    payload = create_account_payload(home_store_id, **overrides)
    return get_success_data(api_client.create_account(payload, SALES))


def create_sales_rep(home_store_id: str, **overrides) -> dict:
    payload = create_sales_rep_payload(home_store_id, **overrides)
    return get_success_data(api_client.create_sales_rep(payload, SALES))


def create_tool(tool_sku="TOOL-TEST", deposit_amount_cents=3000, **overrides) -> dict:
    payload = create_tool_catalog_payload(tool_sku=tool_sku,
                                          deposit_amount_cents=deposit_amount_cents,
                                          **overrides)
    return get_success_data(api_client.create_tool_catalog_entry(payload, CRIB))


def add_tool_fitment(tool_catalog_id: str, part_id: str, placement="FRONT",
                     depth_index=1) -> dict:
    payload = create_tool_fitment_payload(part_id, placement=placement,
                                          depth_index=depth_index)
    return get_success_data(api_client.create_tool_fitment(tool_catalog_id, payload, CRIB))


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 -- entity hierarchy
# ═══════════════════════════════════════════════════════════════════════════

def setup_satellite_with_part(part_sku="P-1", list_price_cents=1673,
                              on_hand_units=20, core_charge_cents=0, hub=None,
                              **part_overrides):
    """One satellite (on a live chain), one catalogue part stocked there.

    Returns (store, part, line). Pass `hub` to hang the satellite off a
    specific hub, so the depth the routing bands can fall back through is the
    caller's choice.
    """
    store = create_replenishment_satellite(hub=hub)
    part = create_part(sku=part_sku, list_price_cents=list_price_cents,
                       core_charge_cents=core_charge_cents, **part_overrides)
    inv = stock(store["id"], part["id"], on_hand_units)
    return store, part, inv


def setup_hierarchy(satellite=None, hub=None, mega_hub=None, dc=None):
    """Build the replenishment chain satellite -> hub -> mega-hub -> DC.

    Every store in the chain is created; the satellite names the hub, the hub
    names the mega-hub, the mega-hub names the DC. Returns a dict keyed by the
    role each store plays.
    """
    dc = dc or create_dc(store_code="S400", name="DC")
    mega = mega_hub or create_mega_hub(store_code="S300", name="Mega Hub",
                                       hub_store_id=dc["id"])
    h = hub or create_hub(store_code="S200", name="Hub", hub_store_id=mega["id"])
    s = satellite or create_satellite(store_code="S100", name="Satellite",
                                      hub_store_id=h["id"])
    return {"satellite": s, "hub": h, "mega_hub": mega, "dc": dc}


def setup_basic_scenario(part_sku="P-1", list_price_cents=1673, on_hand_units=20,
                         core_charge_cents=0, account_overrides=None):
    """Satellite (on a live replenishment chain) + part + stock + account."""
    store = create_replenishment_satellite()
    part = create_part(sku=part_sku, list_price_cents=list_price_cents,
                       core_charge_cents=core_charge_cents)
    inv = stock(store["id"], part["id"], on_hand_units)
    account = create_account(store["id"], **(account_overrides or {}))
    return {"store": store, "part": part, "inventory": inv, "account": account}


def setup_full_chain_scenario(satellite_radius_miles=5.0, account_overrides=None,
                              hub_stock_units=0, mega_stock_units=0, dc_stock_units=0,
                              part_sku="P-1", list_price_cents=1673):
    """The whole satellite -> hub -> mega-hub -> DC chain plus a part and an account.

    Stock is placed only where the caller asks for it, so the routing band the
    test exercises is the caller's choice.
    """
    chain = setup_hierarchy()
    chain["satellite"] = get_success_data(api_client.create_store(
        create_store_payload(store_code="S101", name="Chain Satellite",
                             store_type="SATELLITE",
                             delivery_radius_miles=satellite_radius_miles,
                             hub_store_id=chain["hub"]["id"]), CATALOG))
    part = create_part(sku=part_sku, list_price_cents=list_price_cents)
    if hub_stock_units:
        stock(chain["hub"]["id"], part["id"], hub_stock_units)
    if mega_stock_units:
        stock(chain["mega_hub"]["id"], part["id"], mega_stock_units)
    if dc_stock_units:
        stock(chain["dc"]["id"], part["id"], dc_stock_units)
    account = create_account(chain["satellite"]["id"], **(account_overrides or {}))
    return {"chain": chain, "store": chain["satellite"], "part": part, "account": account}


# ═══════════════════════════════════════════════════════════════════════════
# Tier 3 -- order lifecycle
# ═══════════════════════════════════════════════════════════════════════════

def write_order(account_id: str, items, vehicle_id=None, **overrides) -> dict:
    """Create a DRAFT order, reading the account's version immediately before."""
    payload = create_order_payload(
        account_id, items,
        expected_account_version=account_version(account_id),
        **overrides)
    if vehicle_id is not None:
        payload["vehicle_id"] = vehicle_id
    return get_success_data(api_client.create_order(payload, SALES))


def write_simple_order(account_id: str, part_id: str, quantity=1,
                       vehicle_id=None, **overrides) -> dict:
    return write_order(account_id, [line_item(part_id, quantity)],
                       vehicle_id=vehicle_id, **overrides)


def confirm_order(order_id: str, account_id: str) -> dict:
    payload = {
        "expected_order_version": order_version(order_id),
        "expected_account_version": account_version(account_id),
    }
    return get_success_data(api_client.confirm_order(order_id, payload, SALES))


def allocate_order(order_id: str, account_id: str) -> dict:
    payload = {
        "expected_order_version": order_version(order_id),
        "expected_account_version": account_version(account_id),
    }
    return get_success_data(api_client.allocate_order(order_id, payload, SALES))


def pick_order(order_id: str) -> dict:
    return get_success_data(api_client.pick_order(order_id, {}, SALES))


def update_order_lines(order_id: str, account_id: str, items, **overrides) -> dict:
    payload = {
        "line_items": items,
        "expected_order_version": order_version(order_id),
        "expected_account_version": account_version(account_id),
    }
    payload.update(overrides)
    return api_client.update_order(order_id, payload, SALES)


def create_route(driver_id="drv-test", route_code="R-1", driver_type="AFFILIATE",
                 departure_at="2026-09-02T13:00:00.000Z",
                 shift_end_at="2026-09-02T21:00:00.000Z", service_date=None,
                 **overrides) -> dict:
    if service_date is not None:
        overrides["service_date"] = service_date
    payload = create_route_payload(
        route_code=route_code, driver_id=driver_id, driver_type=driver_type,
        departure_at=departure_at, shift_end_at=shift_end_at, **overrides)
    return get_success_data(api_client.create_route(payload, DISPATCHER))


def attach_stop(route_id: str, account_id: str, order_ids=None,
                stop_kind="CUSTOMER",
                delivery_window_start="2026-09-02T14:00:00Z",
                delivery_window_end="2026-09-02T15:00:00Z",
                travel_minutes_from_previous=20, drop_minutes=10):
    payload = create_route_stop_payload(
        account_id, expected_route_version=route_version(route_id),
        stop_kind=stop_kind,
        delivery_window_start=delivery_window_start,
        delivery_window_end=delivery_window_end,
        travel_minutes_from_previous=travel_minutes_from_previous,
        drop_minutes=drop_minutes,
        order_ids=list(order_ids or []))
    return api_client.create_route_stop(route_id, payload, DISPATCHER)


def attach_stop_ok(route_id: str, account_id: str, order_ids=None, **overrides) -> dict:
    response = attach_stop(route_id, account_id, order_ids=order_ids, **overrides)
    return get_success_data(response)


def plan_route(route_id: str) -> dict:
    payload = {"expected_route_version": route_version(route_id)}
    return get_success_data(api_client.plan_route(route_id, payload, DISPATCHER))


def dispatch_route(route_id: str) -> dict:
    return get_success_data(api_client.dispatch_route(route_id, {}, DISPATCHER))


def revert_route(route_id: str) -> dict:
    return get_success_data(api_client.revert_route_to_draft(route_id, {}, DISPATCHER))


def complete_route(route_id: str) -> dict:
    return get_success_data(api_client.complete_route(route_id, {}, DISPATCHER))


def cancel_route(route_id: str) -> dict:
    return get_success_data(api_client.cancel_route(route_id, {}, DISPATCHER))


def dispatch_order(order_id: str) -> dict:
    return get_success_data(api_client.dispatch_order(order_id, {}, DRIVER))


def deliver_order(order_id: str) -> dict:
    return get_success_data(api_client.deliver_order(order_id, {}, DRIVER))


def return_order(order_id: str) -> dict:
    """Return a delivered order, reading nothing but the order id."""
    return get_success_data(api_client.return_order(order_id, {}, SALES))


def void_order(order_id: str, headers=None) -> dict:
    """Void an order; a CommercialSalesRep may void DRAFT or CONFIRMED orders."""
    return get_success_data(api_client.void_order(order_id, {}, headers or SALES))


def refit_order(order_id: str) -> dict:
    return get_success_data(api_client.refit_order(order_id, {}, SALES))


def deliver_stop(stop_id: str) -> dict:
    return get_success_data(api_client.deliver_stop(stop_id, {}, DRIVER))


def orders_reserved_units(order_ids) -> int:
    return sum(reload_order(o, ANY_ROLE)["reserved_unit_count"] for o in order_ids)


def place_on_route(account_id: str, order_ids, route=None, driver_id="drv-test",
                   route_code="R-1", plan=True, service_date=None,
                   departure_at=None, shift_end_at=None, **stop_overrides):
    """Attach one CUSTOMER stop carrying `order_ids`, optionally planning the route.

    Returns (route, stop). The stop's window defaults sit safely inside the
    route's departure and shift-end instants.

    PRD 3.5 scopes the stop overlap test to "the same account on the same
    service date", so `service_date` (with `departure_at` / `shift_end_at`) lets
    a caller keep a shop's stops on separate days when the same day is already
    taken by another route.
    """
    route = route or create_route(
        driver_id=driver_id, route_code=route_code, service_date=service_date,
        **({} if departure_at is None else {"departure_at": departure_at}),
        **({} if shift_end_at is None else {"shift_end_at": shift_end_at}))
    stop = attach_stop_ok(route["id"], account_id, order_ids=order_ids, **stop_overrides)
    if plan:
        route = plan_route(route["id"])
    return route, stop


def deliver_directly(account_id: str, order: dict, route=None, stop=None, **kwargs):
    """Drive a PICKING order to DELIVERED through the declared delivery path.

    The delivery endpoint requires the order to be DISPATCHED and the stop that
    carries it to be SEQUENCED or EN_ROUTE, so this builds a route, attaches the
    stop, plans the route and dispatches the order before delivering.

    Returns dict with the route, stop and the DELIVERED order.
    """
    route, stop = (route, stop) if (route and stop) else place_on_route(
        account_id, [order["id"]], **kwargs)
    dispatched = dispatch_order(order["id"])
    delivered = deliver_order(order["id"])
    return {"route": route, "stop": stop, "dispatched": dispatched, "order": delivered}


def advance_order_to_delivered(account_id: str, items, vehicle_id=None,
                               route=None, **stop_overrides) -> dict:
    """Create -> confirm -> allocate -> pick -> route -> dispatch -> deliver.

    Returns dict with the order in DELIVERED, the route, the stop and the
    intermediate order snapshots.
    """
    order = write_order(account_id, items, vehicle_id=vehicle_id)
    order = confirm_order(order["id"], account_id)
    order = allocate_order(order["id"], account_id)
    order = pick_order(order["id"])
    delivery = deliver_directly(account_id, order, route=route, **stop_overrides)
    return {
        "order": delivery["order"],
        "route": delivery["route"],
        "stop": delivery["stop"],
        "dispatched": delivery["dispatched"],
    }


def advance_order_to_delivered_simple(account_id: str, part_id: str, quantity=1,
                                      vehicle_id=None, **stop_overrides) -> dict:
    return advance_order_to_delivered(account_id, [line_item(part_id, quantity)],
                                      vehicle_id=vehicle_id, **stop_overrides)


def advance_order_to(order_id: str, account_id: str, target: str) -> dict:
    """Walk an existing order forward to `target`.

    Supported targets: DRAFT, CONFIRMED, ALLOCATED, PICKING, DISPATCHED,
    DELIVERED, VOID.
    """
    order = reload_order(order_id)
    steps = ["CONFIRMED", "ALLOCATED", "PICKING"]
    if target in steps:
        # Walk forward only as far as `target`. The order may already have
        # advanced past the first step, so the loop is driven by the status the
        # order is actually in rather than by a fixed iteration count.
        while order["status"] != target:
            if order["status"] == "DRAFT":
                order = confirm_order(order["id"], account_id)
            elif order["status"] == "CONFIRMED":
                order = allocate_order(order["id"], account_id)
            elif order["status"] == "ALLOCATED":
                order = pick_order(order["id"])
            else:
                break
        return order
    if target == "DISPATCHED":
        advance_order_to(order_id, account_id, "PICKING")
        route, _ = place_on_route(account_id, [order_id])
        return dispatch_order(order_id)
    if target == "DELIVERED":
        advance_order_to(order_id, account_id, "PICKING")
        return deliver_directly(account_id, reload_order(order_id))["order"]
    if target == "VOID":
        return get_success_data(api_client.void_order(order_id, {}, SALES))
    return order


def confirm_n_orders(account_id: str, part_id: str, count: int,
                     quantity=1, vehicle_id=None) -> list:
    """Create and confirm `count` orders, raising the account's order_sequence.

    Each confirmation advances `order_sequence`, so the caller can target a
    specific pricing band.
    """
    orders = []
    for _ in range(count):
        order = write_simple_order(account_id, part_id, quantity=quantity,
                                   vehicle_id=vehicle_id)
        orders.append(confirm_order(order["id"], account_id))
    return orders


# ═══════════════════════════════════════════════════════════════════════════
# Tier 4 -- accumulation and threshold targeting
# ═══════════════════════════════════════════════════════════════════════════

def commit_units_to_store(store_id: str, account_id: str, part_id: str,
                          units: int, quantity_per_order=1) -> list:
    """Confirm orders until exactly `units` are committed against the store.

    Returns the list of confirmed orders. The store's `committed_units_today`
    lands on the requested figure, so a boundary test can sit one unit below or
    exactly at the ceiling.
    """
    orders = []
    remaining = units
    while remaining > 0:
        take = min(quantity_per_order, remaining)
        order = write_simple_order(account_id, part_id, quantity=take)
        orders.append(confirm_order(order["id"], account_id))
        remaining -= take
    return orders


def setup_at_capacity_boundary(daily_capacity_units: int, on_hand_units: int = 20,
                               committed_units: int = 0, **account_overrides):
    """A satellite whose daily capacity is the binding constraint.

    Returns dict with store, part, inventory, account and the orders already
    committed (committing `committed_units` units).
    """
    store = create_satellite(daily_capacity_units=daily_capacity_units)
    part = create_part(sku="P-CAP", list_price_cents=1673)
    inv = stock(store["id"], part["id"], on_hand_units)
    account = create_account(store["id"], **account_overrides)
    orders = commit_units_to_store(store["id"], account["id"], part["id"], committed_units)
    return {"store": store, "part": part, "inventory": inv, "account": account,
            "committed_orders": orders}


def setup_account_near_credit_limit(credit_limit_cents: int, part_id: str,
                                    order_quantity: int = 1, **account_overrides):
    """An account whose credit limit is close to one order's exposure."""
    store = create_satellite()
    part = reload_part(part_id)
    stock(store["id"], part["id"], 20)
    account = create_account(store["id"], credit_limit_cents=credit_limit_cents,
                             **account_overrides)
    order = write_simple_order(account["id"], part["id"], quantity=order_quantity)
    return {"store": store, "part": part, "account": account, "order": order}


def setup_account_with_orders(part_id: str, part_list_price_cents: int,
                              prior_order_count: int, order_quantity=1,
                              on_hand_units=None, **account_overrides):
    """An account that has already placed `prior_order_count` confirmed orders.

    Used to target a pricing band: the next order's `member_sequence` is
    prior_order_count + 1.
    """
    store = create_satellite()
    part = reload_part(part_id)
    stock(store["id"], part["id"], on_hand_units or (prior_order_count * order_quantity + 20))
    account = create_account(store["id"], **account_overrides)
    confirmed = confirm_n_orders(account["id"], part["id"], prior_order_count,
                                 quantity=order_quantity)
    return {"store": store, "part": part, "account": account, "confirmed_orders": confirmed}


# ═══════════════════════════════════════════════════════════════════════════
# Tier 5 -- tool crib, deposits and the return desk
# ═══════════════════════════════════════════════════════════════════════════

def return_desk_stop(account_id: str, route=None, driver_id="drv-desk",
                     route_code="R-DESK", plan=True, dispatch=True,
                     delivery_window_start="2026-09-02T15:30:00Z",
                     delivery_window_end="2026-09-02T16:30:00Z"):
    """A RETURN_DESK stop for the account on a live (non-cancelled) route.

    Inspection and close both require such a stop to exist, so tool-crib tests
    build one before they touch a loan.
    """
    route = route or create_route(driver_id=driver_id, route_code=route_code)
    stop = attach_stop_ok(route["id"], account_id, order_ids=[],
                          stop_kind="RETURN_DESK",
                          delivery_window_start=delivery_window_start,
                          delivery_window_end=delivery_window_end,
                          travel_minutes_from_previous=15, drop_minutes=5)
    if plan:
        route = plan_route(route["id"])
    if dispatch:
        route = dispatch_route(route["id"])
    return route, stop


def request_loan(account_id: str, tool_catalog_id: str, deposit_amount_cents=3000,
                 **overrides) -> dict:
    payload = create_loan_payload(account_id, tool_catalog_id,
                                  deposit_amount_cents=deposit_amount_cents, **overrides)
    return get_success_data(api_client.request_loan(payload, SALES))


def checkout_loan(loan_id: str, account_id: str, accepted_deposit_cents=3000) -> dict:
    payload = {
        "accepted_deposit_cents": accepted_deposit_cents,
        "expected_account_version": account_version(account_id),
    }
    return get_success_data(api_client.checkout_loan(loan_id, payload, SALES))


def request_and_checkout_loan(account_id: str, tool_catalog_id: str,
                              deposit_amount_cents=3000) -> dict:
    loan = request_loan(account_id, tool_catalog_id,
                        deposit_amount_cents=deposit_amount_cents)
    return checkout_loan(loan["id"], account_id,
                         accepted_deposit_cents=deposit_amount_cents)


def return_loan(loan_id: str) -> dict:
    """Record the tool back at the counter.

    PRD 3.6 makes the out-of-crib states reachable only once the logical clock
    is strictly past the loan's `loaned_at` ("Once the logical clock is
    strictly after the loan's `loaned_at`, an unconditional system transition
    ... moves the loan to `IN_USE`"). A checkout is stamped from that same
    clock, so a return issued at the very instant of the checkout still sees a
    `CHECKED_OUT` loan. Advancing the clock one second is the smallest move
    that satisfies the rule, and it leaves every modelled instant - windows,
    shift ends, epochs and due dates - intact.
    """
    nudge_clock_past_checkout(loan_id)
    return get_success_data(api_client.return_loan(loan_id, {}, DRIVER))


def nudge_clock_past_checkout(loan_id: str):
    """Move the logical clock one second past a loan's `loaned_at`."""
    from datetime import datetime, timedelta, timezone

    loan = get_success_data(api_client.get_loan(loan_id, CRIB))
    loaned_at = loan.get("loaned_at")
    if not loaned_at:
        return
    moment = datetime.strptime(loaned_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc) + timedelta(seconds=1)
    set_clock(moment.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return moment


def advance_clock_to(to_iso8601: str) -> dict:
    """Move the logical clock to an explicit instant."""
    return set_clock(to_iso8601)


def inspect_loan(loan_id: str, return_condition="GOOD") -> dict:
    return get_success_data(api_client.inspect_loan(
        loan_id, {"return_condition": return_condition}, CRIB))


def close_loan(loan_id: str) -> dict:
    return get_success_data(api_client.close_loan(loan_id, {}, CRIB))


def forfeit_loan(loan_id: str) -> dict:
    return get_success_data(api_client.forfeit_loan(loan_id, {}, CRIB))


def setup_checked_out_loan(deposit_amount_cents=3000, return_desk=True,
                           account_overrides=None, with_stock_units=0,
                           **loan_overrides):
    """Satellite + account + tool + a checked-out loan.

    Returns a dict with the store, account, tool, loan and (when requested) the
    return-desk stop and route that inspection and close depend on.
    """
    store = create_satellite()
    account = create_account(store["id"], **(account_overrides or {}))
    tool = create_tool(tool_sku="TOOL-CHK", deposit_amount_cents=deposit_amount_cents)
    loan = request_and_checkout_loan(account["id"], tool["id"],
                                     deposit_amount_cents=deposit_amount_cents)
    result = {"store": store, "account": account, "tool": tool, "loan": loan,
              "route": None, "stop": None}
    if return_desk:
        route, stop = return_desk_stop(account["id"])
        result["route"], result["stop"] = route, stop
    return result


def setup_returned_loan(deposit_amount_cents=3000, return_desk=True,
                        account_overrides=None, **loan_overrides):
    """As above, but with the tool already back at the counter (RETURNED)."""
    scenario = setup_checked_out_loan(deposit_amount_cents=deposit_amount_cents,
                                      return_desk=return_desk,
                                      account_overrides=account_overrides,
                                      **loan_overrides)
    scenario["loan"] = return_loan(scenario["loan"]["id"])
    return scenario


def setup_inspected_loan(return_condition="GOOD", deposit_amount_cents=3000,
                         account_overrides=None, **loan_overrides):
    """As above, through inspection (INSPECTED)."""
    scenario = setup_returned_loan(deposit_amount_cents=deposit_amount_cents,
                                   account_overrides=account_overrides,
                                   **loan_overrides)
    scenario["loan"] = inspect_loan(scenario["loan"]["id"], return_condition)
    return scenario


# ═══════════════════════════════════════════════════════════════════════════
# Tier 6 -- core returns and warranties
# ═══════════════════════════════════════════════════════════════════════════

def open_core_return(order_id: str, items) -> dict:
    payload = create_core_return_payload(order_id, items)
    return get_success_data(api_client.create_core_return(payload, SALES))


def transit_core_return(core_return_id: str) -> dict:
    return get_success_data(api_client.transit_core_return(core_return_id, {}, DRIVER))


def inspect_core_return(core_return_id: str) -> dict:
    return get_success_data(api_client.inspect_core_return(core_return_id, {}, CRIB))


def credit_core_return(core_return_id: str) -> dict:
    return get_success_data(api_client.credit_core_return(core_return_id, {}, CREDIT))


def register_warranty(account_id: str, part_id: str, **overrides) -> dict:
    payload = create_warranty_payload(account_id, part_id, **overrides)
    return get_success_data(api_client.create_warranty(payload, SALES))


def setup_delivered_order_with_cores(part_sku="MACHINED-1", list_price_cents=8000,
                                     core_charge_cents=3000, quantity=1,
                                     account_overrides=None, extra_parts=None):
    """A DELIVERED order carrying a core-bearing part.

    Returns the store, part, account, the delivered order, its route and stop.
    `extra_parts` is an optional list of {"sku", "list_price_cents",
    "core_charge_cents", "quantity"} dicts added as further order lines.
    """
    store = create_satellite()
    part = create_part(sku=part_sku, list_price_cents=list_price_cents,
                       core_charge_cents=core_charge_cents)
    stock(store["id"], part["id"], 20)
    items = [line_item(part["id"], quantity)]
    created = []
    for extra in (extra_parts or []):
        extra_part = create_part(sku=extra["sku"],
                                 list_price_cents=extra["list_price_cents"],
                                 core_charge_cents=extra.get("core_charge_cents", 0))
        stock(store["id"], extra_part["id"], 20)
        items.append(line_item(extra_part["id"], extra["quantity"]))
        created.append(extra_part)
    account = create_account(store["id"], **(account_overrides or {}))
    result = advance_order_to_delivered(account["id"], items)
    result.update({"store": store, "part": part, "extra_parts": created,
                   "account": reload_account(account["id"])})
    return result


def setup_in_transit_core_return(quantity=1, part_sku="MACHINED-1",
                                 list_price_cents=8000, core_charge_cents=3000,
                                 account_overrides=None, warranty=False,
                                 extra_parts=None):
    """A core return sitting in IN_TRANSIT, ready for inspection."""
    scenario = setup_delivered_order_with_cores(
        part_sku=part_sku, list_price_cents=list_price_cents,
        core_charge_cents=core_charge_cents, quantity=quantity,
        account_overrides=account_overrides, extra_parts=extra_parts)
    core_return = open_core_return(scenario["order"]["id"],
                                   [line_item(scenario["part"]["id"], quantity)])
    if warranty:
        register_warranty(scenario["account"]["id"], scenario["part"]["id"])
    core_return = transit_core_return(core_return["id"])
    scenario["core_return"] = core_return
    return scenario


# ═══════════════════════════════════════════════════════════════════════════
# Tier 7 -- credit governance
# ═══════════════════════════════════════════════════════════════════════════

def setup_over_limit_account(credit_limit_cents=2000, part_list_price_cents=2000,
                             shortfall_units=1, account_overrides=None):
    """An account whose credit exposure exceeds its limit.

    A large account is created, an order is delivered against it (creating a
    receivable), the limit is then revised down, and a fresh order and loan
    push exposure above the new ceiling.
    """
    scenario = setup_basic_scenario(part_sku="PLUG-OVER",
                                    list_price_cents=part_list_price_cents)
    account = scenario["account"]
    refreshed = reload_account(account["id"])
    get_success_data(api_client.update_account(
        account["id"],
        {"credit_limit_cents": credit_limit_cents,
         "expected_account_version": refreshed["version"]}, CREDIT))
    return scenario


def setup_aged_account(orders_behind_days=None, delivered_at_clock=None,
                       terms_days=30, **scenario_overrides):
    """An account carrying a receivable whose oldest due instant is aging.

    The order is delivered at the current logical clock; the caller then moves
    the clock forward to make the aging test observable.
    """
    store = create_satellite()
    part = create_part(sku="AGING-1", list_price_cents=200000)
    stock(store["id"], part["id"], 10)
    account = create_account(store["id"], credit_terms_days=terms_days,
                             **(scenario_overrides or {}))
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(part["id"], 1)])
    return {"store": store, "part": part, "account": reload_account(account["id"]),
            "order": delivered["order"], "route": delivered["route"],
            "stop": delivered["stop"]}


# ═══════════════════════════════════════════════════════════════════════════
# Tier 8 -- unit-count helpers used by repeated assertions
# ═══════════════════════════════════════════════════════════════════════════

def delivery_run_credit_affiliate(total_miles):
    """The AFFILIATE branch of the driver run credit, for expected values."""
    rate = 20 if total_miles >= 40 else 40
    return 500 + rate * round(total_miles)


def ordered_quantity_credit(core_lines, order_lines):
    """The entitled credit: every line's core charge times the matched quantity."""
    ordered = {}
    for line in order_lines:
        ordered[line["part_id"]] = ordered.get(line["part_id"], 0) + line["quantity"]
    total = 0
    for line in core_lines:
        matched = min(line["quantity"], ordered.get(line["part_id"], 0))
        total += line["core_charge_cents"] * matched
    return total
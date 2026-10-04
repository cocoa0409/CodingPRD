"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API —
the harness restarts the server before each test, so nothing is ever
pre-seeded. All setup calls use `get_success_data()` so a broken precondition
reports a clear "Setup failed" message rather than an ambiguous assertion.

Identity threading: an entity-backed role's header must carry the actual
entity's id whenever the call is ownership-gated (Customer owns BoxOrder and
Subscription; Supplier owns SourcingBid; FulfillmentOperator owns BoxOrder by
its center). The `make_*_headers()` builders from `test_users` are used for
those calls.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as default_api
from .constants import CYCLE_ADVANCE_CLOCK, DEFAULT_CLOCK
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_operator_headers,
    make_supplier_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def reset_clock(api=default_api, instant=DEFAULT_CLOCK):
    """Place the server's logical clock at `instant`."""
    return get_success_data(api.set_clock({"to_iso8601": instant}, ADMIN))


def advance_clock(api, instant):
    return reset_clock(api, instant)


def cycle_start_iso(cycle_index, cadence_hours=168, base=DEFAULT_CLOCK):
    """The instant a service cycle begins, counting from the default clock.

    Cycle 1 begins at the default clock; each further cycle advances by one
    full cadence period.
    """
    from datetime import datetime, timedelta

    start = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=None)
    start = start + timedelta(hours=cadence_hours * (cycle_index - 1))
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def order_deadline_gap_hours(region):
    """The hours between an order's ready_deadline and its build_deadline.

    The PRD fixes both against the same cycle start: the ready deadline is the
    start minus the regional cutoff lead and the build deadline is the start
    plus the build window.
    """
    from .constants import BUILD_WINDOW_HOURS, CUTOFF_LEAD_HOURS

    return CUTOFF_LEAD_HOURS[region] + BUILD_WINDOW_HOURS


# ---------------------------------------------------------------------------
# Single-entity builders
# ---------------------------------------------------------------------------
def make_center(api, code="DEMO-NE", region="NE", name=None, insulation_profile="LIGHT",
                max_concurrent_building_cycles=5, is_active=None):
    payload = {
        "code": code,
        "name": name or f"{code} Center",
        "region": region,
        "insulation_profile": insulation_profile,
        "max_concurrent_building_cycles": max_concurrent_building_cycles,
    }
    if is_active is not None:
        payload["is_active"] = is_active
    return get_success_data(api.create_fulfillment_center(payload, ADMIN))


def make_supplier(api, name="Supply Co", region="NE"):
    return get_success_data(api.create_supplier({"name": name, "region": region}, ADMIN))


def make_customer(api, email="sub@example.com", full_name="Sub Scriber", service_region="NE",
                  **overrides):
    payload = {
        "email": email,
        "full_name": full_name,
        "service_region": service_region,
    }
    payload.update(overrides)
    return get_success_data(api.register_customer(payload, ANON))


def make_subscription(api, customer_id, cadence="WEEKLY"):
    return get_success_data(
        api.create_subscription({"customer_id": customer_id, "cadence": cadence}, ADMIN)
    )


def make_lot(api, supplier_id, center_id, category="FRUIT", procurement_grade="SURPLUS",
             unit_weight_grams=100, quantity_available=300, unit_cost_cents=100,
             product_name="LOT", harvest_date="2026-09-01T00:00:00Z",
             expiry_date="2026-09-20T00:00:00Z", ready_date="2026-09-05T00:00:00Z",
             allergen_codes=None, preference_tags=None):
    payload = {
        "fulfillment_center_id": center_id,
        "product_name": product_name,
        "category": category,
        "procurement_grade": procurement_grade,
        "unit_weight_grams": unit_weight_grams,
        "quantity_available": quantity_available,
        "unit_cost_cents": unit_cost_cents,
        "harvest_date": harvest_date,
        "expiry_date": expiry_date,
        "ready_date": ready_date,
    }
    if allergen_codes is not None:
        payload["allergen_codes"] = allergen_codes
    if preference_tags is not None:
        payload["preference_tags"] = preference_tags
    return get_success_data(api.create_lot(supplier_id, payload, ADMIN))


def make_bid(api, lot_id, supplier_id, cost=None, quantity=None):
    payload = {
        "supply_lot_id": lot_id,
        "supplier_id": supplier_id,
        "bid_unit_cost_cents": cost if cost is not None else 100,
        "quantity_offered": quantity if quantity is not None else 300,
    }
    return get_success_data(
        api.create_bid(payload, make_supplier_headers(supplier_id))
    )


def award_lot(api, lot, bidder_quota=1):
    """Award a lot with its current version. Returns the refreshed lot."""
    return get_success_data(
        api.award_lot(
            lot["id"],
            {"bidder_quota": bidder_quota, "expected_supply_lot_version": lot["version"]},
            ADMIN,
        )
    )


def make_lot_ready(api, lot, quality_outcome="PASS", arrived_at=None):
    payload = {"quality_outcome": quality_outcome, "expected_supply_lot_version": lot["version"]}
    if arrived_at is not None:
        payload["arrived_at"] = arrived_at
    return get_success_data(api.make_lot_ready(lot["id"], payload, ADMIN))


def provision_ready_lot(api, supplier_id, center_id, *, bidder_quota=1, **lot_overrides):
    """Create a lot, bid on it, award it, and clear make-ready PASS.

    Returns the resulting lot (status READY, quality_status PASS).
    """
    lot = make_lot(api, supplier_id, center_id, **lot_overrides)
    make_bid(api, lot["id"], supplier_id, cost=lot_overrides.get("unit_cost_cents", 100),
             quantity=lot_overrides.get("quantity_available", 300))
    lot = award_lot(api, lot, bidder_quota=bidder_quota)
    lot = make_lot_ready(api, lot, "PASS")
    return lot


def make_order(api, customer, subscription, serving_cycle_index=1, cuisine_preference="STANDARD"):
    payload = {
        "customer_id": customer["id"],
        "subscription_id": subscription["id"],
        "serving_cycle_index": serving_cycle_index,
        "cuisine_preference": cuisine_preference,
    }
    return get_success_data(api.create_box_order(payload, ADMIN))


def finalize_order(api, order):
    return get_success_data(
        api.finalize_box_order(
            order["id"], {"expected_box_order_version": order["version"]}, ADMIN
        )
    )


def make_order_buildable(api, order, center, cadence_hours=168):
    """Bring the order to READY_TO_BUILD.

    A DRAFT order is finalised first; an AWAITING_WINDOW order is left as it is.
    The PRD promotes the order out of `AWAITING_WINDOW` the moment the logical
    clock reaches its `ready_deadline`, so the clock is walked to exactly that
    instant and no further — moving on to the `build_deadline` would trip the
    §3.4 fallback that reverts a still-empty `READY_TO_BUILD` order to `DRAFT`.
    """
    current = refresh_order(api, order)
    if current["status"] == "READY_TO_BUILD":
        return current
    if current["status"] in ("DRAFT", "AWAITING_WINDOW"):
        finalized = (
            finalize_order(api, current)
            if current["status"] == "DRAFT"
            else current
        )
    else:
        return current
    # The clock stops at the ready_deadline: that instant both opens the build
    # window and keeps the order strictly inside it.
    advance_clock(api, finalized["ready_deadline"])
    return refresh_order(api, finalized)


def prepare_orders_for_building(api, orders, cadence_hours=168):
    """Finalise every order, then move the clock so all are READY_TO_BUILD.

    Finalisation must happen while each order still meets its cutoff, so the
    clock can only be advanced after the last one commits. The clock stops at
    the shared `ready_deadline`, which is the instant promotion fires and the
    edge of the build window.
    """
    finalized = [finalize_order(api, order) for order in orders]
    advance_clock(api, finalized[0]["ready_deadline"])
    return [refresh_order(api, order) for order in finalized]


def build_order(api, order, center, line_plan, as_role="operator",
                make_buildable=True, cadence_hours=168):
    if make_buildable and order["status"] in ("DRAFT", "AWAITING_WINDOW"):
        order = make_order_buildable(api, order, center, cadence_hours)
    assert order["status"] == "READY_TO_BUILD", (
        f"Setup failed: the order is {order['status']}, not READY_TO_BUILD"
    )
    headers = make_operator_headers(center["id"]) if as_role == "operator" else ADMIN
    return get_success_data(
        api.build_box_order(
            order["id"],
            {"expected_box_order_version": order["version"], "line_plan": line_plan},
            headers,
        )
    )


def pack_order(api, order, center, as_role="operator"):
    headers = make_operator_headers(center["id"]) if as_role == "operator" else ADMIN
    return get_success_data(
        api.pack_box_order(order["id"], {"expected_box_order_version": order["version"]}, headers)
    )


def crash_out(api, order):
    return get_success_data(
        api.crash_out_box_order(
            order["id"], {"expected_box_order_version": order["version"]}, ADMIN
        )
    )


def reroute_back(api, order):
    return get_success_data(
        api.reroute_back_box_order(
            order["id"], {"expected_box_order_version": order["version"]}, ADMIN
        )
    )


def file_claim(api, order, item_id, reason_code="SPOILED", photo_url=None,
               requested_credit_cents=500):
    payload = {
        "box_build_item_id": item_id,
        "reason_code": reason_code,
        "photo_url": photo_url or "https://cdn.example.com/evidence.jpg",
        "requested_credit_cents": requested_credit_cents,
    }
    return get_success_data(api.create_quality_claim(order["id"], payload, ADMIN))


def review_claim(api, claim, outcome):
    return get_success_data(
        api.review_quality_claim(
            claim["id"], {"outcome": outcome, "expected_claim_version": claim["version"]}, ADMIN
        )
    )


def line_plan(*pairs):
    """`line_plan(("lot-id", 5), ("lot-id-2", 4))` -> the endpoint's line_plan form."""
    return [{"supply_lot_id": lot_id, "units": units} for lot_id, units in pairs]


def advance_center_cycle(api, center):
    """Roll a center's build cycle forward by one, per §3.5.

    The roll decrements `serving_cycle_index` to `max(0, index - 1)` and
    recomputes the posture from the new counter.
    """
    current = refresh_center(api, center)
    return get_success_data(
        api.advance_center_cycle(
            center["id"],
            {"expected_fulfillment_center_version": current["version"]},
            ADMIN,
        )
    )


# ---------------------------------------------------------------------------
# Read-back refresh helpers
# ---------------------------------------------------------------------------
def refresh_order(api, order):
    return get_success_data(api.get_box_order(order["id"], ADMIN))


def refresh_lot(api, lot):
    return get_success_data(api.get_supply_lot(lot["id"], ADMIN))


def refresh_supplier(api, supplier):
    return get_success_data(api.get_supplier(supplier["id"], ADMIN))


def refresh_subscription(api, subscription):
    return get_success_data(api.get_subscription(subscription["id"], ADMIN))


def refresh_center(api, center):
    return get_success_data(api.get_fulfillment_center(center["id"], ADMIN))


def refresh_customer(api, customer):
    return get_success_data(api.get_customer(customer["id"], ADMIN))


def refresh_claim(api, claim):
    claims = get_success_data(api.list_quality_claims(ADMIN))
    for row in claims:
        if row["id"] == claim["id"]:
            return row
    raise AssertionError("Setup failed: the claim disappeared from the collection")


def order_items(api, order, status=None):
    params = {"status": status} if status else None
    data = get_success_data(api.list_box_order_items(order["id"], ADMIN, params))
    return data


def order_cold_chain_packs(api, order):
    return get_success_data(api.list_box_order_cold_chain_packs(order["id"], ADMIN))


def order_claims(api, order, status=None):
    params = {"status": status} if status else None
    return get_success_data(api.list_order_quality_claims(order["id"], ADMIN, params))


# ---------------------------------------------------------------------------
# Tier 2/3 — composite scenarios
# ---------------------------------------------------------------------------
def setup_center_supplier_lot(api, *, code="DEMO-NE", region="NE", category="FRUIT",
                              procurement_grade="SURPLUS", unit_weight_grams=100,
                              unit_cost_cents=100, quantity_available=300,
                              max_concurrent_building_cycles=5, supplier_name="Supply Co",
                              preference_tags=None, allergen_codes=None,
                              harvest_date="2026-09-01T00:00:00Z",
                              expiry_date="2026-09-20T00:00:00Z",
                              ready_date="2026-09-05T00:00:00Z"):
    """Center + supplier + one awarded, PASS lot. Returns (center, supplier, lot)."""
    reset_clock(api, DEFAULT_CLOCK)
    center = make_center(
        api, code=code, region=region,
        max_concurrent_building_cycles=max_concurrent_building_cycles,
    )
    supplier = make_supplier(api, name=supplier_name, region=region)
    lot = provision_ready_lot(
        api, supplier["id"], center["id"], category=category,
        procurement_grade=procurement_grade, unit_weight_grams=unit_weight_grams,
        unit_cost_cents=unit_cost_cents, quantity_available=quantity_available,
        preference_tags=preference_tags, allergen_codes=allergen_codes,
        harvest_date=harvest_date, expiry_date=expiry_date, ready_date=ready_date,
    )
    return center, supplier, lot


def setup_subscriber(api, *, region="NE", email="sub@example.com", full_name="Sub Scriber",
                     cadence="WEEKLY", **customer_overrides):
    """Register a customer and open one subscription. Returns (customer, subscription)."""
    customer = make_customer(
        api, email=email, full_name=full_name, service_region=region, **customer_overrides
    )
    subscription = make_subscription(api, customer["id"], cadence=cadence)
    return customer, subscription


def setup_box_scenario(api, *, cycles=(2,), cuisine_preference="STANDARD",
                       lot_overrides=None, region="NE", code="DEMO-NE",
                       max_concurrent_building_cycles=5, customer_overrides=None,
                       cadence="WEEKLY", email="sub@example.com"):
    """Center + supplier + one PASS lot + one subscriber + N DRAFT orders.

    Returns a dict with center, supplier, lot, customer, subscription, orders.
    """
    lot_overrides = lot_overrides or {}
    customer_overrides = customer_overrides or {}
    center, supplier, lot = setup_center_supplier_lot(
        api, code=code, region=region, max_concurrent_building_cycles=max_concurrent_building_cycles,
        **lot_overrides,
    )
    customer, subscription = setup_subscriber(
        api, region=region, email=email, cadence=cadence, **customer_overrides
    )
    # Each cycle-bound order belongs to its own subscriber: the PRD refuses two
    # orders for one subscription and one serving cycle.
    subscribers = [(customer, subscription)]
    orders = [
        make_order(api, customer, subscription, serving_cycle_index=cycles[0],
                   cuisine_preference=cuisine_preference)
    ]
    for index, cycle in enumerate(list(cycles)[1:], start=1):
        extra_customer, extra_subscription = setup_subscriber(
            api, region=region, email=f"sub{index}-{email}", cadence=cadence
        )
        subscribers.append((extra_customer, extra_subscription))
        orders.append(
            make_order(api, extra_customer, extra_subscription, serving_cycle_index=cycle,
                       cuisine_preference=cuisine_preference)
        )
    return {
        "center": center,
        "supplier": supplier,
        "lot": lot,
        "customer": customer,
        "subscription": subscription,
        "subscribers": subscribers,
        "orders": orders,
    }


def setup_built_order(api, *, plan=None, pack=False, cycles=(2,), lot_overrides=None,
                      region="NE", code="DEMO-NE", max_concurrent_building_cycles=5,
                      email="sub@example.com", order_index=0, cuisine_preference="STANDARD"):
    """One subscriber whose order is built (and optionally packed).

    `plan` is a list of (lot-key, units) pairs where lot-key is "main" for the
    scenario's single lot. Returns (scenario_dict, order, items).
    """
    scenario = setup_box_scenario(
        api, cycles=cycles, lot_overrides=lot_overrides, region=region, code=code,
        max_concurrent_building_cycles=max_concurrent_building_cycles, email=email,
        cuisine_preference=cuisine_preference,
    )
    lot = scenario["lot"]
    order = scenario["orders"][order_index]
    center = scenario["center"]
    if plan is None:
        plan = line_plan((lot["id"], 6))
    order = build_order(api, order, center, plan)
    scenario["orders"][order_index] = order
    if pack:
        order = pack_order(api, order, center)
        scenario["orders"][order_index] = order
    items = order_items(api, order)
    return scenario, order, items


def setup_claimed_order(api, *, requested_credit_cents=500, reason_code="SPOILED",
                        photo_url=None, pack=True, clock=None, **kwargs):
    """An order built from one lot, packed, with one claim filed on its line.

    Returns (scenario, order, items, claim).
    """
    scenario, order, items = setup_built_order(api, pack=pack, **kwargs)
    if clock:
        advance_clock(api, clock)
    included = [i for i in items if i["status"] == "INCLUDED"]
    assert included, "Setup failed: the built order carries no INCLUDED line"
    claim = file_claim(
        api, order, included[0]["id"], reason_code=reason_code, photo_url=photo_url,
        requested_credit_cents=requested_credit_cents,
    )
    return scenario, order, included, claim


def uuids(count, start=1):
    """Deterministic, syntactically valid UUIDs for missing-resource probes."""
    return [
        f"00000000-0000-4000-8000-{i:012d}" for i in range(start, start + count)
    ]


# Re-export the composite clock constant for tests that need the ready-deadline hop.
READY_DEADLINE_CLOCK = CYCLE_ADVANCE_CLOCK
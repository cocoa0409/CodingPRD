"""Composite preconditions built from the public endpoint surface.

The harness restarts the server before every test, so each test opens against an
empty store with the logical clock at its 2026-09-01T00:00:00Z startup default.
Every fixture therefore builds its preconditions from scratch using only the
documented endpoints. Setup calls go through ``get_success_data`` (any 2xx), so a
fixture never hard-codes the 200-versus-201 split; the tests themselves assert
the status codes that matter.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .test_users import (
    make_crew_headers,
    make_customer_headers,
    make_manager_headers,
    make_shift_lead_headers,
)
from .types import (
    JsonObject,
    OrderKind,
)


class Bundle(object):
    """A small attribute bag so a test can read ``bundle.daypart["id"]`` fluently."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return "Bundle(%s)" % ", ".join(sorted(self.__dict__))


# ----------------------------------------------------------------- logical clock
def set_clock(client, to_iso8601: str) -> JsonObject:
    """Move the logical clock; the response reports the resulting clock."""
    return get_success_data(client.set_clock(to_iso8601, make_manager_headers()))


# ------------------------------------------------------------------- store days
def create_store_day(client, business_date: str, **overrides) -> JsonObject:
    return get_success_data(
        client.create_store_day(
            factories.store_day_payload(business_date=business_date, **overrides),
            make_manager_headers(),
        )
    )


def read_store_day(client, day_id) -> JsonObject:
    return get_success_data(client.get_store_day(day_id, make_manager_headers()))


# --------------------------------------------------------------------- dayparts
def create_daypart(client, day_id, **overrides) -> JsonObject:
    return get_success_data(
        client.create_daypart(
            day_id, factories.daypart_payload(**overrides), make_manager_headers()
        )
    )


def read_daypart(client, daypart_id) -> JsonObject:
    return get_success_data(client.get_daypart(daypart_id, make_manager_headers()))


# ----------------------------------------------------------------- demand events
def create_demand_event(client, day_id, **overrides) -> JsonObject:
    return get_success_data(
        client.create_demand_event(
            day_id, factories.demand_event_payload(**overrides), make_manager_headers()
        )
    )


# ---------------------------------------------------------------------- products
def create_product(client, **overrides) -> JsonObject:
    return get_success_data(
        client.create_product(factories.product_payload(**overrides), make_manager_headers())
    )


# ------------------------------------------------------------------ locker slots
def create_locker_slot(client, day_id, slot_number: int = 1) -> JsonObject:
    return get_success_data(
        client.create_locker_slot(
            day_id, factories.locker_slot_payload(slot_number=slot_number),
            make_manager_headers(),
        )
    )


# ------------------------------------------------- planning / open composites
def planned_store_day(client, business_date, daypart_overrides=None) -> Bundle:
    """A store day in PLANNING with one daypart. Returns (store_day, daypart)."""
    sd = create_store_day(client, business_date)
    dp = create_daypart(client, sd["id"], **(daypart_overrides or {}))
    return Bundle(store_day=sd, daypart=dp)


def open_store_day_with_active_daypart(
    client,
    business_date,
    active_at,
    daypart_overrides=None,
):
    """Store day opened and clock moved into the daypart window.

    ``active_at`` is an ISO instant inside the (default LUNCH 600-840) window;
    the clock move auto-activates the daypart. Returns Bundle(store_day, daypart).
    """
    bundle = planned_store_day(client, business_date, daypart_overrides)
    get_success_data(client.open_store_day(bundle.store_day["id"], make_manager_headers()))
    set_clock(client, active_at)
    daypart = read_daypart(client, bundle.daypart["id"])
    assert daypart["status"] == "ACTIVE", (
        "daypart did not auto-activate at %s" % active_at
    )
    return Bundle(store_day=read_store_day(client, bundle.store_day["id"]), daypart=daypart)


# ----------------------------------------------------------- production batches
def create_proofed_dough_batch(client, day_id, size_units=10) -> JsonObject:
    """MIXING -> PROOFING -> PROOFED. Callers must have the clock set so that the
    120-minute proof floor has passed by the second advance."""
    db = get_success_data(
        client.create_dough_batch(
            day_id, factories.batch_payload(size_units=size_units), make_crew_headers()
        )
    )
    return db


def advance_dough(client, batch_id) -> JsonObject:
    return get_success_data(client.advance_dough_batch(batch_id, make_crew_headers()))


def create_cheese_batch(client, day_id, size_units=10) -> JsonObject:
    return get_success_data(
        client.create_cheese_batch(
            day_id, factories.batch_payload(size_units=size_units), make_crew_headers()
        )
    )


def advance_cheese(client, batch_id) -> JsonObject:
    return get_success_data(client.advance_cheese_batch(batch_id, make_crew_headers()))


def ready_batches(
    client,
    day_id,
    size_units=10,
    business_date=None,
    mix_at="08:00:00Z",
    floor_reached_at="10:05:00Z",
    rest_reached_at="10:35:00Z",
) -> Bundle:
    """Dough PROOFED + cheese READY using the standard clock ladder.

    Call with the clock anywhere at or before ``mix_at``; the helper mixes both
    batches at ``mix_at``, advances dough MIXING -> PROOFING, then moves the clock
    to ``floor_reached_at`` (>= mix + 120 min) to mark PROOFED and advance cheese
    PREPPING -> RESTING, then to ``rest_reached_at`` (>= mix + 30 min) to mark
    cheese READY.
    """
    set_clock(client, "%sT%s" % (business_date, mix_at))
    db = create_proofed_dough_batch(client, day_id, size_units=size_units)
    cb = create_cheese_batch(client, day_id, size_units=size_units)
    advance_dough(client, db["id"])  # MIXING -> PROOFING at mix_at
    set_clock(client, "%sT%s" % (business_date, floor_reached_at))
    advance_dough(client, db["id"])  # PROOFING -> PROOFED (floor inclusive)
    advance_cheese(client, cb["id"])  # PREPPING -> RESTING
    set_clock(client, "%sT%s" % (business_date, rest_reached_at))
    advance_cheese(client, cb["id"])  # RESTING -> READY (rest floor passed)
    return Bundle(
        dough_batch=get_success_data(client.get_dough_batch(db["id"], make_crew_headers())),
        cheese_batch=get_success_data(client.get_cheese_batch(cb["id"], make_crew_headers())),
    )


# --------------------------------------------------------------- production run
def create_run(client, daypart_id, product_id, dough_batch_id, cheese_batch_id, quantity) -> JsonObject:
    return get_success_data(
        client.create_production_run(
            daypart_id,
            factories.production_run_payload(product_id, dough_batch_id, cheese_batch_id, quantity),
            make_shift_lead_headers(),
        )
    )


def read_run(client, run_id) -> JsonObject:
    return get_success_data(client.get_production_run(run_id, make_crew_headers()))


def start_baking(client, run_id) -> JsonObject:
    return get_success_data(client.start_baking(run_id, make_crew_headers()))


def rack_run(client, run_id) -> JsonObject:
    return get_success_data(client.rack_run(run_id, make_crew_headers()))


def racked_run(client, daypart_id, product_id, dough_batch_id, cheese_batch_id, quantity) -> JsonObject:
    """Create -> start-baking -> rack. Returns the HOLDING run."""
    run = create_run(client, daypart_id, product_id, dough_batch_id, cheese_batch_id, quantity)
    start_baking(client, run["id"])
    return rack_run(client, run["id"])


def holding_units(client, run_id, limit=None) -> list:
    """HOLDING units of a run, as a plain list.

    With ``limit`` given, returns that single page (for pagination tests).
    Without it, enumerates every page — PRD: "the `limit` parameter caps the
    number of items returned: it defaults to 10 when omitted" — so a helper
    never silently truncates the rack to the first 10 units.
    """
    params = {"production_run_id": run_id, "status": "HOLDING"}
    if limit is not None:
        params["limit"] = limit
        resp = client.list_hold_units(make_crew_headers(), params=params)
        body = get_success_data(resp)
        return body if isinstance(body, list) else body
    collected = []
    offset = 0
    page_size = 100  # PRD upper bound for limit
    while True:
        params["limit"] = page_size
        params["offset"] = offset
        resp = client.list_hold_units(make_crew_headers(), params=params)
        body = get_success_data(resp)
        page = body if isinstance(body, list) else body
        collected.extend(page)
        if len(page) < page_size:
            return collected
        offset += page_size


def open_day_with_stock(
    client,
    business_date,
    active_at="10:35:00Z",
    run_quantity=3,
    rack_capacity=20,
    base_demand_units=10,
    batch_size=None,
    product_overrides=None,
    daypart_overrides=None,
) -> Bundle:
    """Full made-ahead pipeline with a strictly forward-moving clock.

    Sequence: clock to 08:00 -> store day + LUNCH daypart (PLANNING) -> dough and
    cheese batches mixed -> dough to PROOFING -> clock to 10:05 -> dough PROOFED,
    cheese RESTING -> clock to ``active_at`` (default 10:35, inside the default
    600-840 window) -> cheese READY -> store day opened (the daypart auto-activates
    because the clock is already inside its window) -> product -> one run racked
    (HOLDING) with ``run_quantity`` fresh hold units.

    Returns Bundle(store_day, daypart, product, dough_batch, cheese_batch, run).
    """
    set_clock(client, "%sT08:00:00Z" % business_date)
    # The rack_capacity / base_demand_units parameters exist precisely to size
    # the daypart this helper builds; dropping them silently would rack
    # `run_quantity` units into the factory-default rack.
    merged_daypart_overrides = {
        "rack_capacity": rack_capacity,
        "base_demand_units": base_demand_units,
    }
    merged_daypart_overrides.update(daypart_overrides or {})
    bundle = planned_store_day(client, business_date, merged_daypart_overrides)
    db = create_proofed_dough_batch(
        client, bundle.store_day["id"], size_units=batch_size or max(10, run_quantity)
    )
    cb = create_cheese_batch(
        client, bundle.store_day["id"], size_units=batch_size or max(10, run_quantity)
    )
    advance_dough(client, db["id"])  # MIXING -> PROOFING at 08:00
    set_clock(client, "%sT10:05:00Z" % business_date)
    advance_dough(client, db["id"])  # PROOFING -> PROOFED (>= mix + 120 min)
    advance_cheese(client, cb["id"])  # PREPPING -> RESTING
    set_clock(client, "%sT%s" % (business_date, active_at))
    advance_cheese(client, cb["id"])  # RESTING -> READY (>= prep + 30 min)
    product = create_product(client, **(product_overrides or {}))
    get_success_data(
        client.open_store_day(bundle.store_day["id"], make_manager_headers())
    )
    daypart = read_daypart(client, bundle.daypart["id"])
    assert daypart["status"] == "ACTIVE", (
        "daypart did not auto-activate at %s" % active_at
    )
    run = racked_run(
        client,
        daypart["id"],
        product["id"],
        db["id"],
        cb["id"],
        run_quantity,
    )
    assert run["status"] == "HOLDING"
    return Bundle(
        store_day=read_store_day(client, bundle.store_day["id"]),
        daypart=daypart,
        product=product,
        dough_batch=get_success_data(client.get_dough_batch(db["id"], make_crew_headers())),
        cheese_batch=get_success_data(client.get_cheese_batch(cb["id"], make_crew_headers())),
        run=run,
    )


# ----------------------------------------------------------------------- orders
def create_order(client, store_day_id, daypart_id, customer_id, kind, lines, role=None) -> JsonObject:
    headers = (
        make_customer_headers(customer_id)
        if kind in (OrderKind.PORTAL_STANDARD, OrderKind.PORTAL_PREORDER)
        else make_shift_lead_headers()
    )
    if role == "Customer":
        headers = make_customer_headers(customer_id)
    elif role == "ShiftLead":
        headers = make_shift_lead_headers()
    return get_success_data(
        client.create_order(
            factories.order_payload(store_day_id, daypart_id, customer_id, kind, lines),
            headers,
        )
    )


def read_order(client, order_id, customer_id=None) -> JsonObject:
    headers = (
        make_customer_headers(customer_id)
        if customer_id is not None
        else make_manager_headers()
    )
    return get_success_data(client.get_order(order_id, headers))


def pay_order(client, order_id, customer_id) -> JsonObject:
    return get_success_data(client.pay_order(order_id, make_customer_headers(customer_id)))


def start_preparation(client, order_id) -> JsonObject:
    return get_success_data(client.start_preparation(order_id, make_crew_headers()))


def mark_ready(client, order_id) -> JsonObject:
    return get_success_data(client.mark_ready(order_id, make_crew_headers()))


def claim_order(client, order_id, customer_id, pickup_code) -> JsonObject:
    return get_success_data(
        client.claim_order(order_id, {"pickup_code": pickup_code}, make_customer_headers(customer_id))
    )


def paid_portal_order(client, store_day_id, daypart_id, customer_id, product_id, quantity=1, kind=OrderKind.PORTAL_STANDARD) -> JsonObject:
    """PORTAL order placed and paid, still PLACED."""
    order = create_order(
        client,
        store_day_id,
        daypart_id,
        customer_id,
        kind,
        [factories.order_line(product_id, quantity=quantity)],
    )
    return pay_order(client, order["id"], customer_id)


def ready_portal_order(client, store_day_id, daypart_id, customer_id, product_id, quantity=1) -> JsonObject:
    """PORTAL_STANDARD order paid, prepared, and marked READY (needs an IDLE slot)."""
    order = paid_portal_order(client, store_day_id, daypart_id, customer_id, product_id, quantity=quantity)
    start_preparation(client, order["id"])
    return mark_ready(client, order["id"])


def picked_up_portal_order(client, store_day_id, daypart_id, customer_id, product_id, quantity=1) -> JsonObject:
    """Full portal lifecycle through PICKED_UP (needs an IDLE slot)."""
    order = ready_portal_order(client, store_day_id, daypart_id, customer_id, product_id, quantity=quantity)
    return claim_order(client, order["id"], customer_id, order["pickup_code"])


__all__ = [
    "Bundle",
    "set_clock",
    "create_store_day",
    "read_store_day",
    "create_daypart",
    "read_daypart",
    "create_demand_event",
    "create_product",
    "create_locker_slot",
    "planned_store_day",
    "open_store_day_with_active_daypart",
    "create_proofed_dough_batch",
    "advance_dough",
    "create_cheese_batch",
    "advance_cheese",
    "ready_batches",
    "create_run",
    "read_run",
    "start_baking",
    "rack_run",
    "racked_run",
    "holding_units",
    "open_day_with_stock",
    "create_order",
    "read_order",
    "pay_order",
    "start_preparation",
    "mark_ready",
    "claim_order",
    "paid_portal_order",
    "ready_portal_order",
    "picked_up_portal_order",
]

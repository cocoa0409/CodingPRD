"""Cross-entity state gates: runs blocked by batch state; preorders by daypart state."""

from test_helpers import (
    ApiErrorId,
    OrderKind,
    fixtures,
    factories,
    make_crew_headers,
    make_customer_headers,
    make_manager_headers,
    validate_error,
    validate_success,
)


def _planned_run_with_proofing_dough(client, business_date="2026-09-22"):
    """ACTIVE daypart; dough only PROOFING (proof floor not reached); cheese READY;
    a PLANNED run referencing both."""
    fixtures.set_clock(client, "%sT08:00:00Z" % business_date)
    day = fixtures.planned_store_day(client, business_date)
    db = fixtures.create_proofed_dough_batch(client, day.store_day["id"], size_units=10)
    cb = fixtures.create_cheese_batch(client, day.store_day["id"], size_units=10)
    product = fixtures.create_product(client)
    fixtures.advance_dough(client, db["id"])  # MIXING -> PROOFING at 08:00
    fixtures.advance_cheese(client, cb["id"])  # PREPPING -> RESTING
    fixtures.set_clock(client, "%sT10:35:00Z" % business_date)
    fixtures.advance_cheese(client, cb["id"])  # RESTING -> READY
    fixtures.get_success_data(
        client.open_store_day(day.store_day["id"], make_manager_headers())
    )
    run = fixtures.create_run(
        client, day.daypart["id"], product["id"], db["id"], cb["id"], 2
    )
    return fixtures.Bundle(
        store_day=day.store_day, daypart=day.daypart, product=product,
        dough_batch=db, cheese_batch=cb, run=run,
    )


def test_start_baking_blocked_while_dough_still_proofing(client):
    """Daypart ACTIVE and cheese READY are not enough: dough PROOFING blocks the
    bake with ERR_DOUGH_UNAVAILABLE and the run stays PLANNED.

    "the referenced dough batch to be `PROOFED` with `remaining_units` of at
    least the run's `quantity` (otherwise `ERR_DOUGH_UNAVAILABLE`)"

    Design: Difficulty/cross_entity_state_dependency/production_run_start_baking_gated_by_dough_batch_state
    """
    bundle = _planned_run_with_proofing_dough(client)

    dough = fixtures.get_success_data(
        client.get_dough_batch(bundle.dough_batch["id"], make_crew_headers())
    )
    assert dough["status"] == "PROOFING"

    resp = client.start_baking(bundle.run["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_DOUGH_UNAVAILABLE)

    run = fixtures.read_run(client, bundle.run["id"])
    assert run["status"] == "PLANNED"
    cheese = fixtures.get_success_data(
        client.get_cheese_batch(bundle.cheese_batch["id"], make_crew_headers())
    )
    assert cheese["remaining_units"] == 10, "cheese untouched by the rejected bake"


def test_start_baking_succeeds_once_dough_proofed(client):
    """Once the dough reaches PROOFED the same call succeeds — only the dough
    state was blocking.

    "the referenced dough batch to be `PROOFED` with `remaining_units` of at
    least the run's `quantity` (otherwise `ERR_DOUGH_UNAVAILABLE`)"

    Design: Difficulty/cross_entity_state_dependency/production_run_start_baking_gated_by_dough_batch_state
    """
    bundle = _planned_run_with_proofing_dough(client)

    # Clock past the 120-minute proof floor (mix 08:00, PROOFING at 08:00).
    fixtures.set_clock(client, "2026-09-22T10:05:00Z")
    fixtures.advance_dough(client, bundle.dough_batch["id"])
    fixtures.set_clock(client, "2026-09-22T10:35:00Z")

    baked = validate_success(
        client.start_baking(bundle.run["id"], make_crew_headers()), 200
    )
    assert baked["status"] == "BAKING"
    dough = fixtures.get_success_data(
        client.get_dough_batch(bundle.dough_batch["id"], make_crew_headers())
    )
    assert dough["remaining_units"] == 8


def _paid_preorder_for_planned_daypart(client, business_date="2026-09-23"):
    """Store day OPEN but clock before the DINNER window, so the daypart stays
    PLANNED; a PORTAL_PREORDER for 2 units placed and paid."""
    bundle = fixtures.planned_store_day(
        client,
        business_date,
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1080,
        },
    )
    fixtures.get_success_data(
        client.open_store_day(bundle.store_day["id"], make_manager_headers())
    )
    fixtures.set_clock(client, "%sT10:00:00Z" % business_date)
    product = fixtures.create_product(client)
    order = validate_success(
        client.create_order(
            factories.order_payload(
                bundle.store_day["id"],
                bundle.daypart["id"],
                "cust-8",
                OrderKind.PORTAL_PREORDER,
                [factories.order_line(product["id"], quantity=2, customized=False)],
            ),
            make_customer_headers("cust-8"),
        ),
        201,
    )
    fixtures.pay_order(client, order["id"], "cust-8")
    return bundle, product, order


def test_preorder_preparation_blocked_while_daypart_planned(client):
    """The payment axis is satisfied, but a PAID PORTAL_PREORDER cannot prepare
    while its promised daypart is still PLANNED.

    "a `PORTAL_PREORDER` may only begin preparation once its promised daypart is
    `ACTIVE` (otherwise `ERR_PREORDER_DAYPART_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/preorder_start_preparation_gated_by_promised_daypart_state
    """
    bundle, _product, order = _paid_preorder_for_planned_daypart(client)

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["status"] == "PLANNED"

    resp = client.start_preparation(order["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_PREORDER_DAYPART_NOT_ACTIVE)

    stored = fixtures.read_order(client, order["id"], customer_id="cust-8")
    assert stored["fulfillment_status"] == "PLACED"
    assert stored["payment_status"] == "PAID", "the payment axis is unaffected"


def test_preorder_gate_is_daypart_state_not_payment(client):
    """A PORTAL_STANDARD order against the same still-PLANNED daypart fails at
    placement — proving the preorder gate is the promised daypart's state.

    "while `PORTAL_STANDARD` and `COUNTER` orders require the daypart to already
    be `ACTIVE` (otherwise `ERR_DAYPART_NOT_ACTIVE`)"
    "a `PORTAL_PREORDER` may only begin preparation once its promised daypart is
    `ACTIVE` (otherwise `ERR_PREORDER_DAYPART_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/preorder_start_preparation_gated_by_promised_daypart_state
    """
    bundle, product, order = _paid_preorder_for_planned_daypart(client)

    resp = client.start_preparation(order["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_PREORDER_DAYPART_NOT_ACTIVE)

    create_resp = client.create_order(
        factories.order_payload(
            bundle.store_day["id"],
            bundle.daypart["id"],
            "cust-8b",
            OrderKind.PORTAL_STANDARD,
            [factories.order_line(product["id"], quantity=1, customized=False)],
        ),
        make_customer_headers("cust-8b"),
    )
    validate_error(create_resp, ApiErrorId.ERR_DAYPART_NOT_ACTIVE)

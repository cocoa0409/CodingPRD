"""Corner coverage of endpoint behavior: pagination envelope and batch consumption."""

from test_helpers import (
    OrderKind,
    fixtures,
    factories,
    make_crew_headers,
    make_manager_headers,
    make_shift_lead_headers,
    validate_paginated,
    validate_success,
)


def test_list_orders_pagination_envelope(client):
    """limit=1 over two orders pages the array and reports the totals in meta.

    "The `limit` parameter caps the number of items returned: it defaults to 10
    when omitted, accepts a minimum of 1, and is bounded above at 100. The
    `offset` parameter skips a number of items before returning the page and
    defaults to 0."
    "List responses carry `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the response envelope."

    Design: Corner/endpoints/list_orders_pagination_envelope
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-11-02", "2026-11-02T11:00:00Z"
    )
    product = fixtures.create_product(client)
    for walk_in in ("walk-e1", "walk-e2"):
        validate_success(
            client.create_order(
                factories.order_payload(
                    day.store_day["id"],
                    day.daypart["id"],
                    walk_in,
                    OrderKind.COUNTER,
                    [factories.order_line(product["id"], quantity=1, customized=False)],
                ),
                make_shift_lead_headers(),
            ),
            201,
        )

    rows, meta = validate_paginated(
        client.list_orders(
            make_manager_headers(),
            params={"store_day_id": day.store_day["id"], "limit": 1, "offset": 0},
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_start_baking_consumes_both_batches(client):
    """One start-baking decrements both pools by the quantity; a batch at zero
    depletes automatically.

    "Starting the bake decrements both batches' `remaining_units` by the run's
    `quantity` — a batch driven to zero depletes automatically per §3.2 — stamps
    `baked_at`, and moves the run to `BAKING`."
    "When baking consumption drives `remaining_units` to zero, the batch moves
    automatically from `PROOFED` to the terminal `DEPLETED` state."

    Design: Corner/endpoints/start_baking_consumes_both_batches
    """
    business_date = "2026-11-03"
    fixtures.set_clock(client, "%sT08:00:00Z" % business_date)
    day = fixtures.planned_store_day(client, business_date)
    db = fixtures.create_proofed_dough_batch(client, day.store_day["id"], size_units=3)
    cb = fixtures.create_cheese_batch(client, day.store_day["id"], size_units=3)
    product = fixtures.create_product(client)
    fixtures.advance_dough(client, db["id"])
    fixtures.advance_cheese(client, cb["id"])
    fixtures.set_clock(client, "%sT10:05:00Z" % business_date)
    fixtures.advance_dough(client, db["id"])
    fixtures.advance_cheese(client, cb["id"])
    fixtures.set_clock(client, "%sT10:35:00Z" % business_date)
    fixtures.get_success_data(
        client.open_store_day(day.store_day["id"], make_manager_headers())
    )
    run = fixtures.create_run(
        client, day.daypart["id"], product["id"], db["id"], cb["id"], 3
    )

    baked = validate_success(client.start_baking(run["id"], make_crew_headers()), 200)
    assert baked["status"] == "BAKING"

    dough = fixtures.get_success_data(client.get_dough_batch(db["id"], make_crew_headers()))
    assert dough["remaining_units"] == 0
    assert dough["status"] == "DEPLETED"

    cheese = fixtures.get_success_data(
        client.get_cheese_batch(cb["id"], make_crew_headers())
    )
    assert cheese["remaining_units"] == 0
    assert cheese["status"] == "DEPLETED"

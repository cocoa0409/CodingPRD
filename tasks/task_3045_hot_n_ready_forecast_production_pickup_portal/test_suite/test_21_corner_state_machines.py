"""Corner coverage of state machines: batches, hold expiry, order closeout guards."""

from test_helpers import (
    ApiErrorId,
    OrderKind,
    fixtures,
    factories,
    make_crew_headers,
    make_customer_headers,
    make_manager_headers,
    make_shift_lead_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _proofed_dough(client, business_date="2026-10-03"):
    """Dough batch at PROOFED (mixed 08:00, proofing 08:00, proofed at 10:05).
    Leaves the clock at 10:05 inside a LUNCH window."""
    fixtures.set_clock(client, "%sT08:00:00Z" % business_date)
    sd = fixtures.create_store_day(client, business_date)
    fixtures.create_daypart(client, sd["id"])
    db = fixtures.create_proofed_dough_batch(client, sd["id"], size_units=5)
    fixtures.advance_dough(client, db["id"])  # MIXING -> PROOFING at 08:00
    fixtures.set_clock(client, "%sT10:05:00Z" % business_date)
    proofed = fixtures.advance_dough(client, db["id"])  # PROOFING -> PROOFED
    assert proofed["status"] == "PROOFED"
    return sd, db


def test_dough_batch_advance_from_proofed_rejected(client):
    """PROOFED has no forward transition via advance: ERR_BATCH_STATE, unchanged.

    "Calling advance on a batch whose state has no forward transition is
    rejected with `ERR_BATCH_STATE`."

    Design: Corner/state_machines/dough_batch_advance_from_proofed_rejected
    """
    _sd, db = _proofed_dough(client)

    resp = client.advance_dough_batch(db["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_BATCH_STATE)

    stored = fixtures.get_success_data(
        client.get_dough_batch(db["id"], make_crew_headers())
    )
    assert stored["status"] == "PROOFED"


def test_dough_batch_expires_at_max_proof_window(client):
    """At proofed_at + 240 minutes exactly the sweep moves the batch to EXPIRED
    and start-baking fails with ERR_DOUGH_UNAVAILABLE.

    "once the clock reaches `proofed_at` plus 240 minutes (again inclusive), the
    batch is swept to the terminal `EXPIRED` state and its `remaining_units` are
    frozen, unusable."
    "the referenced dough batch to be `PROOFED` with `remaining_units` of at
    least the run's `quantity` (otherwise `ERR_DOUGH_UNAVAILABLE`)"

    Design: Corner/state_machines/dough_batch_expires_at_max_proof_window
    """
    business_date = "2026-10-04"
    fixtures.set_clock(client, "%sT08:00:00Z" % business_date)
    sd = fixtures.create_store_day(client, business_date)
    dp = fixtures.create_daypart(client, sd["id"])
    fixtures.get_success_data(client.open_store_day(sd["id"], make_manager_headers()))
    db = fixtures.create_proofed_dough_batch(client, sd["id"], size_units=5)
    cb = fixtures.create_cheese_batch(client, sd["id"], size_units=5)
    product = fixtures.create_product(client)
    fixtures.advance_dough(client, db["id"])  # MIXING -> PROOFING at 08:00
    fixtures.advance_cheese(client, cb["id"])  # PREPPING -> RESTING
    fixtures.set_clock(client, "%sT10:05:00Z" % business_date)
    fixtures.advance_dough(client, db["id"])  # PROOFED at 10:05
    fixtures.advance_cheese(client, cb["id"])  # READY
    run = fixtures.create_run(client, dp["id"], product["id"], db["id"], cb["id"], 1)

    # proofed_at 10:05 + 240 minutes = 14:05 (inclusive upper bound).
    fixtures.set_clock(client, "%sT14:05:00Z" % business_date)
    dough = fixtures.get_success_data(
        client.get_dough_batch(db["id"], make_crew_headers())
    )
    assert dough["status"] == "EXPIRED"

    resp = client.start_baking(run["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_DOUGH_UNAVAILABLE)


def test_hold_unit_expired_exactly_at_hold_expires_at(client):
    """One minute before expiry the unit survives; at racked_at + 30 exactly the
    sweep discards it HOLD_EXPIRED with a waste-log row.

    "the clock must be strictly before the unit's `hold_expires_at`, because the
    boundary instant itself counts as expired"
    "And it is **discarded**, moving from `HOLDING` to the terminal `DISCARDED`
    state, either automatically when the expiry sweep finds the clock at or past
    `hold_expires_at`, or manually by a `ShiftLead`."

    Design: Corner/state_machines/hold_unit_expired_exactly_at_hold_expires_at
    """
    business_date = "2026-10-05"
    bundle = fixtures.open_day_with_stock(
        client, business_date, active_at="10:35:00Z", run_quantity=1, batch_size=5
    )
    units = fixtures.holding_units(client, bundle.run["id"])
    unit_id = units[0]["id"]

    fixtures.set_clock(client, "%sT11:04:00Z" % business_date)
    before = fixtures.get_success_data(client.get_hold_unit(unit_id, make_crew_headers()))
    assert before["status"] == "HOLDING", "one minute before expiry the unit survives"

    fixtures.set_clock(client, "%sT11:05:00Z" % business_date)
    after = fixtures.get_success_data(client.get_hold_unit(unit_id, make_crew_headers()))
    assert after["status"] == "DISCARDED", "the boundary instant itself is expired"
    assert after["discarded_reason"] == "HOLD_EXPIRED"

    logs, meta = validate_paginated(
        client.list_waste_logs_of(bundle.store_day["id"], make_manager_headers())
    )
    assert meta["total_count"] == 1
    assert logs[0]["reason"] == "HOLD_EXPIRED"
    assert logs[0]["donated"] is False


def _ready_portal(client, business_date="2026-10-06"):
    day = fixtures.open_store_day_with_active_daypart(
        client, business_date, "%sT11:00:00Z" % business_date
    )
    fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)
    order = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-c1", product["id"]
    )
    return day, product, order


def test_order_cancel_after_ready_rejected(client):
    """Cancel exists only from PLACED or IN_PREPARATION; a READY order refuses.

    "A customer may cancel an order while it is `PLACED` or `IN_PREPARATION`
    (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/order_cancel_after_ready_rejected
    """
    _day, _product, order = _ready_portal(client)
    assert order["fulfillment_status"] == "READY"

    resp = client.cancel_order(order["id"], make_customer_headers("cust-c1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    stored = fixtures.read_order(client, order["id"], customer_id="cust-c1")
    assert stored["fulfillment_status"] == "READY"
    assert stored["payment_status"] == "PAID"


def test_store_day_close_blocked_by_occupied_locker(client):
    """Every daypart CLOSED is not enough: one OCCUPIED slot blocks the close.

    "Closing the store day is a `StoreManager` action with two guards, checked
    in order: every daypart of the day must already be `CLOSED` (otherwise
    `ERR_DAYPARTS_STILL_ACTIVE`), and no locker slot of the day may be
    `OCCUPIED` (otherwise `ERR_LOCKER_SLOTS_OCCUPIED`)."

    Design: Corner/state_machines/store_day_close_blocked_by_occupied_locker
    """
    day, _product, order = _ready_portal(client, business_date="2026-10-07")
    # The READY order occupies the only slot; closing the daypart is allowed.
    fixtures.get_success_data(
        client.close_daypart(day.daypart["id"], make_shift_lead_headers())
    )

    resp = client.close_store_day(day.store_day["id"], make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_LOCKER_SLOTS_OCCUPIED)

    stored = fixtures.read_store_day(client, day.store_day["id"])
    assert stored["status"] == "OPEN"


def test_daypart_close_blocked_by_baking_run(client):
    """A BAKING run blocks the daypart close; the daypart stays ACTIVE.

    "Closing requires that no production run of the daypart still be `BAKING` —
    outstanding bakes block the close with `ERR_RUNS_IN_PROGRESS`."

    Design: Corner/state_machines/daypart_close_blocked_by_baking_run
    """
    business_date = "2026-10-08"
    fixtures.set_clock(client, "%sT08:00:00Z" % business_date)
    day = fixtures.planned_store_day(client, business_date)
    db = fixtures.create_proofed_dough_batch(client, day.store_day["id"], size_units=5)
    cb = fixtures.create_cheese_batch(client, day.store_day["id"], size_units=5)
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
        client, day.daypart["id"], product["id"], db["id"], cb["id"], 1
    )
    fixtures.start_baking(client, run["id"])

    resp = client.close_daypart(day.daypart["id"], make_shift_lead_headers())
    validate_error(resp, ApiErrorId.ERR_RUNS_IN_PROGRESS)

    stored = fixtures.read_daypart(client, day.daypart["id"])
    assert stored["status"] == "ACTIVE"


def test_open_without_dayparts_rejected(client):
    """Opening a day with no dayparts fails and the day stays PLANNING.

    "It requires at least one daypart to exist for the day in `PLANNED` status;
    with none defined, the open is rejected with `ERR_NO_DAYPARTS_DEFINED`."

    Design: Corner/state_machines/open_without_dayparts_rejected
    """
    sd = fixtures.create_store_day(client, "2026-10-09")

    resp = client.open_store_day(sd["id"], make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_NO_DAYPARTS_DEFINED)

    stored = fixtures.read_store_day(client, sd["id"])
    assert stored["status"] == "PLANNING"


def test_double_claim_rejected_second_time(client):
    """The first claim succeeds; the second hits the terminal-state lockdown.

    "claiming an order that is not `READY` yields `ERR_INVALID_STATE`"
    "A successful claim moves the order to the terminal `PICKED_UP` state"

    Design: Corner/state_machines/double_claim_rejected_second_time
    """
    _day, _product, order = _ready_portal(client, business_date="2026-10-10")
    claimed = fixtures.claim_order(client, order["id"], "cust-c1", order["pickup_code"])
    assert claimed["fulfillment_status"] == "PICKED_UP"

    resp = client.claim_order(
        order["id"], {"pickup_code": order["pickup_code"]},
        make_customer_headers("cust-c1"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    stored = fixtures.read_order(client, order["id"], customer_id="cust-c1")
    assert stored["fulfillment_status"] == "PICKED_UP"


def test_paid_preorder_auto_readies_at_daypart_activation(client):
    """The auto-activation sweep readies a PAID preorder: READY with a code and
    an occupied slot, no crew action.

    "any daypart whose activation window has been reached while its store day
    is `OPEN` auto-activates from `PLANNED` to `ACTIVE`."

    Design: Corner/state_machines/paid_preorder_auto_readies_at_daypart_activation
    """
    bundle = fixtures.planned_store_day(
        client,
        "2026-10-11",
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1020,
        },
    )
    slot = fixtures.create_locker_slot(client, bundle.store_day["id"], slot_number=1)
    fixtures.get_success_data(
        client.open_store_day(bundle.store_day["id"], make_manager_headers())
    )
    fixtures.set_clock(client, "2026-10-11T10:00:00Z")
    product = fixtures.create_product(client)
    order = validate_success(
        client.create_order(
            factories.order_payload(
                bundle.store_day["id"],
                bundle.daypart["id"],
                "cust-c4",
                OrderKind.PORTAL_PREORDER,
                [factories.order_line(product["id"], quantity=1, customized=False)],
            ),
            make_customer_headers("cust-c4"),
        ),
        201,
    )
    fixtures.pay_order(client, order["id"], "cust-c4")

    # 16:00Z == window_start_minute 960: auto-activation fires.
    fixtures.set_clock(client, "2026-10-11T16:00:00Z")

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["status"] == "ACTIVE"

    stored = fixtures.read_order(client, order["id"], customer_id="cust-c4")
    assert stored["fulfillment_status"] == "READY", (
        "the activation sweep readies PAID preorders without crew action"
    )
    assert stored.get("pickup_code"), "a pickup code is minted at readiness"

    slot_after = validate_success(
        client.get_locker_slot(slot["id"], make_manager_headers()), 200
    )
    assert slot_after["status"] == "OCCUPIED"
    assert slot_after["current_order_id"] == order["id"]

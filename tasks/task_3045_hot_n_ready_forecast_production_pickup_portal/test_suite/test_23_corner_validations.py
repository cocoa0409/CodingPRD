"""Corner coverage of validation rules: windows, promo discipline, capacity, claims."""

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


def test_daypart_window_overlap_rejected_adjacency_allowed(client):
    """Half-open daypart windows: one minute of true overlap is rejected while a
    touching window is accepted.

    "Two dayparts of the same store day may not overlap in time under the
    half-open minute semantics of §2.7, regardless of label; touching windows
    are permitted, but any true overlap is rejected with
    `ERR_DAYPART_WINDOW_OVERLAP`."

    Design: Corner/validations/daypart_window_overlap_rejected
    """
    sd = fixtures.create_store_day(client, "2026-10-18")
    manager = make_manager_headers()
    validate_success(
        client.create_daypart(sd["id"], factories.daypart_payload(), manager), 201
    )

    resp = client.create_daypart(
        sd["id"],
        factories.daypart_payload(
            label="DINNER", window_start_minute=839, window_end_minute=1080
        ),
        manager,
    )
    validate_error(resp, ApiErrorId.ERR_DAYPART_WINDOW_OVERLAP)

    adjacent = validate_success(
        client.create_daypart(
            sd["id"],
            factories.daypart_payload(
                label="DINNER", window_start_minute=840, window_end_minute=1080
            ),
            manager,
        ),
        201,
    )
    assert adjacent["window_start_minute"] == 840


def test_daypart_window_inversion_rejected(client):
    """An end not strictly greater than the start fails the range rule with 400.

    "the start must be at least 0 and the end must be strictly greater than the
    start, otherwise `ERR_VALIDATION`"

    Design: Corner/validations/daypart_window_inversion_rejected
    """
    sd = fixtures.create_store_day(client, "2026-10-19")

    resp = client.create_daypart(
        sd["id"],
        factories.daypart_payload(window_start_minute=840, window_end_minute=840),
        make_manager_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_promo_price_must_be_below_list(client):
    """promo equal to list violates the strict inequality at creation.

    "Promotional price points must sit strictly below the list price: a
    `promo_price_cents` that is present but not less than `list_price_cents` is
    rejected with `ERR_PROMO_PRICE_INVALID`, both at creation and on update."

    Design: Corner/validations/promo_price_must_be_below_list
    """
    resp = client.create_product(
        factories.product_payload(list_price_cents=600, promo_price_cents=600),
        make_manager_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_PROMO_PRICE_INVALID)


def test_promo_price_locked_while_open_day_references_product(client):
    """With a non-CLOSED run referencing the product on an OPEN day, the promo
    price is frozen: the edit is rejected and the value stays.

    "While `promo_locked` is true, the promotional price may not be created,
    changed, or removed — any such attempt is rejected with
    `ERR_PROMO_PRICE_LOCKED` — although other attributes remain editable."

    Design: Corner/validations/promo_price_locked_while_open_day_references_product
    """
    bundle = fixtures.open_day_with_stock(
        client,
        "2026-10-20",
        active_at="10:35:00Z",
        run_quantity=1,
        batch_size=5,
        product_overrides={"promo_price_cents": 500},
    )

    product = fixtures.get_success_data(
        client.get_product(bundle.product["id"], make_manager_headers())
    )
    assert product["promo_locked"] is True

    resp = client.update_product(
        bundle.product["id"], {"promo_price_cents": 450}, make_manager_headers()
    )
    validate_error(resp, ApiErrorId.ERR_PROMO_PRICE_LOCKED)

    stored = fixtures.get_success_data(
        client.get_product(bundle.product["id"], make_manager_headers())
    )
    assert stored["promo_locked"] is True
    assert stored["promo_price_cents"] == 500, "the locked price is unchanged"


def test_rack_capacity_exceeded_boundary(client):
    """Occupancy 3 + 1 racks at capacity 4; the next unit would exceed and is
    rejected wholesale.

    "the daypart's current rack occupancy — the count of its hold units in
    `HOLDING` or `ALLOCATED` status — plus the run's `quantity` must not exceed
    the daypart's `rack_capacity`, otherwise the rack is rejected wholesale with
    `ERR_RACK_CAPACITY_EXCEEDED`."

    Design: Corner/validations/rack_capacity_exceeded_boundary
    """
    business_date = "2026-10-21"
    fixtures.set_clock(client, "%sT08:00:00Z" % business_date)
    day = fixtures.planned_store_day(
        client, business_date, daypart_overrides={"rack_capacity": 4}
    )
    db = fixtures.create_proofed_dough_batch(client, day.store_day["id"], size_units=10)
    cb = fixtures.create_cheese_batch(client, day.store_day["id"], size_units=10)
    fixtures.advance_dough(client, db["id"])
    fixtures.advance_cheese(client, cb["id"])
    fixtures.set_clock(client, "%sT10:05:00Z" % business_date)
    fixtures.advance_dough(client, db["id"])
    fixtures.advance_cheese(client, cb["id"])
    fixtures.set_clock(client, "%sT10:35:00Z" % business_date)
    fixtures.get_success_data(
        client.open_store_day(day.store_day["id"], make_manager_headers())
    )
    product = fixtures.create_product(client)

    run_a = fixtures.racked_run(
        client, day.daypart["id"], product["id"], db["id"], cb["id"], 3
    )
    run_b = fixtures.racked_run(
        client, day.daypart["id"], product["id"], db["id"], cb["id"], 1
    )
    assert run_a["status"] == "HOLDING" and run_b["status"] == "HOLDING"

    run_c = fixtures.create_run(
        client, day.daypart["id"], product["id"], db["id"], cb["id"], 1
    )
    fixtures.start_baking(client, run_c["id"])

    resp = client.rack_run(run_c["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_RACK_CAPACITY_EXCEEDED)

    stored = fixtures.read_run(client, run_c["id"])
    assert stored["status"] == "BAKING"


def test_preorder_requires_planned_daypart(client):
    """A PORTAL_PREORDER against an already-ACTIVE daypart is rejected.

    "a `PORTAL_PREORDER` promises a daypart that is still `PLANNED` (otherwise
    `ERR_PREORDER_DAYPART_NOT_PLANNED`)"

    Design: Corner/validations/preorder_requires_planned_daypart
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-10-22", "2026-10-22T11:00:00Z"
    )
    product = fixtures.create_product(client)

    resp = client.create_order(
        factories.order_payload(
            day.store_day["id"],
            day.daypart["id"],
            "cust-c9",
            OrderKind.PORTAL_PREORDER,
            [factories.order_line(product["id"], quantity=1, customized=False)],
        ),
        make_customer_headers("cust-c9"),
    )
    validate_error(resp, ApiErrorId.ERR_PREORDER_DAYPART_NOT_PLANNED)

    ok = validate_success(
        client.create_order(
            factories.order_payload(
                day.store_day["id"],
                day.daypart["id"],
                "cust-c9b",
                OrderKind.PORTAL_STANDARD,
                [factories.order_line(product["id"], quantity=1, customized=False)],
            ),
            make_customer_headers("cust-c9b"),
        ),
        201,
    )
    assert ok["kind"] == "PORTAL_STANDARD"


def _ready_portal_and_counter(client, business_date="2026-10-23"):
    day = fixtures.open_store_day_with_active_daypart(
        client, business_date, "%sT11:00:00Z" % business_date
    )
    fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)
    portal = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-c10", product["id"]
    )
    counter = validate_success(
        client.create_order(
            factories.order_payload(
                day.store_day["id"],
                day.daypart["id"],
                "walk-c11",
                OrderKind.COUNTER,
                [factories.order_line(product["id"], quantity=1, customized=False)],
            ),
            make_shift_lead_headers(),
        ),
        201,
    )
    fixtures.start_preparation(client, counter["id"])
    counter = fixtures.mark_ready(client, counter["id"])
    return day, portal, counter


def test_claim_wrong_code_and_counter_claim_rejected(client):
    """Wrong code on a READY portal order is ERR_PICKUP_CODE_INVALID; claiming a
    COUNTER order is ERR_NOT_PORTAL_ORDER.

    "Claiming a `COUNTER` order is rejected with `ERR_NOT_PORTAL_ORDER`;
    claiming an order that is not `READY` yields `ERR_INVALID_STATE`; a code
    that does not match is rejected with `ERR_PICKUP_CODE_INVALID`"

    Design: Corner/validations/claim_wrong_code_and_counter_claim_rejected
    """
    _day, portal, counter = _ready_portal_and_counter(client)

    resp_wrong = client.claim_order(
        portal["id"], {"pickup_code": "999999"}, make_customer_headers("cust-c10")
    )
    validate_error(resp_wrong, ApiErrorId.ERR_PICKUP_CODE_INVALID)

    resp_counter = client.claim_order(
        counter["id"], {"pickup_code": "999999"}, make_customer_headers("walk-c11")
    )
    validate_error(resp_counter, ApiErrorId.ERR_NOT_PORTAL_ORDER)

    stored = fixtures.read_order(client, portal["id"], customer_id="cust-c10")
    assert stored["fulfillment_status"] == "READY"


def test_pickup_code_valid_at_exact_expiry_instant(client):
    """The claim boundary is inclusive: at code_expires_at exactly the claim
    succeeds.

    "a claim arriving after `code_expires_at` — the boundary itself is still
    valid, so the clock sitting exactly at expiry claims successfully — is
    rejected with `ERR_PICKUP_CODE_EXPIRED`."

    Design: Corner/validations/pickup_code_valid_at_exact_expiry_instant
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-10-24", "2026-10-24T11:00:00Z"
    )
    fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)
    order = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-c12", product["id"]
    )
    # ready at 11:00Z; code_expires_at is 45 minutes later.
    assert "11:45" in order["code_expires_at"]

    fixtures.set_clock(client, "2026-10-24T11:45:00Z")
    claimed = validate_success(
        client.claim_order(
            order["id"], {"pickup_code": order["pickup_code"]},
            make_customer_headers("cust-c12"),
        ),
        200,
    )
    assert claimed["fulfillment_status"] == "PICKED_UP"


def test_no_show_sweep_refunds_and_logs_waste(client):
    """Past code_expires_at the sweep flips the order EXPIRED_NO_SHOW, refunds
    it, and logs a NO_SHOW row; a late claim then fails on state.

    "a portal order still `READY` once the clock has passed `code_expires_at`
    moves to the terminal `EXPIRED_NO_SHOW` state, a `PAID` order is refunded to
    `REFUNDED`, and its locker slot goes to `CLEANING`."
    "yet each unit is also appended to the waste log with reason `NO_SHOW`
    (donated false, one row per unit)"

    Design: Corner/validations/no_show_sweep_refunds_and_logs_waste
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-10-25", "2026-10-25T11:00:00Z"
    )
    fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)
    order = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-c13", product["id"]
    )

    fixtures.set_clock(client, "2026-10-25T11:46:00Z")

    stored = fixtures.read_order(client, order["id"], customer_id="cust-c13")
    assert stored["fulfillment_status"] == "EXPIRED_NO_SHOW"
    assert stored["payment_status"] == "REFUNDED"

    resp = client.claim_order(
        order["id"], {"pickup_code": order["pickup_code"]},
        make_customer_headers("cust-c13"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    logs, meta = validate_paginated(
        client.list_waste_logs_of(
            day.store_day["id"], make_manager_headers(), params={"reason": "NO_SHOW"}
        )
    )
    assert meta["total_count"] == 1
    assert logs[0]["reason"] == "NO_SHOW"
    assert logs[0]["donated"] is False


def test_mark_ready_without_idle_locker_rejected(client):
    """With the only slot OCCUPIED, the next mark-ready fails and mints no code.

    "the pool is the store day's locker slots in `IDLE` status, and if that pool
    is empty the mark-ready is rejected with `ERR_NO_LOCKER_AVAILABLE`."

    Design: Corner/validations/mark_ready_without_idle_locker_rejected
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-10-26", "2026-10-26T11:00:00Z"
    )
    fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)
    order_a = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-c14", product["id"]
    )
    assert order_a["locker_slot_id"] is not None

    order_b = fixtures.paid_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-c15", product["id"]
    )
    fixtures.start_preparation(client, order_b["id"])

    resp = client.mark_ready(order_b["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_NO_LOCKER_AVAILABLE)

    stored = fixtures.read_order(client, order_b["id"], customer_id="cust-c15")
    assert stored["fulfillment_status"] == "IN_PREPARATION"
    assert stored.get("pickup_code") is None


def test_manual_discard_invalid_reason_rejected(client):
    """NO_SHOW and HOLD_EXPIRED are not manual-discard reasons.

    "A manual discard requires the unit to still be `HOLDING` (otherwise
    `ERR_INVALID_STATE`) and a `reason` of `DAMAGED` or `QUALITY` — any other
    reason, including `HOLD_EXPIRED` or `NO_SHOW`, is rejected with
    `ERR_INVALID_DISCARD_REASON`"

    Design: Corner/validations/manual_discard_invalid_reason_rejected
    """
    bundle = fixtures.open_day_with_stock(
        client, "2026-10-27", active_at="10:35:00Z", run_quantity=1, batch_size=5
    )
    units = fixtures.holding_units(client, bundle.run["id"])

    for bad_reason in ("NO_SHOW", "HOLD_EXPIRED"):
        resp = client.discard_hold_unit(
            units[0]["id"], {"reason": bad_reason}, make_shift_lead_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DISCARD_REASON)

    stored = fixtures.get_success_data(
        client.get_hold_unit(units[0]["id"], make_crew_headers())
    )
    assert stored["status"] == "HOLDING"


def test_customization_rejected_for_locked_product(client):
    """A customized line on a non-customizable product is a 422 even when
    everything else about the order is valid.

    "Customization is the exception, not the rule: any line with `customized`
    set true must reference a product whose `customization_allowed` is true,
    otherwise placement is rejected with `ERR_CUSTOMIZATION_NOT_ALLOWED`."

    Design: Corner/validations/customization_rejected_for_locked_product
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-10-28", "2026-10-28T11:00:00Z"
    )
    product = fixtures.create_product(client)  # customization_allowed false

    resp = client.create_order(
        factories.order_payload(
            day.store_day["id"],
            day.daypart["id"],
            "cust-c16",
            OrderKind.PORTAL_STANDARD,
            [factories.order_line(product["id"], quantity=1, customized=True)],
        ),
        make_customer_headers("cust-c16"),
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMIZATION_NOT_ALLOWED)


def test_event_cancel_after_window_start_rejected(client):
    """Once the clock reaches window_start_at the event is ACTIVE and cannot be
    cancelled.

    "Only a `SCHEDULED` event may be cancelled — attempting to cancel one whose
    window has already begun is rejected with `ERR_EVENT_NOT_CANCELLABLE`"

    Design: Corner/validations/event_cancel_after_window_start_rejected
    """
    sd = fixtures.create_store_day(client, "2026-10-29")
    event = fixtures.create_demand_event(
        client,
        sd["id"],
        name="Rally",
        window_start_at="2026-10-29T12:00:00Z",
        window_end_at="2026-10-29T14:00:00Z",
        demand_multiplier=2.0,
    )

    fixtures.set_clock(client, "2026-10-29T12:30:00Z")
    active = validate_success(
        client.get_demand_event(event["id"], make_manager_headers()), 200
    )
    assert active["status"] == "ACTIVE"

    resp = client.cancel_demand_event(event["id"], make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_CANCELLABLE)

    stored = validate_success(
        client.get_demand_event(event["id"], make_manager_headers()), 200
    )
    assert stored["status"] == "ACTIVE"


def test_duplicate_business_date_and_sku_rejected(client):
    """Both uniqueness rules reject the second writer.

    "a `YYYY-MM-DD` UTC calendar date that must be unique across all store days
    — a duplicate is rejected with `ERR_DUPLICATE_BUSINESS_DATE`"
    "A `StoreManager` creates a product with a unique `sku` (duplicates rejected
    with `ERR_DUPLICATE_SKU`)"

    Design: Corner/validations/duplicate_business_date_and_sku_rejected
    """
    manager = make_manager_headers()
    fixtures.create_store_day(client, "2026-10-30")
    fixtures.create_product(client)

    resp_day = client.create_store_day(
        factories.store_day_payload(business_date="2026-10-30"), manager
    )
    validate_error(resp_day, ApiErrorId.ERR_DUPLICATE_BUSINESS_DATE)

    resp_sku = client.create_product(
        factories.product_payload(name="Pepperoni Again", list_price_cents=650),
        manager,
    )
    validate_error(resp_sku, ApiErrorId.ERR_DUPLICATE_SKU)


def test_station_capacity_one_per_minute(client):
    """The small-footprint rule: two different crew members cannot cover the
    same station over overlapping windows.

    "Second, the small-footprint rule: at most one `SCHEDULED` shift per station
    may cover any minute of the candidate window, regardless of which crew
    members are involved."

    Design: Corner/validations/station_capacity_one_per_minute
    """
    sd = fixtures.create_store_day(client, "2026-10-31")
    lead = make_shift_lead_headers()
    validate_success(
        client.create_crew_shift(
            sd["id"],
            factories.crew_shift_payload(
                crew_member_id="crew-A", station="OVEN", start_minute=600, end_minute=780
            ),
            lead,
        ),
        201,
    )

    resp = client.create_crew_shift(
        sd["id"],
        factories.crew_shift_payload(
            crew_member_id="crew-B", station="OVEN", start_minute=700, end_minute=800
        ),
        lead,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_CONFLICT)


def test_proof_floor_boundary_exactly_120_minutes(client):
    """At proofing_started_at + 119 the advance fails; at +120 exactly it
    succeeds — the floor is inclusive.

    "advancing it again moves it `PROOFING → PROOFED`, stamping `proofed_at`,
    but only once the clock has reached `proofing_started_at` plus 120 minutes —
    the proofing floor is inclusive, so exactly 120 minutes is enough, and an
    earlier attempt is rejected with `ERR_PROOF_NOT_READY`."

    Design: Corner/validations/proof_floor_boundary_exactly_120_minutes
    """
    fixtures.set_clock(client, "2026-11-01T08:00:00Z")
    sd = fixtures.create_store_day(client, "2026-11-01")
    db = fixtures.create_proofed_dough_batch(client, sd["id"], size_units=5)
    fixtures.set_clock(client, "2026-11-01T08:05:00Z")
    fixtures.advance_dough(client, db["id"])  # PROOFING at 08:05

    fixtures.set_clock(client, "2026-11-01T10:04:00Z")  # +119 minutes
    resp = client.advance_dough_batch(db["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_PROOF_NOT_READY)

    fixtures.set_clock(client, "2026-11-01T10:05:00Z")  # exactly +120 minutes
    proofed = validate_success(
        client.advance_dough_batch(db["id"], make_crew_headers()), 200
    )
    assert proofed["status"] == "PROOFED"

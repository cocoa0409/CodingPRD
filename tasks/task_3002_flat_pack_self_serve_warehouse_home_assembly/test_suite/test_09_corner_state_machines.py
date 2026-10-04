"""Corner design — section: state_machines."""
from test_helpers import (
    COORD,
    OPS,
    PROVIDER,
    ApiErrorId,
    add_line,
    add_return_line,
    checkout,
    create_article,
    create_assembly_job,
    create_booking,
    create_claim,
    create_customer,
    create_delivery_slot,
    create_order,
    create_return,
    create_standalone_reservation,
    cust_headers,
    current_slot_version,
    get_success_data,
    grade_line,
    seed_member_points,
    set_clock,
    setup_article_with_stock,
    setup_delivery_paid_order,
    setup_fulfilled_order,
    setup_store_and_customer,
    submit_return,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_checkout_from_paid_returns_invalid_state(api):
    """PRD §3.3: "The order emerges from checkout in `PAID`."
    PRD §2.9: "state-machine legality — wrong from-state ... yielding
    `ERR_INVALID_STATE` ... (HTTP 409)."

    Design: Corner/state_machines/checkout_from_paid_returns_invalid_state
    """
    store, customer = setup_store_and_customer()
    article, _, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)
    stock = stocks[0]
    order = create_order(customer, store["id"])
    add_line(customer, order["id"], article["id"], qty=1)
    checkout(customer, order["id"])

    resp = api.checkout_order(order["id"], {}, cust_headers(customer))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert stock_after["on_hand"] == 4, "the failed checkout must not decrement again"


def test_fulfill_fulfilled_reservation_returns_invalid_state(api):
    """PRD §3.4: "A successful fulfillment decrements both `reserved` and
    `on_hand` by the quantity on every carton, moving the reservation to
    `FULFILLED`."
    PRD §2.9: "state-machine legality — wrong from-state ... yielding
    `ERR_INVALID_STATE` ... (HTTP 409)."

    Design: Corner/state_machines/fulfill_fulfilled_reservation_returns_invalid_state
    """
    store, customer = setup_store_and_customer()
    article, _, stocks = setup_article_with_stock(
        store, on_hand=3, price_cents=3000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(30, 0.4, 3)])
    stock = stocks[0]
    reservation = create_standalone_reservation(customer, store["id"], article["id"], qty=1)
    validate_success(api.fulfill_reservation(reservation["id"], OPS))

    resp = api.fulfill_reservation(reservation["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert stock_after["on_hand"] == 2
    assert stock_after["reserved"] == 0


def test_fulfill_after_expiry_transitions_expired_and_rejects(api):
    """PRD §3.4: "fulfilling at or after that instant instead flips the
    reservation to `EXPIRED` and rejects the request with
    `ERR_RESERVATION_EXPIRED`."
    PRD §2.6: "A reservation created "now" expires exactly 24 hours later; a
    fulfillment attempted at the exact expiry instant is already too late,
    because the reservation is expired from its `expires_at` moment onward,
    inclusive."

    Design: Corner/state_machines/fulfill_after_expiry_transitions_expired_and_rejects
    """
    store, customer = setup_store_and_customer()
    article, _, stocks = setup_article_with_stock(
        store, on_hand=3, price_cents=3000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(30, 0.4, 3)])
    stock = stocks[0]
    reservation = create_standalone_reservation(customer, store["id"], article["id"], qty=1)

    set_clock("2026-09-02T00:00:01Z")
    resp = api.fulfill_reservation(reservation["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_RESERVATION_EXPIRED)
    assert resp.status_code == 409

    res_after = get_success_data(api.get_reservation(reservation["id"], OPS))
    assert res_after["status"] == "EXPIRED"
    stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert stock_after["on_hand"] == 3
    assert stock_after["reserved"] == 0


def test_booking_start_from_waitlisted_rejected(api):
    """PRD §3.5: "From `SCHEDULED`, a `DeliveryCoordinator` starts the run,
    moving the booking to `OUT_FOR_DELIVERY` and the order's `delivery_status`
    with it."
    PRD §2.9: "state-machine legality — wrong from-state ... yielding
    `ERR_INVALID_STATE` ... (HTTP 409)."

    Design: Corner/state_machines/booking_start_from_waitlisted_rejected
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, on_hand=4, price_cents=9000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(90, 1.0, 4)])
    slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                capacity_weight_kg=100, capacity_volume_m3=5)
    o1, _ = setup_delivery_paid_order(customer, store, article, qty=1)
    b1 = create_booking(customer, o1["id"], slot["id"],
                        expected_slot_version=current_slot_version(slot["id"]))
    assert b1["status"] == "CONFIRMED"

    o2, _ = setup_delivery_paid_order(customer, store, article, qty=1)
    b2 = create_booking(customer, o2["id"], slot["id"],
                        expected_slot_version=current_slot_version(slot["id"]))
    assert b2["status"] == "WAITLISTED"

    resp = api.start_delivery_booking(b2["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    o2_after = get_success_data(api.get_order(o2["id"], cust_headers(customer)))
    assert o2_after["delivery_status"] == "WAITLISTED"


def test_job_complete_from_requested_rejected(api):
    """PRD §3.6: "Accepting dispatch moves it to `DISPATCHED`; starting work
    moves it to `IN_PROGRESS` and the order's `assembly_status` follows."
    PRD §3.6: "Completion is where money meets the estimate: the crew reports
    `actual_minutes`, and `billed_minutes` is set to the lesser of that report
    and the estimate scaled by one and a half"
    PRD §2.9: "state-machine legality — wrong from-state ... yielding
    `ERR_INVALID_STATE` ... (HTTP 409)."

    Design: Corner/state_machines/job_complete_from_requested_rejected
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, on_hand=5, price_cents=1000, category="FURNITURE",
        requires_assembly=True, register_standard_minutes=30)
    order, _ = setup_fulfilled_order(customer, store, [(article, 1)])
    job = create_assembly_job(customer, order["id"], provider_id="CREW-A",
                              window_start="2026-09-10T10:00:00Z",
                              window_end="2026-09-10T11:00:00Z")
    assert job["status"] == "REQUESTED"

    resp = api.complete_assembly_job(job["id"], {"actual_minutes": 25}, PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    job_after = get_success_data(api.get_assembly_job(job["id"], PROVIDER))
    assert job_after["status"] == "REQUESTED"
    assert job_after["billed_minutes"] is None


def test_claim_ship_from_submitted_rejected(api):
    """PRD §3.7: "An approved claim moves to `APPROVED`, and a later ship
    action by `StoreOps` ends it at `SHIPPED`."
    PRD §2.9: "state-machine legality — wrong from-state ... yielding
    `ERR_INVALID_STATE` ... (HTTP 409)."

    Design: Corner/state_machines/claim_ship_from_submitted_rejected
    """
    set_clock()
    customer = create_customer()
    article = create_article()
    claim = create_claim(customer, article["id"], value=500)
    assert claim["status"] == "SUBMITTED"

    resp = api.ship_spare_part_claim(claim["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    claim_after = get_success_data(api.get_spare_part_claim(claim["id"], OPS))
    assert claim_after["status"] == "SUBMITTED"


def test_settle_with_ungraded_lines_returns_ungraded_lines(api):
    """PRD §3.8: "Settlement is allowed only once every line has been graded;
    an attempt with any line still ungraded is rejected with
    `ERR_UNGRADED_LINES`."
    PRD §3.8: "the very first graded line automatically moves the request from
    `SUBMITTED` to `GRADING`."

    Design: Corner/state_machines/settle_with_ungraded_lines_returns_ungraded_lines
    """
    store, customer = setup_store_and_customer()
    article, _, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)
    stock = stocks[0]
    order, order_lines = setup_fulfilled_order(customer, store, [(article, 2)])

    ret = create_return(customer, order_id=order["id"])
    rl1 = add_return_line(customer, ret["id"], article["id"], qty=1,
                          order_line_id=order_lines[0]["id"])
    add_return_line(customer, ret["id"], article["id"], qty=1,
                    order_line_id=order_lines[0]["id"])
    submit_return(customer, ret["id"])
    grade_line(ret["id"], rl1["id"], "LIKE_NEW")

    resp = api.settle_return(ret["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_UNGRADED_LINES)
    assert resp.status_code == 409
    ret_after = get_success_data(api.get_return(ret["id"], OPS))
    assert ret_after["status"] == "GRADING"
    stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert stock_after["on_hand"] == 3, "no partial restock from the failed settle"


def test_order_close_from_paid_rejected(api):
    """PRD §3.3: "when an order moves from `FULFILLED` or `DELIVERED` to
    `CLOSED` — either by the customer's explicit close or automatically the
    moment its assembly finishes"
    PRD §2.9: "state-machine legality — wrong from-state ... yielding
    `ERR_INVALID_STATE` ... (HTTP 409)."

    Design: Corner/state_machines/order_close_from_paid_rejected
    """
    store, member = setup_store_and_customer(member=True)
    article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=500)
    order = create_order(member, store["id"])
    add_line(member, order["id"], article["id"], qty=1)
    checkout(member, order["id"])

    resp = api.close_order(order["id"], cust_headers(member))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    order_after = get_success_data(api.get_order(order["id"], cust_headers(member)))
    assert order_after["status"] == "PAID"
    customer_after = get_success_data(api.get_customer(member["id"], OPS))
    assert customer_after["points_balance"] == 0


def test_checkout_fullserve_line_autocreates_reservation(api):
    """PRD §3.3: "Every `PICKUP_COUNTER` line instead auto-creates an
    `ACTIVE` pickup-counter reservation with its `order_line_id` set and an
    expiry exactly 24 hours out, and increments `reserved` by the quantity on
    every carton — the boxes stay on the shelf but are promised."
    PRD §3.4: "A standalone reservation has a null `order_line_id` (the
    checkout-created kind has it set)"

    Design: Corner/state_machines/checkout_fullserve_line_autocreates_reservation
    """
    store, customer = setup_store_and_customer()
    article, _, stocks = setup_article_with_stock(
        store, on_hand=3, price_cents=3000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(30, 0.4, 3)])
    stock = stocks[0]
    order = create_order(customer, store["id"])
    line = add_line(customer, order["id"], article["id"], qty=1)

    paid = checkout(customer, order["id"])
    assert paid["status"] == "PAID"

    reservations, _ = validate_paginated(
        api.list_reservations(OPS, params={"order_line_id": line["id"]}))
    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation["status"] == "ACTIVE"
    assert reservation["qty"] == 1
    assert reservation["order_line_id"] == line["id"]
    from datetime import datetime, timezone
    expires = datetime.fromisoformat(reservation["expires_at"].replace("Z", "+00:00"))
    assert expires == datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc), (
        "expiry exactly 24 hours out from the 2026-09-01T00:00:00Z clock"
    )
    stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert stock_after["on_hand"] == 3
    assert stock_after["reserved"] == 1


def test_order_cancel_compensates_stock_reservations_and_points(api):
    """PRD §3.3: "The cancellation then compensates in full — every
    `SELF_PICK` line restocks by adding its quantity back to `on_hand` on each
    carton, every still-`ACTIVE` auto-created reservation flips to `CANCELLED`
    and releases its `reserved` units per carton, and the redeemed
    `points_discount_cents` are re-credited to the customer's balance."

    Design: Corner/state_machines/order_cancel_compensates_stock_reservations_and_points
    """
    store, member = setup_store_and_customer(member=True)
    art_a, _, stocks_a = setup_article_with_stock(store, on_hand=5, price_cents=500)
    art_b, _, stocks_b = setup_article_with_stock(
        store, on_hand=3, price_cents=3000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(30, 0.4, 3)])
    seed_member_points(member, store, 1000)

    order = create_order(member, store["id"])
    add_line(member, order["id"], art_a["id"], qty=1)
    line_b = add_line(member, order["id"], art_b["id"], qty=1)
    # cap floor(3500 x 0.20) = 700; request exactly 700.
    paid = checkout(member, order["id"], redeem_points=700)
    assert paid["total_cents"] == 2800
    assert paid["points_discount_cents"] == 700
    mid_customer = get_success_data(api.get_customer(member["id"], OPS))
    assert mid_customer["points_balance"] == 300

    cancelled = validate_success(api.cancel_order(order["id"], cust_headers(member)))
    assert cancelled["status"] == "CANCELLED"

    stock_a = get_success_data(api.get_bin_stock(stocks_a[0]["id"], OPS))
    assert stock_a["on_hand"] == 5, "SELF_PICK restock"
    stock_b = get_success_data(api.get_bin_stock(stocks_b[0]["id"], OPS))
    assert stock_b["on_hand"] == 3
    assert stock_b["reserved"] == 0
    reservations, _ = validate_paginated(
        api.list_reservations(OPS, params={"order_line_id": line_b["id"]}))
    assert len(reservations) == 1
    assert reservations[0]["status"] == "CANCELLED"
    customer_after = get_success_data(api.get_customer(member["id"], OPS))
    assert customer_after["points_balance"] == 1000

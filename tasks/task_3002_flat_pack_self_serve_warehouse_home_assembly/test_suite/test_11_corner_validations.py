"""Corner design — section: validations."""
from test_helpers import (
    ApiErrorId,
    OPS,
    add_line,
    add_return_line,
    checkout,
    create_booking,
    create_claim,
    create_customer,
    create_delivery_slot,
    create_order,
    create_return,
    cust_headers,
    current_slot_version,
    get_success_data,
    setup_article_with_stock,
    setup_delivery_paid_order,
    setup_fulfilled_order,
    setup_store_and_customer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role the
    server does not recognize, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    store, _ = setup_store_and_customer()
    resp = api.get_store(store["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_customer_cannot_read_other_customers_order_forbidden(api):
    """PRD §2.1: "when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting customer record, and ownership checks on any resource that
    references a customer compare the resource's `customer_id` field to
    `X-User-ID`. A customer may read and mutate only its own orders,
    reservations, bookings, assembly requests, claims, and returns."

    Design: Corner/validations/customer_cannot_read_other_customers_order_forbidden
    """
    store, owner = setup_store_and_customer()
    other = create_customer()
    order = create_order(owner, store["id"])

    resp = api.get_order(order["id"], cust_headers(other))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403


def test_multi_carton_shortage_distinct_from_insufficient_stock(api):
    """PRD §3.3: "When every carton of an article falls short — or the
    article simply has no cartons or no stock rows — the checkout is rejected
    with `ERR_INSUFFICIENT_STOCK`; when some cartons could cover the quantity
    but at least one cannot, the rejection is `ERR_MULTI_CARTON_SHORTAGE`,
    because a multi-box product must be picked as a complete set."

    Design: Corner/validations/multi_carton_shortage_distinct_from_insufficient_stock
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, price_cents=5000, category="FURNITURE",
        cartons=[(10, 0.1, 3), (8, 0.08, 2)])
    order = create_order(customer, store["id"])
    add_line(customer, order["id"], article["id"], qty=3)

    resp = api.checkout_order(order["id"], {}, cust_headers(customer))
    validate_error(resp, ApiErrorId.ERR_MULTI_CARTON_SHORTAGE)
    assert resp.status_code == 422
    order_after = get_success_data(api.get_order(order["id"], cust_headers(customer)))
    assert order_after["status"] == "DRAFT"
    stock_rows = get_success_data(api.list_bin_stock(OPS, params={"store_id": store["id"]}))
    assert {r["on_hand"] for r in stock_rows} == {3, 2}, "no stock was decremented"


def test_return_qty_beyond_purchased_rejected(api):
    """PRD §3.8: "a receipted line must reference a line of the receipted
    order, and its `qty` may not exceed what that order line has left — the
    line's purchased `qty` minus its already-accepted `returned_qty` — with
    any excess rejected as `ERR_RETURN_QTY_EXCEEDED`"

    Design: Corner/validations/return_qty_beyond_purchased_rejected
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=500)
    order, order_lines = setup_fulfilled_order(customer, store, [(article, 1)])
    ret = create_return(customer, order_id=order["id"])

    resp = api.add_return_line(
        ret["id"],
        {"article_id": article["id"], "qty": 2, "assembly_state": "UNOPENED",
         "order_line_id": order_lines[0]["id"]},
        cust_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_QTY_EXCEEDED)
    assert resp.status_code == 422
    lines, _ = validate_paginated(
        api.list_return_lines(ret["id"], cust_headers(customer)))
    assert len(lines) == 0
    ret_after = get_success_data(api.get_return(ret["id"], cust_headers(customer)))
    assert ret_after["status"] == "DRAFT"


def test_no_receipt_return_requires_membership(api):
    """PRD §3.8: "a no-receipt line leaves `order_line_id` null, and
    no-receipt returns are a member privilege, so a customer whose
    `member_status` is not `ACTIVE` is turned away with `ERR_RECEIPT_REQUIRED`
    at line creation."

    Design: Corner/validations/no_receipt_return_requires_membership
    """
    store, non_member = setup_store_and_customer(member=False)
    article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=500)
    ret = create_return(non_member)

    resp = api.add_return_line(
        ret["id"],
        {"article_id": article["id"], "qty": 1, "assembly_state": "UNOPENED"},
        cust_headers(non_member),
    )
    validate_error(resp, ApiErrorId.ERR_RECEIPT_REQUIRED)
    assert resp.status_code == 422


def test_return_against_draft_order_not_returnable(api):
    """PRD §3.8: "When an order is named the request is receipted — its
    `receipted` flag is true — and the referenced order must be in
    `FULFILLED`, `DELIVERED`, or `CLOSED`, otherwise the request is rejected
    with `ERR_ORDER_NOT_RETURNABLE`."

    Design: Corner/validations/return_against_draft_order_not_returnable
    """
    store, customer = setup_store_and_customer()
    order = create_order(customer, store["id"])

    resp = api.create_return({"order_id": order["id"]}, cust_headers(customer))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_RETURNABLE)
    assert resp.status_code == 409


def test_duplicate_bin_stock_row_rejected(api):
    """PRD §3.1: "a bin-stock row joins a `store_id` and a `carton_id`,
    exactly one row per store-and-carton pair — attempting to create a second
    row for an existing pair is rejected with `ERR_DUPLICATE_BIN_STOCK`."

    Design: Corner/validations/duplicate_bin_stock_row_rejected
    """
    store, customer = setup_store_and_customer()
    article, cartons, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)

    resp = api.create_bin_stock(
        {"store_id": store["id"], "carton_id": cartons[0]["id"], "on_hand": 2}, OPS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BIN_STOCK)
    assert resp.status_code == 409
    original = get_success_data(api.get_bin_stock(stocks[0]["id"], OPS))
    assert original["on_hand"] == 5


def test_booking_heavier_than_empty_slot_never_fits(api):
    """PRD §3.5: "A booking can be impossible before it is inconvenient: if
    its weight or volume alone would exceed the slot's capacity even on an
    empty slot, the request is rejected outright with `ERR_BOOKING_NEVER_FITS`
    rather than parked on a waitlist."

    Design: Corner/validations/booking_heavier_than_empty_slot_never_fits
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, on_hand=2, price_cents=9000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(150, 1.0, 2)])
    slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                capacity_weight_kg=100, capacity_volume_m3=5)
    order, _ = setup_delivery_paid_order(customer, store, article, qty=1)

    resp = api.create_delivery_booking(
        order["id"],
        {"slot_id": slot["id"], "access_type": "ELEVATOR", "floor": 1,
         "expected_slot_version": slot["version"]},
        cust_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_NEVER_FITS)
    assert resp.status_code == 422
    order_after = get_success_data(api.get_order(order["id"], cust_headers(customer)))
    assert order_after["delivery_status"] == "NONE"


def test_walkup_high_with_heavy_carton_infeasible(api):
    """PRD §3.5: "a `WALKUP_HIGH` booking in which any carton of any line
    weighs more than 40 kilograms cannot be serviced at all and is rejected
    with `ERR_ACCESS_INFEASIBLE` before any fee is quoted."
    PRD §3.5: "A weight surcharge follows: nothing while the booking weighs at
    most 50 kilograms"

    Design: Corner/validations/walkup_high_with_heavy_carton_infeasible
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, on_hand=2, price_cents=4000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(50, 0.5, 2)])
    slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                capacity_weight_kg=500, capacity_volume_m3=5)

    order1, _ = setup_delivery_paid_order(customer, store, article, qty=1)
    resp = api.create_delivery_booking(
        order1["id"],
        {"slot_id": slot["id"], "access_type": "WALKUP_HIGH", "floor": 4,
         "expected_slot_version": slot["version"]},
        cust_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_ACCESS_INFEASIBLE)
    assert resp.status_code == 422

    # Same load with ELEVATOR access succeeds at the bare ZONE_A base fee.
    order2, _ = setup_delivery_paid_order(customer, store, article, qty=1)
    booking = create_booking(customer, order2["id"], slot["id"],
                             expected_slot_version=current_slot_version(slot["id"]),
                             access_type="ELEVATOR", floor=4)
    assert booking["status"] == "CONFIRMED"
    assert booking["fee_cents"] == 4900


def test_slot_in_past_rejected(api):
    """PRD §3.5: "a slot whose `service_date` is before the current logical
    date is rejected with `ERR_SLOT_IN_PAST`."
    PRD §2.6: "Before any client call has been made, the clock reads exactly
    2026-09-01T00:00:00Z, and it never falls back to wall-clock time
    thereafter."

    Design: Corner/validations/slot_in_past_rejected
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=500)
    slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                capacity_weight_kg=100, capacity_volume_m3=2,
                                service_date="2026-08-01")
    order, _ = setup_delivery_paid_order(customer, store, article, qty=1)

    resp = api.create_delivery_booking(
        order["id"],
        {"slot_id": slot["id"], "access_type": "ELEVATOR", "floor": 1,
         "expected_slot_version": slot["version"]},
        cust_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_IN_PAST)
    assert resp.status_code == 422


def test_claim_count_limit_at_exactly_three(api):
    """PRD §3.7: "First the count: if the customer already has 3 such claims
    in the window, approval is rejected with `ERR_CLAIM_LIMIT_EXCEEDED`."
    PRD §3.7: "Review is a `StoreOps` decision expressed through a `decision`
    input — approve or deny — with an optional `review_note`."

    Design: Corner/validations/claim_count_limit_at_exactly_three
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=500)

    claims = [create_claim(customer, article["id"], value=100) for _ in range(4)]
    for claim in claims[:3]:
        reviewed = validate_success(
            api.review_spare_part_claim(claim["id"], {"decision": "APPROVE"}, OPS))
        assert reviewed["status"] == "APPROVED"

    resp = api.review_spare_part_claim(claims[3]["id"], {"decision": "APPROVE"}, OPS)
    validate_error(resp, ApiErrorId.ERR_CLAIM_LIMIT_EXCEEDED)
    assert resp.status_code == 422
    fourth = get_success_data(api.get_spare_part_claim(claims[3]["id"], OPS))
    assert fourth["status"] == "SUBMITTED"


def test_claim_value_limit_at_exactly_3000(api):
    """PRD §3.7: "Then the value: if the summed `part_value_cents` of those
    prior claims plus this claim's declared value would exceed 3000 cents,
    approval is rejected with `ERR_CLAIM_VALUE_EXCEEDED` — a cumulative value
    of exactly 3000 cents after this claim is still allowed."

    Design: Corner/validations/claim_value_limit_at_exactly_3000
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=500)

    c1 = create_claim(customer, article["id"], value=1500)
    c2 = create_claim(customer, article["id"], value=1500)
    c3 = create_claim(customer, article["id"], value=100)

    reviewed1 = validate_success(
        api.review_spare_part_claim(c1["id"], {"decision": "APPROVE"}, OPS))
    assert reviewed1["status"] == "APPROVED"
    reviewed2 = validate_success(
        api.review_spare_part_claim(c2["id"], {"decision": "APPROVE"}, OPS))
    assert reviewed2["status"] == "APPROVED", "cumulative exactly 3000 is allowed"

    resp = api.review_spare_part_claim(c3["id"], {"decision": "APPROVE"}, OPS)
    validate_error(resp, ApiErrorId.ERR_CLAIM_VALUE_EXCEEDED)
    assert resp.status_code == 422

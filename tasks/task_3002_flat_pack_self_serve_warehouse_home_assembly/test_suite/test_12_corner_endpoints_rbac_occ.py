"""Corner design — sections: endpoints, rbac, cross_cutting_complexity_layers,
consistency_model."""
from test_helpers import (
    ApiErrorId,
    COORD,
    OPS,
    PROVIDER,
    add_line,
    add_return_line,
    checkout,
    create_article,
    create_assembly_job,
    create_booking,
    create_customer,
    create_customer_payload,
    create_delivery_slot,
    create_order,
    create_reservation_payload,
    create_return,
    create_standalone_reservation,
    cust_headers,
    current_slot_version,
    get_success_data,
    grade_line,
    is_iso8601_timestamp,
    is_iso8601_timestamp,
    is_iso8601_timestamp,
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

UNKNOWN_ORDER_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def test_run_sweep_expires_reservations_and_reports_ids(api):
    """PRD §3.4: "The sweep is a `StoreOps`-only, per-store checkpoint with
    two phases. First it expires every due reservation in the store as just
    described; then it runs waitlist promotion (§3.5) across every delivery
    slot of the store. Its response names what it did through
    `expired_reservation_ids` and `promoted_booking_ids`."
    PRD §3.4: "the ops-run sweep transitions every `ACTIVE` reservation whose
    `expires_at` has been reached to `EXPIRED`, releasing its `reserved` units
    per carton and recomputing the affected stock signals."

    Design: Corner/endpoints/run_sweep_expires_reservations_and_reports_ids
    """
    store, customer = setup_store_and_customer()
    article, _, stocks = setup_article_with_stock(
        store, on_hand=3, price_cents=3000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(30, 0.4, 3)])
    stock = stocks[0]

    r1 = create_standalone_reservation(customer, store["id"], article["id"], qty=1)
    set_clock("2026-09-01T12:00:00Z")
    r2 = create_standalone_reservation(customer, store["id"], article["id"], qty=1)
    set_clock("2026-09-02T06:00:00Z")

    sweep1 = validate_success(api.run_sweep(store["id"], OPS))
    assert sweep1["expired_reservation_ids"] == [r1["id"]], (
        "only R1 (expired 2026-09-02T00:00:00Z) is due; R2 expires "
        "2026-09-02T12:00:00Z and is still active"
    )
    assert sweep1["promoted_booking_ids"] == []

    sweep2 = validate_success(api.run_sweep(store["id"], OPS))
    assert sweep2["expired_reservation_ids"] == []

    stock_after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert stock_after["reserved"] == 1, "only R2 remains ACTIVE"
    r1_after = get_success_data(api.get_reservation(r1["id"], OPS))
    assert r1_after["status"] == "EXPIRED"
    r2_after = get_success_data(api.get_reservation(r2["id"], OPS))
    assert r2_after["status"] == "ACTIVE"


def test_error_response_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard error envelope format" with "`response_type`: "error"" and a
    `data` object carrying `error_id` and `message`.
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/error_response_envelope_shape
    """
    set_clock()
    resp = api.get_order(UNKNOWN_ORDER_ID, OPS)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_ORDER_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------

def test_customer_cannot_create_store_forbidden(api):
    """PRD §2.1: "**PlatformAdmin** is the platform operator: it manages
    stores, the article catalog, carton registration, assembly standards,
    customer registration, and the logical clock."
    PRD §2.1: "A recognized role attempting an operation outside its grant, or
    a `Customer` acting on a resource owned by another customer, is rejected
    with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_create_store_forbidden
    """
    set_clock()
    customer = create_customer()
    resp = api.create_store({"name": "Rogue", "code": "ST-ROGUE-1"}, cust_headers(customer))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403


def test_storeops_cannot_dispatch_assembly_job_forbidden(api):
    """PRD §2.1: "**AssemblyProvider** is a third-party assembly crew: it
    drives job dispatch, start, hold, resume, and completion."
    PRD §2.1: "A recognized role attempting an operation outside its grant, or
    a `Customer` acting on a resource owned by another customer, is rejected
    with `ERR_FORBIDDEN`."

    Design: Corner/rbac/storeops_cannot_dispatch_assembly_job_forbidden
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, on_hand=5, price_cents=1000, category="FURNITURE",
        requires_assembly=True, register_standard_minutes=30)
    order, _ = setup_fulfilled_order(customer, store, [(article, 1)])
    job = create_assembly_job(customer, order["id"], provider_id="CREW-A",
                              window_start="2026-09-10T10:00:00Z",
                              window_end="2026-09-10T11:00:00Z")

    resp = api.dispatch_assembly_job(job["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403
    job_after = get_success_data(api.get_assembly_job(job["id"], OPS))
    assert job_after["status"] == "REQUESTED"


def test_assemblyprovider_cannot_grade_return_forbidden(api):
    """PRD §2.1: "**StoreOps** is in-store operations staff: it manages bin
    stock, fulfills and cancels reservations, completes pickup handover,
    enrolls members, grades and settles returns, and reviews spare-part
    claims."
    PRD §2.1: "A recognized role attempting an operation outside its grant, or
    a `Customer` acting on a resource owned by another customer, is rejected
    with `ERR_FORBIDDEN`."

    Design: Corner/rbac/assemblyprovider_cannot_grade_return_forbidden
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=500)
    order, order_lines = setup_fulfilled_order(customer, store, [(article, 1)])
    ret = create_return(customer, order_id=order["id"])
    ret_line = add_return_line(customer, ret["id"], article["id"], qty=1,
                               order_line_id=order_lines[0]["id"])
    submit_return(customer, ret["id"])

    resp = api.grade_return_line(ret["id"], ret_line["id"], {"condition_grade": "LIKE_NEW"}, PROVIDER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403
    line_after = get_success_data(api.get_return_line(ret_line["id"], OPS))
    assert line_after["condition_grade"] is None


def test_deliverycoordinator_cannot_fulfill_reservation_forbidden(api):
    """PRD §2.1: "**StoreOps** is in-store operations staff: it manages bin
    stock, fulfills and cancels reservations, completes pickup handover,
    enrolls members, grades and settles returns, and reviews spare-part
    claims."
    PRD §2.1: "A recognized role attempting an operation outside its grant, or
    a `Customer` acting on a resource owned by another customer, is rejected
    with `ERR_FORBIDDEN`."

    Design: Corner/rbac/deliverycoordinator_cannot_fulfill_reservation_forbidden
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, on_hand=3, price_cents=3000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(30, 0.4, 3)])
    reservation = create_standalone_reservation(customer, store["id"], article["id"], qty=1)

    resp = api.fulfill_reservation(reservation["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403
    res_after = get_success_data(api.get_reservation(reservation["id"], OPS))
    assert res_after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers (optimistic concurrency)
# ---------------------------------------------------------------------------

def test_occ_stock_adjust_stale_version_412(api):
    """PRD §2.7: "Adjusting a bin-stock row requires `expected_stock_version`,
    carrying the `version` of the row the operator last observed; because
    adjustments are delta-based, a request written against a stale row — one
    since mutated by a checkout, a reservation, a fulfillment, a return
    restock, or a prior adjustment — is rejected with `ERR_STALE_VERSION`
    (HTTP 412) so the operator re-reads the row before re-applying the delta."
    PRD §3.1: "the adjustment is applied on top of the current count, the
    result must stay non-negative and at least as large as `reserved`, and the
    row's `version` increments by 1"

    Design: Corner/cross_cutting_complexity_layers/occ_stock_adjust_stale_version_412
    """
    store, _ = setup_store_and_customer()
    article, cartons, stocks = setup_article_with_stock(store, on_hand=5, price_cents=500)
    stock = stocks[0]

    first = validate_success(api.adjust_bin_stock(
        stock["id"],
        {"delta_on_hand": 2, "expected_stock_version": stock["version"]},
        OPS,
    ))
    assert first["on_hand"] == 7
    assert first["version"] == 2

    resp = api.adjust_bin_stock(
        stock["id"],
        {"delta_on_hand": 2, "expected_stock_version": stock["version"]},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412
    after = get_success_data(api.get_bin_stock(stock["id"], OPS))
    assert after["on_hand"] == 7, "the rejected delta was not applied"


def test_occ_booking_create_stale_slot_412(api):
    """PRD §2.7: "Creating a delivery booking for an order requires
    `expected_slot_version`, carrying the `version` of the target delivery
    slot the client last observed; if the slot's current `version` has
    advanced — because another booking has since consumed or released
    capacity — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    forcing the client to re-read the slot before quoting fee and capacity
    again."
    PRD §3.5: "A fitting booking is born `CONFIRMED`: it adds its totals to
    the slot's used figures, bumps the slot's `version` by 1"

    Design: Corner/cross_cutting_complexity_layers/occ_booking_create_stale_slot_412
    """
    store, customer = setup_store_and_customer()
    article, _, _ = setup_article_with_stock(
        store, on_hand=4, price_cents=1000, category="FURNITURE",
        pick_policy="FULL_SERVE", cartons=[(10, 0.1, 4)])
    slot = create_delivery_slot(store["id"], zone="ZONE_A",
                                capacity_weight_kg=100, capacity_volume_m3=2)

    o1, _ = setup_delivery_paid_order(customer, store, article, qty=1)
    o2, _ = setup_delivery_paid_order(customer, store, article, qty=1)

    b1 = create_booking(customer, o1["id"], slot["id"],
                        expected_slot_version=slot["version"])
    assert b1["status"] == "CONFIRMED"
    slot_mid = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(customer)))
    assert slot_mid["version"] == slot["version"] + 1

    resp = api.create_delivery_booking(
        o2["id"],
        {"slot_id": slot["id"], "access_type": "ELEVATOR", "floor": 1,
         "expected_slot_version": slot["version"]},
        cust_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412
    o2_after = get_success_data(api.get_order(o2["id"], cust_headers(customer)))
    assert o2_after["delivery_status"] == "NONE"


def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the resource
    is created and increments by exactly 1 on every mutation, including
    mutations caused by cascades from other resources"
    PRD §2.4: "`created_at` is fixed at creation, while `updated_at` refreshes
    on every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    set_clock()
    customer = get_success_data(api.create_customer(create_customer_payload(), OPS))
    assert customer["version"] == 1

    enrolled = validate_success(api.enroll_customer(customer["id"], OPS))
    assert enrolled["version"] == 2
    # PRD §2.4: updated_at refreshes on every mutation; both timestamps are
    # server-rendered ISO 8601 strings.
    assert is_iso8601_timestamp(enrolled["updated_at"])
    assert enrolled["created_at"] == customer["created_at"], "created_at is fixed at creation"


# ---------------------------------------------------------------------------
# consistency_model (immediate)
# ---------------------------------------------------------------------------

def test_checkout_response_reflects_computed_totals_immediately(api):
    """PRD §2.4: "the response reflects the new value immediately."
    PRD §3.3: "Eighth, `total_cents` is the subtotal minus the discount minus
    the applied points."
    PRD §3.3: "The order emerges from checkout in `PAID`."

    Design: Corner/consistency_model/checkout_response_reflects_computed_totals_immediately
    """
    store, member = setup_store_and_customer(member=True)
    article, _, _ = setup_article_with_stock(
        store, on_hand=10, price_cents=115, category="FOOD")
    order = create_order(member, store["id"])
    add_line(member, order["id"], article["id"], qty=1)

    resp = api.checkout_order(order["id"], {}, cust_headers(member))
    paid = validate_success(resp)
    assert paid["status"] == "PAID"
    assert paid["subtotal_cents"] == 115
    assert paid["discount_cents"] == 12
    assert paid["total_cents"] == 103

    fetched = get_success_data(api.get_order(order["id"], cust_headers(member)))
    assert fetched["status"] == paid["status"]
    assert fetched["subtotal_cents"] == paid["subtotal_cents"]
    assert fetched["discount_cents"] == paid["discount_cents"]
    assert fetched["total_cents"] == paid["total_cents"]

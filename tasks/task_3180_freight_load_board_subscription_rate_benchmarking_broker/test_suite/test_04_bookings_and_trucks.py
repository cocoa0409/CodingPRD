"""Bookings and truck post state interactions."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    set_test_clock, setup_verified_broker, setup_verified_carrier,
    setup_broker_carrier_booked, post_load, post_truck,
    create_booking_payload, create_load_post_payload,
    get_load, get_truck, get_booking,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


def test_load_post_withdrawn_is_terminal_and_cannot_be_booked():
    """PRD §3.3: "Withdrawing a load not in `OPEN` is rejected with
    `ERR_LOAD_POST_NOT_OPEN`" and §3.4: "The referenced load must be `OPEN`
    and currently `LISTED`"

    Design: Corner/state_machines/load_post_withdrawn_is_terminal_and_cannot_be_booked
    """
    set_test_clock()
    bctx = setup_verified_broker()
    cctx = setup_verified_carrier()
    load = post_load(bctx)
    truck = post_truck(cctx)
    get_success_data(api_client.withdraw_load_post(load["id"], bctx["broker_headers"]))

    resp = api_client.create_booking(
        create_booking_payload(load["id"], truck["id"]), cctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_LOAD_POST_NOT_OPEN)
    rows, meta = validate_paginated(api_client.list_bookings(
        ADMIN, params={"load_post_id": load["id"]}))
    assert rows == []


def test_load_post_expires_eagerly_when_clock_passes_pickup_window_end():
    """PRD §3.3: "An `OPEN` load whose `pickup_window_end` has been reached
    becomes `EXPIRED`" and "Both transitions fire eagerly when the clock is
    set and lazily when the record is read."

    Design: Corner/state_machines/load_post_expires_eagerly_when_clock_passes_pickup_window_end
    """
    set_test_clock()
    bctx = setup_verified_broker()
    load = post_load(bctx)
    set_test_clock("2026-08-05T00:00:00Z")
    expired = get_load(load["id"])
    assert expired["status"] == "EXPIRED"
    resp = api_client.withdraw_load_post(load["id"], bctx["broker_headers"])
    validate_error(resp, ApiErrorId.ERR_LOAD_POST_NOT_OPEN)


def test_booking_complete_creates_booking_sourced_rate_transaction():
    """PRD §3.4: "completing it moves the booking to `COMPLETED`, moves both
    posts to `COMPLETED`, and — critically — mints the system's most trusted
    rate data point: a `RateTransaction` with `source` `BOOKING`, `rate_kind`
    `SPOT`, the booking carrier as `reporter_carrier_org_id`, `rate_cents`
    equal to the booking's `agreed_rate_cents`, and `transaction_date` equal
    to the logical clock at completion. The booking's `rate_transaction_id` is
    set to point at this new record."

    Design: Corner/state_machines/booking_complete_creates_booking_sourced_rate_transaction
    """
    set_test_clock()
    ctx = setup_broker_carrier_booked()
    bk, load, truck, cctx = ctx["booking"], ctx["load"], ctx["truck"], ctx["cctx"]

    r = validate_success(api_client.complete_booking(bk["id"], cctx["carrier_headers"]))
    assert r["status"] == "COMPLETED"
    assert r["rate_transaction_id"]
    assert get_load(load["id"])["status"] == "COMPLETED"
    assert get_truck(truck["id"])["status"] == "COMPLETED"

    rows, meta = validate_paginated(api_client.list_rate_transactions(
        ADMIN, params={"booking_id": bk["id"]}))
    assert len(rows) == 1
    rt = rows[0]
    assert rt["source"] == "BOOKING"
    assert rt["rate_kind"] == "SPOT"
    assert rt["rate_cents"] == bk["agreed_rate_cents"]
    assert rt["status"] == "ACCEPTED"
    assert rt["reporter_carrier_org_id"] == cctx["carrier"]["id"]


def test_booking_cancel_restores_load_open_and_truck_available():
    """PRD §3.4: "Cancellation returns both posts to the market: the load goes
    back to `OPEN` with `visibility` restored to `LISTED`, and the truck goes
    back to `AVAILABLE`."

    Design: Corner/state_machines/booking_cancel_restores_load_open_and_truck_available
    """
    set_test_clock()
    ctx = setup_broker_carrier_booked()
    bk, load, truck, bctx = ctx["booking"], ctx["load"], ctx["truck"], ctx["bctx"]

    r = validate_success(api_client.cancel_booking(bk["id"], bctx["broker_headers"]))
    assert r["status"] == "CANCELLED"
    reloaded = get_load(load["id"])
    assert reloaded["status"] == "OPEN"
    assert reloaded["visibility"] == "LISTED"
    assert get_truck(truck["id"])["status"] == "AVAILABLE"


def test_booking_requires_truck_post_available():
    """PRD §3.4: "The referenced load must be `OPEN` and currently `LISTED`,
    the referenced truck must be `AVAILABLE`, and both the carrier org and the
    posting broker org must pass the safety gate of §3.1"

    Design: Difficulty/cross_entity_state_dependency/booking_requires_truck_post_available
    """
    set_test_clock()
    bctx = setup_verified_broker()
    cctx = setup_verified_carrier()
    load = post_load(bctx)
    truck = post_truck(cctx)
    get_success_data(api_client.withdraw_truck_post(truck["id"], cctx["carrier_headers"]))

    resp = api_client.create_booking(
        create_booking_payload(load["id"], truck["id"]), cctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_TRUCK_POST_NOT_AVAILABLE)
    rows, _ = validate_paginated(api_client.list_bookings(
        ADMIN, params={"load_post_id": load["id"]}))
    assert rows == []
    assert get_load(load["id"])["status"] == "OPEN"


def test_existence_checked_before_state_on_unknown_load_id():
    """PRD §2.9: "Identifiers are validated left-to-right in the order the
    endpoint declares them, and the first missing identifier produces the
    corresponding 404 error from §5."

    Design: Corner/validations/existence_checked_before_state_on_unknown_load_id
    """
    set_test_clock()
    cctx = setup_verified_carrier()
    resp = api_client.create_booking(
        {"load_post_id": "00000000-0000-4000-8000-000000000001",
         "truck_post_id": "00000000-0000-4000-8000-000000000002",
         "agreed_rate_cents": 100000}, cctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_LOAD_POST_NOT_FOUND)

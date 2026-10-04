"""Order booking rules: the Monday ship-week rule, commitment-window vs
weekly-volume ordering, exact-fill volume semantics, the expired-commitment
state gate, and OCC on the commitment version.
"""

from test_helpers import (
    ADMIN,
    api_client,
    book_order,
    create_active_commitment,
    create_complex,
    create_customer,
    create_order_payload,
    make_customer_headers,
    read_commitment,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def test_ship_week_not_monday_rejected(api):
    """2026-09-08 is a Tuesday: rejected before the commitment-window check,
    which the date would have passed.

    PRD §3.6: "Checks fire in this order: ownership for the `Customer` role;
    payload shape; the commitment must be `ACTIVE` (else
    `ERR_INVALID_STATE`); the stale-version check
    (`ERR_STALE_COMMITMENT_VERSION`); the `ship_week_start` must be exactly a
    Monday at 00:00:00 UTC (else `ERR_SHIP_WEEK_NOT_MONDAY`); the ship week
    must lie within the commitment's effectiveness window, both ends
    inclusive (else `ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW`); ...".

    Design: Corner/validations/ship_week_not_monday_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    customer = create_customer()
    commitment = create_active_commitment(customer["id"])

    version = read_commitment(commitment["id"])["version"]
    response = api.create_order(
        commitment["id"],
        create_order_payload(
            ship_week_start="2026-09-08T00:00:00Z",  # a Tuesday
            dozen_ordered=1_000,
            size_class="LARGE",
            expected_commitment_version=version,
        ),
        make_customer_headers(customer["id"]),
    )
    error = validate_error(response, ERR.ERR_SHIP_WEEK_NOT_MONDAY)
    assert error["error_id"] != ERR.ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW.value
    rows, meta = validate_paginated(
        api.list_commitment_orders(commitment["id"], ADMIN)
    )
    assert rows == [] and meta["total_count"] == 0


def test_order_create_reports_window_before_volume(api):
    """A ship week outside the commitment window AND over the weekly volume
    reports the temporal failure first.

    PRD §3.6: "Checks fire in this order: ... the ship week must lie within
    the commitment's effectiveness window, both ends inclusive (else
    `ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW`); the customer must not be
    `SUSPENDED` (else `ERR_CUSTOMER_SUSPENDED`); and the week's volume must
    fit — `dozen_ordered` may not exceed `weekly_dozen_committed` minus the
    dozens already held by the commitment's `BOOKED`, `ALLOCATED`, and
    `SHIPPED` orders for that same ship week, with exact fill allowed (else
    `ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED`)."
    PRD §2.11: "validation proceeds in layers and the **first** failing layer
    determines the error."

    Design: Difficulty/priority_pair_validation_conflict/order_create_reports_window_before_volume
    """
    set_clock("2026-09-01T00:00:00Z")
    customer = create_customer(name="Budget Basket")
    commitment = create_active_commitment(
        customer["id"], weekly_dozen_committed=10_000,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )

    # 2027-01-04 is a Monday (so the Monday rule passes) but lies outside
    # the window; 15000 > 10000 also breaks the volume rule.
    version = read_commitment(commitment["id"])["version"]
    response = api.create_order(
        commitment["id"],
        create_order_payload(
            ship_week_start="2027-01-04T00:00:00Z",
            dozen_ordered=15_000,
            size_class="LARGE",
            expected_commitment_version=version,
        ),
        make_customer_headers(customer["id"]),
    )
    error = validate_error(response, ERR.ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW)
    assert error["error_id"] != ERR.ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED.value


def test_order_create_rejection_books_nothing(api):
    """The window-first rejection leaves no order behind and does not bump
    the commitment's version.

    PRD §3.6: "Checks fire in this order: ... the ship week must lie within
    the commitment's effectiveness window, both ends inclusive (else
    `ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW`)".
    PRD §3.6: "A booked order starts `BOOKED`, carries its parent
    `commitment_id`, and the booking itself bumps the commitment's
    `version`." — a rejected booking is not a booking.

    Design: Difficulty/priority_pair_validation_conflict/order_create_reports_window_before_volume
    """
    set_clock("2026-09-01T00:00:00Z")
    customer = create_customer(name="Budget Basket")
    commitment = create_active_commitment(
        customer["id"], weekly_dozen_committed=10_000,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )
    version_before = read_commitment(commitment["id"])["version"]

    response = api.create_order(
        commitment["id"],
        create_order_payload(
            ship_week_start="2027-01-04T00:00:00Z",
            dozen_ordered=15_000,
            size_class="LARGE",
            expected_commitment_version=version_before,
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(response, ERR.ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW)

    rows, meta = validate_paginated(
        api.list_commitment_orders(commitment["id"], ADMIN)
    )
    assert rows == [] and meta["total_count"] == 0
    assert read_commitment(commitment["id"])["version"] == version_before


def test_weekly_volume_exact_fill_then_one_dozen_overflow(api):
    """6000 then 4000 dozen exactly fill the 10000-dozen week; a further
    single dozen overflows the aggregate.

    PRD §3.6: "the week's volume must fit — `dozen_ordered` may not exceed
    `weekly_dozen_committed` minus the dozens already held by the
    commitment's `BOOKED`, `ALLOCATED`, and `SHIPPED` orders for that same
    ship week, with exact fill allowed (else
    `ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED`)".

    Design: Corner/validations/weekly_volume_exact_fill_then_one_dozen_overflow
    """
    set_clock("2026-09-01T00:00:00Z")
    customer = create_customer()
    commitment = create_active_commitment(
        customer["id"], weekly_dozen_committed=10_000,
        price_adjustment_cents_per_dozen=0,
    )

    first = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=6_000,
    )
    assert first["status"] == "BOOKED"
    second = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=4_000,
    )
    assert second["status"] == "BOOKED"

    version = read_commitment(commitment["id"])["version"]
    response = api.create_order(
        commitment["id"],
        create_order_payload(
            ship_week_start="2026-09-07T00:00:00Z",
            dozen_ordered=1,
            size_class="LARGE",
            expected_commitment_version=version,
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(response, ERR.ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED)

    rows, meta = validate_paginated(
        api.list_commitment_orders(commitment["id"], ADMIN)
    )
    assert meta["total_count"] == 2 and len(rows) == 2


def test_order_create_on_expired_commitment_returns_invalid_state(api):
    """After the checkpoint expires the commitment, order creation fails the
    state gate even though the requested week lies inside the printed window.

    PRD §3.5: "Any complex's operations checkpoint expires an `ACTIVE`
    commitment into `EXPIRED` once the clock passes `effective_to`."
    PRD §3.6: "Checks fire in this order: ownership for the `Customer` role;
    payload shape; the commitment must be `ACTIVE` (else
    `ERR_INVALID_STATE`); ...".

    Design: Corner/state_machines/order_create_on_expired_commitment_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    customer = create_customer(name="Budget Basket")
    commitment = create_active_commitment(
        customer["id"], weekly_dozen_committed=10_000,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-20T00:00:00Z",
    )

    set_clock("2026-09-21T00:00:00Z")
    run_ops(complex_["id"])
    expired = read_commitment(commitment["id"])
    assert expired["status"] == "EXPIRED"

    response = api.create_order(
        commitment["id"],
        create_order_payload(
            ship_week_start="2026-09-14T00:00:00Z",  # inside the old window
            dozen_ordered=100,
            size_class="LARGE",
            expected_commitment_version=expired["version"],
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(response, ERR.ERR_INVALID_STATE)
    rows, meta = validate_paginated(
        api.list_commitment_orders(commitment["id"], ADMIN)
    )
    assert rows == [] and meta["total_count"] == 0


def test_stale_commitment_version_returns_412(api):
    """OCC on the commitment version: booking bumps the version, so a second
    create replaying the pre-first version is rejected.

    PRD §2.10: "`POST /api/commitments/{id}/orders` — the request body must
    carry `expected_commitment_version` equal to the commitment's current
    `version`. Booking an order itself bumps the commitment's `version`
    (weekly allocation bookkeeping), so a second create carrying the
    pre-first-create version is stale. A mismatch is rejected with
    `ERR_STALE_COMMITMENT_VERSION` (HTTP 412), preventing the client from
    booking against a commitment state it has not observed."

    Design: Corner/complexity_layers/stale_commitment_version_returns_412
    """
    set_clock("2026-09-01T00:00:00Z")
    customer = create_customer()
    commitment = create_active_commitment(customer["id"])
    version = read_commitment(commitment["id"])["version"]

    created = validate_success(
        api.create_order(
            commitment["id"],
            create_order_payload(
                ship_week_start="2026-09-07T00:00:00Z",
                dozen_ordered=1_000,
                size_class="LARGE",
                expected_commitment_version=version,
            ),
            make_customer_headers(customer["id"]),
        ),
        201,
    )
    assert created["status"] == "BOOKED"
    bumped = read_commitment(commitment["id"])
    assert bumped["version"] == version + 1

    response = api.create_order(
        commitment["id"],
        create_order_payload(
            ship_week_start="2026-09-07T00:00:00Z",
            dozen_ordered=2_000,
            size_class="LARGE",
            expected_commitment_version=version,
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(response, ERR.ERR_STALE_COMMITMENT_VERSION)

    rows, meta = validate_paginated(
        api.list_commitment_orders(commitment["id"], ADMIN)
    )
    assert meta["total_count"] == 1 and len(rows) == 1

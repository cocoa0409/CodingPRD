"""Shipping: the ship-window bounds, the quotation precondition, the
terminal-state lockdown on cancel, and immediate consistency of the
PROVISIONAL settlement cascade.
"""

from test_helpers import (
    ADMIN,
    PLANT,
    api_client,
    allocate_order,
    book_order,
    create_active_commitment,
    create_complex,
    create_customer,
    create_house,
    create_and_place_flock,
    make_customer_headers,
    publish_quotation,
    read_order,
    read_order_settlement,
    set_clock,
    setup_laying_complex,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def _setup_allocated_order(api, with_quotation=True):
    """LAYING flock of 80000; ACTIVE commitment (+12); order of 10000 dozen
    for week 2026-09-07, ALLOCATED."""
    set_clock("2026-09-01T00:00:00Z")
    env = setup_laying_complex(hens=80_000)
    customer = create_customer()
    commitment = create_active_commitment(
        customer["id"], price_adjustment_cents_per_dozen=12,
    )
    if with_quotation:
        publish_quotation(
            price_cents_per_dozen=150, effective_date="2026-09-07T00:00:00Z"
        )
    order = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=10_000,
    )
    order = allocate_order(order["id"])
    assert order["status"] == "ALLOCATED"
    return env, customer, commitment, order


def test_ship_before_week_start_returns_422(api):
    """Shipping before the clock reaches ship_week_start fails the lower
    window bound.

    PRD §3.6: "a `PlantManager` ships an `ALLOCATED` order (else
    `ERR_INVALID_STATE`) when the clock has reached `ship_week_start` but is
    not yet fourteen days past it (else `ERR_ORDER_OUTSIDE_SHIP_WINDOW`)".

    Design: Corner/state_machines/ship_before_week_start_returns_422
    """
    _, _, _, order = _setup_allocated_order(api)
    set_clock("2026-09-06T00:00:00Z")  # day before the ship week

    validate_error(api.ship_order(order["id"], PLANT),
                   ERR.ERR_ORDER_OUTSIDE_SHIP_WINDOW)
    assert read_order(order["id"])["status"] == "ALLOCATED"
    rows, meta = validate_paginated(
        api.list_order_settlements(order["id"], ADMIN)
    )
    assert rows == [] and meta["total_count"] == 0


def test_ship_without_any_quotation_returns_no_quotation(api):
    """With zero quotations for the region/size at or before the clock, ship
    fails and no settlement is created.

    PRD §3.6: "when at least one quotation for the commitment's region and
    the order's size class is effective at or before the clock (else
    `ERR_NO_QUOTATION`)".
    PRD §3.6: "Shipping creates the order's one-to-one **settlement**".

    Design: Corner/errors/ship_without_any_quotation_returns_no_quotation
    """
    _, _, _, order = _setup_allocated_order(api, with_quotation=False)
    set_clock("2026-09-08T00:00:00Z")

    validate_error(api.ship_order(order["id"], PLANT), ERR.ERR_NO_QUOTATION)
    assert read_order(order["id"])["status"] == "ALLOCATED"
    rows, meta = validate_paginated(
        api.list_order_settlements(order["id"], ADMIN)
    )
    assert rows == [] and meta["total_count"] == 0


def test_order_cancel_from_shipped_returns_invalid_state(api):
    """CANCELLED is reachable only from BOOKED, ALLOCATED or BLOCKED.

    PRD §3.6: "Cancellation belongs to the owning `Customer` alone and is
    legal from `BOOKED`, `ALLOCATED`, or `BLOCKED` (else
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/order_cancel_from_shipped_returns_invalid_state
    """
    _, customer, _, order = _setup_allocated_order(api)
    set_clock("2026-09-08T00:00:00Z")
    shipped = ship_and_read(order["id"])
    assert shipped["status"] == "SHIPPED"

    validate_error(
        api.cancel_order(order["id"], make_customer_headers(customer["id"])),
        ERR.ERR_INVALID_STATE,
    )
    assert read_order(order["id"])["status"] == "SHIPPED"


def test_ship_response_and_settlement_immediately_visible(api):
    """Immediate consistency: the ship response carries SHIPPED, and the very
    next read shows the PROVISIONAL settlement priced off the point
    quotation.

    PRD §2.8: "The consistency model is immediate: a mutation and every
    cascade it triggers are visible in the same request's response and in all
    subsequent reads."
    PRD §3.6: "Shipping creates the order's one-to-one **settlement** —
    linked by `sales_order_id`, `ship_week_start` copied from the order,
    `dozen_shipped` set from the order's `allocated_dozen` — in `PROVISIONAL`
    status with the provisional pricing of §3.4".
    PRD §3.4: "The `provisional_unit_price_cents` is that index plus the
    commitment's `price_adjustment_cents_per_dozen`".

    Design: Corner/consistency_model/ship_response_and_settlement_immediately_visible
    """
    _, _, _, order = _setup_allocated_order(api)
    set_clock("2026-09-08T00:00:00Z")

    shipped = validate_success(api.ship_order(order["id"], PLANT))
    assert shipped["status"] == "SHIPPED"

    settlement = read_order_settlement(order["id"])
    assert settlement["status"] == "PROVISIONAL"
    assert settlement["sales_order_id"] == order["id"]
    assert settlement["dozen_shipped"] == 10_000
    # Point quotation 150 (effective 2026-09-07) + adjustment 12.
    assert settlement["provisional_index_cents"] == 150
    assert settlement["provisional_unit_price_cents"] == 162
    assert settlement["provisional_total_cents"] == 1_620_000


def ship_and_read(order_id):
    """Ship and return the updated order."""
    validate_success(api_client.ship_order(order_id, PLANT))
    return read_order(order_id)

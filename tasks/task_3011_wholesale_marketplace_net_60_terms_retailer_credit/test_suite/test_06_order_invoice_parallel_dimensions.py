"""Parallel state dimensions: the order's fulfillment state and its invoice's
collection state evolve independently (queue A, non_linear_state_machine)."""

from test_helpers import (
    ADMIN,
    make_brand_headers,
    read_invoice,
    read_order,
    set_clock,
    shipped_invoice_scenario,
    validate_success,
)


def test_invoice_ages_to_overdue_while_order_stays_delivered(api):
    """PRD §3.5: "The first is the order's invoice — exactly one per order —
    issued `OPEN` with `amount_due_cents` equal to the order's
    `subtotal_cents`, a `due_date` sixty days after the shipment timestamp (the
    net-60 terms), and `paid_amount_cents` at zero so that `balance_cents`
    equals `amount_due_cents`."
    PRD §3.9: "When the logical clock has moved past an invoice's `due_date`
    and a balance remains, the invoice transitions `OPEN → OVERDUE` the next
    time it is read or written."
    PRD §3.5: "Delivery is a lighter touch: the brand marks a shipped order
    delivered, moving it `SHIPPED → DELIVERED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions
    """
    (retailer, _, brand, order, invoice, _
     ) = shipped_invoice_scenario(api, unit_price_cents=30000, qty=1)

    # Ship at the default clock 2026-09-01: due_date is 60 days later.
    assert invoice["due_date"] == "2026-10-31T00:00:00Z"
    assert invoice["status"] == "OPEN"
    assert invoice["balance_cents"] == 30000

    # Deliver the order; the invoice does not move.
    validate_success(api.deliver_order(order["id"], make_brand_headers(brand["id"])))
    assert read_invoice(api, invoice["id"])["status"] == "OPEN"

    # Advance the clock past the due date: the invoice flips lazily on read
    # while the order remains DELIVERED.
    set_clock(api, "2026-11-05T00:00:00Z")
    overdue = read_invoice(api, invoice["id"])
    assert overdue["status"] == "OVERDUE"
    assert overdue["balance_cents"] == 30000
    assert read_order(api, order["id"])["status"] == "DELIVERED"


def test_write_off_leaves_order_delivered(api):
    """PRD §3.9: "An `OVERDUE` invoice that the retailer never cures may be
    written off by a `PlatformAdmin`, but only once the logical clock has
    reached at least thirty days past the `due_date`; an earlier attempt — or
    an attempt on an invoice that is not `OVERDUE` — fails with
    `ERR_WRITE_OFF_TOO_EARLY` (HTTP 422). Write-off moves the invoice `OVERDUE
    → WRITTEN_OFF`, a terminal state; it recomputes the account's
    `available_cents` because the balance is no longer outstanding, and it
    feeds the retailer's `risk_tier` recomputation through the adverse tally
    of the underwriting calculation."
    PRD §3.5: "Delivery is a lighter touch: the brand marks a shipped order
    delivered, moving it `SHIPPED → DELIVERED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions
    """
    (retailer, _, brand, order, invoice, _
     ) = shipped_invoice_scenario(api, unit_price_cents=30000, qty=1)
    validate_success(api.deliver_order(order["id"], make_brand_headers(brand["id"])))

    # Past due + 30d grace -> write-off succeeds; the order stays DELIVERED.
    set_clock(api, "2026-12-05T00:00:00Z")
    written_off = validate_success(api.write_off_invoice(invoice["id"], ADMIN))
    assert written_off["status"] == "WRITTEN_OFF"
    assert read_order(api, order["id"])["status"] == "DELIVERED", (
        "the collection dimension must never mutate the fulfillment dimension"
    )

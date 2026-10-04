"""Queue B (Corner/consistency_model): shipment's side effects are visible
immediately after the call."""

from test_helpers import (
    make_brand_headers,
    order_invoice,
    order_line,
    order_payout,
    place_order,
    read_brand,
    standard_market,
    validate_success,
)


def test_ship_side_effects_visible_immediately(api):
    """PRD §3.5: "Shipment atomically produces two artifacts. The first is the
    order's invoice — exactly one per order — issued `OPEN` with
    `amount_due_cents` equal to the order's `subtotal_cents`, a `due_date`
    sixty days after the shipment timestamp (the net-60 terms), and
    `paid_amount_cents` at zero so that `balance_cents` equals
    `amount_due_cents`. The second is the order's payout, computed immediately
    and scheduled: `gross_cents` equals the order's `subtotal_cents` at
    shipment, the commission rate `commission_bps` is 2,500 basis points when
    the order is an opening marketplace order (attribution `MARKETPLACE` with
    `order_seq` equal to 1), 1,500 basis points for any subsequent marketplace
    order, and zero basis points for any brand-referred order — including a
    brand-referred opening order. The `commission_cents` is the gross
    multiplied by the rate in basis points and divided by ten thousand, rounded
    half-up to whole cents, and `net_cents` is the gross minus the commission.
    The payout's `scheduled_date` is the shipment timestamp plus the brand's
    `payout_delay_days`, fixed at computation, and the brand's
    `payout_balance_cents` is immediately credited by `net_cents`. The payout
    begins life `SCHEDULED`."

    Design: Corner/consistency_model/ship_side_effects_visible_immediately
    """
    retailer, _, brand = standard_market(
        api, {"lead_time_days": 0, "payout_delay_days": 10}, {"store_type": "ONLINE"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 10000, 2)])

    shipped = validate_success(
        api.ship_order(order["id"], make_brand_headers(brand["id"]))
    )
    assert shipped["status"] == "SHIPPED"

    invoice = order_invoice(api, order["id"])
    assert invoice["status"] == "OPEN"
    assert invoice["amount_due_cents"] == 20000
    assert invoice["due_date"] == "2026-10-31T00:00:00Z"  # ship + 60 days
    assert invoice["balance_cents"] == 20000

    payout = order_payout(api, order["id"])
    assert payout["status"] == "SCHEDULED"
    assert payout["scheduled_date"] == "2026-09-11T00:00:00Z"  # ship + 10 days
    assert payout["commission_bps"] == 2500
    assert payout["net_cents"] == 15000

    assert read_brand(api, brand["id"])["payout_balance_cents"] == 15000

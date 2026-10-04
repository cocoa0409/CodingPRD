"""Return credit: opening-order-free versus reorder-fee variants
(queue A, dual_variant_calc)."""

from test_helpers import (
    active_brand,
    approve_return,
    delivered_order,
    first_line_id,
    order_invoice,
    order_line,
    read_invoice,
    receive_return,
    request_return,
    verified_retailer_with_account,
)


def _delivered_pair(api, unit_price=5000, qty=4):
    """One retailer + brand pair with two shipped-and-delivered orders."""
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0, payout_delay_days=7)
    order1 = delivered_order(api, retailer["id"], brand["id"],
                             [order_line("S1", unit_price, qty)])
    order2 = delivered_order(api, retailer["id"], brand["id"],
                             [order_line("S2", unit_price, qty)])
    return retailer, brand, order1, order2


def test_opening_order_return_is_free(api):
    """PRD §3.6: "then the fee, which is zero cents when `is_opening_order` is
    true and otherwise fifteen percent of the merchandise value rounded half-up
    to whole cents, computed from the merchandise value and never from the
    invoice balance"
    PRD §3.4: "`order_seq` equal to 1 marks the opening order, which matters
    for free returns (§3.6) and commission tiering (§3.5)."

    Design: Difficulty/dual_variant_calc/return_credit_opening_free_vs_reorder_fee
    """
    retailer, brand, order1, _ = _delivered_pair(api)

    ra = request_return(api, retailer["id"], order1["id"],
                        first_line_id(api, order1["id"]), 4)
    assert ra["is_opening_order"] is True
    approve_return(api, ra["id"], brand["id"])
    received = receive_return(api, ra["id"])

    assert received["return_fee_cents"] == 0, (
        f"opening-order return fee must be 0, got {received['return_fee_cents']}"
    )
    assert received["credit_cents"] == 20000
    invoice = read_invoice(api, order_invoice(api, order1["id"])["id"])
    assert invoice["amount_due_cents"] == 0


def test_reorder_return_carries_fifteen_percent_fee(api):
    """PRD §3.6: "then the fee, which is zero cents when `is_opening_order` is
    true and otherwise fifteen percent of the merchandise value rounded half-up
    to whole cents, computed from the merchandise value and never from the
    invoice balance; then the raw credit of merchandise minus fee; and finally
    `credit_cents`, clamped so it never exceeds the invoice's current
    `amount_due_cents` and never goes below zero."

    Design: Difficulty/dual_variant_calc/return_credit_opening_free_vs_reorder_fee
    """
    retailer, brand, _, order2 = _delivered_pair(api)

    ra = request_return(api, retailer["id"], order2["id"],
                        first_line_id(api, order2["id"]), 4)
    assert ra["is_opening_order"] is False
    approve_return(api, ra["id"], brand["id"])
    received = receive_return(api, ra["id"])

    # fee = round_half_up(20000 * 0.15) = 3000; credit = 17000
    assert received["return_fee_cents"] == 3000
    assert received["credit_cents"] == 17000
    invoice = read_invoice(api, order_invoice(api, order2["id"])["id"])
    assert invoice["amount_due_cents"] == 3000

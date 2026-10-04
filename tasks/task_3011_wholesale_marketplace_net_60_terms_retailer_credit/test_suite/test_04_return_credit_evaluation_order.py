"""Return-credit pinned evaluation order (queue A, combinatorial_formula):
merchandise -> fee from merchandise -> clamp against the pre-credit
amount_due."""

from test_helpers import (
    active_brand,
    approve_return,
    delivered_order,
    first_line_id,
    order_invoice,
    order_line,
    pay_invoice,
    read_invoice,
    receive_return,
    request_return,
    verified_retailer_with_account,
)


def test_fee_comes_from_merchandise_not_invoice_balance(api):
    """PRD §3.6: "The return credit is computed in a pinned order: first the
    returned merchandise value, the sum over the authorization's lines of each
    returned quantity times its order line's `unit_price_cents`; then the fee,
    which is zero cents when `is_opening_order` is true and otherwise fifteen
    percent of the merchandise value rounded half-up to whole cents, computed
    from the merchandise value and never from the invoice balance; then the raw
    credit of merchandise minus fee; and finally `credit_cents`, clamped so it
    never exceeds the invoice's current `amount_due_cents` and never goes below
    zero."

    Design: Difficulty/combinatorial_formula/return_credit_mode_c_evaluation_order
    """
    retailer, _ = verified_retailer_with_account(api, store_type="HYBRID")
    brand = active_brand(api, lead_time_days=0, payout_delay_days=7)

    # Opening order establishes order_seq=1 for the pair; it is left intact so
    # the retailer's return rate stays below the 0.20 abuse-guard threshold.
    order1 = delivered_order(api, retailer["id"], brand["id"],
                             [order_line("S1", 5000, 4)])

    # Reorder: 4x5000 shipped+delivered, then a 5000 partial payment.
    order2 = delivered_order(api, retailer["id"], brand["id"],
                             [order_line("S2", 5000, 4)])
    invoice2 = order_invoice(api, order2["id"])
    pay_invoice(api, invoice2["id"], retailer["id"], 5000)

    ra = request_return(api, retailer["id"], order2["id"],
                        first_line_id(api, order2["id"]), 4)
    approve_return(api, ra["id"], brand["id"])
    received = receive_return(api, ra["id"])

    # fee from merchandise (20000 * 0.15 = 3000), never from balance (15000).
    assert received["return_fee_cents"] == 3000, (
        f"fee must be computed from merchandise 20000, got {received['return_fee_cents']}"
    )
    assert received["credit_cents"] == 17000

    refreshed = read_invoice(api, invoice2["id"])
    assert refreshed["amount_due_cents"] == 3000
    assert refreshed["paid_amount_cents"] == 5000


def test_return_credit_can_close_the_invoice_to_paid(api):
    """PRD §3.6: "The invoice's `amount_due_cents` is then reduced by
    `credit_cents` (it too can never fall below zero), `balance_cents` is
    recomputed, and the invoice's status is re-evaluated — if the balance
    reaches zero while the invoice is `OPEN` or `OVERDUE`, it flips to `PAID`."

    Design: Difficulty/combinatorial_formula/return_credit_mode_c_evaluation_order
    """
    retailer, _ = verified_retailer_with_account(api, store_type="HYBRID")
    brand = active_brand(api, lead_time_days=0, payout_delay_days=7)

    # A full return of the opening order carries no fee, so the credit equals
    # the invoice's amount_due and the balance reaches exactly zero.
    order1 = delivered_order(api, retailer["id"], brand["id"],
                             [order_line("S1", 5000, 4)])
    invoice1 = order_invoice(api, order1["id"])

    ra = request_return(api, retailer["id"], order1["id"],
                        first_line_id(api, order1["id"]), 4)
    approve_return(api, ra["id"], brand["id"])
    receive_return(api, ra["id"])

    refreshed = read_invoice(api, invoice1["id"])
    assert refreshed["amount_due_cents"] == 0
    assert refreshed["balance_cents"] == 0
    assert refreshed["status"] == "PAID", (
        f"balance reaching zero from OPEN must flip the invoice to PAID, "
        f"got {refreshed['status']}"
    )

"""Transitive cascades (queue A): the fraud-confirm chain and the
return-receipt chain."""

from test_helpers import (
    approve_return,
    confirm_flag,
    delivered_order,
    first_line_id,
    get_credit_account,
    order_invoice,
    order_line,
    payouts_for_order,
    place_order,
    raise_flag,
    read_brand,
    read_invoice,
    read_order,
    read_retailer,
    receive_return,
    request_return,
    standard_market,
)


def test_fraud_confirm_suspends_and_freezes(api):
    """PRD §3.7: "For `STRAW_STOREFRONT` or `CONSUMER_RESELLER`, the linked
    retailer transitions `VERIFIED → SUSPENDED`; its credit account transitions
    `ACTIVE → FROZEN`; and every one of its orders still `PLACED` is cancelled
    — and each such cancellation issues a compensating payout to the order's
    brand, already `PAID`, with a commission of zero basis points so that
    `net_cents` equals the order's `subtotal_cents`, crediting the brand's
    `payout_balance_cents` by that amount."

    Design: Difficulty/transitive_cascade/fraud_confirm_retailer_cascade
    """
    retailer, account, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "ONLINE"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 10000, 2)])
    flag = raise_flag(api, retailer["id"], "STRAW_STOREFRONT", order["id"])

    confirmed = confirm_flag(api, flag["id"])
    assert confirmed["status"] == "CONFIRMED"

    assert read_retailer(api, retailer["id"])["verification_status"] == "SUSPENDED"
    assert get_credit_account(api, account["id"])["status"] == "FROZEN"


def test_fraud_confirm_cancels_orders_with_compensating_payout(api):
    """PRD §3.7: "every one of its orders still `PLACED` is cancelled — and
    each such cancellation issues a compensating payout to the order's brand,
    already `PAID`, with a commission of zero basis points so that `net_cents`
    equals the order's `subtotal_cents`, crediting the brand's
    `payout_balance_cents` by that amount. Brands whose merchandise was
    committed against a fraudulent buyer are thus made whole immediately."

    Design: Difficulty/transitive_cascade/fraud_confirm_retailer_cascade
    """
    retailer, account, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "ONLINE"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 10000, 2)])
    flag = raise_flag(api, retailer["id"], "STRAW_STOREFRONT", order["id"])

    confirm_flag(api, flag["id"])

    assert read_order(api, order["id"])["status"] == "CANCELLED"
    payouts = payouts_for_order(api, order["id"])
    assert len(payouts) == 1, "exactly one compensating payout is expected"
    payout = payouts[0]
    assert payout["status"] == "PAID"
    assert payout["commission_bps"] == 0
    assert payout["net_cents"] == 20000
    assert read_brand(api, brand["id"])["payout_balance_cents"] == 20000


def test_return_receive_credits_invoice_and_completes_order(api):
    """PRD §3.6: "The invoice's `amount_due_cents` is then reduced by
    `credit_cents` (it too can never fall below zero), `balance_cents` is
    recomputed, and the invoice's status is re-evaluated — if the balance
    reaches zero while the invoice is `OPEN` or `OVERDUE`, it flips to `PAID`.
    The referenced order transitions per its own machine: from `DELIVERED` to
    `PARTIALLY_RETURNED` when at least one line still has units sold, or to
    `RETURNED` when every line's `net_sold_qty` has reached zero"

    Design: Difficulty/transitive_cascade/return_receive_cascade
    """
    retailer, _, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "BRICK_AND_MORTAR"}
    )
    order = delivered_order(api, retailer["id"], brand["id"],
                            [order_line("S1", 5000, 2)])
    invoice = order_invoice(api, order["id"])

    ra = request_return(api, retailer["id"], order["id"],
                        first_line_id(api, order["id"]), 2)
    approve_return(api, ra["id"], brand["id"])
    received = receive_return(api, ra["id"])

    assert received["status"] == "RECEIVED"
    assert received["credit_cents"] == 10000  # opening order, fee 0
    refreshed_invoice = read_invoice(api, invoice["id"])
    assert refreshed_invoice["amount_due_cents"] == 0
    assert refreshed_invoice["status"] == "PAID"
    assert read_order(api, order["id"])["status"] == "RETURNED"


def test_return_receive_recomputes_retailer_return_rate(api):
    """PRD §3.6: "The `return_rate` itself is a simple ratio maintained across
    all of the retailer's activity: the numerator is the total units returned
    across return authorizations that have reached `RECEIVED`, spanning every
    order; the denominator is the total `net_sold_qty` across all order lines
    whose order is not `CANCELLED`; when the denominator is zero the rate is
    zero."

    Design: Difficulty/transitive_cascade/return_receive_cascade
    """
    retailer, _, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "BRICK_AND_MORTAR"}
    )
    order = delivered_order(api, retailer["id"], brand["id"],
                            [order_line("S1", 5000, 4)])

    ra = request_return(api, retailer["id"], order["id"],
                        first_line_id(api, order["id"]), 2)
    approve_return(api, ra["id"], brand["id"])
    receive_return(api, ra["id"])

    refreshed = read_retailer(api, retailer["id"])
    # Receipt first draws net_sold_qty down 4 -> 2, then recomputes the rate:
    # numerator 2 returned units over denominator 2 net-sold units = 1.0.
    assert refreshed["return_rate"] == 1.0, (
        f"2 returned of 2 remaining net sold must read 1.0, got {refreshed['return_rate']}"
    )

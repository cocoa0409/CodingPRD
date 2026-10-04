"""Queue B (Corner/calculations): commission tier selection and return-rate
input-set filtering."""

from test_helpers import (
    ADMIN,
    active_brand,
    approve_return,
    brand_payload,
    confirm_documents,
    delivered_order,
    first_line_id,
    get_success_data,
    make_brand_headers,
    make_retailer_headers,
    open_credit_account,
    order_line,
    payouts_for_order,
    place_order,
    read_retailer,
    receive_return,
    register_retailer,
    request_return,
    ship_order,
    validate_success,
    verified_retailer_with_account,
)


def test_commission_tiers_opening_vs_reorder_vs_referred(api):
    """PRD §3.5: "the commission rate `commission_bps` is 2,500 basis points
    when the order is an opening marketplace order (attribution `MARKETPLACE`
    with `order_seq` equal to 1), 1,500 basis points for any subsequent
    marketplace order, and zero basis points for any brand-referred order —
    including a brand-referred opening order."
    PRD §3.4: "The `attribution` is `BRAND_REFERRED` if the retailer's
    registration was bound to this brand's referral code, and `MARKETPLACE`
    otherwise."

    Design: Corner/calculations/commission_tiers_opening_vs_reorder_vs_referred
    """
    # Brand A with a marketplace-sourced retailer: opening then reorder.
    # BRICK_AND_MORTAR's 250000 provisional limit covers both 100000 orders.
    brand_a = active_brand(api, lead_time_days=0, payout_delay_days=7)
    rm, _ = verified_retailer_with_account(api, store_type="BRICK_AND_MORTAR")
    om1 = place_order(api, rm["id"], brand_a["id"], [order_line("S1", 10000, 10)])
    ship_order(api, om1["id"], brand_a["id"])
    om2 = place_order(api, rm["id"], brand_a["id"], [order_line("S2", 10000, 10)])
    ship_order(api, om2["id"], brand_a["id"])

    # Brand B with a referral-bound retailer: even the opening order pays 0.
    brand_b = get_success_data(
        api.create_brand(brand_payload(lead_time_days=0, payout_delay_days=7),
                         make_brand_headers("new-brand"))
    )
    validate_success(api.activate_brand(brand_b["id"], make_brand_headers(brand_b["id"])))
    rr = register_retailer(api, referral_code=brand_b["referral_code"])
    confirm_documents(api, rr["id"])
    validate_success(api.verify_retailer(rr["id"], {"decision": "APPROVE"}, ADMIN))
    open_credit_account(api, rr["id"])
    orr1 = place_order(api, rr["id"], brand_b["id"], [order_line("S1", 10000, 10)])
    ship_order(api, orr1["id"], brand_b["id"])

    p_om1 = payouts_for_order(api, om1["id"])[0]
    assert p_om1["commission_bps"] == 2500
    assert p_om1["commission_cents"] == 25000
    assert p_om1["net_cents"] == 75000

    p_om2 = payouts_for_order(api, om2["id"])[0]
    assert p_om2["commission_bps"] == 1500
    assert p_om2["commission_cents"] == 15000
    assert p_om2["net_cents"] == 85000

    p_orr1 = payouts_for_order(api, orr1["id"])[0]
    assert p_orr1["commission_bps"] == 0
    assert p_orr1["commission_cents"] == 0
    assert p_orr1["net_cents"] == 100000


def test_return_rate_excludes_cancelled_orders(api):
    """PRD §3.6: "The `return_rate` itself is a simple ratio maintained across
    all of the retailer's activity: the numerator is the total units returned
    across return authorizations that have reached `RECEIVED`, spanning every
    order; the denominator is the total `net_sold_qty` across all order lines
    whose order is not `CANCELLED`; when the denominator is zero the rate is
    zero."
    PRD §3.6: "The value is stored to four decimal places with round-half-up,
    and it is recomputed on every unit-affecting mutation."

    Design: Corner/calculations/return_rate_excludes_cancelled_orders
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)

    order1 = delivered_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 4)])
    ra = request_return(api, retailer["id"], order1["id"],
                        first_line_id(api, order1["id"]), 2)
    approve_return(api, ra["id"], brand["id"])
    receive_return(api, ra["id"])
    # Receipt draws net_sold_qty down 4 -> 2 before the rate is recomputed:
    # 2 returned / 2 net sold = 1.0.
    assert read_retailer(api, retailer["id"])["return_rate"] == 1.0

    # Placing a second order grows the denominator: 2 / (2 + 4) = 0.3333.
    order2 = place_order(api, retailer["id"], brand["id"], [order_line("S2", 5000, 4)])
    assert read_retailer(api, retailer["id"])["return_rate"] == 0.3333

    # Cancelling it removes its units from the denominator again: 2 / 2 = 1.0.
    validate_success(api.cancel_order(order2["id"], make_retailer_headers(retailer["id"])))
    assert read_retailer(api, retailer["id"])["return_rate"] == 1.0


def test_underwriting_tier_boundaries(api):
    """PRD §3.3: "The limit equals the base, plus 50,000 cents for each on-time
    invoice, minus 100,000 cents for each adverse invoice, and the result is
    then clamped to lie between 50,000 cents on the low end and 1,000,000 cents
    on the high end inclusive."
    PRD §3.3: "The retailer's `risk_tier` derives from the clamped limit: a
    limit of 100,000 cents or less is `HIGH`, a limit above 100,000 and at most
    400,000 cents is `MEDIUM`, and anything above 400,000 cents is `LOW`."

    Design: Corner/calculations/underwriting_tier_boundaries
    """
    from test_helpers import (
        get_credit_account,
        order_invoice,
        pay_invoice,
        set_clock,
    )

    retailer, account = verified_retailer_with_account(
        api, store_type="BRICK_AND_MORTAR"
    )
    brand = active_brand(api, lead_time_days=0)

    def _ship_and_invoice(sku):
        order = place_order(api, retailer["id"], brand["id"],
                            [order_line(sku, 10000, 1)])
        ship_order(api, order["id"], brand["id"])
        return order_invoice(api, order["id"])

    inv1 = _ship_and_invoice("S1")
    inv2 = _ship_and_invoice("S2")
    inv3 = _ship_and_invoice("S3")

    # Invoices 1 and 3 settle on time (before their due dates); invoice 2
    # settles after its due date.
    pay_invoice(api, inv1["id"], retailer["id"], 10000)
    pay_invoice(api, inv3["id"], retailer["id"], 10000)
    set_clock(api, "2026-11-15T00:00:00Z")
    pay_invoice(api, inv2["id"], retailer["id"], 10000)

    reviewed = validate_success(
        api.limit_review(
            account["id"],
            {
                "expected_credit_account_version": get_credit_account(
                    api, account["id"]
                )["version"]
            },
            ADMIN,
        )
    )
    # 250000 + 2*50000 - 1*100000 = 250000 -> strictly inside MEDIUM.
    assert reviewed["limit_cents"] == 250000
    assert read_retailer(api, retailer["id"])["risk_tier"] == "MEDIUM"

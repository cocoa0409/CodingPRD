"""Underwriting formula: multi-input arithmetic plus the two-sided clamp
(queue A, combinatorial_formula)."""

from test_helpers import (
    ADMIN,
    active_brand,
    get_credit_account,
    order_invoice,
    order_line,
    pay_invoice,
    place_order,
    read_retailer,
    set_clock,
    ship_order,
    validate_success,
    verified_retailer_with_account,
)


def test_limit_review_clamps_to_floor_after_two_write_offs(api):
    """PRD §3.3: "The limit equals the base, plus 50,000 cents for each on-time
    invoice, minus 100,000 cents for each adverse invoice, and the result is
    then clamped to lie between 50,000 cents on the low end and 1,000,000 cents
    on the high end inclusive."
    PRD §3.3: "The retailer's `risk_tier` derives from the clamped limit: a
    limit of 100,000 cents or less is `HIGH`, a limit above 100,000 and at most
    400,000 cents is `MEDIUM`, and anything above 400,000 cents is `LOW`."

    Design: Difficulty/combinatorial_formula/underwriting_mode_a_tiered_clamp
    """
    retailer, account = verified_retailer_with_account(api, store_type="ONLINE")
    assert account["limit_cents"] == 150000  # provisional

    brand = active_brand(api, lead_time_days=0, payout_delay_days=7)
    invoices = []
    for sku in ("S1", "S2"):
        order = place_order(api, retailer["id"], brand["id"],
                            [order_line(sku, 10000, 1)])
        ship_order(api, order["id"], brand["id"])
        invoices.append(order_invoice(api, order["id"]))

    # Age both invoices past due (+30d grace) and write them off.
    set_clock(api, "2026-12-20T00:00:00Z")
    for invoice in invoices:
        validate_success(api.write_off_invoice(invoice["id"], ADMIN))
        assert read_retailer(api, retailer["id"])  # touch point

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
    # raw: 150000 - 2*100000 = -50000 -> floor clamp 50000
    assert reviewed["limit_cents"] == 50000, (
        f"expected floor-clamped 50000, got {reviewed['limit_cents']}"
    )
    refreshed = read_retailer(api, retailer["id"])
    assert refreshed["risk_tier"] == "HIGH", (
        f"limit 50000 <= 100000 must be HIGH, got {refreshed['risk_tier']}"
    )


def test_on_time_and_late_mix_lands_at_tier_boundary(api):
    """PRD §3.3: "An invoice counts toward the on-time tally when it reached
    `PAID` and the payment that drove its balance to zero was recorded with a
    `paid_at` no later than the invoice's `due_date`; an invoice counts toward
    the adverse tally when it is `WRITTEN_OFF`, or when it reached `PAID` but
    the settling payment's `paid_at` fell after the `due_date`."
    PRD §3.3: "a limit of 100,000 cents or less is `HIGH`, a limit above
    100,000 and at most 400,000 cents is `MEDIUM`, and anything above 400,000
    cents is `LOW`."

    Design: Difficulty/combinatorial_formula/underwriting_mode_a_tiered_clamp
    """
    retailer, account = verified_retailer_with_account(
        api, store_type="BRICK_AND_MORTAR"
    )
    brand = active_brand(api, lead_time_days=0, payout_delay_days=7)

    def _ship_and_invoice(sku):
        order = place_order(api, retailer["id"], brand["id"],
                            [order_line(sku, 10000, 1)])
        ship_order(api, order["id"], brand["id"])
        return order_invoice(api, order["id"])

    inv1 = _ship_and_invoice("S1")
    inv2 = _ship_and_invoice("S2")
    inv3 = _ship_and_invoice("S3")

    # Invoice 1 and 3 paid on time (clock still at the default, before due).
    pay_invoice(api, inv1["id"], retailer["id"], 10000)
    pay_invoice(api, inv3["id"], retailer["id"], 10000)
    # Invoice 2 paid late: after its due date.
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
    # 250000 + 2*50000 - 1*100000 = 250000
    assert reviewed["limit_cents"] == 250000, (
        f"expected 250000, got {reviewed['limit_cents']}"
    )
    refreshed = read_retailer(api, retailer["id"])
    assert refreshed["risk_tier"] == "MEDIUM"

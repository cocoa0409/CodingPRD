"""Credit-limit underwriting: the provisional variant at account opening versus
the behavioral variant at limit review (queue A, dual_variant_calc)."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_brand,
    confirm_documents,
    get_credit_account,
    order_invoice,
    order_line,
    pay_invoice,
    place_order,
    read_retailer,
    register_retailer,
    set_clock,
    ship_order,
    validate_error,
    validate_success,
    verified_retailer_with_account,
)


def test_provisional_limit_is_pure_store_type_base(api):
    """PRD §3.3: "At opening, the underwriting calculation runs in its
    provisional form — the retailer has no invoice history yet, so the limit is
    purely a function of store type — and the account comes up `ACTIVE` with
    `available_cents` equal to the freshly computed `limit_cents`."
    PRD §3.3: "Every retailer starts from a base by store type: 250,000 cents
    for `BRICK_AND_MORTAR`, 150,000 cents for `ONLINE`, and 200,000 cents for
    `HYBRID`."

    Design: Difficulty/dual_variant_calc/credit_limit_provisional_vs_behavioral
    """
    retailer = register_retailer(api, store_type="BRICK_AND_MORTAR")
    confirm_documents(api, retailer["id"])
    validate_success(api.verify_retailer(retailer["id"], {"decision": "APPROVE"}, ADMIN))

    account = validate_success(
        api.create_credit_account({"retailer_id": retailer["id"]}, ADMIN), 201
    )
    assert account["status"] == "ACTIVE"
    assert account["limit_cents"] == 250000, (
        f"provisional BRICK_AND_MORTAR limit must be 250000, got {account['limit_cents']}"
    )
    assert account["available_cents"] == 250000

    online = register_retailer(api, store_type="ONLINE")
    confirm_documents(api, online["id"])
    validate_success(api.verify_retailer(online["id"], {"decision": "APPROVE"}, ADMIN))
    online_account = validate_success(
        api.create_credit_account({"retailer_id": online["id"]}, ADMIN), 201
    )
    assert online_account["limit_cents"] == 150000


def test_behavioral_review_adjusts_base_with_late_invoice(api):
    """PRD §3.3: "The limit equals the base, plus 50,000 cents for each on-time
    invoice, minus 100,000 cents for each adverse invoice, and the result is
    then clamped to lie between 50,000 cents on the low end and 1,000,000 cents
    on the high end inclusive."
    PRD §3.3: "an invoice counts toward the adverse tally when it is
    `WRITTEN_OFF`, or when it reached `PAID` but the settling payment's
    `paid_at` fell after the `due_date`."

    Design: Difficulty/dual_variant_calc/credit_limit_provisional_vs_behavioral
    """
    retailer, account = verified_retailer_with_account(
        api, store_type="BRICK_AND_MORTAR"
    )
    assert account["limit_cents"] == 250000  # provisional variant at opening

    brand = active_brand(api, lead_time_days=0, payout_delay_days=7)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 20000, 1)])
    ship_order(api, order["id"], brand["id"])
    invoice = order_invoice(api, order["id"])

    # Advance past the net-60 due date, then pay late.
    set_clock(api, "2026-11-15T00:00:00Z")
    pay_invoice(api, invoice["id"], retailer["id"], 20000)

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
    # behavioral variant: 250000 + 0*50000 - 1*100000 = 150000
    assert reviewed["limit_cents"] == 150000, (
        f"expected 150000 after one late-paid invoice, got {reviewed['limit_cents']}"
    )
    refreshed = read_retailer(api, retailer["id"])
    assert refreshed["risk_tier"] == "MEDIUM", (
        f"150000 is above 100000 and at most 400000 -> MEDIUM, got {refreshed['risk_tier']}"
    )


def test_review_rejects_stale_account_version(api):
    """PRD §2.8: "A credit limit review submitted for an account must carry
    `expected_credit_account_version`, the account `version` the reviewer last
    observed; if the account's current `version` has advanced — because a
    payment, shipment, return, or write-off has since mutated the account's
    derived fields — the review is rejected with `ERR_STALE_VERSION` (HTTP 412),
    so a reviewer never re-underwrites an account whose posture they have not
    seen."

    Design: Difficulty/dual_variant_calc/credit_limit_provisional_vs_behavioral
    """
    retailer, account = verified_retailer_with_account(
        api, store_type="BRICK_AND_MORTAR"
    )
    stale_version = account["version"]

    brand = active_brand(api, lead_time_days=0)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 10000, 1)])
    ship_order(api, order["id"], brand["id"])
    invoice = order_invoice(api, order["id"])
    pay_invoice(api, invoice["id"], retailer["id"], 10000)

    response = api.limit_review(
        account["id"], {"expected_credit_account_version": stale_version}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

"""Queue B (Corner/cross_cutting): optimistic concurrency guards and the
due-date selection of the payout batch run."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_brand,
    create_grant,
    exclusivity_grant_payload,
    get_credit_account,
    make_brand_headers,
    order_invoice,
    order_line,
    order_payout,
    pay_invoice,
    place_order,
    read_brand,
    set_clock,
    ship_order,
    validate_error,
    validate_success,
    verified_retailer,
    verified_retailer_with_account,
)


def test_occ_credit_limit_review_stale(api):
    """PRD §3.3: "The review is OCC-guarded per §2.8: the request must carry
    `expected_credit_account_version`, and a stale value is rejected with
    `ERR_STALE_VERSION` (HTTP 412). A successful review recomputes `limit_cents`
    under the behavioral variant, resets `available_cents` to the new limit
    minus the sum of the retailer's outstanding invoice balances, recomputes
    the linked retailer's `risk_tier`, and increments the account's `version`."

    Design: Corner/cross_cutting/occ_credit_limit_review_stale
    """
    retailer, account = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 10000, 1)])
    ship_order(api, order["id"], brand["id"])
    invoice = order_invoice(api, order["id"])

    pre = get_credit_account(api, account["id"])["version"]
    # Paying the invoice mutates the account's derived fields (bumps version).
    pay_invoice(api, invoice["id"], retailer["id"], 10000)

    stale = api.limit_review(account["id"], {"expected_credit_account_version": pre},
                             ADMIN)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    fresh = get_credit_account(api, account["id"])["version"]
    reviewed = validate_success(
        api.limit_review(account["id"], {"expected_credit_account_version": fresh},
                         ADMIN)
    )
    # ONLINE base 150000 + 1 on-time invoice * 50000 = 200000.
    assert reviewed["limit_cents"] == 200000


def test_occ_exclusivity_create_stale(api):
    """PRD §2.8: "Likewise, creating an exclusivity grant must carry
    `expected_brand_version`, the brand `version` the client last observed; if
    the brand's `version` has advanced — through a new grant, a payout accrual,
    or an abuse assessment — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.8: "Creating the grant bumps the brand's `version` along with the
    new grant's own bookkeeping."

    Design: Corner/cross_cutting/occ_exclusivity_create_stale
    """
    holder = verified_retailer(api, lat=54.5, lng=-114.5)
    other = verified_retailer(api, lat=55.5, lng=-115.5)
    brand = active_brand(api, lead_time_days=0)

    stale_version = read_brand(api, brand["id"])["version"]
    create_grant(api, brand["id"], holder["id"],
                 center_lat=54.5, center_lng=-114.5)

    rejected = api.create_exclusivity_grant(
        exclusivity_grant_payload(brand["id"], other["id"], stale_version,
                                  center_lat=55.5, center_lng=-115.5),
        make_brand_headers(brand["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION, 412)

    fresh_version = read_brand(api, brand["id"])["version"]
    granted = validate_success(
        api.create_exclusivity_grant(
            exclusivity_grant_payload(brand["id"], other["id"], fresh_version,
                                      center_lat=55.5, center_lng=-115.5),
            make_brand_headers(brand["id"]),
        ),
        201,
    )
    assert granted["status"] == "ACTIVE"


def test_payout_process_due_selects_only_due(api):
    """PRD §3.10: "A periodic batch run, invoked by a `PlatformAdmin`, sweeps
    every payout still `SCHEDULED` whose `scheduled_date` has been reached by
    the logical clock and moves each to `PROCESSING`, debiting each brand's
    `payout_balance_cents` by that payout's `net_cents` — the debit is recorded
    even when it takes the balance negative."
    PRD §3.5: "The payout's `scheduled_date` is the shipment timestamp plus the
    brand's `payout_delay_days`, fixed at computation, and the brand's
    `payout_balance_cents` is immediately credited by `net_cents`."

    Design: Corner/cross_cutting/payout_process_due_selects_only_due
    """
    retailer, account = verified_retailer_with_account(api, store_type="ONLINE")
    brand1 = active_brand(api, lead_time_days=0, payout_delay_days=7)
    brand2 = active_brand(api, lead_time_days=0, payout_delay_days=30)

    o1 = place_order(api, retailer["id"], brand1["id"], [order_line("S1", 10000, 1)])
    ship_order(api, o1["id"], brand1["id"])
    o2 = place_order(api, retailer["id"], brand2["id"], [order_line("S1", 10000, 1)])
    ship_order(api, o2["id"], brand2["id"])

    # Both are opening marketplace orders: net 7500 each.
    assert read_brand(api, brand1["id"])["payout_balance_cents"] == 7500
    assert read_brand(api, brand2["id"])["payout_balance_cents"] == 7500

    # At 2026-09-08 only brand1's payout (scheduled +7d) is due; brand2's
    # payout (scheduled +30d = 2026-10-01) stays SCHEDULED.
    set_clock(api, "2026-09-08T00:00:00Z")
    validate_success(api.process_due_payouts(ADMIN))

    assert read_brand(api, brand1["id"])["payout_balance_cents"] == 0
    assert read_brand(api, brand2["id"])["payout_balance_cents"] == 7500
    assert order_payout(api, o2["id"])["status"] == "SCHEDULED"

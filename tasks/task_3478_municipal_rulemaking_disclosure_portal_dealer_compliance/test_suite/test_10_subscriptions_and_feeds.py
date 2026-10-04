"""Market-data licensing: the four-input monthly fee, the pinned
round-per-line-then-sum annual invoice, activation gating, and licensed
feed access (PRD sections 2.7, 3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cents,
    create_advisor_org,
    create_dealer_org,
    create_issuer_org,
    create_subscription,
    create_trade,
    make_market_data_subscriber_headers,
    set_clock,
    setup_active_subscription,
    suspend_organization,
    validate_error,
    validate_success,
)

LICENSING = TEST_USERS["licensing_officer_headers"]

UNKNOWN_SUBSCRIPTION_ID = "11111111-2222-3333-4444-555555555555"


def test_monthly_fee_interacts_all_four_inputs(api):
    """PRD section 3.7: "The unrounded fee is then the product's base
    charge plus the per-seat rate multiplied by the billable seats, the
    whole of that multiplied first by the license-scope multiplier and then
    by the licensee organization's type discount, and the final result is
    rounded half-up to a whole cent exactly once — no intermediate rounding
    occurs. The schedule is: base charges of 250,000 cents for
    `TRADE_REALTIME`, 99,999 cents for `TRADE_HISTORICAL`, and 150,000
    cents for `DISCLOSURE_ARCHIVE`; per-seat rates of 5,000, 2,500, and
    1,000 cents respectively; included allowances of 5, 10, and 20 seats
    respectively; scope multipliers of 1.0 for `INTERNAL`, 1.5 for
    `DISPLAY`, and 2.25 for `REDISTRIBUTION`; and an org-type discount of
    0.9 for a `MUNICIPAL_ADVISOR` licensee with 1.0 (no discount) for
    `ISSUER`, `OBLIGATED_PERSON`, and `BROKER_DEALER` licensees."
    (250000 + 7*5000) * 2.25 * 0.9 rounds to 577125; the annual invoice
    is twelve times that.

    Design: Difficulty/combinatorial_formula/subscription_fee_multi_input_interaction
    """
    org = create_advisor_org(api, org_code="MA-200", name="Advisor Two")
    resp = api.create_data_subscription(
        {
            "product_code": "TRADE_REALTIME",
            "licensee_org_id": org["id"],
            "subscriber_principal": "sub-ma-1",
            "license_scope": "REDISTRIBUTION",
            "seats": 12,
        },
        LICENSING,
    )
    data = validate_success(resp, 201)
    assert_cents(data["monthly_fee_cents"], 577125, "monthly_fee_cents")
    assert_cents(data["annual_invoice_cents"], 6925500, "annual_invoice_cents")


def test_included_seat_floor_never_bills_below_zero(api):
    """PRD section 3.7: "The number of billable seats is the requested
    `seats` minus the product's included allowance, never fewer than
    zero." For TRADE_REALTIME x REDISTRIBUTION on a MUNICIPAL_ADVISOR
    licensee: seats == 5 (the included allowance) bills (250000 + 0) *
    2.25 * 0.9 = 506250; the sixth seat adds exactly one 5,000-cent rate
    step — (255000) * 2.25 * 0.9 = 516375.

    Design: Difficulty/combinatorial_formula/subscription_fee_multi_input_interaction
    """
    org = create_advisor_org(api, org_code="MA-201", name="Advisor Floor")
    at_floor = create_subscription(
        api, org["id"], product_code="TRADE_REALTIME",
        subscriber_principal="sub-fl-1", license_scope="REDISTRIBUTION", seats=5,
    )
    assert_cents(at_floor["monthly_fee_cents"], 506250, "monthly fee at the included-seat floor")

    one_over = create_subscription(
        api, org["id"], product_code="TRADE_REALTIME",
        subscriber_principal="sub-fl-2", license_scope="REDISTRIBUTION", seats=6,
    )
    assert_cents(one_over["monthly_fee_cents"], 516375, "monthly fee one seat above the floor")


def test_annual_invoice_rounds_per_line_then_sums(api):
    """PRD section 3.7: "The annual invoice, `annual_invoice_cents`, is
    twelve times the stored monthly fee: each of the twelve identical
    monthly lines is rounded to whole cents first and the lines are then
    summed — computing the annual figure by rounding a single unrounded
    yearly total is forbidden, because the two orders diverge whenever the
    unrounded monthly fee carries a fractional cent." TRADE_HISTORICAL x
    DISPLAY x 11 seats on a BROKER_DEALER licensee: (99999 + 1*2500) * 1.5
    = 153748.5, rounded per line to 153749; twelve lines sum to 1844988
    (the forbidden order would give 1844982).

    Design: Difficulty/combinatorial_formula/annual_invoice_round_per_line_then_sum
    """
    org = create_dealer_org(api, org_code="BD-201", name="Dealer Two")
    resp = api.create_data_subscription(
        {
            "product_code": "TRADE_HISTORICAL",
            "licensee_org_id": org["id"],
            "subscriber_principal": "sub-bd-1",
            "license_scope": "DISPLAY",
            "seats": 11,
        },
        LICENSING,
    )
    data = validate_success(resp, 201)
    assert_cents(data["monthly_fee_cents"], 153749, "monthly_fee_cents")
    assert_cents(data["annual_invoice_cents"], 1844988, "annual_invoice_cents")


def test_annual_invoice_rounding_order_with_zero_billable_seats(api):
    """PRD section 3.7: "rounded half-up to a whole cent exactly once" for
    the monthly line, and the invoice "is twelve times the stored monthly
    fee". TRADE_HISTORICAL x DISPLAY with seats == 10 (the included
    allowance) leaves the odd-cent base 99999: 99999 * 1.5 = 149998.5,
    rounded half-up per line to 149999, times twelve = 1799988 (the
    forbidden sum-then-round order would give 1799982).

    Design: Difficulty/combinatorial_formula/annual_invoice_round_per_line_then_sum
    """
    org = create_dealer_org(api, org_code="BD-202", name="Dealer Rounding")
    subscription = create_subscription(
        api, org["id"], product_code="TRADE_HISTORICAL",
        subscriber_principal="sub-bd-2", license_scope="DISPLAY", seats=10,
    )
    assert_cents(subscription["monthly_fee_cents"], 149999, "monthly_fee_cents")
    assert_cents(subscription["annual_invoice_cents"], 1799988, "annual_invoice_cents")


def test_subscription_activation_requires_active_licensee_org(api):
    """PRD section 3.7: a subscription names "a `licensee_org_id` whose
    organization must be `ACTIVE` both at creation and again at activation
    — otherwise `ERR_ORG_SUSPENDED`".

    Design: Corner/validations/subscription_activation_requires_active_licensee_org
    """
    org = create_issuer_org(api, org_code="IS-3009", name="Issuer Licensee")
    subscription = create_subscription(
        api, org["id"], product_code="DISCLOSURE_ARCHIVE",
        subscriber_principal="sub-i-1", license_scope="INTERNAL", seats=1,
    )
    suspend_organization(api, org["id"], reason="regulatory")

    resp = api.transition_data_subscription(subscription["id"], {"to_state": "ACTIVE"}, LICENSING)
    validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED)


def test_feed_without_subscription_returns_product_not_licensed(api):
    """PRD section 3.7: "A `MarketDataSubscriber` may pull the feed for a
    product only when an `ACTIVE` data subscription exists for the path's
    `product_code` whose `subscriber_principal` equals the caller's
    `X-User-ID`; without one the request is rejected with
    `ERR_PRODUCT_NOT_LICENSED` (HTTP 403), the last check in the §2.5
    order."

    Design: Corner/validations/feed_without_subscription_returns_product_not_licensed
    """
    create_dealer_org(api, org_code="BD-3010", name="Dealer Nolicense")
    resp = api.get_data_feed("TRADE_REALTIME", make_market_data_subscriber_headers("sub-stranger"))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_LICENSED)


def test_licensed_feed_returns_product_dataset_and_authorizing_subscription(api):
    """PRD section 3.7: "A successful feed read returns the `product_code`,
    the `subscription_id` that authorized the pull, and a `record_count`
    giving the number of records currently in the product dataset:
    `DISSEMINATED` trade reports for `TRADE_REALTIME` and
    `TRADE_HISTORICAL`, and `PUBLISHED` disclosure submissions for
    `DISCLOSURE_ARCHIVE`."

    Design: Corner/endpoints/licensed_feed_returns_product_dataset
    """
    org, subscription = setup_active_subscription(
        api, product_code="TRADE_REALTIME", subscriber_principal="sub-ok",
        license_scope="INTERNAL", seats=3,
    )
    set_clock(api, "2026-09-01T12:00:00Z")
    create_trade(api, org["id"], trade_type="CUSTOMER_BUY", par_amount=100000,
                 price=100.0, executed_at="2026-09-01T11:55:00Z")
    create_trade(api, org["id"], trade_type="CUSTOMER_SELL", par_amount=200000,
                 price=100.5, executed_at="2026-09-01T11:56:00Z")

    resp = api.get_data_feed("TRADE_REALTIME", make_market_data_subscriber_headers("sub-ok"))
    feed = validate_success(resp, 200)
    assert feed["product_code"] == "TRADE_REALTIME"
    assert feed["subscription_id"] == subscription["id"]
    assert feed["record_count"] == 2, (
        f"two DISSEMINATED trades must yield record_count 2, got {feed['record_count']}"
    )


def test_feed_license_is_scoped_to_the_registered_principal(api):
    """PRD section 3.7: "A `MarketDataSubscriber` may pull the feed for a
    product only when an `ACTIVE` data subscription exists for the path's
    `product_code` whose `subscriber_principal` equals the caller's
    `X-User-ID`" — a subscription registered to a different principal does
    not license the pull, and the refusal is `ERR_PRODUCT_NOT_LICENSED`
    (HTTP 403).

    Design: Corner/rbac/subscriber_with_wrong_principal_cannot_pull_feed
    """
    setup_active_subscription(
        api, product_code="TRADE_HISTORICAL", subscriber_principal="sub-ok",
        license_scope="INTERNAL", seats=2,
    )
    resp = api.get_data_feed(
        "TRADE_HISTORICAL", make_market_data_subscriber_headers("sub-other")
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_LICENSED)


def test_transition_unknown_subscription_returns_not_found(api):
    """PRD section 2.7: "Each resource family carries its own not-found
    error identifier:" — for data subscriptions that identifier is
    `ERR_SUBSCRIPTION_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/transition_unknown_subscription_returns_subscription_not_found
    """
    resp = api.transition_data_subscription(
        UNKNOWN_SUBSCRIPTION_ID, {"to_state": "ACTIVE"}, LICENSING
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND)

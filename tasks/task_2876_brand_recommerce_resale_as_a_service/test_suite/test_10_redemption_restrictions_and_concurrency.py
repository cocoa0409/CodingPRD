"""The four redemption restrictions, their declared order, and the
optimistic-concurrency check that sits in front of all of them.

Every purchase here settles the same listing — an OUTERWEAR grade B unit at
floor(50000 * 3900 / 10000) = 19500, so gross 19500, a 900 bp channel fee of
1755 and an order total of 21255 — and only the brand-currency terms vary. As in
§3.5 a unit can only be refurbished in a bay belonging to the store that took
custody of its trade-in, so the seller's item always arrives `IN_STORE` and the
buyer's brand currency always comes from a mail-in trade-in of their own.
"""

from test_helpers import (
    ADMIN,
    CREDIT_POLICY_CORE,
    CREDIT_POLICY_OPEN,
    GRADE_POLICY_FOOTWEAR_A,
    GRADE_POLICY_OUTERWEAR_B,
    MERCH,
    TEST_DEFAULTS,
    api_client,
    assert_credit_ledger_entry,
    assert_instant,
    assert_null,
    assert_pagination_meta,
    assert_resale_order,
    assert_unit_dimensions,
    create_customer,
    create_resale_order_payload,
    fetch_customer,
    fetch_grant,
    fetch_order,
    fetch_unit,
    grant_ledger_entries,
    list_unit,
    make_customer_headers,
    patch_customer,
    pause_channel,
    place_order,
    return_request_payload,
    setup_credit_source_grant,
    setup_estate,
    setup_listed_unit,
    setup_refurbished_unit,
    validate_error,
    validate_paginated,
    validate_success,
)

GROSS = 19500
FEE = 1755
TOTAL = 21255


def _seller_listing(estate, **overrides):
    """Ava's OWNED_INVENTORY unit, refurbished for nothing and listed at 19500."""
    scenario = setup_listed_unit(estate, loyalty_tier="PLUS", **overrides)
    assert scenario["grant"]["issued_amount_minor"] == 10500
    assert scenario["unit"]["list_price_minor"] == GROSS
    assert_unit_dimensions(scenario["unit"], "LISTED", "CAPITALIZED")
    return scenario


def _attempt_purchase(buyer, channel, unit, requested_credit_minor, version=None):
    """A purchase whose refusal is the thing being observed."""
    payload = create_resale_order_payload(
        buyer["id"],
        channel["id"],
        unit["id"],
        requested_credit_minor,
        fetch_customer(buyer["id"])["version"] if version is None else version,
    )
    return api_client.create_resale_order(payload, make_customer_headers(buyer["id"]))


def _orders_of(customer_id):
    return validate_paginated(
        api_client.list_resale_orders(ADMIN, {"customer_id": customer_id})
    )


def _open_policy_estate():
    """A brand-currency policy that permits redeeming the entire order total.

    With `max_redemption_pct_bp` at ten thousand the cap is the order total
    itself, so the cash-remainder floor is the only rule left that can bind.
    """
    return setup_estate(
        grade_policies=(GRADE_POLICY_OUTERWEAR_B, GRADE_POLICY_FOOTWEAR_A),
        credit_policy=CREDIT_POLICY_OPEN,
    )


def _rich_buyer(estate):
    """Ben, holding one 48300 grant — more than any request in this file draws."""
    scenario = setup_credit_source_grant(
        estate,
        loyalty_tier="PLUS",
        product_category="FOOTWEAR",
        declared_grade="A",
        assessed_grade="A",
        msrp_minor=TEST_DEFAULTS["FOOTWEAR_MSRP_MINOR"],
        item_mass_grams=TEST_DEFAULTS["FOOTWEAR_MASS_GRAMS"],
    )
    # 42000 base + 4200 mail-in + 2100 PLUS loyalty, each computed off the base.
    assert scenario["grant"]["issued_amount_minor"] == 48300
    assert scenario["customer"]["credit_balance_minor"] == 48300
    return scenario


def test_a_cash_remainder_of_exactly_the_policy_minimum_is_accepted():
    """499 of residual cash is refused and 500 is accepted, one minor unit apart.

    PRD §3.7: "The fourth is the cash-remainder rule: `credit_applied_minor` is
    `requested_credit_minor` persisted verbatim, `cash_due_minor` is
    `order_total_minor` minus `credit_applied_minor`, and whenever any brand
    currency at all is applied the residual `cash_due_minor` must be at least the
    policy's `min_cash_remainder_minor`; falling below it is
    `ERR_MIN_CASH_REMAINDER`."
    PRD §3.7: "Fourth, the redemption cap is `order_total_minor` multiplied by the
    `ACTIVE` brand-currency policy's `max_redemption_pct_bp`, divided by ten
    thousand and rounded down."
    PRD §3.7: "The second is the cap: `requested_credit_minor` must not exceed the
    redemption cap just computed, and the boundary is inclusive, so a request
    exactly equal to the cap is accepted while a request strictly above it is
    refused with `ERR_REDEMPTION_CAP_EXCEEDED`."
    PRD §3.7: "The third is availability: `requested_credit_minor` must not exceed
    the buyer's available credit, which is the sum of `remaining_minor` over their
    eligible unexpired grants; exceeding it is `ERR_INSUFFICIENT_CREDIT`."
    PRD §3.7: "A grant drawn down but not emptied moves from `ISSUED` to
    `PARTIALLY_REDEEMED`; a grant taken to a `remaining_minor` of exactly zero
    moves to `EXHAUSTED`, whether it started at `ISSUED` or at
    `PARTIALLY_REDEEMED`."
    PRD §3.1: "Whenever brand currency moves, the balance is **recomputed from
    scratch** as the sum of `remaining_minor` over that customer's grants whose
    `status` is `ISSUED` or `PARTIALLY_REDEEMED`."

    Design: Difficulty/boundary_precision_check/cash_remainder_exactly_at_policy_minimum_is_accepted
    """
    estate = _open_policy_estate()
    seller = _seller_listing(estate)
    unit = seller["unit"]
    funded = _rich_buyer(estate)
    buyer = funded["customer"]

    # The cap is floor(21255 * 10000 / 10000) = 21255 and the balance is 48300,
    # so neither the cap nor availability can answer either request.
    validate_error(
        _attempt_purchase(buyer, seller["channel"], unit, 20756),
        "ERR_MIN_CASH_REMAINDER",
        422,
    )

    order = place_order(buyer, seller["channel"], unit, 20755)
    assert_resale_order(order)
    assert order["gross_price_minor"] == GROSS
    assert order["channel_fee_minor"] == FEE
    assert order["order_total_minor"] == TOTAL
    assert order["credit_applied_minor"] == 20755
    # 21255 - 20755 lands exactly on min_cash_remainder_minor, and the bound is
    # inclusive from below.
    assert order["cash_due_minor"] == 500
    assert order["status"] == "PLACED"

    drawn = fetch_grant(funded["grant"]["id"])
    assert drawn["remaining_minor"] == 27545
    assert drawn["status"] == "PARTIALLY_REDEEMED"
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 27545
    assert fetch_unit(unit["id"])["lifecycle_state"] == "RESERVED"


def test_the_refused_remainder_writes_nothing_and_the_quoted_version_still_holds():
    """A rejected purchase is completely inert, retry included.

    PRD §3.7: "The fourth is the cash-remainder rule: `credit_applied_minor` is
    `requested_credit_minor` persisted verbatim, `cash_due_minor` is
    `order_total_minor` minus `credit_applied_minor`, and whenever any brand
    currency at all is applied the residual `cash_due_minor` must be at least the
    policy's `min_cash_remainder_minor`; falling below it is
    `ERR_MIN_CASH_REMAINDER`."
    PRD §2.9: "The rule the platform follows is that all links of a cascade
    complete inside the same request or none of them do: there is no partially
    applied acceptance, no partially settled return, and no state in which a ledger
    entry exists without its grant having been adjusted to match."
    PRD §2.8: "**Placing a resale order** requires `expected_customer_version` in
    the request body, carrying the `version` of the buying customer as the client
    last observed it."
    PRD §2.8: "If that value does not equal the customer's current `version`, the
    order is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412)."
    PRD §3.7: "As the last cross-entity effect, the purchased unit moves from
    `LISTED` to `RESERVED` and its version is incremented; its
    `current_price_minor` is now frozen inside the order's `gross_price_minor` and
    the unit is no longer eligible for any markdown step."

    Design: Difficulty/boundary_precision_check/cash_remainder_exactly_at_policy_minimum_is_accepted
    """
    estate = _open_policy_estate()
    seller = _seller_listing(estate)
    unit = seller["unit"]
    funded = _rich_buyer(estate)
    buyer = funded["customer"]
    grant_id = funded["grant"]["id"]
    version_before = fetch_customer(buyer["id"])["version"]

    validate_error(
        _attempt_purchase(
            buyer, seller["channel"], unit, 20756, version=version_before
        ),
        "ERR_MIN_CASH_REMAINDER",
        422,
    )

    rows, meta = _orders_of(buyer["id"])
    assert rows == []
    assert_pagination_meta(meta, 0)

    untouched_grant = fetch_grant(grant_id)
    assert untouched_grant["remaining_minor"] == 48300
    assert untouched_grant["status"] == "ISSUED"
    assert len(grant_ledger_entries(grant_id)) == 1

    unmoved = fetch_customer(buyer["id"])
    assert unmoved["credit_balance_minor"] == 48300
    # The refusal was not a mutation, so the caller's view is still current.
    assert unmoved["version"] == version_before

    still_listed = fetch_unit(unit["id"])
    assert still_listed["lifecycle_state"] == "LISTED"
    assert still_listed["version"] == unit["version"]

    order = place_order(
        buyer,
        seller["channel"],
        unit,
        20755,
        expected_customer_version=version_before,
    )
    assert order["credit_applied_minor"] == 20755
    assert order["cash_due_minor"] == 500
    assert fetch_grant(grant_id)["remaining_minor"] == 27545
    assert fetch_customer(buyer["id"])["version"] > version_before
    assert fetch_unit(unit["id"])["lifecycle_state"] == "RESERVED"


def test_the_stale_version_check_answers_before_the_redemption_cap_does():
    """One impossible request, two different refusals, decided by the version alone.

    PRD §2.8: "**Placing a resale order** requires `expected_customer_version` in
    the request body, carrying the `version` of the buying customer as the client
    last observed it."
    PRD §2.8: "If that value does not equal the customer's current `version`, the
    order is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412)."
    PRD §3.1: "A `ProgramAdmin` may later revise a customer's `status`, their
    `loyalty_tier`, or both, and each such edit is a mutation of the customer row."
    PRD §3.7: "The second is the cap: `requested_credit_minor` must not exceed the
    redemption cap just computed, and the boundary is inclusive, so a request
    exactly equal to the cap is accepted while a request strictly above it is
    refused with `ERR_REDEMPTION_CAP_EXCEEDED`."
    PRD §3.7: "Fourth, the redemption cap is `order_total_minor` multiplied by the
    `ACTIVE` brand-currency policy's `max_redemption_pct_bp`, divided by ten
    thousand and rounded down."

    Design: Corner/validations/stale_customer_version_outranks_the_redemption_cap
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    unit = seller["unit"]
    funded = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    buyer = funded["customer"]
    assert funded["grant"]["issued_amount_minor"] == 11500
    stale_version = fetch_customer(buyer["id"])["version"]

    # An unrelated administrative edit supersedes the version the client holds.
    revised = patch_customer(buyer["id"], {"loyalty_tier": "STANDARD"})
    assert revised["loyalty_tier"] == "STANDARD"
    assert revised["version"] > stale_version

    # 99999 breaks the cap of floor(21255 * 5000 / 10000) = 10627 and the balance
    # of 11500 both, yet the stale version is what the platform answers with.
    validate_error(
        _attempt_purchase(
            buyer, seller["channel"], unit, 99999, version=stale_version
        ),
        "ERR_STALE_CUSTOMER_VERSION",
        412,
    )

    # With the version current, the same amount reaches the cap check.
    validate_error(
        _attempt_purchase(buyer, seller["channel"], unit, 99999),
        "ERR_REDEMPTION_CAP_EXCEEDED",
        422,
    )

    assert fetch_unit(unit["id"])["lifecycle_state"] == "LISTED"
    assert fetch_grant(funded["grant"]["id"])["remaining_minor"] == 11500
    assert _orders_of(buyer["id"])[0] == []

    order = place_order(buyer, seller["channel"], unit, 10627)
    assert order["status"] == "PLACED"
    assert order["order_total_minor"] == TOTAL
    # Exactly on the cap, and 21255 - 10627 clears the 500 cash floor.
    assert order["credit_applied_minor"] == 10627
    assert order["cash_due_minor"] == 10628

    drawn = fetch_grant(funded["grant"]["id"])
    assert drawn["remaining_minor"] == 873
    assert drawn["status"] == "PARTIALLY_REDEEMED"
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 873


def test_suspension_answers_before_the_paused_channel_and_both_clear_together():
    """Two blocking conditions lifted one at a time, in the order the PRD pins.

    PRD §3.7: "Before any money is computed, the buyer's `status` must be `ACTIVE`
    or the order is refused with `ERR_CUSTOMER_SUSPENDED`; the channel must be
    `ACTIVE` or the order is refused with `ERR_CHANNEL_NOT_ACTIVE`; the unit must be
    in `lifecycle_state` `LISTED` **and** its `listed_channel_id` must equal the
    order's `channel_id`, either failure surfacing as `ERR_UNIT_NOT_LISTED`; and an
    `ACTIVE` brand-currency policy must be live, otherwise
    `ERR_CREDIT_POLICY_MISSING`, since it is that policy that supplies the
    redemption terms."
    PRD §3.1: "A customer whose `status` is `SUSPENDED` may neither surrender an
    item nor buy one: both trade-in submission and resale-order placement reject a
    suspended participant with `ERR_CUSTOMER_SUSPENDED`."
    PRD §3.1: "A channel's `status` begins `ACTIVE` and may be paused; a `PAUSED`
    channel accepts neither new listings nor new resale orders, and both refusals
    carry `ERR_CHANNEL_NOT_ACTIVE`."
    PRD §3.7: "An order that applies no credit is exempt from that last rule."
    PRD §3.7: "The order itself is created in `status` `PLACED` with `reason_type`
    `NONE`, `fulfilled_at`, `warranty_expires_at` and `return_requested_at` all
    null, and `restock_fee_minor`, `refund_cash_minor` and `refund_credit_minor`
    all 0."

    Design: Corner/validations/suspension_outranks_paused_channel_and_both_clear_on_reactivation
    """
    estate = setup_estate()
    channel = estate["channel"]
    unit = _seller_listing(estate)["unit"]
    buyer = create_customer(email="ben@example.com", full_name="Ben Ortiz")
    assert buyer["status"] == "ACTIVE"
    assert buyer["credit_balance_minor"] == 0

    suspended = patch_customer(buyer["id"], {"status": "SUSPENDED"})
    assert suspended["status"] == "SUSPENDED"
    assert pause_channel(channel["id"])["status"] == "PAUSED"

    # Both gates are shut; the buyer's own status is the one that answers.
    validate_error(
        _attempt_purchase(buyer, channel, unit, 0),
        "ERR_CUSTOMER_SUSPENDED",
        409,
    )

    reinstated = patch_customer(buyer["id"], {"status": "ACTIVE"})
    assert reinstated["status"] == "ACTIVE"

    # With the buyer clear, the next gate in the declared order speaks.
    validate_error(
        _attempt_purchase(buyer, channel, unit, 0),
        "ERR_CHANNEL_NOT_ACTIVE",
        409,
    )

    assert _orders_of(buyer["id"])[0] == []
    assert fetch_unit(unit["id"])["lifecycle_state"] == "LISTED"

    revived = validate_success(
        api_client.patch_channel(channel["id"], {"status": "ACTIVE"}, ADMIN)
    )
    assert revived["status"] == "ACTIVE"

    order = place_order(buyer, channel, unit, 0)
    assert_resale_order(order)
    assert order["status"] == "PLACED"
    assert order["reason_type"] == "NONE"
    assert order["gross_price_minor"] == GROSS
    assert order["channel_fee_minor"] == FEE
    assert order["order_total_minor"] == TOTAL
    assert order["credit_applied_minor"] == 0
    # No credit was applied, so the cash-remainder rule never engages.
    assert order["cash_due_minor"] == TOTAL
    assert order["restock_fee_minor"] == 0
    assert order["refund_cash_minor"] == 0
    assert order["refund_credit_minor"] == 0
    assert_null(order["fulfilled_at"], "fulfilled_at")
    assert_null(order["warranty_expires_at"], "warranty_expires_at")
    assert_null(order["return_requested_at"], "return_requested_at")
    assert fetch_unit(unit["id"])["lifecycle_state"] == "RESERVED"


def test_a_forbidden_policy_only_bites_when_the_buyer_actually_draws_credit():
    """The same holder on the same channel: 5000 is refused and 0 goes through.

    PRD §3.7: "The first is channel eligibility: every grant the buyer would draw
    upon must be redeemable in this channel, meaning its pinned brand-currency
    policy's `eligible_assortment` must admit the channel's `channel_type`; a buyer
    holding credit that its policy forbids here is refused with
    `ERR_CREDIT_NOT_REDEEMABLE_HERE`."
    PRD §3.1: "That restriction is read against the purchase channel's commercial
    identity: `RESALE_ONLY` permits redemption only where the channel's
    `channel_type` is `RESALE_MARKETPLACE` or `OUTLET`, `NEW_ONLY` permits it only
    where the `channel_type` is `FULL_PRICE_DTC`, and `BOTH` permits it anywhere."
    PRD §3.7: "A grant qualifies only if its `customer_id` is the buyer's, its
    `status` is `ISSUED` or `PARTIALLY_REDEEMED`, its `expires_at` lies strictly
    after the logical clock, and its pinned brand-currency policy's
    `eligible_assortment` admits this channel's `channel_type`."
    PRD §3.7: "An order that applies no credit is exempt from that last rule."
    PRD §3.7: "Third, `order_total_minor` is `gross_price_minor` plus
    `channel_fee_minor`."

    Design: Corner/validations/redeemability_rule_applies_only_when_credit_is_actually_drawn
    """
    estate = setup_estate(
        credit_policy=dict(CREDIT_POLICY_CORE, eligible_assortment="NEW_ONLY")
    )
    assert estate["credit_policy"]["eligible_assortment"] == "NEW_ONLY"
    # The selling channel is a resale marketplace, which NEW_ONLY does not admit.
    assert estate["channel"]["channel_type"] == "RESALE_MARKETPLACE"

    seller = _seller_listing(estate)
    unit = seller["unit"]
    funded = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    buyer = funded["customer"]
    grant_id = funded["grant"]["id"]
    assert funded["grant"]["issued_amount_minor"] == 11500

    # 5000 sits under the 10627 cap and well under the 11500 balance, so only the
    # pinned policy's assortment can be the reason for the refusal.
    validate_error(
        _attempt_purchase(buyer, seller["channel"], unit, 5000),
        "ERR_CREDIT_NOT_REDEEMABLE_HERE",
        409,
    )

    order = place_order(buyer, seller["channel"], unit, 0)
    assert order["status"] == "PLACED"
    assert order["order_total_minor"] == TOTAL
    assert order["credit_applied_minor"] == 0
    assert order["cash_due_minor"] == TOTAL

    # A purchase that drew nothing walked no waterfall at all.
    untouched = fetch_grant(grant_id)
    assert untouched["remaining_minor"] == 11500
    assert untouched["status"] == "ISSUED"
    assert untouched["version"] == funded["grant"]["version"]
    assert len(grant_ledger_entries(grant_id)) == 1
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 11500


def test_the_purchase_and_fulfilment_sequence_refuses_every_step_out_of_turn():
    """One unit walked from READY to FULFILLED, refused at each premature step.

    PRD §3.7: "the unit must be in `lifecycle_state` `LISTED` **and** its
    `listed_channel_id` must equal the order's `channel_id`, either failure
    surfacing as `ERR_UNIT_NOT_LISTED`"
    PRD §3.7: "The third is availability: `requested_credit_minor` must not exceed
    the buyer's available credit, which is the sum of `remaining_minor` over their
    eligible unexpired grants; exceeding it is `ERR_INSUFFICIENT_CREDIT`."
    PRD §3.8: "An order in any status other than `FULFILLED` is refused with
    `ERR_ORDER_NOT_RETURN_REQUESTABLE`."
    PRD §3.7: "Fulfilment is performed by a `MerchandisingManager` or a
    `ProgramAdmin` and advances the order from `PLACED` to `FULFILLED`; any other
    starting status is `ERR_ORDER_NOT_FULFILLABLE`, and the unit must be sitting in
    `RESERVED`."
    PRD §3.7: "Fulfilment stamps `fulfilled_at` from the logical clock and computes
    `warranty_expires_at` as `fulfilled_at` plus the `warranty_days` of the `ACTIVE`
    condition-tier policy for the unit's (`product_category`, `condition_grade`)
    pair — so the warranty a buyer gets is a property of the tier they bought, not
    of the order."

    Design: Corner/errors/purchase_and_fulfilment_sequence_errors_are_triggerable
    """
    estate = setup_estate()
    channel = estate["channel"]
    unit = setup_refurbished_unit(estate, loyalty_tier="PLUS")["unit"]
    assert_unit_dimensions(unit, "READY", "CAPITALIZED")

    # Ben has never traded anything in, so he holds no grants at all.
    buyer = create_customer(email="ben@example.com", full_name="Ben Ortiz")
    assert buyer["credit_balance_minor"] == 0

    validate_error(
        _attempt_purchase(buyer, channel, unit, 0), "ERR_UNIT_NOT_LISTED", 409
    )

    listed = list_unit(unit["id"], channel["id"])
    assert listed["list_price_minor"] == GROSS

    # 100 is far below the cap of floor(21255 * 5000 / 10000) = 10627, so only the
    # empty eligible grant set can be the reason.
    validate_error(
        _attempt_purchase(buyer, channel, listed, 100), "ERR_INSUFFICIENT_CREDIT", 422
    )

    order = place_order(buyer, channel, listed, 0)
    assert order["status"] == "PLACED"
    assert order["gross_price_minor"] == GROSS
    assert order["channel_fee_minor"] == FEE
    assert order["order_total_minor"] == TOTAL
    assert order["cash_due_minor"] == TOTAL

    # A return needs a FULFILLED order, so the window rules never even run.
    validate_error(
        api_client.request_resale_order_return(
            order["id"],
            return_request_payload("BUYER_REMORSE"),
            make_customer_headers(buyer["id"]),
        ),
        "ERR_ORDER_NOT_RETURN_REQUESTABLE",
        409,
    )

    fulfilled = validate_success(
        api_client.fulfill_resale_order(order["id"], MERCH)
    )
    assert fulfilled["status"] == "FULFILLED"
    assert_instant(fulfilled["fulfilled_at"], "2026-08-01T00:00:00Z", "fulfilled_at")
    # 30 warranty days from the OUTERWEAR grade B tier policy.
    assert_instant(
        fulfilled["warranty_expires_at"],
        "2026-08-31T00:00:00Z",
        "warranty_expires_at",
    )
    assert fetch_unit(unit["id"])["lifecycle_state"] == "SOLD"

    validate_error(
        api_client.fulfill_resale_order(order["id"], MERCH),
        "ERR_ORDER_NOT_FULFILLABLE",
        409,
    )
    assert fetch_order(order["id"])["status"] == "FULFILLED"


def test_a_superseded_balance_view_cannot_settle_and_the_refreshed_one_can():
    """The identical redemption body fails 412 and then succeeds unchanged.

    PRD §2.8: "**Placing a resale order** requires `expected_customer_version` in
    the request body, carrying the `version` of the buying customer as the client
    last observed it."
    PRD §2.8: "If that value does not equal the customer's current `version`, the
    order is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412)."
    PRD §2.8: "In each case the version field is a **required** input, not an
    optional hint — omitting it is a malformed request, not a waiver of the check."
    PRD §3.7: "Either way its `remaining_minor` is reduced by the allocated amount
    and its version is incremented."
    PRD §3.7: "With every grant settled, the buyer's `credit_balance_minor` is
    recomputed and their version incremented."
    PRD §3.7: "The fourth is the cash-remainder rule: `credit_applied_minor` is
    `requested_credit_minor` persisted verbatim, `cash_due_minor` is
    `order_total_minor` minus `credit_applied_minor`, and whenever any brand
    currency at all is applied the residual `cash_due_minor` must be at least the
    policy's `min_cash_remainder_minor`; falling below it is
    `ERR_MIN_CASH_REMAINDER`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_customer_version_blocks_a_redemption_computed_from_a_superseded_balance
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    unit = seller["unit"]
    # A mail-in trade-in at STANDARD: 10000 base plus the 1000 mail-in bonus.
    funded = setup_credit_source_grant(estate)
    buyer = funded["customer"]
    grant_id = funded["grant"]["id"]
    assert funded["grant"]["issued_amount_minor"] == 11000

    read = fetch_customer(buyer["id"])
    assert read["credit_balance_minor"] == 11000
    version_read = read["version"]

    promoted = patch_customer(buyer["id"], {"loyalty_tier": "PLUS"})
    assert promoted["loyalty_tier"] == "PLUS"
    assert promoted["version"] == version_read + 1
    # The promotion does not retroactively enlarge a grant already issued.
    assert promoted["credit_balance_minor"] == 11000

    validate_error(
        _attempt_purchase(buyer, seller["channel"], unit, 5000, version=version_read),
        "ERR_STALE_CUSTOMER_VERSION",
        412,
    )

    assert fetch_unit(unit["id"])["lifecycle_state"] == "LISTED"
    refused_grant = fetch_grant(grant_id)
    assert refused_grant["remaining_minor"] == 11000
    assert refused_grant["status"] == "ISSUED"

    order = place_order(
        buyer,
        seller["channel"],
        unit,
        5000,
        expected_customer_version=promoted["version"],
    )
    assert order["order_total_minor"] == TOTAL
    assert order["credit_applied_minor"] == 5000
    assert order["cash_due_minor"] == 16255

    settled = fetch_customer(buyer["id"])
    assert settled["credit_balance_minor"] == 6000
    # The accepted order is the only write since the promotion.
    assert settled["version"] == promoted["version"] + 1


def test_the_placement_response_and_the_reads_right_after_it_already_agree():
    """Nothing about the redemption is deferred to a later pass.

    PRD §3.7: "Every touched grant receives exactly one ledger entry with
    `entry_type` `REDEEM`, a negative `amount_minor` equal to the amount drawn from
    it, a `balance_after_minor` equal to that grant's `remaining_minor` after the
    draw, `occurred_at` from the logical clock, and `resale_order_id` set to the
    order that caused it."
    PRD §3.7: "A grant drawn down but not emptied moves from `ISSUED` to
    `PARTIALLY_REDEEMED`; a grant taken to a `remaining_minor` of exactly zero
    moves to `EXHAUSTED`, whether it started at `ISSUED` or at
    `PARTIALLY_REDEEMED`."
    PRD §3.7: "With every grant settled, the buyer's `credit_balance_minor` is
    recomputed and their version incremented."
    PRD §3.7: "As the last cross-entity effect, the purchased unit moves from
    `LISTED` to `RESERVED` and its version is incremented; its
    `current_price_minor` is now frozen inside the order's `gross_price_minor` and
    the unit is no longer eligible for any markdown step."
    PRD §3.7: "The ledger entries an order produced are separately listable by the
    same three roles with an optional `entry_type` filter, `limit` and `offset` — a
    `Customer` seeing only their own, per §2.10."

    Design: Corner/consistency_model/redemption_is_visible_in_the_same_request_and_in_immediate_reads
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    unit = seller["unit"]
    funded = setup_credit_source_grant(estate)
    buyer = funded["customer"]
    grant_id = funded["grant"]["id"]
    assert funded["grant"]["issued_amount_minor"] == 11000
    version_before = fetch_customer(buyer["id"])["version"]

    # The placement response alone must already carry the settled money.
    order = place_order(buyer, seller["channel"], unit, 5000)
    assert_resale_order(order)
    assert order["status"] == "PLACED"
    assert order["gross_price_minor"] == GROSS
    assert order["channel_fee_minor"] == FEE
    assert order["order_total_minor"] == TOTAL
    assert order["credit_applied_minor"] == 5000
    assert order["cash_due_minor"] == 16255

    # The very next read of the grant shows the draw already applied.
    grant = fetch_grant(grant_id)
    assert grant["issued_amount_minor"] == 11000
    assert grant["remaining_minor"] == 6000
    assert grant["status"] == "PARTIALLY_REDEEMED"

    customer = fetch_customer(buyer["id"])
    assert customer["credit_balance_minor"] == 6000
    assert customer["version"] == version_before + 1

    rows, meta = validate_paginated(
        api_client.list_credit_grant_ledger_entries(
            grant_id, ADMIN, {"entry_type": "REDEEM"}
        )
    )
    assert_pagination_meta(meta, 1)
    entry = rows[0]
    assert_credit_ledger_entry(entry)
    assert entry["entry_type"] == "REDEEM"
    assert entry["amount_minor"] == -5000
    assert entry["balance_after_minor"] == 6000
    assert entry["credit_grant_id"] == grant_id
    assert entry["resale_order_id"] == order["id"]
    assert_instant(entry["occurred_at"], "2026-08-01T00:00:00Z", "occurred_at")

    reserved = fetch_unit(unit["id"])
    assert reserved["lifecycle_state"] == "RESERVED"
    assert reserved["current_price_minor"] == GROSS
    assert reserved["version"] > unit["version"]

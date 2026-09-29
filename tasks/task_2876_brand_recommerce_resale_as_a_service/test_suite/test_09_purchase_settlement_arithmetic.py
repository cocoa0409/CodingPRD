"""Purchase settlement: the pinned evaluation order, the fee bands and the
redemption cap.

The recurring shape here is one OUTERWEAR grade B unit listed at
floor(50000 * 3900 / 10000) = 19500, bought with brand currency that a second
participant earned on a mail-in trade-in. Because a unit can only be refurbished
while its trade-in has a custody store — the bay must belong to the store that
took custody, per PRD §3.5 — the seller's item always comes in through
`IN_STORE`, and the mail-in bonus therefore only ever appears on the buyer's own
grant.
"""

from test_helpers import (
    ADMIN,
    BAY_CLEANING,
    CHANNEL_RESALE_MP,
    GRADE_POLICY_FOOTWEAR_A,
    GRADE_POLICY_FOOTWEAR_SALVAGE,
    GRADE_POLICY_OUTERWEAR_B,
    TEST_DEFAULTS,
    WINDOW_09_11,
    api_client,
    assert_credit_ledger_entry,
    assert_grant_conservation,
    assert_instant,
    assert_ledger_balances_run,
    assert_money_fields_are_integers,
    assert_null,
    assert_pagination_meta,
    assert_resale_order,
    assert_unit_dimensions,
    create_customer,
    create_resale_order_payload,
    fetch_customer,
    fetch_grant,
    fetch_unit,
    grant_ledger_entries,
    make_customer_headers,
    place_order,
    set_clock,
    setup_accepted_trade_in,
    setup_credit_source_grant,
    setup_estate,
    setup_listed_unit,
    validate_error,
    validate_paginated,
)

# The settlement figures every test in this file leans on, for a gross of 19500.
GROSS = 19500
FEE_AT_900_BP = 1755
TOTAL = 21255
# What keying the band on the order total instead of the gross would have paid.
FEE_IF_BAND_READ_THE_TOTAL = 1268
TOTAL_IF_BAND_READ_THE_TOTAL = 20768
REDEMPTION_CAP = 10627


def _seller_listing(estate, **overrides):
    """Ava's own OWNED_INVENTORY unit, refurbished for nothing and listed at 19500."""
    scenario = setup_listed_unit(estate, loyalty_tier="PLUS", **overrides)
    unit = scenario["unit"]
    # Baseline 19500 clears the ceil(10500 * 11500 / 10000) = 12075 margin floor
    # and sits under the floor(50000 * 7000 / 10000) = 35000 channel ceiling.
    assert scenario["grant"]["issued_amount_minor"] == 10500
    assert unit["list_price_minor"] == GROSS
    assert unit["current_price_minor"] == GROSS
    assert_unit_dimensions(unit, "LISTED", "CAPITALIZED")
    return scenario


def _funded_buyer(estate):
    """Ben, holding a single 11500 grant from a mail-in trade-in of his own."""
    scenario = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    # 10000 base + 1000 mail-in bonus + 500 PLUS loyalty, none of them compounded.
    assert scenario["grant"]["issued_amount_minor"] == 11500
    assert scenario["grant"]["remaining_minor"] == 11500
    assert scenario["grant"]["status"] == "ISSUED"
    assert scenario["customer"]["credit_balance_minor"] == 11500
    return scenario


def _attempt_purchase(buyer, channel, unit, requested_credit_minor):
    """A purchase whose refusal is the thing being observed."""
    payload = create_resale_order_payload(
        buyer["id"],
        channel["id"],
        unit["id"],
        requested_credit_minor,
        fetch_customer(buyer["id"])["version"],
    )
    return api_client.create_resale_order(payload, make_customer_headers(buyer["id"]))


def _orders_of(customer_id):
    return validate_paginated(
        api_client.list_resale_orders(ADMIN, {"customer_id": customer_id})
    )


def test_the_fee_band_is_selected_from_the_gross_price_not_the_order_total():
    """One order, and every figure on it separates the two evaluation orders.

    PRD §3.7: "First, `gross_price_minor` is snapshotted from the unit's
    `current_price_minor` — whatever the markdown cadence had brought it down to
    at that moment."
    PRD §3.7: "Second, the channel fee is derived from that gross price through a
    three-band schedule, and the band is selected from **`gross_price_minor`
    alone, never from the order total**."
    PRD §3.7: "`channel_fee_minor` is the gross price multiplied by the selected
    rate in basis points, divided by ten thousand, rounded **half up**."
    PRD §3.7: "Third, `order_total_minor` is `gross_price_minor` plus
    `channel_fee_minor`."
    PRD §3.7: "Fourth, the redemption cap is `order_total_minor` multiplied by the
    `ACTIVE` brand-currency policy's `max_redemption_pct_bp`, divided by ten
    thousand and rounded down."
    PRD §3.7: "Selecting the fee band from `order_total_minor` rather than from
    the gross price yields a different fee, a different total and a different cap,
    and is wrong."
    PRD §3.7: "The fourth is the cash-remainder rule: `credit_applied_minor` is
    `requested_credit_minor` persisted verbatim, `cash_due_minor` is
    `order_total_minor` minus `credit_applied_minor`, and whenever any brand
    currency at all is applied the residual `cash_due_minor` must be at least the
    policy's `min_cash_remainder_minor`; falling below it is
    `ERR_MIN_CASH_REMAINDER`."
    PRD §3.7: "The order itself is created in `status` `PLACED` with `reason_type`
    `NONE`, `fulfilled_at`, `warranty_expires_at` and `return_requested_at` all
    null, and `restock_fee_minor`, `refund_cash_minor` and `refund_credit_minor`
    all 0."
    PRD §3.7: "As the last cross-entity effect, the purchased unit moves from
    `LISTED` to `RESERVED` and its version is incremented; its
    `current_price_minor` is now frozen inside the order's `gross_price_minor` and
    the unit is no longer eligible for any markdown step."

    Design: Difficulty/combinatorial_formula/resale_settlement_fee_tier_keyed_on_gross_not_order_total
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    unit = seller["unit"]
    buyer = _funded_buyer(estate)

    order = place_order(
        buyer["customer"], seller["channel"], unit, REDEMPTION_CAP
    )
    assert_resale_order(order)
    assert_money_fields_are_integers(order)

    assert order["gross_price_minor"] == GROSS
    # 19500 is at most twenty thousand, so the 900 bp row applies: 1755 exactly.
    assert order["channel_fee_minor"] == FEE_AT_900_BP
    # 650 bp of the gross is what a band keyed on the total 21255 would charge.
    assert order["channel_fee_minor"] != FEE_IF_BAND_READ_THE_TOTAL
    assert order["order_total_minor"] == TOTAL
    assert order["order_total_minor"] != TOTAL_IF_BAND_READ_THE_TOTAL
    # floor(21255 * 5000 / 10000) = 10627, and the request sits exactly on it.
    assert order["credit_applied_minor"] == REDEMPTION_CAP
    assert order["cash_due_minor"] == 10628
    # 10628 clears the 500 minimum cash remainder with room to spare.
    assert order["cash_due_minor"] >= 500

    assert order["status"] == "PLACED"
    assert order["reason_type"] == "NONE"
    assert_null(order["fulfilled_at"], "fulfilled_at")
    assert_null(order["warranty_expires_at"], "warranty_expires_at")
    assert_null(order["return_requested_at"], "return_requested_at")
    assert order["restock_fee_minor"] == 0
    assert order["refund_cash_minor"] == 0
    assert order["refund_credit_minor"] == 0
    assert order["customer_id"] == buyer["customer"]["id"]
    assert order["channel_id"] == seller["channel"]["id"]
    assert order["resale_unit_id"] == unit["id"]

    drawn = fetch_grant(buyer["grant"]["id"])
    assert drawn["remaining_minor"] == 873
    assert drawn["status"] == "PARTIALLY_REDEEMED"
    assert fetch_customer(buyer["customer"]["id"])["credit_balance_minor"] == 873

    sold = fetch_unit(unit["id"])
    assert sold["lifecycle_state"] == "RESERVED"
    assert sold["current_price_minor"] == GROSS
    assert sold["version"] > unit["version"]
    # Selling moves only the commercial dimension.
    assert sold["accounting_state"] == "CAPITALIZED"


def test_a_dearer_unit_can_carry_the_smaller_fee_because_the_band_reads_gross():
    """Two listings on one channel, and the fee ordering inverts the price ordering.

    PRD §3.7: "Second, the channel fee is derived from that gross price through a
    three-band schedule, and the band is selected from **`gross_price_minor`
    alone, never from the order total**."
    PRD §3.7: "The bands are upper-inclusive and are tried in declared order: a
    gross price of at most twenty thousand minor units is charged nine hundred
    basis points; a gross price of at most sixty thousand minor units is charged
    six hundred and fifty basis points; anything above sixty thousand is charged
    four hundred and fifty basis points."
    PRD §3.7: "`channel_fee_minor` is the gross price multiplied by the selected
    rate in basis points, divided by ten thousand, rounded **half up**."
    PRD §3.7: "Third, `order_total_minor` is `gross_price_minor` plus
    `channel_fee_minor`."
    PRD §3.7: "Selecting the fee band from `order_total_minor` rather than from
    the gross price yields a different fee, a different total and a different cap,
    and is wrong."
    PRD §3.7: "An order that applies no credit is exempt from that last rule."
    PRD §3.6: "The **baseline resale value** is the unit's `reference_msrp_minor`
    multiplied by the tier's `resale_price_pct_bp`, divided by ten thousand and
    rounded down."

    Design: Difficulty/combinatorial_formula/resale_settlement_fee_tier_keyed_on_gross_not_order_total
    """
    estate = setup_estate(
        bays=(BAY_CLEANING, dict(BAY_CLEANING, code="BAY-C2")),
    )
    cheaper = _seller_listing(estate)
    channel = cheaper["channel"]

    # A second item from the same participant, dearer by exactly enough to cross
    # the twenty-thousand band edge: floor(53000 * 3900 / 10000) = 20670, which
    # clears its own ceil(11130 * 11500 / 10000) = 12800 margin floor.
    dearer = setup_listed_unit(
        estate,
        bay=estate["bays"][1],
        customer=cheaper["customer"],
        msrp_minor=53000,
    )
    assert dearer["grant"]["issued_amount_minor"] == 11130
    assert dearer["unit"]["list_price_minor"] == 20670
    assert dearer["unit"]["current_price_minor"] == 20670

    buyer = create_customer(email="ben@example.com", full_name="Ben Ortiz")
    assert buyer["credit_balance_minor"] == 0

    on_the_cheaper = place_order(buyer, channel, cheaper["unit"], 0)
    assert on_the_cheaper["gross_price_minor"] == GROSS
    assert on_the_cheaper["channel_fee_minor"] == FEE_AT_900_BP
    assert on_the_cheaper["order_total_minor"] == TOTAL
    assert on_the_cheaper["credit_applied_minor"] == 0
    assert on_the_cheaper["cash_due_minor"] == TOTAL

    on_the_dearer = place_order(buyer, channel, dearer["unit"], 0)
    assert on_the_dearer["gross_price_minor"] == 20670
    # 20670 is above twenty thousand, so 650 bp: round_half_up(1343.55) = 1344.
    assert on_the_dearer["channel_fee_minor"] == 1344
    assert on_the_dearer["order_total_minor"] == 22014
    assert on_the_dearer["credit_applied_minor"] == 0
    assert on_the_dearer["cash_due_minor"] == 22014

    # The dearer item pays the smaller fee. Reading the band off the order total
    # would have put both orders in the 650 bp band and charged the cheaper item
    # 1268 — less than the dearer one, not more.
    assert on_the_dearer["gross_price_minor"] > on_the_cheaper["gross_price_minor"]
    assert on_the_dearer["channel_fee_minor"] < on_the_cheaper["channel_fee_minor"]
    assert on_the_cheaper["channel_fee_minor"] != FEE_IF_BAND_READ_THE_TOTAL

    for unit_id in (cheaper["unit"]["id"], dearer["unit"]["id"]):
        assert fetch_unit(unit_id)["lifecycle_state"] == "RESERVED"


def _full_msrp_estate():
    """FOOTWEAR grade A priced at its whole MSRP on a channel that clamps nothing.

    With `resale_price_pct_bp` and `max_resale_price_ratio_bp` both at ten
    thousand, a `CONSIGNED` unit lists at exactly its `reference_msrp_minor`,
    which is what lets a test choose a gross price to the minor unit.
    """
    return setup_estate(
        grade_policies=(dict(GRADE_POLICY_FOOTWEAR_A, resale_price_pct_bp=10000),),
        bays=(BAY_CLEANING, dict(BAY_CLEANING, code="BAY-C2")),
        channels=(dict(CHANNEL_RESALE_MP, max_resale_price_ratio_bp=10000),),
    )


def _consigned_listing(estate, msrp_minor, bay, customer=None):
    """A consigned FOOTWEAR grade A unit listed at exactly ``msrp_minor``."""
    scenario = setup_listed_unit(
        estate,
        bay=bay,
        window=WINDOW_09_11,
        customer=customer,
        loyalty_tier="PLUS",
        product_category="FOOTWEAR",
        declared_grade="A",
        assessed_grade="A",
        msrp_minor=msrp_minor,
        item_mass_grams=TEST_DEFAULTS["FOOTWEAR_MASS_GRAMS"],
        ownership_treatment="CONSIGNED",
    )
    unit = scenario["unit"]
    assert unit["capitalized_cost_minor"] == 0
    assert unit["list_price_minor"] == msrp_minor
    assert unit["current_price_minor"] == msrp_minor
    assert_unit_dimensions(unit, "LISTED", "UNCAPITALIZED")
    return scenario


def test_the_first_fee_band_is_upper_inclusive_at_twenty_thousand():
    """Twenty thousand exactly pays 900 bp; one minor unit more pays 650 bp.

    PRD §3.7: "The bands are upper-inclusive and are tried in declared order: a
    gross price of at most twenty thousand minor units is charged nine hundred
    basis points; a gross price of at most sixty thousand minor units is charged
    six hundred and fifty basis points; anything above sixty thousand is charged
    four hundred and fifty basis points."
    PRD §3.7: "A gross price of exactly twenty thousand therefore selects the
    nine-hundred-basis-point band, not the next one."
    PRD §3.7: "`channel_fee_minor` is the gross price multiplied by the selected
    rate in basis points, divided by ten thousand, rounded **half up**."
    PRD §3.7: "Third, `order_total_minor` is `gross_price_minor` plus
    `channel_fee_minor`."
    PRD §3.6: "A `CONSIGNED` unit has a `capitalized_cost_minor` of 0, which makes
    its margin floor 0 and leaves the channel ceiling as the only binding
    constraint."
    PRD §3.6: "Otherwise `list_price_minor` is the greater of the baseline resale
    value and the margin floor, then clamped down to the channel ceiling — that is,
    the lesser of the channel ceiling and that greater-of pair."

    Design: Corner/calculations/channel_fee_first_tier_band_is_upper_inclusive_at_20000
    """
    estate = _full_msrp_estate()
    channel = estate["channel"]
    at_the_edge = _consigned_listing(estate, 20000, estate["bays"][0])
    just_over = _consigned_listing(
        estate, 20001, estate["bays"][1], customer=at_the_edge["customer"]
    )

    buyer = create_customer(email="ben@example.com", full_name="Ben Ortiz")
    assert buyer["credit_balance_minor"] == 0

    on_the_edge = place_order(buyer, channel, at_the_edge["unit"], 0)
    assert on_the_edge["gross_price_minor"] == 20000
    # 20000 is "at most twenty thousand", so 900 bp: round_half_up(1800.0).
    assert on_the_edge["channel_fee_minor"] == 1800
    assert on_the_edge["order_total_minor"] == 21800
    assert on_the_edge["credit_applied_minor"] == 0
    assert on_the_edge["cash_due_minor"] == 21800

    over_the_edge = place_order(buyer, channel, just_over["unit"], 0)
    assert over_the_edge["gross_price_minor"] == 20001
    # The next band down: round_half_up(20001 * 650 / 10000) = round_half_up(1300.065).
    assert over_the_edge["channel_fee_minor"] == 1300
    assert over_the_edge["order_total_minor"] == 21301
    assert over_the_edge["cash_due_minor"] == 21301

    # One minor unit dearer, and 499 minor units cheaper to buy — only an
    # upper-inclusive band edge produces that.
    assert over_the_edge["gross_price_minor"] > on_the_edge["gross_price_minor"]
    assert over_the_edge["order_total_minor"] < on_the_edge["order_total_minor"]


def test_the_second_fee_band_is_upper_inclusive_at_sixty_thousand():
    """Sixty thousand exactly stays on 650 bp; the open-ended row starts at 60001.

    PRD §3.7: "The bands are upper-inclusive and are tried in declared order: a
    gross price of at most twenty thousand minor units is charged nine hundred
    basis points; a gross price of at most sixty thousand minor units is charged
    six hundred and fifty basis points; anything above sixty thousand is charged
    four hundred and fifty basis points."
    PRD §3.7: "`channel_fee_minor` is the gross price multiplied by the selected
    rate in basis points, divided by ten thousand, rounded **half up**."
    PRD §3.7: "Third, `order_total_minor` is `gross_price_minor` plus
    `channel_fee_minor`."
    PRD §3.6: "The **baseline resale value** is the unit's `reference_msrp_minor`
    multiplied by the tier's `resale_price_pct_bp`, divided by ten thousand and
    rounded down."
    PRD §3.6: "A `CONSIGNED` unit has a `capitalized_cost_minor` of 0, which makes
    its margin floor 0 and leaves the channel ceiling as the only binding
    constraint."

    Design: Corner/calculations/channel_fee_second_tier_band_is_upper_inclusive_at_60000
    """
    estate = _full_msrp_estate()
    channel = estate["channel"]
    at_the_edge = _consigned_listing(estate, 60000, estate["bays"][0])
    just_over = _consigned_listing(
        estate, 60001, estate["bays"][1], customer=at_the_edge["customer"]
    )

    buyer = create_customer(email="ben@example.com", full_name="Ben Ortiz")

    on_the_edge = place_order(buyer, channel, at_the_edge["unit"], 0)
    assert on_the_edge["gross_price_minor"] == 60000
    # 60000 is "at most sixty thousand": round_half_up(3900.0).
    assert on_the_edge["channel_fee_minor"] == 3900
    assert on_the_edge["order_total_minor"] == 63900
    assert on_the_edge["cash_due_minor"] == 63900

    over_the_edge = place_order(buyer, channel, just_over["unit"], 0)
    assert over_the_edge["gross_price_minor"] == 60001
    # "anything above sixty thousand": round_half_up(60001 * 450 / 10000).
    assert over_the_edge["channel_fee_minor"] == 2700
    assert over_the_edge["order_total_minor"] == 62701
    assert over_the_edge["cash_due_minor"] == 62701

    assert over_the_edge["gross_price_minor"] > on_the_edge["gross_price_minor"]
    assert over_the_edge["order_total_minor"] < on_the_edge["order_total_minor"]


def test_the_redemption_cap_floors_the_half_unit_and_bounds_the_request():
    """10628 is refused and 10627 is accepted, one minor unit apart.

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
    PRD §3.7: "Every touched grant receives exactly one ledger entry with
    `entry_type` `REDEEM`, a negative `amount_minor` equal to the amount drawn from
    it, a `balance_after_minor` equal to that grant's `remaining_minor` after the
    draw, `occurred_at` from the logical clock, and `resale_order_id` set to the
    order that caused it."
    PRD §3.7: "A grant drawn down but not emptied moves from `ISSUED` to
    `PARTIALLY_REDEEMED`; a grant taken to a `remaining_minor` of exactly zero
    moves to `EXHAUSTED`, whether it started at `ISSUED` or at
    `PARTIALLY_REDEEMED`."

    Design: Corner/calculations/redemption_cap_floors_the_half_unit_and_bounds_the_request
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    unit = seller["unit"]
    funded = _funded_buyer(estate)
    buyer = funded["customer"]
    grant_id = funded["grant"]["id"]

    # The buyer holds 11500, comfortably more than either request, so availability
    # cannot be what answers — only the cap can.
    validate_error(
        _attempt_purchase(buyer, seller["channel"], unit, 10628),
        "ERR_REDEMPTION_CAP_EXCEEDED",
        422,
    )

    # floor(21255 * 5000 / 10000) is 10627.5 truncated, not rounded up.
    still_listed = fetch_unit(unit["id"])
    assert still_listed["lifecycle_state"] == "LISTED"
    assert still_listed["version"] == unit["version"]
    rows, meta = _orders_of(buyer["id"])
    assert rows == []
    assert_pagination_meta(meta, 0)
    untouched = fetch_grant(grant_id)
    assert untouched["remaining_minor"] == 11500
    assert untouched["status"] == "ISSUED"
    assert len(grant_ledger_entries(grant_id)) == 1
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 11500

    order = place_order(buyer, seller["channel"], unit, REDEMPTION_CAP)
    assert order["order_total_minor"] == TOTAL
    assert order["credit_applied_minor"] == REDEMPTION_CAP
    assert order["cash_due_minor"] == 10628

    drawn = fetch_grant(grant_id)
    assert drawn["remaining_minor"] == 873
    assert drawn["status"] == "PARTIALLY_REDEEMED"

    entries = grant_ledger_entries(grant_id)
    assert len(entries) == 2
    assert_grant_conservation(drawn, entries)
    assert_ledger_balances_run(entries)
    redeem = entries[1]
    assert_credit_ledger_entry(redeem)
    assert redeem["entry_type"] == "REDEEM"
    assert redeem["amount_minor"] == -REDEMPTION_CAP
    assert redeem["balance_after_minor"] == 873
    assert redeem["resale_order_id"] == order["id"]
    assert_instant(redeem["occurred_at"], "2026-08-01T00:00:00Z", "occurred_at")

    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 873
    assert fetch_unit(unit["id"])["lifecycle_state"] == "RESERVED"


def test_the_waterfall_drains_the_earliest_expiring_grant_first():
    """Two grants, one redemption, and the later grant only sees the remainder.

    PRD §3.7: "A grant qualifies only if its `customer_id` is the buyer's, its
    `status` is `ISSUED` or `PARTIALLY_REDEEMED`, its `expires_at` lies strictly
    after the logical clock, and its pinned brand-currency policy's
    `eligible_assortment` admits this channel's `channel_type`."
    PRD §3.7: "Redemption then walks that set as a **waterfall**, ordered by
    ascending `expires_at` and, where two grants expire together, by ascending
    `created_at` — never by identifier."
    PRD §3.7: "Each grant is drained to zero before the next one is touched, so
    only the last grant in the walk may be left partially drawn."
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
    PRD §3.4: "It copies `customer_id` from the trade-in, records `trade_in_id` as
    the acceptance that produced it, records `credit_policy_id` as the `ACTIVE`
    brand-currency policy and `credit_policy_version` as that policy's current
    `version`, sets `issued_amount_minor` to the freshly computed final appraisal
    and `remaining_minor` to the same figure, sets `issued_at` equal to the
    trade-in's `accepted_at`, computes `expires_at` as `issued_at` plus the pinned
    policy's `expiry_days` whole days, and enters `status` `ISSUED`."
    PRD §2.3: "Unless a specific endpoint states otherwise, every list endpoint
    returns its rows sorted by creation timestamp in ascending order."

    Design: Corner/calculations/credit_waterfall_drains_the_earliest_expiring_grant_first
    """
    estate = setup_estate(
        grade_policies=(GRADE_POLICY_OUTERWEAR_B, GRADE_POLICY_FOOTWEAR_SALVAGE),
    )

    # Day one mints the earlier-expiring grant on a salvage-tier item, whose unit
    # is never refurbished and so never competes as a listing.
    early = setup_accepted_trade_in(
        estate,
        loyalty_tier="PLUS",
        product_category="FOOTWEAR",
        declared_grade="SALVAGE",
        assessed_grade="SALVAGE",
        msrp_minor=TEST_DEFAULTS["FOOTWEAR_MSRP_MINOR"],
        item_mass_grams=TEST_DEFAULTS["FOOTWEAR_MASS_GRAMS"],
    )
    # floor(120000 * 500 / 10000) = 6000 base plus a 300 PLUS loyalty term.
    assert early["grant"]["issued_amount_minor"] == 6300
    assert early["grant"]["remaining_minor"] == 6300
    assert_instant(
        early["grant"]["expires_at"], "2027-01-28T00:00:00Z", "expires_at"
    )
    # PRD §3.4: a SALVAGE assessed grade moves the freshly minted unit to
    # SALVAGED inside the very same acceptance request, so it is never listable.
    assert early["unit"]["lifecycle_state"] == "SALVAGED"

    # Day two mints the later-expiring grant, on the item that is actually sold.
    set_clock("2026-08-02T00:00:00Z")
    later = _seller_listing(
        estate,
        customer=early["customer"],
        window=("2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z"),
    )
    assert_instant(
        later["grant"]["expires_at"], "2027-01-29T00:00:00Z", "expires_at"
    )
    assert later["grant"]["expires_at"] > early["grant"]["expires_at"]

    buyer = fetch_customer(early["customer"]["id"])
    assert buyer["credit_balance_minor"] == 16800

    order = place_order(buyer, later["channel"], later["unit"], REDEMPTION_CAP)
    assert order["gross_price_minor"] == GROSS
    assert order["channel_fee_minor"] == FEE_AT_900_BP
    assert order["order_total_minor"] == TOTAL
    assert order["credit_applied_minor"] == REDEMPTION_CAP
    assert order["cash_due_minor"] == 10628

    drained = fetch_grant(early["grant"]["id"])
    assert drained["remaining_minor"] == 0
    assert drained["status"] == "EXHAUSTED"

    # 10627 - 6300 = 4327 is all the later grant ever sees.
    partial = fetch_grant(later["grant"]["id"])
    assert partial["remaining_minor"] == 6173
    assert partial["status"] == "PARTIALLY_REDEEMED"

    early_entries = grant_ledger_entries(early["grant"]["id"])
    assert len(early_entries) == 2
    assert_grant_conservation(drained, early_entries)
    assert_ledger_balances_run(early_entries)
    assert early_entries[1]["entry_type"] == "REDEEM"
    assert early_entries[1]["amount_minor"] == -6300
    assert early_entries[1]["balance_after_minor"] == 0
    assert early_entries[1]["resale_order_id"] == order["id"]
    assert_instant(
        early_entries[1]["occurred_at"], "2026-08-02T00:00:00Z", "occurred_at"
    )

    later_entries = grant_ledger_entries(later["grant"]["id"])
    assert len(later_entries) == 2
    assert_grant_conservation(partial, later_entries)
    assert_ledger_balances_run(later_entries)
    assert later_entries[1]["entry_type"] == "REDEEM"
    assert later_entries[1]["amount_minor"] == -4327
    assert later_entries[1]["balance_after_minor"] == 6173
    assert later_entries[1]["resale_order_id"] == order["id"]

    settled = fetch_customer(early["customer"]["id"])
    assert settled["credit_balance_minor"] == 6173
    assert settled["version"] > buyer["version"]

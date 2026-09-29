"""Calculations: line pricing, surcharge clamps, aggregate input sets and rounding."""

from test_helpers import (
    ADMIN_HEADERS,
    CERT_ENV_A,
    CHANNEL_KIND_DIRECT,
    CHANNEL_KIND_NDC_AGGREGATOR,
    CONTENT_TIER_FULL,
    CONTENT_TIER_STANDARD,
    FULFILLMENT_CANCELLED,
    ITEM_SCOPE_FARE,
    ITEM_TYPE_BUNDLE_ANCILLARY,
    ITEM_TYPE_FARE,
    ITEM_TYPE_SURCHARGE,
    PAYMENT_ACTION_VOID,
    PAYMENT_PAID,
    PAYMENT_VOIDED,
    REQUEST_TYPE_REFUND,
    SR_APPROVED,
    TEST_PASSED,
    TIER_1,
    agency_headers,
    assert_readiness,
    assert_settlement,
    fixtures as fx,
    validate_paginated,
)

CORNER_BASIS = "YCORN01"
CORNER_FARE_CENTS = 45010
CORNER_NET_CENTS = 46585


def _corner_agency(api):
    return fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )


def _lines(api, offer_id, headers=None):
    rows, meta = validate_paginated(
        api.list_offer_items(
            offer_id, headers=headers or ADMIN_HEADERS, params={"limit": 100}
        )
    )
    assert meta["total_count"] == len(rows)
    return rows


def test_a_bundled_line_is_discounted_first_and_marked_up_second(api):
    """PRD §3.5: "Second, the bundle discount is applied — and *only* to bundled ancillary
    lines: the discounted value is the line's list amount multiplied by one minus the bundle's
    `bundle_discount_pct`, carried at full precision with no rounding."
    PRD §3.5: "Third, the channel markup is applied and the line is rounded: the line's
    `net_amount_cents` is the discounted value multiplied by one plus the channel's
    `content_markup_pct`, rounded half up to whole cents."
    PRD §3.5: "Lines are numbered by a 1-based `sequence` in a fixed presentation order: the
    fare line first, then the bundled ancillary lines ordered by `item_code` ascending, then the
    à la carte ancillary lines ordered by `item_code` ascending, then the surcharge lines in the
    same ascending `threshold_cents` and `created_at` order in which they were evaluated."

    Design: Corner/calculations/corner_bundle_line_discount_is_applied_before_the_channel_markup
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    fx.create_ancillary(
        api,
        ancillary_code="BAG20",
        name="Checked bag 20kg",
        list_amount_cents=7010,
        min_content_tier_rank=1,
        refundable=True,
    )
    fx.create_ancillary(
        api,
        ancillary_code="SEAT_STD",
        name="Standard seat",
        list_amount_cents=3010,
        min_content_tier_rank=1,
        refundable=False,
    )
    bundle = fx.create_bundle(
        api,
        bundle_code="FLEX_CORNER",
        ancillary_codes=["BAG20", "SEAT_STD"],
        bundle_discount_pct=0.10,
        min_content_tier_rank=1,
    )

    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        headers=headers,
        bundle_id=bundle["id"],
    )
    assert offer["item_count"] == 3
    assert offer["bundle_id"] == bundle["id"]

    fare, bag, seat = _lines(api, offer["id"])
    assert fare["sequence"] == 1
    assert fare["item_type"] == ITEM_TYPE_FARE
    assert fare["item_code"] == CORNER_BASIS
    assert fare["list_amount_cents"] == CORNER_FARE_CENTS
    assert fare["net_amount_cents"] == CORNER_NET_CENTS

    # 7,010 * 0.90 = 6,309 exactly, then * 1.035 = 6,529.815 -> 6,530.
    assert bag["sequence"] == 2
    assert bag["item_type"] == ITEM_TYPE_BUNDLE_ANCILLARY
    assert bag["item_code"] == "BAG20"
    assert bag["list_amount_cents"] == 7010
    assert bag["net_amount_cents"] == 6530
    assert bag["refundable"] is True

    # 3,010 * 0.90 = 2,709 exactly, then * 1.035 = 2,803.815 -> 2,804.
    assert seat["sequence"] == 3
    assert seat["item_type"] == ITEM_TYPE_BUNDLE_ANCILLARY
    assert seat["item_code"] == "SEAT_STD"
    assert seat["list_amount_cents"] == 3010
    assert seat["net_amount_cents"] == 2804
    assert seat["refundable"] is False

    assert offer["subtotal_cents"] == 55919
    assert offer["surcharge_cents"] == 0
    assert offer["total_cents"] == 55919


def _surcharge_channel(api, channel_code, **rule):
    channel = fx.create_full_channel(
        api,
        channel_code=channel_code,
        channel_kind=CHANNEL_KIND_NDC_AGGREGATOR,
        content_tier=CONTENT_TIER_STANDARD,
        content_markup_pct=0.035,
    )
    if rule:
        fx.add_surcharge_rule(api, channel["id"], **rule)
    return channel


def test_the_threshold_is_inclusive_and_one_cent_below_it_emits_no_line(api):
    """PRD §3.5: "The rule fires only when its scope base is greater than or equal to its
    `threshold_cents` — the boundary is inclusive, so a scope base exactly equal to the threshold
    does fire."
    PRD §3.5: "When the scope base is strictly below the threshold the rule emits nothing at
    all, which is why `item_count` varies between two otherwise identical offers on the same
    channel."
    PRD §3.5: "Each rule computes its own scope base from its `item_scope`: a rule scoped to
    `FARE` measures the `net_amount_cents` of the fare line alone; a rule scoped to `ANCILLARY`
    measures the sum of `net_amount_cents` across the à la carte ancillary lines and the bundled
    ancillary lines together; a rule scoped to `ALL` measures the offer's `subtotal_cents`."

    Design: Corner/calculations/corner_surcharge_fires_at_the_threshold_and_stays_silent_one_cent_below
    """
    channel = _surcharge_channel(
        api,
        "CORNER_SUR",
        surcharge_code="YQ_HIGH",
        item_scope=ITEM_SCOPE_FARE,
        rate_pct=0.02,
        threshold_cents=46585,
        min_cents=0,
        max_cents=999999,
    )
    partner = _corner_agency(api)
    on_filing = fx.create_active_filing(
        api, fare_basis_code="YSURC01", base_amount_cents=45010
    )
    off_filing = fx.create_active_filing(
        api, fare_basis_code="YSURC02", base_amount_cents=45009
    )
    headers = agency_headers(partner["id"])

    # 45,010 * 1.035 = 46,585.35 -> 46,585, exactly the threshold, so the rule fires.
    firing = fx.construct_offer(
        api, channel["id"], partner["id"], on_filing["id"], headers=headers
    )
    assert firing["subtotal_cents"] == 46585
    assert firing["surcharge_cents"] == 932
    assert firing["total_cents"] == 47517
    assert firing["item_count"] == 2

    _fare, surcharge = _lines(api, firing["id"])
    assert surcharge["sequence"] == 2
    assert surcharge["item_type"] == ITEM_TYPE_SURCHARGE
    assert surcharge["item_code"] == "YQ_HIGH"
    # 46,585 * 0.02 = 931.70 -> 932, inside both clamps.
    assert surcharge["list_amount_cents"] == 932
    assert surcharge["net_amount_cents"] == 932
    assert surcharge["refundable"] is False

    # 45,009 * 1.035 = 46,584.315 -> 46,584, one cent short of the threshold.
    silent = fx.construct_offer(
        api, channel["id"], partner["id"], off_filing["id"], headers=headers
    )
    assert silent["subtotal_cents"] == 46584
    assert silent["surcharge_cents"] == 0
    assert silent["total_cents"] == 46584
    assert silent["item_count"] == 1

    silent_lines = _lines(api, silent["id"])
    assert len(silent_lines) == 1
    assert all(line["item_type"] != ITEM_TYPE_SURCHARGE for line in silent_lines)


def test_the_clamps_are_applied_after_rounding_and_recorded_separately(api):
    """PRD §3.5: "A firing rule produces one surcharge line. The raw amount is the scope base
    multiplied by the rule's `rate_pct`, rounded half up to whole cents; that rounding happens
    **before** the clamps, not after."
    PRD §3.5: "The clamped amount is then the raw amount raised to at least the rule's
    `min_cents` and lowered to at most the rule's `max_cents`."
    PRD §3.5: "The emitted line records the raw amount in its `list_amount_cents` and the clamped
    amount in its `net_amount_cents`, so a clamped surcharge remains auditable against what the
    rate alone would have produced."
    PRD §3.5: "The offer's `surcharge_cents` is the sum of `net_amount_cents` over the emitted
    surcharge lines, and `total_cents` is `subtotal_cents` plus `surcharge_cents`."

    Design: Corner/calculations/corner_surcharge_clamps_below_min_and_above_max
    """
    channel = _surcharge_channel(
        api,
        "CORNER_CLAMP",
        surcharge_code="TINY",
        item_scope=ITEM_SCOPE_FARE,
        rate_pct=0.001,
        threshold_cents=0,
        min_cents=500,
        max_cents=4000,
    )
    fx.add_surcharge_rule(
        api,
        channel["id"],
        surcharge_code="HUGE",
        item_scope=ITEM_SCOPE_FARE,
        rate_pct=0.10,
        threshold_cents=1000,
        min_cents=0,
        max_cents=4000,
    )
    partner = _corner_agency(api)
    filing = fx.create_active_filing(
        api, fare_basis_code="YCLMP01", base_amount_cents=45010
    )

    offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        headers=agency_headers(partner["id"]),
    )
    assert offer["subtotal_cents"] == 46585
    assert offer["item_count"] == 3

    _fare, tiny, huge = _lines(api, offer["id"])
    # Ascending threshold_cents: TINY at 0 is evaluated before HUGE at 1,000.
    assert tiny["sequence"] == 2
    assert tiny["item_code"] == "TINY"
    # 46,585 * 0.001 = 46.585 -> 47, lifted to the 500 floor.
    assert tiny["list_amount_cents"] == 47
    assert tiny["net_amount_cents"] == 500

    assert huge["sequence"] == 3
    assert huge["item_code"] == "HUGE"
    # 46,585 * 0.10 = 4,658.5 -> 4,659, cut to the 4,000 ceiling.
    assert huge["list_amount_cents"] == 4659
    assert huge["net_amount_cents"] == 4000

    assert offer["surcharge_cents"] == 4500
    assert offer["total_cents"] == 51085


def _corner_scenario(api):
    """CORNER_NDC, agency Alpha with a SIGNED agreement, and YCORN01 sellable."""
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = _corner_agency(api)
    filing = fx.create_ndc_filing(api, fare_basis_code=CORNER_BASIS)
    agreement = fx.create_signed_agreement(
        api,
        partner["id"],
        channel["id"],
        partner["version"],
        proposed_incentive_pct=0.025,
        incentive_cap_cents=1000000,
        target_net_revenue_cents=5000000,
    )
    return channel, partner, filing, agreement


def _paid_corner_order(api, channel, partner, filing, headers):
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    assert offer["total_cents"] == CORNER_NET_CENTS
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order = fx.create_order(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    fx.capture_payment(api, order["id"], CORNER_NET_CENTS, headers=headers)
    return order


def test_a_voided_order_enters_neither_aggregate_population(api):
    """PRD §3.6: "A void advances `AUTHORIZED → VOIDED` with no precondition; it forces
    `fulfillment_status` to `CANCELLED`, leaves the channel's `booking_count` untouched precisely
    because the order never reached `PAID`, and increases `version` by 1."
    PRD §3.3: "An agreement accumulates `cumulative_net_revenue_cents`, defined as the sum of
    `net_revenue_cents` over the orders that name this agreement and whose `payment_status` is
    `PAID`. Orders sitting in `AUTHORIZED`, `VOIDED` or `REFUNDED` contribute nothing, and an
    order's `fulfillment_status` is irrelevant to the ledger entirely — a cancelled-but-paid order
    still counts."
    PRD §3.9: "Both read the same order population — the orders on this channel whose
    `payment_status` is `PAID`, which is precisely the population counted by the channel's
    `booking_count` — and the same clock-independent channel configuration."

    Design: Corner/calculations/corner_voided_order_never_enters_the_revenue_or_booking_base
    """
    channel, partner, filing, agreement = _corner_scenario(api)
    headers = agency_headers(partner["id"])
    _paid = _paid_corner_order(api, channel, partner, filing, headers)

    second_offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, second_offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    second_order = fx.create_order(
        api, second_offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers
    )
    voided = fx.advance_payment(
        api, second_order["id"], PAYMENT_ACTION_VOID, headers=headers
    )
    assert voided["payment_status"] == PAYMENT_VOIDED
    assert voided["fulfillment_status"] == FULFILLMENT_CANCELLED
    # The frozen revenue figure survives the void; it simply stops being counted.
    assert voided["net_revenue_cents"] == CORNER_NET_CENTS

    ledger = fx.read_channel(api, channel["id"])
    assert ledger["booking_count"] == 1
    # 400,000 / 1 paid booking, not halved by the voided order.
    assert ledger["cost_per_booking_flat_cents"] == 400000
    # 12 + 40 from the one paid order plus the 582 accrual on the SIGNED agreement.
    assert ledger["activity_cost_cents"] == 634
    assert ledger["cost_per_booking_activity_cents"] == 634

    balance = fx.read_agreement(api, agreement["id"])
    assert balance["cumulative_net_revenue_cents"] == CORNER_NET_CENTS
    assert balance["incentive_tier"] == TIER_1
    assert balance["incentive_accrued_cents"] == 582

    _rows, meta = validate_paginated(
        api.list_orders(
            headers=ADMIN_HEADERS,
            params={"channel_id": channel["id"], "payment_status": PAYMENT_PAID},
        )
    )
    assert meta["total_count"] == 1


def test_a_base_below_the_middle_floor_draws_the_flat_low_tier_fee(api):
    """PRD §3.7: "When the refundable base is strictly below 50,000 cents,
    `cancellation_fee_cents` is a flat 2,500 cents."
    PRD §3.7: "`refund_total_cents` is the refundable base less the cancellation fee, floored at
    zero — a base smaller than its own flat fee refunds nothing rather than going negative."
    PRD §3.7: "`incentive_clawback_cents` is the refund total multiplied by the rate of the tier
    the agreement carries *at this moment*, before the refund cascade has moved anything: 0.010
    when the agreement's `incentive_tier` is `TIER_1`, 0.025 when it is `TIER_2`, and 0.040 when
    it is `TIER_3`, with the product rounded half up to whole cents."
    PRD §3.7: "`refundable_base_cents` is the sum of `net_amount_cents` over the priced lines of
    the order's offer whose `refundable` flag is true."

    Design: Corner/calculations/corner_refund_fee_uses_the_low_tier_constant_below_the_mid_floor
    """
    channel, partner, filing, agreement = _corner_scenario(api)
    headers = agency_headers(partner["id"])
    order = _paid_corner_order(api, channel, partner, filing, headers)

    request = fx.open_service_request(
        api,
        order["id"],
        REQUEST_TYPE_REFUND,
        headers=headers,
        requested_change_note="customer cancelled",
    )
    assert_settlement(request, 0, 0, 0, 0)

    approved = fx.approve_service_request(api, request["id"])
    assert approved["status"] == SR_APPROVED
    # Base 46,585 < 50,000 -> flat 2,500 fee -> total 44,085; 44,085 * 0.010 = 440.85 -> 441.
    assert_settlement(approved, CORNER_NET_CENTS, 2500, 44085, 441)

    untouched = fx.read_order(api, order["id"], headers=headers)
    assert untouched["payment_status"] == PAYMENT_PAID
    assert untouched["refunded_amount_cents"] == 0

    balance = fx.read_agreement(api, agreement["id"])
    assert balance["incentive_accrued_cents"] == 582
    assert balance["cumulative_net_revenue_cents"] == CORNER_NET_CENTS


def test_a_line_landing_on_the_half_cent_rounds_up_not_to_the_even_neighbour(api):
    """PRD §2.5: "Wherever a computation produces a non-integral value, the service rounds **half
    up** — a value exactly on the half-cent boundary rounds away from zero to the larger magnitude
    — and it does so at the exact point the relevant calculation nominates, never earlier and never
    later."
    PRD §3.5: "Third, the channel markup is applied and the line is rounded: the line's
    `net_amount_cents` is the discounted value multiplied by one plus the channel's
    `content_markup_pct`, rounded half up to whole cents."

    Design: Corner/calculations/corner_line_markup_rounds_half_up_away_from_the_even_neighbour
    """
    channel = fx.create_full_channel(
        api,
        channel_code="CORNER_PREC",
        channel_kind=CHANNEL_KIND_DIRECT,
        content_tier=CONTENT_TIER_FULL,
        content_markup_pct=0.05,
        required_disclosure_codes=[],
    )
    partner = _corner_agency(api)
    filing = fx.create_active_filing(
        api, fare_basis_code="YPREC01", base_amount_cents=4010
    )

    offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        headers=agency_headers(partner["id"]),
    )
    fare = _lines(api, offer["id"])[0]
    # 4,010 * 1.05 = 4,210.50 exactly: half up gives 4,211, never 4,210.
    assert fare["net_amount_cents"] == 4211
    assert fare["net_amount_cents"] != 4210
    assert offer["subtotal_cents"] == 4211
    assert offer["total_cents"] == 4211


def test_a_tied_weighted_mean_rounds_upward_on_both_readiness_variants(api):
    """PRD §3.8: "Each considered test carries a weight of 3 when its `is_mandatory` is true and 1
    when it is false."
    PRD §3.8: "otherwise it is the sum over considered tests of that test's `score` multiplied by
    its weight, divided by the sum of those same weights, rounded half up to an integer."
    PRD §3.8: "Only tests in `PASSED` or `FAILED` are considered; scheduled tests, which still
    hold reserved minutes, and cancelled tests never enter either variant's numerator or
    denominator."
    PRD §3.8: "The `PROVISIONAL` variant, stored in `readiness_score_provisional`, first drops
    every considered test that is both mandatory and failed from the population — removing it from
    the numerator **and** from the denominator — and is 0 when the remaining population is empty;
    otherwise it is the same weighted mean over the remaining tests, rounded half up."

    Design: Corner/calculations/corner_readiness_weighted_mean_rounds_a_tie_upward
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_tech_partner(
        api, partner_name="Tango Corner Systems", iata_code="55555551"
    )
    certification = fx.open_certification(
        api, partner["id"], channel["id"], env_code=CERT_ENV_A
    )
    mandatory = fx.schedule_test(
        api,
        certification["id"],
        partner["id"],
        "SHOP_SEARCH",
        "2026-08-03T09:00:00.000Z",
        duration_minutes=60,
        is_mandatory=True,
    )
    optional = fx.schedule_test(
        api,
        certification["id"],
        partner["id"],
        "ORDER_CREATE",
        "2026-08-03T13:00:00.000Z",
        duration_minutes=30,
        is_mandatory=False,
    )

    fx.report_outcome(api, mandatory["id"], partner["id"], TEST_PASSED, score=90)
    # The still-scheduled optional slot is outside the population, so 270/3 = 90.
    after_first = fx.read_certification(api, certification["id"])
    assert_readiness(after_first, 90, 90, mandatory_failed_count=0)
    assert after_first["reserved_test_minutes"] == 30

    fx.report_outcome(api, optional["id"], partner["id"], TEST_PASSED, score=68)
    # (90*3 + 68*1) / 4 = 338/4 = 84.5 -> 85 on both variants, never 84.
    final = fx.read_certification(api, certification["id"])
    assert_readiness(final, 85, 85, mandatory_failed_count=0, reserved_test_minutes=0)
    assert final["readiness_score_strict"] != 84
    assert final["readiness_score_provisional"] != 84

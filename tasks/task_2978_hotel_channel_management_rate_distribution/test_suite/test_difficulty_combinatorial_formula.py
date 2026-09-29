"""Multi-step money formulas whose declared step order is itself observable.

Three calculations in the contract combine several operations whose sequence
changes the answer: the six-step sell-rate resolution caps the total stacked
discount before the plan clamp rather than after, the reservation charge rounds
commission once per night and only then sums, and the loyalty credit reads its
tier from gross while applying the rate to net. Each test pins the intermediate
fields the contract exposes, so a wrong ordering is reported as the step that
disagrees rather than as a single wrong total.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    REVENUE_MANAGER_HEADERS,
    assert_nightly_breakdown,
    assert_quoted_rate,
    assert_reservation_totals,
    factories,
    fixtures,
)

# ── The quoted night and the plan band the cap is measured against ─────────

# The stay night every quote below is taken for, and the offer window that
# covers it.
QUOTE_STAY_DATE = "2026-09-10"
OFFER_START = "2026-09-01"
OFFER_END = "2026-09-30"

# The plan's own base, and the low floor that keeps the clamp of step five out
# of the way while the cap of step three is being pinned.
PLAN_BASE_CENTS = 25000
LOW_FLOOR_CENTS = 15000
PLAN_CEILING_CENTS = 40000

# Thirty percent of the base, floored: the cap the total discount is measured
# against.
EXPECTED_CAP_CENTS = 7500


def _plan_with_floor(api, world, code: str, floor_amount_cents: int):
    """An ACTIVE public plan on the canonical property at the canonical base."""
    return fixtures.create_active_rate_plan(
        api,
        world["property_id"],
        code=code,
        rate_class="PUBLIC",
        base_amount_cents=PLAN_BASE_CENTS,
        floor_amount_cents=floor_amount_cents,
        ceiling_amount_cents=PLAN_CEILING_CENTS,
    )


def _quote(api, mapping_id: str):
    """The quoted-rate read for a member booking from the channel's own market."""
    query = factories.quoted_rate_params(
        stay_date=QUOTE_STAY_DATE,
        member_flag=True,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )
    return validate_success(api.get_quoted_rate(mapping_id, REVENUE_MANAGER_HEADERS, query), 200)


def _verified_mapping_id(api, world, rate_plan_id: str) -> str:
    """Map the plan on the live OTA and verify it, so its price can be quoted."""
    mapping = fixtures.create_verified_mapping(
        api, rate_plan_id, world["channel_id"], world["room_type_id"]
    )
    return mapping["id"]


def test_stacking_cap_pulls_the_total_discount_back_to_thirty_percent_of_base(api, world):
    """A thirty percent member offer and a ten dollar geo offer take 8500 off a
    25000 base between them, which exceeds the cap of thirty percent of that base,
    so the total discount becomes 7500 and the night resolves at 17500.

    Design: Difficulty/combinatorial_formula/sell_rate_stacking_cap_applies_to_total_after_nested_clamp
    """
    plan = _plan_with_floor(api, world, "BARCAP", LOW_FLOOR_CENTS)
    fixtures.create_approved_promotion(
        api,
        plan["id"],
        start_date=OFFER_START,
        end_date=OFFER_END,
        code="MEMBER30",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=3000,
    )
    fixtures.create_approved_promotion(
        api,
        plan["id"],
        start_date=QUOTE_STAY_DATE,
        end_date="2026-09-11",
        code="GEO10USD",
        promo_kind="GEO_OFFER",
        discount_kind="AMOUNT",
        discount_amount_cents=1000,
        geo_market_codes=[fixtures.OTA_GEO_MARKET],
    )
    mapping_id = _verified_mapping_id(api, world, plan["id"])

    quote = _quote(api, mapping_id)
    # 25000 x 0.7 = 17500, then -1000 = 16500, so the raw total discount is 8500.
    # The cap is floor(25000 x 3000 / 10000) = 7500, so the discount is rewritten
    # to 7500 and the running amount to 25000 - 7500 = 17500. A 0bp channel
    # adjustment leaves it there, and 17500 sits inside [15000, 40000].
    assert_quoted_rate(
        quote,
        {
            "channel_mapping_id": mapping_id,
            "stay_date": QUOTE_STAY_DATE,
            "base_amount_cents": PLAN_BASE_CENTS,
            "promotion_discount_cents": EXPECTED_CAP_CENTS,
            "discount_cap_cents": EXPECTED_CAP_CENTS,
            "channel_adjusted_cents": 17500,
            "clamped_cents": 17500,
            "sell_amount_cents": 17500,
            "applied_promotion_codes": ["MEMBER30", "GEO10USD"],
        },
    )
    # Capping each offer on its own would have left the 16500 the two offers
    # produced, and clamping to the floor before capping would have left 15000.
    assert quote["sell_amount_cents"] == 17500, (
        "the total discount should be capped before the clamp, giving 17500 rather "
        f"than 16500 or 15000, got {quote['sell_amount_cents']}"
    )


def test_stacking_cap_binds_on_two_individually_compliant_promotions(api, world):
    """Two percent offers that each respect the thirty percent ceiling on their own
    compound to a thirty-two percent reduction, and it is that combined effect the
    cap pulls back: the reported discount is the cap, not the 8000 they took.

    Design: Difficulty/combinatorial_formula/sell_rate_stacking_cap_applies_to_total_after_nested_clamp
    """
    plan = _plan_with_floor(api, world, "BARPCT", LOW_FLOOR_CENTS)
    fixtures.create_approved_promotion(
        api,
        plan["id"],
        start_date=OFFER_START,
        end_date=OFFER_END,
        code="MEMBER20",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=2000,
    )
    fixtures.create_approved_promotion(
        api,
        plan["id"],
        start_date=OFFER_START,
        end_date=OFFER_END,
        code="GEO15PCT",
        promo_kind="GEO_OFFER",
        discount_kind="PERCENT",
        discount_bp=1500,
        geo_market_codes=[fixtures.OTA_GEO_MARKET],
    )
    mapping_id = _verified_mapping_id(api, world, plan["id"])

    quote = _quote(api, mapping_id)
    # 25000 x 0.8 = 20000, then 20000 x 0.85 = 17000: a total discount of 8000,
    # while each offer alone would have taken only 5000 or 3750. 8000 exceeds the
    # 7500 cap, so the running amount is 25000 - 7500 = 17500.
    assert_quoted_rate(
        quote,
        {
            "base_amount_cents": PLAN_BASE_CENTS,
            "promotion_discount_cents": EXPECTED_CAP_CENTS,
            "discount_cap_cents": EXPECTED_CAP_CENTS,
            "channel_adjusted_cents": 17500,
            "clamped_cents": 17500,
            "sell_amount_cents": 17500,
            "applied_promotion_codes": ["MEMBER20", "GEO15PCT"],
        },
    )
    # Both offers participate and compound in the fixed kind order, so a cap
    # applied per offer would have left the compounded 17000 untouched.
    assert quote["sell_amount_cents"] == 17500, (
        "the cap should bind on the combined 8000 discount, giving 17500 rather than "
        f"the compounded 17000, got {quote['sell_amount_cents']}"
    )


def test_plan_clamp_lifts_the_capped_amount_to_the_floor_after_the_cap(api, world):
    """With a floor of 22000 the capped amount of 17500 is lifted back to the floor,
    and the read still reports the 7500 discount the offer actually took: the clamp
    is the fifth step, so it cannot feed back into the third.

    Design: Difficulty/combinatorial_formula/sell_rate_stacking_cap_applies_to_total_after_nested_clamp
    """
    plan = _plan_with_floor(api, world, "BARFLOOR", 22000)
    fixtures.create_approved_promotion(
        api,
        plan["id"],
        start_date=OFFER_START,
        end_date=OFFER_END,
        code="MEMBER30",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=3000,
    )
    mapping_id = _verified_mapping_id(api, world, plan["id"])

    quote = _quote(api, mapping_id)
    # 25000 x 0.7 = 17500, a discount of exactly 7500, which equals the cap and is
    # therefore not reduced. The 0bp channel leaves 17500, which is below the
    # 22000 floor and rises to it, and the plan carries no inclusion.
    assert_quoted_rate(
        quote,
        {
            "base_amount_cents": PLAN_BASE_CENTS,
            "promotion_discount_cents": EXPECTED_CAP_CENTS,
            "discount_cap_cents": EXPECTED_CAP_CENTS,
            "channel_adjusted_cents": 17500,
            "clamped_cents": 22000,
            "sell_amount_cents": 22000,
            "applied_promotion_codes": ["MEMBER30"],
        },
    )
    # The discount the read reports is the one measured against the base at step
    # three, not the 3000 the difference between base and final amount suggests.
    assert quote["promotion_discount_cents"] == EXPECTED_CAP_CENTS, (
        "the reported discount should be the capped step-three total 7500, not the "
        f"3000 the clamped amount implies, got {quote['promotion_discount_cents']}"
    )


# ── The per-night commission world ─────────────────────────────────────────

# The three-night stay whose middle price change makes the rounding visible.
STAY_ARRIVAL = "2026-09-10"
STAY_NIGHT_2 = "2026-09-11"
STAY_NIGHT_3 = "2026-09-12"
STAY_DEPARTURE = "2026-09-13"


def _book_member_stay(api, world, rate_plan_id: str, arrival_date: str, nights: int):
    """Book a member stay from the channel's served market and pin the 201."""
    payload = factories.reservation_payload(
        channel_id=world["channel_id"],
        rate_plan_id=rate_plan_id,
        room_type_id=world["room_type_id"],
        arrival_date=arrival_date,
        nights=nights,
        member_flag=True,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )
    return validate_success(api.create_reservation(payload, REVENUE_MANAGER_HEADERS), 201)


def test_commission_is_rounded_per_night_then_summed_across_a_three_night_stay(api, world):
    """A stay whose geo offer covers only its first two nights prices at 21500,
    21500 and 22500; each night's commission is rounded on its own and the three
    rounded amounts are summed, which is a cent more than one rounding of the gross.

    Design: Difficulty/combinatorial_formula/commission_rounded_per_night_then_summed_not_on_gross
    """
    fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date=OFFER_START,
        end_date=OFFER_END,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date=STAY_ARRIVAL,
        end_date=STAY_NIGHT_2,
        code="GEO10USD",
        promo_kind="GEO_OFFER",
        discount_kind="AMOUNT",
        discount_amount_cents=1000,
        geo_market_codes=[fixtures.OTA_GEO_MARKET],
    )
    fixtures.open_inventory_days(
        api, world["room_type_id"], [STAY_ARRIVAL, STAY_NIGHT_2, STAY_NIGHT_3]
    )

    reservation = _book_member_stay(api, world, world["rate_plan_id"], STAY_ARRIVAL, 3)

    assert reservation["departure_date"] == STAY_DEPARTURE, (
        "departure_date should be arrival plus three nights, got "
        f"{reservation['departure_date']!r}"
    )
    # 25000 x 0.9 = 22500 on every night, less the 1000 geo offer on the first two.
    # No plan inclusion, so each night is fully commissionable at 1750bp:
    # 21500 -> 3762.5 rounds half up to 3763, and 22500 -> 3937.5 rounds to 3938.
    assert_nightly_breakdown(
        reservation,
        [
            {
                "stay_date": STAY_ARRIVAL,
                "sell_rate_cents": 21500,
                "commissionable_cents": 21500,
                "commission_cents": 3763,
            },
            {
                "stay_date": STAY_NIGHT_2,
                "sell_rate_cents": 21500,
                "commissionable_cents": 21500,
                "commission_cents": 3763,
            },
            {
                "stay_date": STAY_NIGHT_3,
                "sell_rate_cents": 22500,
                "commissionable_cents": 22500,
                "commission_cents": 3938,
            },
        ],
    )
    # 21500 + 21500 + 22500 = 65500 gross; 3763 + 3763 + 3938 = 11464 commission;
    # net 54036; and 50000 <= 65500 < 70000 puts the stay in the 400bp tier, so
    # the credit is 54036 x 400 / 10000 = 2161.44, rounded once to 2161.
    assert_reservation_totals(
        reservation, gross=65500, commission=11464, net=54036, loyalty_credit=2161
    )
    # One rounding of 65500 x 1750 / 10000 = 11462.5 would have given 11463 and a
    # net of 54037 instead.
    assert reservation["commission_amount_cents"] == 11464, (
        "commission should be the sum of the three per-night roundings, 11464, not "
        f"the 11463 a single rounding of the gross gives, got "
        f"{reservation['commission_amount_cents']}"
    )


def test_two_identical_nights_sum_two_rounded_commissions_not_one_on_the_gross(api, world):
    """Two nights that both price at 22500 each carry a commission of exactly half a
    cent, so both round up and the total is 7876; the same 45000 gross commissioned
    once divides exactly and would give 7875.

    Design: Difficulty/combinatorial_formula/commission_rounded_per_night_then_summed_not_on_gross
    """
    fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date=OFFER_START,
        end_date=OFFER_END,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    fixtures.open_inventory_days(api, world["room_type_id"], [STAY_ARRIVAL, STAY_NIGHT_2])

    reservation = _book_member_stay(api, world, world["rate_plan_id"], STAY_ARRIVAL, 2)

    # No geo offer exists, so both nights resolve at 25000 x 0.9 = 22500 and both
    # commissions are 22500 x 1750 / 10000 = 3937.5, rounded half up to 3938.
    assert_nightly_breakdown(
        reservation,
        [
            {
                "stay_date": STAY_ARRIVAL,
                "sell_rate_cents": 22500,
                "commissionable_cents": 22500,
                "commission_cents": 3938,
            },
            {
                "stay_date": STAY_NIGHT_2,
                "sell_rate_cents": 22500,
                "commissionable_cents": 22500,
                "commission_cents": 3938,
            },
        ],
    )
    # Gross 45000, commission 3938 + 3938 = 7876, net 37124; the gross is below
    # the first loyalty floor of 50000, so the tier is 0bp and the credit is 0.
    assert_reservation_totals(
        reservation, gross=45000, commission=7876, net=37124, loyalty_credit=0
    )
    # 45000 x 1750 / 10000 = 7875 exactly, so a single rounding of the gross would
    # lose the two half cents the contract requires to be rounded up first.
    assert reservation["commission_amount_cents"] == 7876, (
        "two nights of 3938 should sum to 7876, not the 7875 one rounding of the "
        f"45000 gross gives, got {reservation['commission_amount_cents']}"
    )


# ── The package plan world ─────────────────────────────────────────────────

# The child plan's offset over the canonical 25000 parent, and the inclusion that
# rides outside both the clamp and the commission base.
PKG_OFFSET_CENTS = 8000
PKG_RESOLVED_BASE_CENTS = 33000
PKG_INCLUSION_CENTS = 2500
PKG_FLOOR_CENTS = 20000
PKG_CEILING_CENTS = 60000


def _package_plan(api, world, code: str, offset_amount_cents: int, package_inclusion_cents: int):
    """An ACTIVE package plan derived from the canonical parent by a flat offset."""
    plan = fixtures.create_derived_rate_plan(
        api,
        world["property_id"],
        world["rate_plan_id"],
        code=code,
        rate_class="PACKAGE",
        offset_kind="AMOUNT",
        offset_amount_cents=offset_amount_cents,
        package_inclusion_cents=package_inclusion_cents,
        floor_amount_cents=PKG_FLOOR_CENTS,
        ceiling_amount_cents=PKG_CEILING_CENTS,
    )
    return fixtures.activate_rate_plan(api, plan["id"])


def test_package_plan_keys_the_loyalty_tier_on_gross_and_applies_it_to_net(api, world):
    """A two-night package stay grosses 71000 with its inclusions counted in, which
    is the top tier at 600bp, and the credit is that rate on the 59450 net; the 2500
    inclusion per night is added outside the clamp and never commissioned.

    Design: Difficulty/combinatorial_formula/package_loyalty_tier_keyed_on_gross_then_credit_on_net
    """
    plan = _package_plan(api, world, "PKG", PKG_OFFSET_CENTS, PKG_INCLUSION_CENTS)
    # 25000 parent base plus a flat 8000 offset, one derivation hop deep.
    assert plan["derivation_depth"] == 1, (
        f"the child plan should sit one hop from its parent, got {plan['derivation_depth']}"
    )
    assert plan["resolved_base_amount_cents"] == PKG_RESOLVED_BASE_CENTS, (
        "the resolved base should be 25000 + 8000 = 33000, got "
        f"{plan['resolved_base_amount_cents']}"
    )
    fixtures.open_inventory_days(api, world["room_type_id"], [STAY_ARRIVAL, STAY_NIGHT_2])

    reservation = _book_member_stay(api, world, plan["id"], STAY_ARRIVAL, 2)

    # No promotion exists, so each night is 33000 inside [20000, 60000] plus the
    # 2500 inclusion = 35500 sold, of which 33000 is commissionable:
    # 33000 x 1750 / 10000 = 5775 exactly.
    assert_nightly_breakdown(
        reservation,
        [
            {
                "stay_date": STAY_ARRIVAL,
                "sell_rate_cents": 35500,
                "commissionable_cents": PKG_RESOLVED_BASE_CENTS,
                "commission_cents": 5775,
            },
            {
                "stay_date": STAY_NIGHT_2,
                "sell_rate_cents": 35500,
                "commissionable_cents": PKG_RESOLVED_BASE_CENTS,
                "commission_cents": 5775,
            },
        ],
    )
    # Gross 71000, commission 11550, net 59450; 71000 is at or above 70000 so the
    # tier is 600bp, and 59450 x 600 / 10000 = 3567 exactly.
    assert_reservation_totals(
        reservation, gross=71000, commission=11550, net=59450, loyalty_credit=3567
    )
    # Commissioning the 5000 of inclusions across the stay would have given 12426,
    # and keying the tier on the 59450 net would have dropped it to 400bp and 2378.
    assert reservation["commission_amount_cents"] == 11550, (
        "the package inclusion is never commissionable, so commission should be "
        f"11550 rather than 12426, got {reservation['commission_amount_cents']}"
    )
    assert reservation["loyalty_credit_cents"] == 3567, (
        "the tier should be read from the 71000 gross and applied to the 59450 net, "
        f"giving 3567 rather than 2378, got {reservation['loyalty_credit_cents']}"
    )


def test_package_inclusion_lifts_gross_into_the_first_loyalty_tier(api, world):
    """A single package night whose room rate alone is 48000 grosses 53000 once its
    5000 inclusion is added, and it is that gross that earns the 400bp tier: the
    inclusion carries the sell amount past the plan's ceiling and out of commission.

    Design: Difficulty/combinatorial_formula/package_loyalty_tier_keyed_on_gross_then_credit_on_net
    """
    draft = fixtures.create_derived_rate_plan(
        api,
        world["property_id"],
        world["rate_plan_id"],
        code="PKG2",
        rate_class="PACKAGE",
        offset_kind="AMOUNT",
        offset_amount_cents=23000,
        package_inclusion_cents=5000,
        floor_amount_cents=PKG_FLOOR_CENTS,
        ceiling_amount_cents=50000,
    )
    plan = fixtures.activate_rate_plan(api, draft["id"])
    # 25000 + 23000 = 48000, one hop from the canonical parent.
    assert plan["resolved_base_amount_cents"] == 48000, (
        "the resolved base should be 25000 + 23000 = 48000, got "
        f"{plan['resolved_base_amount_cents']}"
    )
    fixtures.open_inventory_days(api, world["room_type_id"], [STAY_ARRIVAL])

    reservation = _book_member_stay(api, world, plan["id"], STAY_ARRIVAL, 1)

    # 48000 lies inside [20000, 50000] so the clamp is a no-op, and the 5000
    # inclusion is then added on top, carrying the night to 53000 - above the
    # plan's own ceiling, which the inclusion is allowed to exceed. Commission is
    # taken on the 48000 room rate only: 48000 x 1750 / 10000 = 8400.
    assert_nightly_breakdown(
        reservation,
        [
            {
                "stay_date": STAY_ARRIVAL,
                "sell_rate_cents": 53000,
                "commissionable_cents": 48000,
                "commission_cents": 8400,
            }
        ],
    )
    # Gross 53000, net 44600; 50000 <= 53000 < 70000 gives 400bp, and
    # 44600 x 400 / 10000 = 1784 exactly.
    assert_reservation_totals(
        reservation, gross=53000, commission=8400, net=44600, loyalty_credit=1784
    )
    # Both ordering errors collapse to nothing here: keying the tier on the 44600
    # net, or on a gross with the inclusion stripped back out to 48000, would put
    # the stay below the first floor of 50000 and earn no credit at all.
    assert reservation["loyalty_credit_cents"] == 1784, (
        "the inclusion counts towards the tier key, so the credit should be 1784 "
        f"rather than 0, got {reservation['loyalty_credit_cents']}"
    )

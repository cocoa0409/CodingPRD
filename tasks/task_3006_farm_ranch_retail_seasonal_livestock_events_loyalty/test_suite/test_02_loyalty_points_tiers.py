"""Loyalty accrual evaluation order, dual tier variants, and tier boundaries."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accrue_points,
    create_account,
    create_open_store,
    set_clock,
    validate_error,
    validate_success,
)

ASSOC = TEST_USERS["store_associate_headers"]

FALL_NOW = "2026-09-20T10:00:00Z"


def test_loyalty_dual_variant_rolling365_vs_posture_season(api):
    """PRD §3.7: "The account's `tier_qualifying_points` is the sum of
    `points_delta` over all of the account's entries where
    `counts_toward_tier` is true and the entry's `created_at` falls within
    the rolling window from 365 days before the logical now through the
    logical now, both bounds inclusive."
    PRD §3.7: "a posture multiplier of 2.0 applies when the entry's `earn_context` is `FEED` and the posting store's posture at entry-creation time is `FALL_FEED`; otherwise the posture multiplier is 1.0."
    PRD §3.7: "The response carries `season_qualifying_points`, a `fuel_discount_cents_per_gal` equal to 5 cents for each full 500-point step of the season total, capped at 50 cents per gallon"

    Design: Difficulty/dual_variant_calc/loyalty_rolling365_vs_posture_season_qualification
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="FALL_FEED", name="Amarillo Farm & Ranch")
    account = create_account(full_name="Dee Keller")

    # First FEED accrual: base 100 x 1.0 tier x 2.0 posture = 200.
    e1 = validate_success(
        api.create_ledger_entry(
            account["id"],
            {
                "entry_type": "ACCRUAL",
                "store_id": store["id"],
                "base_amount_cents": 10000,
                "earn_context": "FEED",
            },
            ASSOC,
        ),
        expected_status=201,
    )
    assert e1["points_delta"] == 200

    # Posture variant at 200: below the 500-point step, so no fuel discount.
    offer1 = validate_success(
        api.get_loyalty_offers(account["id"], ASSOC, params={"store_id": store["id"]})
    )
    assert offer1["season_qualifying_points"] == 200
    assert offer1["fuel_discount_cents_per_gal"] == 0

    # Second FEED accrual: base 250 x 1.0 x 2.0 = 500.
    e2 = validate_success(
        api.create_ledger_entry(
            account["id"],
            {
                "entry_type": "ACCRUAL",
                "store_id": store["id"],
                "base_amount_cents": 25000,
                "earn_context": "FEED",
            },
            ASSOC,
        ),
        expected_status=201,
    )
    assert e2["points_delta"] == 500

    # Posture variant at 700: floor(700/500) = 1 step -> 5 cents/gal, while the
    # rolling-365 variant leaves the tier at NEIGHBOR (700 < 2500).
    offer2 = validate_success(
        api.get_loyalty_offers(account["id"], ASSOC, params={"store_id": store["id"]})
    )
    assert offer2["season_qualifying_points"] == 700
    assert offer2["fuel_discount_cents_per_gal"] == 5
    assert offer2["eligible"] is True

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["tier"] == "NEIGHBOR"
    assert acct["tier_qualifying_points"] == 700


def test_loyalty_offer_eligibility_reads_posture_variant(api):
    """PRD §3.7: "the system computes a season-scoped qualifying total: the sum of `points_delta` over the account's `ACCRUAL` entries whose `posture_at_entry` equals the querying store's current posture — reversals do not count here, and the same purchase history can therefore make a member offer-eligible while their rolling-365-day tier stays `NEIGHBOR`."
    PRD §3.7: "an `eligible` flag that is true when either the fuel discount or the feed coupon is greater than zero."

    Design: Difficulty/dual_variant_calc/loyalty_rolling365_vs_posture_season_qualification
    """
    set_clock(FALL_NOW)
    fall_store = create_open_store(season="FALL_FEED", name="Fall Store")
    winter_store = create_open_store(season="WINTER_HEATING", name="Winter Store")
    account = create_account()

    # 500 posture-season points under FALL_FEED (base 250 x 2.0).
    accrue_points(account, fall_store, 25000, earn_context="FEED")
    # 300 more rolling-365 points under WINTER_HEATING (no posture doubling).
    accrue_points(account, winter_store, 30000, earn_context="OTHER")

    fall_offer = validate_success(
        api.get_loyalty_offers(account["id"], ASSOC, params={"store_id": fall_store["id"]})
    )
    assert fall_offer["season_qualifying_points"] == 500
    assert fall_offer["fuel_discount_cents_per_gal"] == 5
    assert fall_offer["eligible"] is True

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    # Rolling-365 variant sees 500 + 300 = 800 qualifying points: NEIGHBOR.
    assert acct["tier_qualifying_points"] == 800
    assert acct["tier"] == "NEIGHBOR"


def test_loyalty_accrual_circular_tier_multiplier_uses_pre_entry_tier(api):
    """PRD §3.7: "Second, the tier multiplier is read from the account's tier as it stands before this entry is posted: 1.0 for `NEIGHBOR`, 1.25 for `RANCH_HAND`, 1.5 for `HOMESTEAD`."
    PRD §3.7: "Only after the entry posts is the tier re-evaluated — so a tier crossing triggered by this entry never retroactively changes this entry's points; it applies to future purchases."

    Design: Difficulty/combinatorial_formula/loyalty_accrual_circular_tier_multiplier_order
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING", name="Bozeman Farm & Ranch")
    account = create_account(full_name="Hank Roper")

    # Seed exactly 7000 qualifying points -> RANCH_HAND before the crossing entry.
    accrue_points(account, store, 700000, earn_context="OTHER")
    seeded = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert seeded["tier"] == "RANCH_HAND"
    assert seeded["tier_qualifying_points"] == 7000

    # The crossing entry earns at the PRE-ENTRY 1.25 multiplier: 500 x 1.25.
    cross = validate_success(
        api.create_ledger_entry(
            account["id"],
            {
                "entry_type": "ACCRUAL",
                "store_id": store["id"],
                "base_amount_cents": 50000,
                "earn_context": "OTHER",
            },
            ASSOC,
        ),
        expected_status=201,
    )
    assert cross["points_delta"] == 625

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["tier"] == "HOMESTEAD"
    assert acct["tier_qualifying_points"] == 7625

    # The next entry earns at the post-crossing 1.5 multiplier: 100 x 1.5.
    nxt = validate_success(
        api.create_ledger_entry(
            account["id"],
            {
                "entry_type": "ACCRUAL",
                "store_id": store["id"],
                "base_amount_cents": 10000,
                "earn_context": "OTHER",
            },
            ASSOC,
        ),
        expected_status=201,
    )
    assert nxt["points_delta"] == 150


def test_loyalty_accrual_crossing_homestead_boundary_exactly(api):
    """PRD §3.7: "The resulting `tier` is `HOMESTEAD` when qualifying points reach at least 7500, `RANCH_HAND` when they reach at least 2500, and `NEIGHBOR` otherwise; the boundary is inclusive, so exactly 2500 promotes while 2499 does not."
    PRD §3.7: "Second, the tier multiplier is read from the account's tier as it stands before this entry is posted: 1.0 for `NEIGHBOR`, 1.25 for `RANCH_HAND`, 1.5 for `HOMESTEAD`."

    Design: Difficulty/combinatorial_formula/loyalty_accrual_circular_tier_multiplier_order
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account()

    # Seed 7400 -> RANCH_HAND; then a 100-point accrual crosses to exactly 7500.
    accrue_points(account, store, 740000, earn_context="OTHER")
    cross = validate_success(
        api.create_ledger_entry(
            account["id"],
            {
                "entry_type": "ACCRUAL",
                "store_id": store["id"],
                "base_amount_cents": 10000,
                "earn_context": "OTHER",
            },
            ASSOC,
        ),
        expected_status=201,
    )
    # Earned at pre-entry RANCH_HAND: 100 x 1.25 = 125.
    assert cross["points_delta"] == 125

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    # 7400 + 125 = 7525 >= 7500 -> HOMESTEAD (inclusive boundary family).
    assert acct["tier_qualifying_points"] == 7525
    assert acct["tier"] == "HOMESTEAD"


def test_loyalty_tier_promotion_just_below_threshold_stays_neighbor(api):
    """PRD §3.7: "the boundary is inclusive, so exactly 2500 promotes while 2499 does not."

    Design: Difficulty/boundary_precision_check/loyalty_tier_promotion_exactly_at_threshold
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account(full_name="Bea Justbelow")

    accrue_points(account, store, 249900, earn_context="OTHER")

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["tier_qualifying_points"] == 2499
    assert acct["tier"] == "NEIGHBOR"


def test_loyalty_tier_promotion_exactly_at_threshold_promotes(api):
    """PRD §3.7: "the boundary is inclusive, so exactly 2500 promotes while 2499 does not."

    Design: Difficulty/boundary_precision_check/loyalty_tier_promotion_exactly_at_threshold
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account(full_name="Cal Exact")

    accrue_points(account, store, 250000, earn_context="OTHER")

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["tier_qualifying_points"] == 2500
    assert acct["tier"] == "RANCH_HAND"

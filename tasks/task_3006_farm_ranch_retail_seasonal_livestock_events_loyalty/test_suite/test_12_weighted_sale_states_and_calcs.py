"""Weighted sale terminal lockdown, tare feasibility, redemption floor, and
chick volume-discount boundaries."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accrue_points,
    create_account,
    create_account_with_points,
    create_open_store,
    create_provisional_sale,
    create_weighted_sale_payload,
    place_chick_order,
    post_care_log,
    set_clock,
    setup_spring_store,
    validate_error,
    validate_paginated,
    validate_success,
)

MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FALL_NOW = "2026-09-20T10:00:00Z"


def test_weighted_sale_terminal_finalized_lockdown(api):
    """PRD §3.6: "A `StoreAssociate` finalizes a `PROVISIONAL` sale (any other status fails with `ERR_SALE_NOT_PROVISIONAL`, and the same error guards voiding)"
    PRD §3.6: "`FINALIZED` and `VOIDED` are terminal."

    Design: Corner/state_machines/weighted_sale_terminal_finalized_lockdown
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    sale = create_provisional_sale(store, gross_weight_lbs=100)
    finalized = validate_success(
        api.finalize_weighted_sale(sale["id"], {"measured_tare_lbs": 20}, ASSOC)
    )
    assert finalized["final_total_cents"] == 3050  # net 80: 50x40 + 30x35

    refinalize = api.finalize_weighted_sale(
        sale["id"], {"measured_tare_lbs": 18}, ASSOC
    )
    validate_error(refinalize, ApiErrorId.ERR_SALE_NOT_PROVISIONAL)

    void = api.void_weighted_sale(sale["id"], MGR)
    validate_error(void, ApiErrorId.ERR_SALE_NOT_PROVISIONAL)

    sale_after = validate_success(api.get_weighted_sale(sale["id"], ASSOC))
    assert sale_after["status"] == "FINALIZED"
    assert sale_after["final_total_cents"] == 3050


def test_chick_volume_discount_tier_boundary_quantities(api):
    """PRD §3.4: "The bracket keys on quantity: no discount — `discount_pct` 0.00 — for 24 birds or fewer; `discount_pct` 0.10 for 25 through 49 birds; `discount_pct` 0.15 for 50 birds or more."

    Design: Corner/calculations/chick_volume_discount_tier_boundary_quantities
    """
    ctx = setup_spring_store()
    account_a = create_account()
    account_b = create_account(full_name="Kit Bulk")

    o24 = place_chick_order(
        ctx["store"], ctx["lot"], account_a, quantity=24,
        lot_version=ctx["lot_version"],
    )
    assert o24["discount_pct"] == 0.0
    assert o24["total_cents"] == 8376  # 24 x 349

    o25 = place_chick_order(ctx["store"], ctx["lot"], account_b, quantity=25)
    assert o25["discount_pct"] == 0.1
    assert o25["total_cents"] == 7853  # round_half_up(25 x 349 x 0.9)


def test_mortality_rate_exactly_at_threshold_does_not_quarantine(api):
    """PRD §3.3: "When the recomputed rate is strictly greater than 0.05 — a rate of exactly 0.05 does not trigger anything — the lot is quarantined"
    PRD §3.3: "Each `MORTALITY` entry adds its count to the lot's cumulative `mortality_count`, after which the lot's `mortality_rate` is recomputed as the cumulative mortality divided by `quantity_received`, rounded half-up to 4 decimal places."

    Design: Corner/calculations/mortality_rate_exactly_at_threshold_does_not_quarantine
    """
    ctx = setup_spring_store()
    lot_id = ctx["lot"]["id"]

    post_care_log(lot_id, "MORTALITY", mortality_count=5)
    lot5 = validate_success(api.get_livestock_lot(lot_id, MGR))
    assert lot5["mortality_rate"] == 0.05
    assert lot5["status"] == "ON_SALE"  # exactly at threshold: no quarantine

    post_care_log(lot_id, "MORTALITY", mortality_count=1)
    lot6 = validate_success(api.get_livestock_lot(lot_id, MGR))
    assert lot6["mortality_rate"] == 0.06
    assert lot6["status"] == "SUSPENDED"  # strictly greater: quarantine


def test_loyalty_accrual_posture_multiplier_only_for_feed_in_fall(api):
    """PRD §3.7: "Third, a posture multiplier of 2.0 applies when the entry's `earn_context` is `FEED` and the posting store's posture at entry-creation time is `FALL_FEED`; otherwise the posture multiplier is 1.0."
    PRD §3.7: "First, base points are the `base_amount_cents` divided by 100, rounded down to a whole point."

    Design: Corner/calculations/loyalty_accrual_posture_multiplier_only_for_feed_in_fall
    """
    set_clock(FALL_NOW)
    fall_store = create_open_store(season="FALL_FEED", name="Fall Store")
    winter_store = create_open_store(season="WINTER_HEATING", name="Winter Store")
    account = create_account()

    p_feed_fall = accrue_points(account, fall_store, 10000, earn_context="FEED")
    assert p_feed_fall["points_delta"] == 200  # 100 x 1.0 x 2.0

    p_other_fall = accrue_points(account, fall_store, 10000, earn_context="OTHER")
    assert p_other_fall["points_delta"] == 100  # context not FEED

    p_feed_win = accrue_points(account, winter_store, 10000, earn_context="FEED")
    assert p_feed_win["points_delta"] == 100  # posture not FALL_FEED

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["points_balance"] == 400


def test_fuel_offer_rounds_down_partial_steps(api):
    """PRD §3.7: "a `fuel_discount_cents_per_gal` equal to 5 cents for each full 500-point step of the season total, capped at 50 cents per gallon, a `feed_coupon_cents` of 1000 cents when the store's posture is `FALL_FEED` and the account's tier is `RANCH_HAND` or `HOMESTEAD` (0 otherwise), and an `eligible` flag that is true when either the fuel discount or the feed coupon is greater than zero."
    PRD §3.7: "the `points_delta` is the base points multiplied by both multipliers, rounded half-up to an integer."

    Design: Corner/calculations/fuel_offer_rounds_down_partial_steps
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="FALL_FEED", name="Fall Store")
    account = create_account()

    # 200 + 400 + floor(199.99) x 2 = 200 + 400 + 398 = 998 posture-season
    # points (PRD §3.7: base points are base_amount_cents / 100 rounded DOWN
    # before the x2 posture multiplier applies).
    accrue_points(account, store, 10000, earn_context="FEED")
    accrue_points(account, store, 20000, earn_context="FEED")
    accrue_points(account, store, 19999, earn_context="FEED")

    offer = validate_success(
        api.get_loyalty_offers(account["id"], ASSOC, params={"store_id": store["id"]})
    )
    assert offer["season_qualifying_points"] == 998
    assert offer["fuel_discount_cents_per_gal"] == 5  # one full step only
    assert offer["feed_coupon_cents"] == 0  # tier still NEIGHBOR
    assert offer["eligible"] is True


def test_weighted_finalize_redeem_points_capped_at_zero_floor(api):
    """PRD §3.6: "Each point is worth one cent of discount: the `final_total_cents` is the computed price minus the redeemed points, floored at zero"
    PRD §3.6: "Two ledger writes follow atomically when an account is attached: a `REDEMPTION` entry debiting the redeemed points (recorded on the sale as `points_redeemed`), and an `ACCRUAL` entry on the net-of-redemption amount"
    PRD §3.7: "Every entry records `counts_toward_tier` — true for `ACCRUAL` and `REVERSAL`, false for `REDEMPTION` and `ADJUSTMENT`"

    Design: Corner/calculations/weighted_finalize_redeem_points_capped_at_zero_floor
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING", name="Winter Store")
    account = create_account_with_points(store, 5000)

    sale = create_provisional_sale(
        store, gross_weight_lbs=100, loyalty_account_id=account["id"]
    )
    finalized = validate_success(
        api.finalize_weighted_sale(
            sale["id"], {"measured_tare_lbs": 20, "redeem_points": 5000}, ASSOC
        )
    )
    # Raw price 2700; redemption 5000 floors the final at 0.
    assert finalized["final_total_cents"] == 0
    assert finalized["points_redeemed"] == 5000

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["points_balance"] == 0
    # The REDEMPTION does not count toward tier; the accrual on a 0-cent net
    # posts 0 points, so qualifying stays 5000 -> RANCH_HAND.
    assert acct["tier"] == "RANCH_HAND"
    assert acct["tier_qualifying_points"] == 5000


def test_tare_exceeds_gross_rejected_at_finalize(api):
    """PRD §3.6: "recording the `measured_tare_lbs` — the actual container weight, which must be greater than 0 and no greater than the `gross_weight_lbs`, failing otherwise with `ERR_TARE_EXCEEDS_GROSS`."

    Design: Corner/errors/tare_exceeds_gross_rejected_at_finalize
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    sale = create_provisional_sale(store, gross_weight_lbs=20)

    resp = api.finalize_weighted_sale(sale["id"], {"measured_tare_lbs": 25}, ASSOC)
    validate_error(resp, ApiErrorId.ERR_TARE_EXCEEDS_GROSS)

    sale_after = validate_success(api.get_weighted_sale(sale["id"], ASSOC))
    assert sale_after["status"] == "PROVISIONAL"

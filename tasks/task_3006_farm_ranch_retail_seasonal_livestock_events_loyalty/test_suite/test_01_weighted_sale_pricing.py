"""Weighted-sale provisional-vs-final pricing and propane gallon math."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accrue_points,
    create_account,
    create_open_store,
    create_provisional_sale,
    create_weighted_sale_payload,
    set_clock,
    validate_error,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FALL_NOW = "2026-09-20T10:00:00Z"


def test_weighted_sale_provisional_vs_final_tare_pricing_variants_diverge(api):
    """PRD §3.6: "The `provisional_tare_lbs` comes from the standard class table — 2 pounds for `BAG_50`, 20 for `DRUM`, 60 for `TOTE`, 17 for `CYLINDER_20` — and the net weight is the gross minus that standard tare."
    PRD §3.6: "For `FEED_BULK`, the net pounds price through marginal tiers at per-pound cent rates: the first 50 pounds at 40 cents per pound, the next 150 pounds at 35 cents per pound, and everything beyond 200 pounds at 30 cents per pound, summed across tiers."
    PRD §3.6: "The final price uses the identical tier structure as the provisional price but with the net weight computed from the measured tare, so identical gross weights can price differently once the true tare is known."

    Design: Difficulty/dual_variant_calc/weighted_sale_provisional_vs_final_tare_pricing
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="FALL_FEED")

    sale = validate_success(
        api.create_weighted_sale(
            create_weighted_sale_payload(store["id"], gross_weight_lbs=320), ASSOC
        ),
        expected_status=201,
    )
    assert sale["status"] == "PROVISIONAL"
    # Provisional variant: class-table tare 20 -> net 300 -> 2000+5250+3000.
    assert sale["provisional_tare_lbs"] == 20
    assert sale["provisional_total_cents"] == 10250

    finalized = validate_success(
        api.finalize_weighted_sale(sale["id"], {"measured_tare_lbs": 15}, ASSOC)
    )
    # Final variant: measured tare 15 -> net 305 -> 2000+5250+3150.
    assert finalized["final_total_cents"] == 10400
    assert finalized["final_total_cents"] != sale["provisional_total_cents"], (
        "provisional and final variants must diverge once a measured tare is known"
    )
    assert finalized["status"] == "FINALIZED"


def test_weighted_sale_final_variant_uses_measured_tare_for_net(api):
    """PRD §3.6: "The final price uses the identical tier structure as the provisional price but with the net weight computed from the measured tare"
    PRD §3.6: "The evaluation order is pinned: first the net weight, then the tier-or-gallon price, then the rounding to integer cents, then the point-redemption subtraction."

    Design: Difficulty/dual_variant_calc/weighted_sale_provisional_vs_final_tare_pricing
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")

    sale = validate_success(
        api.create_weighted_sale(
            create_weighted_sale_payload(store["id"], gross_weight_lbs=100), ASSOC
        ),
        expected_status=201,
    )
    # Provisional: net 100 - 20 = 80 -> 50x40 + 30x35 = 3050.
    assert sale["provisional_total_cents"] == 3050

    finalized = validate_success(
        api.finalize_weighted_sale(sale["id"], {"measured_tare_lbs": 30}, ASSOC)
    )
    # Final: net 100 - 30 = 70 -> 50x40 + 20x35 = 2700.
    assert finalized["final_total_cents"] == 2700


def test_propane_price_gallon_cap_and_rounding_under_cap(api):
    """PRD §3.6: "For `PROPANE_EXCHANGE`, the dispensed gallons are the net pounds divided by 4.24 pounds per gallon, capped at 20.0 gallons and rounded half-up to 2 decimal places; the price is a flat 1999 cents for the exchange plus the gallons multiplied by 349 cents per gallon, rounded half-up."

    Design: Difficulty/combinatorial_formula/propane_price_nested_min_gallon_cap_and_rounding
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")

    sale = validate_success(
        api.create_weighted_sale(
            create_weighted_sale_payload(
                store["id"],
                sale_kind="PROPANE_EXCHANGE",
                container_class="CYLINDER_20",
                gross_weight_lbs=37,
            ),
            ASSOC,
        ),
        expected_status=201,
    )
    # net = 37 - 17 = 20; gallons = round(20/4.24, 2) = 4.72 (< 20.0 cap).
    assert sale["propane_gallons"] == pytest.approx(4.72)
    assert sale["provisional_total_cents"] == 3646  # 1999 + round(4.72*349)


def test_propane_price_gallon_cap_saturates_at_twenty(api):
    """PRD §3.6: "For `PROPANE_EXCHANGE`, the dispensed gallons are the net pounds divided by 4.24 pounds per gallon, capped at 20.0 gallons and rounded half-up to 2 decimal places; the price is a flat 1999 cents for the exchange plus the gallons multiplied by 349 cents per gallon, rounded half-up."

    Design: Difficulty/combinatorial_formula/propane_price_nested_min_gallon_cap_and_rounding
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")

    sale = validate_success(
        api.create_weighted_sale(
            create_weighted_sale_payload(
                store["id"],
                sale_kind="PROPANE_EXCHANGE",
                container_class="CYLINDER_20",
                gross_weight_lbs=107,
            ),
            ASSOC,
        ),
        expected_status=201,
    )
    # net = 107 - 17 = 90; 90/4.24 = 21.22... capped at 20.0.
    assert sale["propane_gallons"] == pytest.approx(20.0)
    assert sale["provisional_total_cents"] == 8979  # 1999 + 20.0*349

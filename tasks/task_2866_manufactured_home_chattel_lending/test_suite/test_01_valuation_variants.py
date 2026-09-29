"""The two variants of the guide walk on one unit and one guide (PRD §3.3).

The same 1440 sqft MULTI_WIDE on an executed community lot values differently
depending only on ``variant``: the origination walk keeps the flat installation
credit and takes no haircut, while the recovery walk drops that credit to zero
and subtracts the forced-sale discount.
"""

from test_helpers import (
    assert_valuation,
    assert_valuation_breakdown,
    fixtures,
)

CLOCK = "2026-08-01T00:00:00Z"

# The guide walk on a 1440 sqft MULTI_WIDE of model year 2018 valued in 2026:
# eight years of age at 350 bps is 2800 bps of depreciation, so 7200 bps of
# guide value survives 1440 * 4500 * 11500 bps.
BOOK_BASE_CENTS = 5365440
# GOOD is exactly zero; COMMUNITY_WITH_AGREEMENT is a credit of 300 bps.
CONDITION_ADJUSTMENT_CENTS = 0
LOCATION_ADJUSTMENT_CENTS = 160963
PIER_INSTALLATION_CENTS = 250000
ORIGINATION_CERTIFIED_CENTS = 5776403
RECOVERY_FORCED_SALE_DISCOUNT_CENTS = 1215809
RECOVERY_CERTIFIED_CENTS = 4310594
VARIANT_DELTA_CENTS = 1465809


def _community_collateral_with_certified_origination(api):
    """Guide, community with an executed agreement, unit on lot A-14, valued."""
    scenario = fixtures.setup_community_collateral(
        api, clock=CLOCK, agreement="EXECUTED"
    )
    scenario["valuation"] = fixtures.create_certified_valuation(
        api, scenario["unit"]["id"], scenario["guide"]["id"], "ORIGINATION"
    )
    return scenario


def _recovery_liquidation_valuation(api, scenario):
    """A second valuation of the same unit and guide on the liquidation walk."""
    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    return fixtures.create_valuation(
        api,
        scenario["unit"]["id"],
        scenario["guide"]["id"],
        unit["version"],
        "RECOVERY_LIQUIDATION",
        fixtures.RECOVERY,
    )


def test_origination_variant_keeps_installation_credit_and_takes_no_haircut(api):
    """PRD §3.3: "The `installation_adjustment_cents` figure is not proportional
    at all — on the `ORIGINATION` variant it is a flat 850,000 cents for a unit
    on a `PERMANENT_FOUNDATION` and a flat 250,000 cents for a unit on
    `PIER_AND_ANCHOR`, and on the `RECOVERY_LIQUIDATION` variant it is dropped
    entirely and recorded as zero."
    PRD §3.3: "On the `ORIGINATION` variant, both liquidation deductions are
    recorded as zero — `forced_sale_discount_cents` is 0 and
    `detach_and_move_cost_cents` is 0 — and `certified_value_cents` is the
    adjusted subtotal exactly as computed."

    Design: Difficulty/dual_variant_calc/valuation_origination_vs_recovery_liquidation_on_one_unit
    """
    scenario = _community_collateral_with_certified_origination(api)
    valuation = scenario["valuation"]

    assert_valuation(valuation)
    assert valuation["variant"] == "ORIGINATION"
    assert valuation["location_key"] == "COMMUNITY_WITH_AGREEMENT"
    assert_valuation_breakdown(
        valuation,
        book_base_cents=BOOK_BASE_CENTS,
        condition_adjustment_cents=CONDITION_ADJUSTMENT_CENTS,
        location_adjustment_cents=LOCATION_ADJUSTMENT_CENTS,
        installation_adjustment_cents=PIER_INSTALLATION_CENTS,
        forced_sale_discount_cents=0,
        detach_and_move_cost_cents=0,
        certified_value_cents=ORIGINATION_CERTIFIED_CENTS,
    )


def test_recovery_liquidation_variant_drops_installation_and_discounts_subtotal(api):
    """PRD §3.3: "On the `RECOVERY_LIQUIDATION` variant, two deductions apply.
    The `forced_sale_discount_cents` figure is the adjusted subtotal multiplied
    by 2200 basis points divided by ten thousand, rounded half up — the haircut
    a forced sale takes."
    PRD §3.3: "The `detach_and_move_cost_cents` figure is a flat 675,000 cents
    when, and only when, `location_key` is `COMMUNITY_WITHOUT_AGREEMENT`; on
    private land, or in a community whose operator agreement is executed, it is
    zero, because in those cases the unit can be sold where it stands rather
    than detached and hauled away."

    Design: Difficulty/dual_variant_calc/valuation_origination_vs_recovery_liquidation_on_one_unit
    """
    scenario = _community_collateral_with_certified_origination(api)
    recovery = _recovery_liquidation_valuation(api, scenario)

    assert_valuation(recovery)
    assert recovery["variant"] == "RECOVERY_LIQUIDATION"
    assert recovery["location_key"] == "COMMUNITY_WITH_AGREEMENT"
    assert_valuation_breakdown(
        recovery,
        book_base_cents=BOOK_BASE_CENTS,
        condition_adjustment_cents=CONDITION_ADJUSTMENT_CENTS,
        location_adjustment_cents=LOCATION_ADJUSTMENT_CENTS,
        installation_adjustment_cents=0,
        forced_sale_discount_cents=RECOVERY_FORCED_SALE_DISCOUNT_CENTS,
        detach_and_move_cost_cents=0,
        certified_value_cents=RECOVERY_CERTIFIED_CENTS,
    )


def test_recovery_valuation_of_other_variant_leaves_certified_origination_standing(api):
    """PRD §3.3: "It moves any earlier `CERTIFIED` valuation of the same unit and
    the same variant to `SUPERSEDED` — which is precisely why the stale-version
    guard of §2.9 exists on this write, and why `ERR_STALE_UNIT_VERSION` is
    returned when `expected_unit_version` does not match."
    PRD §3.3: "And it leaves the new valuation in `status` `DRAFT`, with
    `certified_by_user_id` and `certified_at` both null."

    Design: Difficulty/dual_variant_calc/valuation_origination_vs_recovery_liquidation_on_one_unit
    """
    scenario = _community_collateral_with_certified_origination(api)
    origination_id = scenario["valuation"]["id"]
    recovery = _recovery_liquidation_valuation(api, scenario)

    assert recovery["status"] == "DRAFT"
    assert recovery["certified_by_user_id"] is None
    assert recovery["certified_at"] is None

    origination = fixtures.read_valuation(api, origination_id)
    assert origination["status"] == "CERTIFIED", (
        "a valuation of a different variant must not supersede the certified "
        "origination valuation of the same unit"
    )
    delta = (
        origination["certified_value_cents"] - recovery["certified_value_cents"]
    )
    assert delta == VARIANT_DELTA_CENTS, (
        f"the two variants must differ by {VARIANT_DELTA_CENTS} cents, got {delta}"
    )

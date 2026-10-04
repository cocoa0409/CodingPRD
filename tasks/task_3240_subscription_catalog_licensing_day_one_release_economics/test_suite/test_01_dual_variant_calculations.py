"""Day-one cannibalisation: the provisional and reconciled readings of the same
projection are two legitimate algorithms over different domains.

The provisional figure is forward-looking, derived from the projection's own
unit count and the title's regional list price. The reconciled figure is
chronological, accumulated from the purchases that actually happened.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    scenario_ready_to_finalize,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_projection_cannibalized_figure_turns_chronological_on_finalize(api):
    """PRD §3.9: "the gross projected sales are the projection's
    `projected_unit_sales_units` multiplied by that price; and
    `projected_cannibalized_unit_sales_cents` is that gross multiplied by
    0.30, rounded half up to two decimals."
    PRD §3.9: "Instead of projecting cannibalisation from units and price, the
    finalized view accumulates the actual purchase revenue: every `Purchase`
    row for the same title and region whose status is `COMPLETED` is taken in
    ascending `created_at` order, and their `total_charged_cents` are
    accumulated into a running total."

    Design: Difficulty/dual_variant_calc/day_one_cannibalization_provisional_vs_chronological
    """
    sc = scenario_ready_to_finalize(api, purchases=3)

    # The regional list price per unit is 7000.00 * 1.20 == 8400.00; the entry
    # is CATALOG_ADD so no retention bonus applies and the PREMIUM tier's
    # 0.075 discount is 630.00, leaving 7770.00 charged on each purchase.
    for purchase in sc.purchases:
        assert purchase["list_price_cents_per_unit"] == pytest.approx(8400.00, abs=0.01), \
            "the regional list price per unit is the title's list price times the multiplier"
        assert purchase["total_charged_cents"] == pytest.approx(7770.00, abs=0.01), \
            "8400.00 less the 630.00 rounded discount"
        assert purchase["status"] == "COMPLETED"

    accumulator = sum(p["total_charged_cents"] for p in sc.purchases)
    assert accumulator == pytest.approx(23310.00, abs=0.01), \
        "three COMPLETED rows accumulate in ascending created_at order"

    # Before finalization the projection is still forward-looking.
    provisional = validate_success(
        api.get_availability_projection(sc.projection["id"], ADMIN)
    )
    assert provisional["projected_cannibalized_unit_sales_cents"] == \
        pytest.approx(1260000.00, abs=0.01), "500 units at 8400.00 times 0.30"
    assert provisional["projected_unit_sales_units"] == 500
    assert provisional["status"] == "DRAFT"

    finalized = validate_success(
        api.finalize_availability_projection(sc.projection["id"], ANALYST)
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["projected_cannibalized_unit_sales_cents"] == \
        pytest.approx(6993.00, abs=0.01), \
        "the 23310.00 accumulator multiplied once by 0.30 and rounded once"
    assert finalized["projected_cannibalized_unit_sales_cents"] != \
        provisional["projected_cannibalized_unit_sales_cents"], \
        "the two variants disagree on byte-identical catalogue data"


def test_projection_finalize_leaves_the_subscription_upside_unchanged(api):
    """PRD §3.9: "The `projected_net_value_cents` and the decision are then
    re-derived from the new downside figure against the unchanged subscription
    upside, and the difference between the finalized and the provisional
    cannibalised figure is exposed on the response as the provisional-to-final
    delta."

    Design: Difficulty/dual_variant_calc/day_one_cannibalization_provisional_vs_chronological
    """
    sc = scenario_ready_to_finalize(api, purchases=3)

    provisional = validate_success(
        api.get_availability_projection(sc.projection["id"], ADMIN)
    )
    upside = provisional["projected_subscription_value_cents"]
    # Net-new value is the capped 1800000.00 engagement amount times 0.60, and
    # the tier uplift is that amount times 0.05 times the two tier steps.
    assert upside == pytest.approx(1260000.00, abs=0.01)
    assert provisional["projected_net_value_cents"] == pytest.approx(0.00, abs=0.01)

    finalized = validate_success(
        api.finalize_availability_projection(sc.projection["id"], ANALYST)
    )
    assert finalized["projected_subscription_value_cents"] == \
        pytest.approx(upside, abs=0.01), \
        "finalization re-derives the downside only; the upside is unchanged"
    assert finalized["projected_net_value_cents"] == pytest.approx(1253007.00, abs=0.01), \
        "1260000.00 upside less the reconciled 6993.00 downside"
    assert finalized["decision"] == "APPROVE_DAY_ONE"

    reread = validate_success(
        api.get_availability_projection(sc.projection["id"], ADMIN)
    )
    assert reread["status"] == "FINALIZED"
    assert reread["projected_cannibalized_unit_sales_cents"] == \
        finalized["projected_cannibalized_unit_sales_cents"], \
        "a finalized projection keeps its reconciled figure on re-read"
    assert reread["projected_net_value_cents"] == finalized["projected_net_value_cents"]
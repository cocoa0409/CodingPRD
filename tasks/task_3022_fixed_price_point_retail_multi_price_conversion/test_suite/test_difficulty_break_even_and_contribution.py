"""Break-even and net contribution: the convergence and divergence variants of one rule.

Both variants share their inputs and differ only in the shape of the answer, so the
two are exercised side by side on the same price point.
"""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    assert_item,
    assert_item_cost_invariants,
    validate_success,
    fixtures,
)



def _convergence_and_divergence_pair(api):
    """Two items straddling the convergence/divergence branch of `unit_margin_cents`.

    The branch is taken on the UNIT margin, `unit_retail_cents - variable_store_cost_cents`
    (PRD §3.3), so the two items are separated by holding the retail at 125 and the
    variable store cost at 126 on one of them:

      * Item 1001 (CONVERGENCE): retail 125, variable 4 -> unit margin 121 > 0;
        landed 120 -> ceil((120*4 + 6) / 121) == ceil(486/121) == 5.
      * Item 1002 (DIVERGENCE_OR_ZERO_MARGIN): retail 125, variable 126 -> unit margin
        -1 <= 0, so no finite break-even exists and the sentinel zero is pinned.
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    common = {"unit_retail_cents": 125, "units_per_case": 4, "fixed_store_handling_cents": 6}
    margin_one = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="1001", base_landed_cost_cents=120,
        variable_store_cost_cents=4, **common)
    margin_zero = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="1002", base_landed_cost_cents=121,
        variable_store_cost_cents=126, **common)
    return price_point, vendor, margin_one, margin_zero


def test_positive_margin_item_break_even_is_finite_while_the_zero_margin_item_pins_zero(api):
    """A positive unit margin yields a finite break-even; a non-positive one pins the sentinel.

    PRD §3.3: "Break-even is evaluated in a pinned order. The system first computes
    `total_landed_cost_cents` as the item's `landed_cost_cents` multiplied by its
    `units_per_case`, plus its `fixed_store_handling_cents`."
    PRD §3.3: "The second regime is `CONVERGENCE`, and it applies when `unit_margin_cents` is
    strictly greater than zero."
    PRD §3.3: "The third regime is `DIVERGENCE_OR_ZERO_MARGIN`, and it applies when
    `unit_margin_cents` is zero or negative."
    PRD §3.3: "No finite break-even exists at a non-positive unit margin, so the rule pins the
    sentinel value zero — not null, not a negative number, and not an unbounded or infinite
    marker."
    PRD §3.3: "The first is `net_contribution_cents_per_unit`, a signed integer computed as the
    item's `unit_retail_cents` minus its `landed_cost_cents` minus its
    `variable_store_cost_cents`."

    Design: Difficulty/dual_variant_calc/break_even_ceiling_at_zero_unit_margin
    """
    price_point, vendor, margin_one, margin_zero = _convergence_and_divergence_pair(api)

    validate_success(
        fixtures.apply_landed_cost(margin_one["id"], applied_amount_cents=120), 201)
    validate_success(
        fixtures.apply_landed_cost(margin_zero["id"], applied_amount_cents=121), 201)

    one = validate_success(api.get_item(margin_one["id"], ANALYST_HEADERS), 200)
    assert_item(one)
    assert_item_cost_invariants(one)
    # unit margin 121 > 0: ceil((120 * 4 + 6) / (125 - 4)) == ceil(486 / 121) == 5.
    assert one["landed_cost_cents"] == 120
    assert one["net_contribution_cents_per_unit"] == 1
    assert one["break_even_units"] == 5, (
        "a positive unit margin is convergent, so break-even is the exact rational rounded up"
    )

    zero = validate_success(api.get_item(margin_zero["id"], ANALYST_HEADERS), 200)
    assert_item(zero)
    assert_item_cost_invariants(zero)
    # unit margin 125 - 126 == -1 <= 0, so the divergence sentinel is pinned.
    assert zero["landed_cost_cents"] == 121
    assert zero["net_contribution_cents_per_unit"] == -122
    assert zero["break_even_units"] == 0, (
        "a negative unit margin is the divergence regime, where the sentinel zero is pinned"
    )


def test_divergent_item_is_reviewed_for_deletion_and_retention_keeps_the_sentinel(api):
    """A divergent item queues for deletion review; retaining it leaves the sentinel at zero.

    PRD §3.4: "If no such pack exists, the item is pushed automatically from `COST_PENDING` into
    `DELETE_REVIEW` — this transition is reached from the landed-cost write's own side-effect
    chain and is never triggered by a direct client call."
    PRD §3.4: "Choosing `RETAIN` returns the item to `ACTIVE` and retains its `price_point_id`."
    PRD §3.3: "The third regime is `DIVERGENCE_OR_ZERO_MARGIN`, and it applies when
    `unit_margin_cents` is zero or negative."
    PRD §3.3: "No finite break-even exists at a non-positive unit margin, so the rule pins the
    sentinel value zero — not null, not a negative number, and not an unbounded or infinite
    marker."

    Design: Difficulty/dual_variant_calc/break_even_ceiling_at_zero_unit_margin
    """
    price_point, vendor, margin_one, margin_zero = _convergence_and_divergence_pair(api)

    validate_success(fixtures.apply_landed_cost(margin_one["id"], applied_amount_cents=120), 201)
    validate_success(fixtures.apply_landed_cost(margin_zero["id"], applied_amount_cents=121), 201)

    assert validate_success(
        api.get_item(margin_one["id"], ANALYST_HEADERS), 200)["status"] == "COST_PENDING"
    assert validate_success(
        api.get_item(margin_zero["id"], ANALYST_HEADERS), 200)["status"] == "DELETE_REVIEW", (
        "a divergent (non-positive unit margin) item with no curing pack queues for deletion review"
    )

    retained = validate_success(
        api.decide_item_deletion(margin_zero["id"], "RETAIN", BUYER_HEADERS), 200)
    assert retained["status"] == "ACTIVE"
    assert retained["price_point_id"] == price_point["id"], (
        "retention keeps the item on its price point"
    )
    assert retained["landed_cost_cents"] == 121
    assert retained["net_contribution_cents_per_unit"] == -122
    assert retained["break_even_units"] == 0, (
        "the divergence sentinel survives the return to ACTIVE: the unit margin is still negative"
    )
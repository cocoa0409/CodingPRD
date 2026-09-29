"""
Formulas whose answer depends on which input the tier reads and on where the
rounding happens, rather than on the arithmetic itself.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    CapacityPosture,
    LotStatus,
    SeriesStatus,
    approx2,
    fixtures,
    validate_success,
)


def _series_priced_at_9720(api):
    """A single-site STAGE_1 series holding two 108-plot entries at 45.00 per plot."""
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Cost Pin"}
    )
    line_a = fixtures.create_line(
        api, program_id, objective_id, designation="SX-2001", seed_inventory_g=100000
    )
    line_b = fixtures.create_line(
        api, program_id, objective_id, designation="SX-2002", seed_inventory_g=100000
    )
    site = fixtures.create_site(
        api, site_code="CP1", environment_class="RAINFED_TEMPERATE",
        total_plot_capacity=300, plot_cost_usd=45.00,
    )
    series = fixtures.create_series(api, program_id, min_locations=1)
    fixtures.create_entry(api, series["id"], line_a["id"], site["id"], plot_count=108)
    fixtures.create_entry(api, series["id"], line_b["id"], site["id"], plot_count=108)
    return program_id, series["id"], site["id"]


def test_management_fee_tier_reads_the_pre_fee_subtotal(api):
    """
    A subtotal of 9720.00 selects the 0.12 rate even though the resulting total
    of 10886.40 sits above the 10000.00 tier boundary.

    PRD 3.6: "Second, a management tier is selected from that subtotal **and from
    nothing else**: the rate is 0.12 when `plot_cost_subtotal_usd` is strictly
    below 10000.00, 0.09 when it is strictly below 50000.00, and 0.07
    otherwise."
    PRD 3.6: "The dependency here looks circular — the total is the subtotal plus
    the fee, while the fee depends on a tier — and it is resolved by fixing the
    tier input to the pre-fee subtotal, never to the total."

    Design: Difficulty/combinatorial_formula/mgmt_fee_tier_pinned_to_pre_fee_subtotal_not_to_total
    """
    _program_id, series_id, _site_id = _series_priced_at_9720(api)

    series = validate_success(api.plant_series(series_id, AGRONOMIST_HEADERS))
    assert series["status"] == SeriesStatus.PLANTED
    # 108 * 45.00 twice.
    assert series["plot_cost_subtotal_usd"] == approx2(9720.00)
    assert series["management_fee_usd"] == approx2(1166.40)
    assert series["total_trial_cost_usd"] == approx2(10886.40)
    # Tiering off the post-fee total would have charged 0.09 and produced this.
    assert series["total_trial_cost_usd"] != approx2(10594.80)


def test_priced_total_lands_on_the_programme_and_leaves_the_site_open(api):
    """
    The stored total is what the programme commits, and the two entries sharing
    one window make a daily peak of 216 plots against a 300-plot capacity.

    PRD 3.6: "When the test passes, the series moves `PLANNING → PLANTED`, the
    three cost fields are stored, the programme's `committed_budget_usd` rises by
    `total_trial_cost_usd`, and every entry of the series still in `status`
    `ENTERED` is cascaded `ENTERED → PLANTED` in `created_at` ascending order."
    PRD 3.5: "`capacity_posture` reads `FROZEN` when utilisation is 1.00 or
    greater, `RESTRICTED` when utilisation is 0.85 or greater but below 1.00, and
    `OPEN` otherwise; a site sitting exactly at 0.85 is therefore `RESTRICTED`
    and a site sitting exactly at 1.00 is `FROZEN`."

    Design: Difficulty/combinatorial_formula/mgmt_fee_tier_pinned_to_pre_fee_subtotal_not_to_total
    """
    program_id, series_id, site_id = _series_priced_at_9720(api)
    fixtures.plant_series(api, series_id)

    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_budget_usd"] == approx2(10886.40)

    site = validate_success(api.get_site(site_id, AGRONOMIST_HEADERS))
    assert site["peak_committed_plot_count"] == 216
    assert site["available_plot_count"] == 84
    assert site["capacity_posture"] == CapacityPosture.OPEN


def test_bag_plan_ceils_each_allocation_before_summing(api):
    """
    Demands of 4000, 9000 and 1300 kg round up to 173, 389 and 57 bags, so the
    plan is 619 rather than the 618 a sum-then-round order would give.

    PRD 3.9: "For each element of `market_allocations` the server inflates that
    market's `demand_kg` by a seed loss allowance of eight percent — multiplying
    it by one plus 0.08 — divides the result by the 25-kilogram commercial bag
    size, and rounds **that quotient up** to the next whole bag."
    PRD 3.9: "Rounding up per allocation and only then summing is the required
    order: summing the demand first and rounding once produces a smaller, wrong
    bag count."

    Design: Difficulty/combinatorial_formula/seed_bags_ceiled_per_allocation_then_summed
    """
    net = fixtures.line_with_reserved_lot(api)

    lot = validate_success(api.get_lot(net.lot_id, PLANNER_HEADERS))
    assert lot["planned_units_bags"] == 619
    assert lot["planned_units_bags"] != 618
    assert lot["status"] == LotStatus.RESERVED
    assert lot["hold_reason"] is None


def test_parent_seed_requirement_is_ceiled_once_at_the_end(api):
    """
    619 bags of 25 kg become 386875 g of parent seed after the single closing
    ceiling, and that figure is what the line debits.

    PRD 3.9: "Next the parent seed requirement: `allocated_seed_g` is
    `planned_units_bags` multiplied by 25 kilograms, converted to grams by
    multiplying by 1000, divided by the field multiplication factor of 40 — one
    gram of parent seed yields forty grams in the multiplication field — and
    rounded up once at the end to a whole gram."
    PRD 3.9: "On success the lot is created in `status` `RESERVED` with
    `hold_reason` null, `allocated_seed_g` is debited from the line's
    `seed_inventory_g`, and the line's `reserved_seed_g` and
    `planned_launch_units_bags` together with the programme's
    `pre_commercial_units_bags` are all re-derived."

    Design: Difficulty/combinatorial_formula/seed_bags_ceiled_per_allocation_then_summed
    """
    net = fixtures.line_with_reserved_lot(api)

    lot = validate_success(api.get_lot(net.lot_id, PLANNER_HEADERS))
    assert lot["allocated_seed_g"] == 386875

    line = validate_success(api.get_line(net.line_id, DIRECTOR_HEADERS))
    assert line["seed_inventory_g"] == 113125
    assert line["reserved_seed_g"] == 386875
    assert line["planned_launch_units_bags"] == 619

    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    assert program["pre_commercial_units_bags"] == 619

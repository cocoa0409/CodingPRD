"""Work-order costing: the overhead band and the per-unit standard cost."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U


def _plant_with_two_confirmed_orders(plant):
    """A GOLD/EU distributor, design D3 released, and two confirmed orders."""
    plant.add_distributor()
    payload = F.economy_motor_design_payload()
    plant.add_design(payload)
    plant.release_design()
    eleven = plant.add_order(quantity=11)
    plant.confirm_order(eleven)
    twelve = plant.add_order(quantity=12)
    plant.confirm_order(twelve)
    return payload, eleven, twelve


def test_overhead_band_is_selected_from_the_direct_cost_alone(plant):
    """1375000 direct is STANDARD even though 1677500 standard clears the floor.

    PRD 3.5: "The `overhead_band` is then selected from `direct_cost_cents`
    **alone** — overhead itself is never part of the band input, even though
    overhead is added to reach the standard cost, so the apparent circularity is
    not real."

    Design: Difficulty/combinatorial_formula/work_order_overhead_band_from_direct_cost_only
    """
    payload, eleven, _twelve = _plant_with_two_confirmed_orders(plant)

    work_order = plant.add_work_order(order=eleven, unit_count=11)

    assert work_order["direct_cost_cents"] == 1375000
    assert work_order["overhead_band"] == "STANDARD"
    assert work_order["overhead_cents"] == 302500
    assert work_order["standard_cost_cents"] == 1677500
    assert work_order["standard_cost_cents"] >= 1500000
    assert work_order["overhead_band"] != "COMPLEX"
    A.assert_cost_rollup(work_order, payload, 11)
    assert work_order["actual_cost_cents"] == work_order["standard_cost_cents"]
    assert work_order["cost_variance_cents"] == 0


def test_cost_read_out_divides_the_standard_cost_by_the_unit_count(plant):
    """The read-out's per-unit standard cost is 1677500 over 11 units.

    PRD 3.5: "That last figure — `standard_cost_cents` divided by `unit_count`,
    rounded to whole cents — is computed on read rather than stored on the work
    order, and it is the same quantity that gets pinned onto a warranty claim at
    analysis time."

    Design: Difficulty/combinatorial_formula/work_order_overhead_band_from_direct_cost_only
    """
    payload, eleven, _twelve = _plant_with_two_confirmed_orders(plant)
    work_order = plant.add_work_order(order=eleven, unit_count=11)

    summary = plant.get_cost_summary(work_order)

    A.assert_cost_summary_shape(summary)
    assert summary["work_order_id"] == work_order["id"]
    assert summary["unit_count"] == 11
    assert summary["per_unit_direct_cost_cents"] == 125000
    assert summary["overhead_band"] == "STANDARD"
    assert summary["standard_cost_cents"] == 1677500
    assert summary["unit_standard_cost_cents"] == 152500
    assert summary["rework_reject_count"] == 0
    assert summary["cost_variance_cents"] == 0
    assert summary["unit_standard_cost_cents"] == A.expected_cost_rollup(payload, 11)[
        "unit_standard_cost_cents"
    ]


def test_direct_cost_exactly_at_the_complex_floor_takes_the_complex_rate(plant):
    """Twelve units land on exactly 1500000 cents and must price at 0.31.

    PRD 3.5: "Both thresholds are inclusive lower bounds: a direct cost of
    exactly 1500000 cents is `COMPLEX`, while 1499999 is `STANDARD`."

    Design: Difficulty/boundary_precision_check/direct_cost_exactly_at_complex_band_minimum_selects_complex
    """
    payload, _eleven, twelve = _plant_with_two_confirmed_orders(plant)

    work_order = plant.add_work_order(order=twelve, unit_count=12)

    assert work_order["direct_cost_cents"] == 1500000
    assert work_order["overhead_band"] == "COMPLEX"
    assert work_order["overhead_cents"] == 465000
    assert work_order["standard_cost_cents"] == 1965000
    assert work_order["overhead_cents"] != 330000
    assert work_order["standard_cost_cents"] != 1830000
    A.assert_cost_rollup(work_order, payload, 12)
    summary = plant.get_cost_summary(work_order)
    assert summary["unit_standard_cost_cents"] == 163750


def test_one_unit_below_the_complex_floor_stays_in_the_standard_band(plant):
    """Eleven and twelve units of the same design straddle the inclusive floor.

    PRD 3.5: "A direct cost of at least 4000000 cents lands in `ENGINEERED`;
    otherwise a direct cost of at least 1500000 cents lands in `COMPLEX`;
    otherwise the band is `STANDARD`."

    Design: Difficulty/boundary_precision_check/direct_cost_exactly_at_complex_band_minimum_selects_complex
    """
    _payload, eleven, twelve = _plant_with_two_confirmed_orders(plant)

    boundary = plant.add_work_order(order=twelve, unit_count=12)
    below = plant.add_work_order(order=eleven, unit_count=11)

    assert (boundary["direct_cost_cents"], boundary["overhead_band"]) == (
        1500000,
        "COMPLEX",
    )
    assert (below["direct_cost_cents"], below["overhead_band"]) == (1375000, "STANDARD")
    assert boundary["overhead_cents"] == 465000
    assert below["overhead_cents"] == 302500
    assert plant.get_cost_summary(boundary)["unit_standard_cost_cents"] == 163750
    assert plant.get_cost_summary(below)["unit_standard_cost_cents"] == 152500


def test_a_second_work_order_needs_the_design_version_it_just_bumped(api, plant):
    """Pinning a design advances that design's own version.

    PRD 3.5: "The design's own `version` advances by 1, which is precisely why
    the concurrency guard exists."

    Design: Difficulty/combinatorial_formula/work_order_overhead_band_from_direct_cost_only
    """
    _payload, eleven, twelve = _plant_with_two_confirmed_orders(plant)
    before = plant.get_design()

    first = plant.add_work_order(order=eleven, unit_count=11)
    after = plant.get_design()

    assert after["version"] == before["version"] + 1
    second = validate_success(
        api.create_work_order(
            F.work_order_payload(
                twelve["id"], plant.design["id"], after["version"], unit_count=12
            ),
            U.PRODUCTION_PLANNER,
        ),
        201,
    )
    assert first["pinned_design_revision_index"] == 0
    assert second["pinned_design_revision_index"] == 0
    assert second["direct_cost_cents"] == 1500000

"""Formulas whose result depends on several inputs interacting non-linearly."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import CENTS, assert_charge_assembly, assert_delivery_load
from test_helpers.factories import create_delivery_load_payload
from test_helpers.fixtures import (
    seed_account,
    seed_catalogue,
    seed_confirmed_delivery_context,
    seed_delivery_order,
)
from test_helpers.test_users import make_dispatch_planner_headers

WASHED_STONE = {
    "sku": "AGG-57",
    "name": "#57 Washed Stone",
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 800,
    "shrinkage_factor": 0.10,
    "moisture_pct": 22.5,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
NARROW_LANE_TRUCK = {
    "truck_code": "T-202",
    "axle_class": "TANDEM",
    "max_payload_lb": 12000,
    "bed_capacity_cubic_yards": 14.0,
    "min_driveway_access_class": "CLASS_C",
}
BASE_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}


def _narrow_lane_context(api):
    """A CLASS_B site, a wide-bedded tandem and a 30.00-cubic-yard confirmed order."""
    return seed_confirmed_delivery_context(
        api,
        material=WASHED_STONE,
        price=BASE_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 22.5},
        account={"business_name": "Stonebridge Hardscape", "credit_limit_cents": 5000000},
        lines=(("BULK", 30.0),),
        driveway_access_class="CLASS_B",
        delivery_distance_miles=5.0,
        truck=NARROW_LANE_TRUCK,
    )


class TestTruckFitMinimumOfThreeCeilings:
    """Geometry, legal weight and site access each cap a trip independently."""

    def test_accepted_load_reports_the_driveway_cap_as_the_binding_ceiling(self, api):
        """The advisory ceiling comes from the tightest of the three inputs.

        PRD 3.5: "And the load's advisory `max_allowed_cubic_yards` is the **smallest**
        of three independent ceilings: the truck's `bed_capacity_cubic_yards`, the
        payload headroom, and the driveway cap for the order's access class."

        Design: Difficulty/combinatorial_formula/truck_fit_three_input_minimum_binds_on_driveway_cap
        """
        context = _narrow_lane_context(api)

        assert context["material"]["effective_density_lb_per_cubic_yard"] == pytest.approx(
            860.00, abs=CENTS
        )
        assert context["lot"]["net_sellable_cubic_yards"] == pytest.approx(83.25, abs=CENTS)

        response = api.create_delivery_load(
            create_delivery_load_payload(
                context["order"]["id"],
                context["truck"]["id"],
                12.0,
                "2026-08-02T08:00:00.000Z",
                "2026-08-02T10:00:00.000Z",
            ),
            headers=make_dispatch_planner_headers(),
        )
        load = validate_success(response, 201)

        assert_delivery_load(load)
        assert load["status"] == "PLANNED"
        # 12.00 * 860.00
        assert load["planned_payload_lb"] == 10320
        # MIN(bed 14.00, FLOOR_2DP(12000 / 860.00) = 13.95, CLASS_B cap 12.00)
        assert load["max_allowed_cubic_yards"] == pytest.approx(12.00, abs=CENTS)

    def test_volume_over_the_driveway_cap_is_refused_while_still_under_the_axle_limit(self, api):
        """A legal weight does not buy a trip that the driveway cap forbids.

        PRD 3.5: "Only then does the capacity gate require `planned_cubic_yards` to be at
        most the lesser of the truck's `bed_capacity_cubic_yards` and the driveway cap
        for the order's access class, else `ERR_LOAD_EXCEEDS_TRUCK_CAPACITY`."

        Design: Difficulty/combinatorial_formula/truck_fit_three_input_minimum_binds_on_driveway_cap
        """
        context = _narrow_lane_context(api)
        order_id = context["order"]["id"]
        truck_id = context["truck"]["id"]

        validate_success(
            api.create_delivery_load(
                create_delivery_load_payload(
                    order_id, truck_id, 12.0, "2026-08-02T08:00:00.000Z", "2026-08-02T10:00:00.000Z"
                ),
                headers=make_dispatch_planner_headers(),
            ),
            201,
        )

        # 12.50 * 860.00 == 10750 lb, comfortably under the 12000-lb axle limit
        rejected = api.create_delivery_load(
            create_delivery_load_payload(
                order_id, truck_id, 12.5, "2026-08-03T08:00:00.000Z", "2026-08-03T10:00:00.000Z"
            ),
            headers=make_dispatch_planner_headers(),
        )
        validate_error(rejected, ApiErrorId.LOAD_EXCEEDS_TRUCK_CAPACITY.value, 422)

        loads, meta = validate_paginated(
            api.list_delivery_loads(
                headers=make_dispatch_planner_headers(), params={"material_order_id": order_id}
            )
        )
        assert meta["total_count"] == 1
        assert [row["planned_cubic_yards"] for row in loads] == [pytest.approx(12.0, abs=CENTS)]


BLACK_MULCH = {
    "sku": "MULCH-BLACK",
    "name": "Black Dyed Mulch",
    "offered_forms": ["BULK", "BAGGED"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
SURCHARGED_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 3333,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 7.5,
}


def _cedar_context(api):
    """A small three-line CLASS_B order priced off an awkward surcharged row."""
    catalogue = seed_catalogue(
        api,
        material=BLACK_MULCH,
        price=SURCHARGED_PRICE,
        lot={"gross_cubic_yards": 200.0, "moisture_pct_at_intake": 15.0},
    )
    account = seed_account(api, business_name="Cedar Ridge Lawn", credit_limit_cents=5000000)
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 1.5), ("BULK", 2.5), ("BAGGED", 10)),
        driveway_access_class="CLASS_B",
        delivery_distance_miles=12.4,
        delivery_address="9 Cedar Ct",
        confirm=True,
    )
    return {"account": account, **catalogue, **seeded}


class TestPerLineRoundingAndFeeAssembly:
    """Where the rounding happens decides the total, and the fees stack on top."""

    def test_each_bulk_line_rounds_before_the_subtotal_is_summed(self, api):
        """Two lines that round down individually must not be summed first.

        PRD 2.6: "Order pricing in particular extends each line at full precision,
        rounds the line, and only then sums the lines; summing at full precision and
        rounding once at order level is explicitly not the rule and produces different
        totals."

        Design: Difficulty/combinatorial_formula/per_line_rounding_before_summation_with_min_load_fee_and_axle_base
        """
        context = _cedar_context(api)
        lines = {(line["form"], line["quantity"]): line for line in context["lines"]}

        line_a = lines[("BULK", 1.5)]
        line_b = lines[("BULK", 2.5)]
        bagged = lines[("BAGGED", 10)]

        # ROUND_HALF_UP(3333 * 1.075) is a display figure only
        assert line_a["unit_price_cents"] == 3583
        assert line_b["unit_price_cents"] == 3583
        # 1.50 * 3582.975 == 5374.4625
        assert line_a["line_price_cents"] == 5374
        # 2.50 * 3582.975 == 8957.4375
        assert line_b["line_price_cents"] == 8957
        assert bagged["unit_price_cents"] == 899
        assert bagged["line_price_cents"] == 8990
        # 10 * 0.037
        assert bagged["line_volume_cubic_yards"] == pytest.approx(0.37, abs=CENTS)

        order = context["order"]
        # 5374 + 8957, not ROUND_HALF_UP(4.00 * 3582.975) == 14332
        assert order["bulk_subtotal_cents"] == 14331
        assert order["bagged_subtotal_cents"] == 8990
        assert order["volume_discount_pct"] == pytest.approx(0.0, abs=CENTS)
        assert order["volume_discount_cents"] == 0

    def test_minimum_load_fee_and_class_b_axle_base_build_the_quoted_total(self, api):
        """The small discounted bulk figure earns the fee, and CLASS_B caps the axle base.

        PRD 3.4: "Step seven sets `delivery_fee_cents` to 0 for a `WILL_CALL` order, and
        otherwise to the axle base for the applicable axle class plus
        `delivery_distance_miles` multiplied by four dollars twenty-five cents per mile,
        that per-mile term being rounded half up to whole cents before it is added."

        Design: Difficulty/combinatorial_formula/per_line_rounding_before_summation_with_min_load_fee_and_axle_base
        """
        order = _cedar_context(api)["order"]

        assert order["fulfillment_status"] == "CONFIRMED"
        assert order["bulk_subtotal_cents"] == 14331
        # the discounted bulk figure sits below the 25000-cent minimum-load threshold
        assert order["min_load_fee_cents"] == 7500
        # TANDEM base 9500 + ROUND_HALF_UP(12.4 * 425)
        assert order["delivery_fee_cents"] == 14770
        assert order["quoted_total_cents"] == 45591
        assert order["final_total_cents"] is None
        assert_charge_assembly(order, 45591)

"""Values sitting exactly on a threshold, and their neighbours one tick away."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    CENTS,
    assert_charge_assembly,
    assert_container_return,
    assert_deposit_fully_resolved,
    assert_instant_equals,
)
from test_helpers.factories import create_delivery_load_payload
from test_helpers.fixtures import (
    advance_clock,
    find_container_return,
    read_account,
    read_container_return,
    read_lot,
    read_order,
    receive_containers,
    seed_account,
    seed_catalogue,
    seed_confirmed_delivery_context,
    seed_delivery_order,
    seed_fulfilled_delivery_order,
    seed_planned_load,
)
from test_helpers.test_users import make_contractor_headers, make_dispatch_planner_headers

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
DAMP_SOIL = {
    "sku": "SOIL-WET",
    "name": "Damp Screened Soil",
    "offered_forms": ["BULK"],
    "seasonal_category": "SOIL",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 20.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
EXACT_PAYLOAD_TRUCK = {
    "truck_code": "T-808",
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 10500,
    "bed_capacity_cubic_yards": 15.0,
    "min_driveway_access_class": "CLASS_C",
}


def _boundary_grading_context(api):
    """A 20.00-cubic-yard CLASS_A order and a truck rated at exactly 10500 lb."""
    context = seed_confirmed_delivery_context(
        api,
        material=DAMP_SOIL,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 20.0},
        account={"business_name": "Boundary Grading LLC", "credit_limit_cents": 5000000},
        lines=(("BULK", 20.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        truck=EXACT_PAYLOAD_TRUCK,
    )
    context["load"] = seed_planned_load(
        api,
        context["order"]["id"],
        context["truck"]["id"],
        10.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T12:00:00.000Z",
    )
    return context


class TestAxlePayloadEqualityBoundary:
    """One hundredth of a cubic yard decides whether the rig is road legal."""

    def test_a_load_weighing_exactly_the_axle_limit_is_accepted(self, api):
        """Equality is legal, and the advisory ceiling lands on the same figure.

        PRD 3.5: "Payload headroom is the truck's `max_payload_lb` divided by the
        effective density, **truncated downward** to two decimal places rather than
        rounded, so that a rounding-up can never authorise an overweight load."

        Design: Difficulty/boundary_precision_check/axle_payload_equality_accepted_and_one_hundredth_rejected
        """
        context = _boundary_grading_context(api)

        # ROUND_HALF_UP(1000 * 1.05, 2)
        assert context["material"]["effective_density_lb_per_cubic_yard"] == pytest.approx(
            1050.00, abs=CENTS
        )
        # ROUND_HALF_UP(100.00 * 0.90 * 0.95, 2)
        assert context["lot"]["net_sellable_cubic_yards"] == pytest.approx(85.50, abs=CENTS)

        load = context["load"]
        assert load["status"] == "PLANNED"
        # 10.00 * 1050.00, exactly equal to the truck's 10500-lb rating
        assert load["planned_payload_lb"] == 10500
        # FLOOR_2DP(10500 / 1050.00) binds below bed 15.00 and the CLASS_A cap of 999.00
        assert load["max_allowed_cubic_yards"] == pytest.approx(10.00, abs=CENTS)

    def test_one_hundredth_of_a_cubic_yard_more_rounds_up_over_the_limit(self, api):
        """10.005 pounds of excess becomes a whole pound once rounding is applied.

        PRD 3.5: "The weight gate requires `planned_payload_lb` to be at most the truck's
        `max_payload_lb`, with exact equality legal, else
        `ERR_AXLE_WEIGHT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/axle_payload_equality_accepted_and_one_hundredth_rejected
        """
        context = _boundary_grading_context(api)
        order_id = context["order"]["id"]

        # ROUND_HALF_UP(10.01 * 1050.00) == 10511, and the weight gate is checked before
        # the order-balance gate lower down the ladder
        rejected = api.create_delivery_load(
            create_delivery_load_payload(
                order_id,
                context["truck"]["id"],
                10.01,
                "2026-08-04T08:00:00.000Z",
                "2026-08-04T12:00:00.000Z",
            ),
            headers=make_dispatch_planner_headers(),
        )
        validate_error(rejected, ApiErrorId.AXLE_WEIGHT_LIMIT_EXCEEDED.value, 422)

        loads, meta = validate_paginated(
            api.list_delivery_loads(
                headers=make_dispatch_planner_headers(), params={"material_order_id": order_id}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in loads] == [context["load"]["id"]]


CEDAR_MULCH = {
    "sku": "MULCH-CEDAR",
    "name": "Cedar Mulch",
    "offered_forms": ["BULK", "BAGGED"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
PALLET_TRUCK = {
    "truck_code": "T-909",
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 20000,
    "bed_capacity_cubic_yards": 15.0,
    "min_driveway_access_class": "CLASS_C",
}
GRACE_DAY = "2026-08-31T00:00:00.000Z"
ONE_SECOND_LATE = "2026-08-31T00:00:01.000Z"


def _cedar_ridge_carriers_out(api):
    """Two pallets issued on 2026-08-01 with the clock parked on the grace day."""
    context = seed_fulfilled_delivery_order(
        api,
        material=CEDAR_MULCH,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Cedar Ridge Gardens", "credit_limit_cents": 5000000},
        lines=(("BULK", 5.0), ("BAGGED", 60)),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        truck=PALLET_TRUCK,
        window_start="2026-08-01T08:00:00.000Z",
        window_end="2026-08-01T12:00:00.000Z",
        driveway_protection_used=True,
        dispatcher_user_id="planner-6",
    )
    context["container_return"] = find_container_return(api, context["order"]["id"])
    advance_clock(api, GRACE_DAY)
    return context


class TestContainerDepositGraceBoundary:
    """A pallet handed in on the grace day and its twin handed in a second later."""

    def test_a_return_on_the_exact_grace_day_earns_the_undecayed_deposit(self, api):
        """Thirty days to the second is still inside the window.

        PRD 3.8: "Its `issued_count` is strictly positive, and how it is arrived at depends
        on the path: on the delivery path it is the total bagged `quantity` across the
        order divided by the yard's forty-eight bags per container and rounded up to a
        whole container, while on the will-call path it is the `pallet_count` the loader
        recorded when handing the carriers over."

        PRD 3.8: "The grace boundary is exact: a return arriving at precisely thirty days
        after `issued_at` earns the full multiplier of 1.00, while one arriving a single
        second later earns 0.75."

        Design: Difficulty/boundary_precision_check/container_deposit_refund_at_exact_grace_day_versus_one_second_later
        """
        context = _cedar_ridge_carriers_out(api)
        account_id = context["account"]["id"]

        order = read_order(api, context["order"]["id"])
        # bulk 10000 + bagged 53940 + minimum-load fee 7500 + TRI_AXLE base 13500
        assert order["quoted_total_cents"] == 84940
        assert_charge_assembly(order, 84940)

        bagged = [line for line in context["lines"] if line["form"] == "BAGGED"][0]
        # ROUND_HALF_UP(60 * 0.037, 2)
        assert bagged["line_volume_cubic_yards"] == pytest.approx(2.22, abs=CENTS)

        record = context["container_return"]
        assert_container_return(record)
        assert record["container_type"] == "PALLET"
        # CEIL(60 / 48)
        assert record["issued_count"] == 2
        assert record["deposit_per_unit_cents"] == 2500
        assert_instant_equals(record["issued_at"], "2026-08-01T00:00:00.000Z")
        assert record["status"] == "OUTSTANDING"
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 5000

        received = receive_containers(api, record["id"], 1, "loader-2")
        assert received["returned_count"] == 1
        # exactly thirty days out, so the multiplier is 1.00 and the whole 2500 comes back
        assert received["refund_cents"] == 2500
        assert received["forfeited_cents"] == 0
        assert received["status"] == "PARTIALLY_RETURNED"
        assert_instant_equals(received["last_received_at"], GRACE_DAY)
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 2500

    def test_the_second_pallet_one_second_late_loses_a_quarter_of_its_deposit(self, api):
        """One second past the grace window is rounded up into a whole week late.

        PRD 3.8: "The refund earned by this visit is the request's `returned_count`
        multiplied by `deposit_per_unit_cents` multiplied by that multiplier, rounded half
        up to whole cents, and it is **added** to the running `refund_cents`; refunds
        accumulate across visits and each visit is decayed by the lateness at the time of
        that visit."

        PRD 3.8: "Where a receive brings the cumulative `returned_count` to exactly
        `issued_count`, the record closes -- the `OUTSTANDING -> CLOSED` step and the
        `PARTIALLY_RETURNED -> CLOSED` step being identical in effect -- and
        `forfeited_cents` is written for the first time as `issued_count` multiplied by
        `deposit_per_unit_cents` minus the accumulated `refund_cents`."

        Design: Difficulty/boundary_precision_check/container_deposit_refund_at_exact_grace_day_versus_one_second_later
        """
        context = _cedar_ridge_carriers_out(api)
        account_id = context["account"]["id"]
        record_id = context["container_return"]["id"]

        receive_containers(api, record_id, 1, "loader-2")
        advance_clock(api, ONE_SECOND_LATE)
        closed = receive_containers(api, record_id, 1, "loader-2")

        assert closed["returned_count"] == 2
        # 2500 already banked plus ROUND_HALF_UP(2500 * 0.75) for the late carrier
        assert closed["refund_cents"] == 4375
        assert closed["status"] == "CLOSED"
        # 2 * 2500 - 4375
        assert closed["forfeited_cents"] == 625
        assert_deposit_fully_resolved(closed)
        assert_instant_equals(closed["last_received_at"], ONE_SECOND_LATE)

        assert read_container_return(api, record_id)["status"] == "CLOSED"
        assert read_account(api, account_id)["pallet_deposit_balance_cents"] == 0


BASE_AGGREGATE = {
    "sku": "AGG-BASE",
    "name": "Crushed Base Aggregate",
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}


def _threshold_paving_confirmed(api):
    """One account, two orders straddling the minimum-load threshold, both confirmed."""
    catalogue = seed_catalogue(
        api,
        material=BASE_AGGREGATE,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(api, business_name="Threshold Paving", credit_limit_cents=5000000)
    headers = make_contractor_headers(account["id"])

    orders = []
    for quantity in (12.5, 12.49):
        seeded = seed_delivery_order(
            api,
            account,
            material_id,
            lines=(("BULK", quantity),),
            driveway_access_class="CLASS_A",
            delivery_distance_miles=0.0,
            delivery_address="1 Threshold Way",
        )
        orders.append(seeded["order"])

    confirmed = [
        validate_success(api.confirm_material_order(order["id"], headers=headers), 200)
        for order in orders
    ]
    return {"account": account, "lot": catalogue["lot"], "on_the_mark": confirmed[0], "short": confirmed[1]}


class TestMinimumLoadFeeThreshold:
    """Twenty cents less material buys a seventy-five-dollar fee."""

    def test_bulk_business_exactly_on_the_threshold_is_exempt_from_the_fee(self, api):
        """The threshold is half-open, so landing on it is above it.

        PRD 3.4: "Step six sets `min_load_fee_cents` to the yard's seventy-five-dollar
        minimum-load fee when all three of the following hold -- the order's
        `fulfillment_mode` is `DELIVERY`, `bulk_subtotal_cents` is greater than zero, and
        the discounted bulk figure from step five is **below** the yard's
        two-hundred-and-fifty-dollar minimum-load threshold -- and to 0 otherwise; a
        `WILL_CALL` order is always exempt from this fee."

        Design: Difficulty/boundary_precision_check/min_load_fee_threshold_exact_versus_one_cent_short
        """
        context = _threshold_paving_confirmed(api)

        on_the_mark = context["on_the_mark"]
        # 12.50 * 2000 lands exactly on the 25000-cent threshold
        assert on_the_mark["bulk_subtotal_cents"] == 25000
        assert on_the_mark["volume_discount_pct"] == pytest.approx(0.0, abs=CENTS)
        assert on_the_mark["volume_discount_cents"] == 0
        assert on_the_mark["min_load_fee_cents"] == 0
        assert on_the_mark["delivery_fee_cents"] == 13500
        assert on_the_mark["quoted_total_cents"] == 38500
        assert_charge_assembly(on_the_mark, 38500)

        short = context["short"]
        # 12.49 * 2000 falls one twenty-cent tick short and pays the whole fee
        assert short["bulk_subtotal_cents"] == 24980
        assert short["min_load_fee_cents"] == 7500
        assert short["delivery_fee_cents"] == 13500
        assert short["quoted_total_cents"] == 45980
        assert_charge_assembly(short, 45980)

        # the cheaper pile costs 7480 cents more: the fee less the 20-cent material saving
        assert short["quoted_total_cents"] - on_the_mark["quoted_total_cents"] == 7480

    def test_both_quotes_roll_up_into_one_credit_position_and_one_reservation(self, api):
        """The non-monotonic pair is booked against the same account and the same pile.

        PRD 3.3: "`credit_used_cents` is the sum, over the account's orders whose
        `fulfillment_status` is `CONFIRMED`, `ALLOCATED` or `FULFILLED` **and** whose
        `settlement_status` is `UNBILLED`, `INVOICED` or `CREDIT_MEMO_ISSUED`, of that
        order's final total where one exists and its quoted total otherwise, minus that
        order's `credit_memo_cents`."

        PRD 3.2: "`reserved_cubic_yards` records what has been promised but not yet
        withdrawn: the sum, over every order line pinned to this lot whose owning order
        sits in `CONFIRMED` or `ALLOCATED`, of that line's `line_volume_cubic_yards` minus
        its `delivered_volume_cubic_yards`, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/min_load_fee_threshold_exact_versus_one_cent_short
        """
        context = _threshold_paving_confirmed(api)

        account = read_account(api, context["account"]["id"])
        # 38500 + 45980
        assert account["credit_used_cents"] == 84480
        assert account["credit_available_cents"] == 5000000 - 84480
        assert account["account_status"] == "ACTIVE"

        lot = read_lot(api, context["lot"]["id"])
        # 12.50 + 12.49
        assert lot["reserved_cubic_yards"] == pytest.approx(24.99, abs=CENTS)
        assert lot["net_sellable_cubic_yards"] == pytest.approx(90.00, abs=CENTS)

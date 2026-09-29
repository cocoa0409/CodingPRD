"""Two overlap rules with opposite conventions, probed at their exact boundaries."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import CENTS, assert_prebuy_contract
from test_helpers.factories import create_delivery_load_payload, create_prebuy_contract_payload
from test_helpers.fixtures import (
    read_order,
    read_prebuy,
    seed_account,
    seed_catalogue,
    seed_confirmed_delivery_context,
    seed_planned_load,
    seed_prebuy,
)
from test_helpers.test_users import make_contractor_headers, make_dispatch_planner_headers

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
DOUBLE_GROUND_MULCH = {
    "sku": "MULCH-DOUBLE",
    "name": "Double Ground Mulch",
    "offered_forms": ["BULK"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
TURNAROUND_TRUCK = {
    "truck_code": "T-333",
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 20000,
    "bed_capacity_cubic_yards": 15.0,
    "min_driveway_access_class": "CLASS_C",
}


def _turnaround_first_booking(api):
    """One truck already booked from 08:00 to 10:00 on a 30.00-cubic-yard order."""
    context = seed_confirmed_delivery_context(
        api,
        material=DOUBLE_GROUND_MULCH,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Turnaround Landscapes", "credit_limit_cents": 5000000},
        lines=(("BULK", 30.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        truck=TURNAROUND_TRUCK,
    )
    context["load_one"] = seed_planned_load(
        api,
        context["order"]["id"],
        context["truck"]["id"],
        10.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T10:00:00.000Z",
    )
    return context


def _book(api, context, window_start, window_end):
    return api.create_delivery_load(
        create_delivery_load_payload(
            context["order"]["id"], context["truck"]["id"], 10.0, window_start, window_end
        ),
        headers=make_dispatch_planner_headers(),
    )


def _truck_bookings(api, truck_id):
    return validate_paginated(
        api.list_delivery_loads(
            headers=make_dispatch_planner_headers(), params={"delivery_truck_id": truck_id}
        )
    )


class TestTruckTurnaroundBufferBoundary:
    """Forty-five minutes of turnaround, applied to both ends of every booking."""

    def test_one_minute_inside_the_trailing_buffer_conflicts_and_the_exact_minute_does_not(self, api):
        """10:44 is inside the buffer; 10:45 is precisely on it and therefore free.

        PRD 3.5: "For every other load of the same truck whose `status` is `PLANNED` or
        `DISPATCHED`, the new window is rejected when the new window's `window_start` falls
        strictly before that load's `window_end` plus forty-five minutes **and**, at the
        same time, that load's `window_start` falls strictly before the new window's
        `window_end` plus forty-five minutes."

        Design: Difficulty/resource_temporal_overlap/truck_window_symmetric_forty_five_minute_buffer_boundary
        """
        context = _turnaround_first_booking(api)

        # 10:44 is one minute short of 10:00 plus the forty-five-minute turnaround
        rejected = _book(api, context, "2026-08-02T10:44:00.000Z", "2026-08-02T12:44:00.000Z")
        validate_error(rejected, ApiErrorId.TRUCK_WINDOW_CONFLICT.value, 409)

        _, meta = _truck_bookings(api, context["truck"]["id"])
        assert meta["total_count"] == 1

        accepted = validate_success(
            _book(api, context, "2026-08-02T10:45:00.000Z", "2026-08-02T12:45:00.000Z"), 201
        )
        assert accepted["status"] == "PLANNED"

        _, meta = _truck_bookings(api, context["truck"]["id"])
        assert meta["total_count"] == 2

    def test_a_window_ending_one_buffer_before_the_booking_is_also_accepted(self, api):
        """The buffer is symmetric, so the leading side has to be tested too.

        PRD 3.5: "The buffer is symmetric and the boundary is exact: a new window starting
        precisely at another load's `window_end` plus forty-five minutes is accepted."

        Design: Difficulty/resource_temporal_overlap/truck_window_symmetric_forty_five_minute_buffer_boundary
        """
        context = _turnaround_first_booking(api)

        second = validate_success(
            _book(api, context, "2026-08-02T10:45:00.000Z", "2026-08-02T12:45:00.000Z"), 201
        )
        # 07:15 plus the buffer lands exactly on load one's 08:00 start, which is not
        # strictly before it
        third = validate_success(
            _book(api, context, "2026-08-02T06:00:00.000Z", "2026-08-02T07:15:00.000Z"), 201
        )

        loads, meta = _truck_bookings(api, context["truck"]["id"])
        assert meta["total_count"] == 3
        assert {row["id"] for row in loads} == {
            context["load_one"]["id"],
            second["id"],
            third["id"],
        }
        assert {row["status"] for row in loads} == {"PLANNED"}

        order = read_order(api, context["order"]["id"])
        assert order["fulfillment_status"] == "ALLOCATED"
        # 60000 bulk clears the minimum-load threshold, leaving only the TRI_AXLE base
        assert order["quoted_total_cents"] == 73500


PREBUY_SALT = {
    "sku": "SALT-PREBUY",
    "name": "Pre-Buy Rock Salt",
    "offered_forms": ["BULK"],
    "seasonal_category": "SALT",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": True,
}


def _first_season_locked(api):
    """An ACTIVE contract covering the 2026-11-01 through 2027-03-31 winter."""
    catalogue = seed_catalogue(api, material=PREBUY_SALT, price=FLAT_PRICE, with_lot=False)
    account = seed_account(
        api, business_name="Seasonal Salt Partners", credit_limit_cents=5000000
    )
    first = seed_prebuy(
        api,
        account,
        catalogue["material"]["id"],
        1500,
        50.0,
        "2026-11-01",
        "2027-03-31",
    )
    return {"account": account, "material": catalogue["material"], "first": first}


def _write_second_season(api, context, season_start_date):
    return api.create_prebuy_contract(
        create_prebuy_contract_payload(
            context["account"]["id"],
            context["material"]["id"],
            1600,
            20.0,
            season_start_date,
            "2027-06-30",
        ),
        headers=make_contractor_headers(context["account"]["id"]),
    )


class TestPreBuySeasonClosedInterval:
    """Season windows are fully closed, so a single shared day is already an overlap."""

    def test_a_season_starting_on_the_previous_seasons_last_day_is_refused(self, api):
        """One shared calendar day is enough to make the two seasons collide.

        PRD 3.3: "A new contract is accepted only when either its `season_end_date` falls
        strictly before the other contract's `season_start_date`, or the other contract's
        `season_end_date` falls strictly before the new contract's `season_start_date`;
        every other arrangement is a conflict, so two seasons that merely touch on a single
        shared calendar day do overlap and the new contract is refused with
        `ERR_PREBUY_SEASON_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/prebuy_season_closed_interval_shares_a_single_day
        """
        context = _first_season_locked(api)

        assert context["first"]["status"] == "ACTIVE"
        assert context["first"]["season_end_date"] == "2027-03-31"

        rejected = _write_second_season(api, context, "2027-03-31")
        validate_error(rejected, ApiErrorId.PREBUY_SEASON_OVERLAP.value, 409)

        untouched = read_prebuy(api, context["first"]["id"])
        assert untouched["status"] == "ACTIVE"
        assert untouched["remaining_cubic_yards"] == pytest.approx(50.0, abs=CENTS)

        _, meta = validate_paginated(
            api.list_prebuy_contracts(
                headers=make_contractor_headers(context["account"]["id"]),
                params={"contractor_account_id": context["account"]["id"]},
            )
        )
        assert meta["total_count"] == 1

    def test_a_season_starting_the_very_next_day_is_accepted(self, api):
        """Strictly-before on the day granularity is satisfied by a one-day gap.

        PRD 3.3: "The contract opens in `DRAFT` with `drawn_cubic_yards` at 0.0 and
        `remaining_cubic_yards` equal to `contracted_cubic_yards`."

        Design: Difficulty/resource_temporal_overlap/prebuy_season_closed_interval_shares_a_single_day
        """
        context = _first_season_locked(api)

        validate_error(
            _write_second_season(api, context, "2027-03-31"),
            ApiErrorId.PREBUY_SEASON_OVERLAP.value,
            409,
        )

        second = validate_success(_write_second_season(api, context, "2027-04-01"), 201)
        assert_prebuy_contract(second)
        assert second["status"] == "DRAFT"
        assert second["season_start_date"] == "2027-04-01"
        assert second["drawn_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        assert second["remaining_cubic_yards"] == pytest.approx(20.0, abs=CENTS)

        contracts, meta = validate_paginated(
            api.list_prebuy_contracts(
                headers=make_contractor_headers(context["account"]["id"]),
                params={"contractor_account_id": context["account"]["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in contracts} == {context["first"]["id"], second["id"]}

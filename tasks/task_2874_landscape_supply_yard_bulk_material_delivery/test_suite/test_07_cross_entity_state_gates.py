"""Gates whose blocking state lives on a neighbour of the record being written."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import CENTS, assert_charge_assembly
from test_helpers.factories import create_delivery_load_payload, create_moisture_reading_payload
from test_helpers.fixtures import (
    read_account,
    read_line,
    read_load,
    read_lot,
    read_material,
    read_order,
    read_truck,
    seed_account,
    seed_catalogue,
    seed_confirmed_delivery_context,
    seed_delivery_order,
    seed_planned_load,
)
from test_helpers.test_users import (
    make_contractor_headers,
    make_dispatch_planner_headers,
    make_yard_admin_headers,
)

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
BIG_TRUCK = {
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 20000,
    "bed_capacity_cubic_yards": 15.0,
    "min_driveway_access_class": "CLASS_C",
}
LEAF_COMPOST = {
    "sku": "SOIL-COMPOST",
    "name": "Leaf Compost",
    "offered_forms": ["BULK"],
    "seasonal_category": "SOIL",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}


def _quarry_lane_quarantined(api):
    """A PLANNED load whose pinned pile has just been quarantined by a wet reading."""
    context = seed_confirmed_delivery_context(
        api,
        material=LEAF_COMPOST,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Quarry Lane Gardens", "credit_limit_cents": 5000000},
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        truck=dict(BIG_TRUCK, truck_code="T-111"),
    )
    context["load"] = seed_planned_load(
        api,
        context["order"]["id"],
        context["truck"]["id"],
        10.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T12:00:00.000Z",
    )
    validate_success(
        api.create_moisture_reading(
            context["lot"]["id"],
            create_moisture_reading_payload(18.0, set_quarantine=True),
            headers=make_yard_admin_headers(),
        ),
        200,
    )
    return context


class TestQuarantinedLotBlocksDispatch:
    """Nothing on the load changes; only the pile it points at does."""

    def test_a_quarantined_pile_stops_the_dispatch_and_leaves_the_yard_position_at_zero(self, api):
        """The reading that blocks the road also re-bases the pile's sellable volume.

        PRD 3.2: "Once `basis` has flipped to `SETTLEMENT` -- meaning at least one moisture
        reading has been filed -- the pile has already settled, so only **half** the
        shrinkage factor is charged and the arithmetic runs on the volume still physically
        on the ground: `net_sellable_cubic_yards` becomes `gross_cubic_yards` minus
        `withdrawn_gross_cubic_yards`, multiplied by one minus half the `shrinkage_factor`,
        multiplied by the moisture multiplier taken from `current_moisture_pct`, with the
        product rounded half up to two decimal places."

        PRD 3.5: "the pinned lot must be `AVAILABLE` rather than `QUARANTINED` or
        `DEPLETED` (`ERR_LOT_QUARANTINED`)"

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_while_pinned_lot_is_quarantined_then_allowed_after_release
        """
        context = _quarry_lane_quarantined(api)

        lot = read_lot(api, context["lot"]["id"])
        assert lot["status"] == "QUARANTINED"
        assert lot["basis"] == "SETTLEMENT"
        # 100.00 * (1 - 0.05) * (1 - 0.03)
        assert lot["net_sellable_cubic_yards"] == pytest.approx(92.15, abs=CENTS)

        # a QUARANTINED lot contributes nothing to the material roll-up
        assert read_material(api, context["material"]["id"])[
            "available_net_cubic_yards"
        ] == pytest.approx(0.00, abs=CENTS)

        rejected = api.dispatch_delivery_load(
            context["load"]["id"], headers=make_dispatch_planner_headers("planner-7")
        )
        validate_error(rejected, ApiErrorId.LOT_QUARANTINED.value, 409)

        assert read_load(api, context["load"]["id"])["status"] == "PLANNED"
        assert read_truck(api, context["truck"]["id"])["status"] == "AVAILABLE"

    def test_lifting_the_quarantine_lets_the_identical_dispatch_through(self, api):
        """A second reading with the flag off is how a pile comes back into play.

        PRD 3.2: "When `set_quarantine` is true the lot moves `AVAILABLE ->
        QUARANTINED`; when it is false the lot moves `QUARANTINED -> AVAILABLE`, so a
        reading is also how a quarantine is lifted."

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_while_pinned_lot_is_quarantined_then_allowed_after_release
        """
        context = _quarry_lane_quarantined(api)

        validate_success(
            api.create_moisture_reading(
                context["lot"]["id"],
                create_moisture_reading_payload(15.0, set_quarantine=False),
                headers=make_yard_admin_headers(),
            ),
            200,
        )

        lot = read_lot(api, context["lot"]["id"])
        assert lot["status"] == "AVAILABLE"
        # 100.00 * (1 - 0.05) * 1.00, the multiplier being clamped at 1.00
        assert lot["net_sellable_cubic_yards"] == pytest.approx(95.00, abs=CENTS)
        # 95.00 sellable less the 10.00 the confirmed line reserved
        assert read_material(api, context["material"]["id"])[
            "available_net_cubic_yards"
        ] == pytest.approx(85.00, abs=CENTS)

        dispatched = validate_success(
            api.dispatch_delivery_load(
                context["load"]["id"], headers=make_dispatch_planner_headers("planner-7")
            ),
            200,
        )
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["dispatched_by_user_id"] == "planner-7"
        assert read_truck(api, context["truck"]["id"])["status"] == "IN_SERVICE"


RIVER_ROCK = {
    "sku": "AGG-RIVER",
    "name": "River Rock",
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
AUGUST_WINDOW = ("2026-08-02T08:00:00.000Z", "2026-08-02T12:00:00.000Z")


def _stonebridge_out_of_service(api):
    """A confirmed order and the only truck in the yard sitting in the shop."""
    context = seed_confirmed_delivery_context(
        api,
        material=RIVER_ROCK,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
        account={"business_name": "Stonebridge Yards", "credit_limit_cents": 5000000},
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        truck=dict(BIG_TRUCK, truck_code="T-222"),
    )
    validate_success(
        api.patch_delivery_truck(
            context["truck"]["id"],
            {"status": "OUT_OF_SERVICE"},
            headers=make_dispatch_planner_headers(),
        ),
        200,
    )
    return context


def _plan_ten_yards(api, context):
    return api.create_delivery_load(
        create_delivery_load_payload(
            context["order"]["id"], context["truck"]["id"], 10.0, *AUGUST_WINDOW
        ),
        headers=make_dispatch_planner_headers(),
    )


class TestOutOfServiceTruckBlocksPlanning:
    """The gate reads the truck row at insert time, and the refusal suppresses a cascade."""

    def test_planning_against_a_shopped_truck_leaves_the_order_where_it_was(self, api):
        """No load row means no promotion, because the promotion rides on the insert.

        PRD 3.5: "The truck must be `AVAILABLE`, else `ERR_TRUCK_UNAVAILABLE`."

        PRD 3.5: "Creation sets `status` to `PLANNED`, pins `inventory_lot_id` to the lot
        allocated to the order's **earliest-created** bulk line, computes
        `planned_payload_lb` and `max_allowed_cubic_yards`, leaves
        `actual_net_cubic_yards`, `driveway_protection_used`, `dispatched_by_user_id` and
        `refusal_reason` null and `spillage_cubic_yards` at 0.0, and transitions the order
        `CONFIRMED -> ALLOCATED` when this is its first load."

        Design: Difficulty/cross_entity_state_dependency/load_planning_blocked_by_out_of_service_truck_then_allowed_after_return
        """
        context = _stonebridge_out_of_service(api)

        assert read_truck(api, context["truck"]["id"])["status"] == "OUT_OF_SERVICE"

        rejected = _plan_ten_yards(api, context)
        validate_error(rejected, ApiErrorId.TRUCK_UNAVAILABLE.value, 409)

        assert read_order(api, context["order"]["id"])["fulfillment_status"] == "CONFIRMED"

        _, meta = validate_paginated(
            api.list_delivery_loads(
                headers=make_dispatch_planner_headers(),
                params={"material_order_id": context["order"]["id"]},
            )
        )
        assert meta["total_count"] == 0

    def test_returning_the_truck_to_service_lets_the_identical_booking_through(self, api):
        """The accepted insert is what pins the pile and promotes the order.

        PRD 3.5: "A commissioned truck starts `AVAILABLE`; the planner may later take it
        out of service or return it, moving `status` among `AVAILABLE`, `IN_SERVICE` and
        `OUT_OF_SERVICE` and advancing the truck's `version`."

        Design: Difficulty/cross_entity_state_dependency/load_planning_blocked_by_out_of_service_truck_then_allowed_after_return
        """
        context = _stonebridge_out_of_service(api)

        validate_error(_plan_ten_yards(api, context), ApiErrorId.TRUCK_UNAVAILABLE.value, 409)

        validate_success(
            api.patch_delivery_truck(
                context["truck"]["id"],
                {"status": "AVAILABLE"},
                headers=make_dispatch_planner_headers(),
            ),
            200,
        )

        load = validate_success(_plan_ten_yards(api, context), 201)
        assert load["status"] == "PLANNED"
        # 10.00 * 1000.00
        assert load["planned_payload_lb"] == 10000
        # MIN(bed 15.00, FLOOR_2DP(20000 / 1000.00) = 20.00, CLASS_A cap 999.00)
        assert load["max_allowed_cubic_yards"] == pytest.approx(15.00, abs=CENTS)
        assert load["inventory_lot_id"] == context["lot"]["id"]

        assert read_order(api, context["order"]["id"])["fulfillment_status"] == "ALLOCATED"


TREATED_SALT = {
    "sku": "SALT-TREATED",
    "name": "Treated Rock Salt",
    "offered_forms": ["BULK"],
    "seasonal_category": "SALT",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}


def _frostline_suspended(api):
    """A DRAFT order whose only line points at a material pulled from sale."""
    catalogue = seed_catalogue(
        api,
        material=TREATED_SALT,
        price=FLAT_PRICE,
        lot={"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0},
    )
    account = seed_account(
        api, business_name="Frostline Maintenance", credit_limit_cents=5000000
    )
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 10.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=0.0,
        delivery_address="31 Frostline Ave",
    )
    validate_success(
        api.patch_material(
            catalogue["material"]["id"], {"status": "SUSPENDED"}, headers=make_yard_admin_headers()
        ),
        200,
    )
    return {
        "account": account,
        "material": catalogue["material"],
        "lot": catalogue["lot"],
        "order": seeded["order"],
        "line": seeded["lines"][0],
    }


class TestSuspendedMaterialBlocksConfirm:
    """The blocking state sits two hops away, through the line and into the catalogue."""

    def test_a_suspended_material_stops_the_confirm_and_the_whole_reservation_fan_out(self, api):
        """Nothing is priced, nothing is reserved and no credit is consumed.

        PRD 3.1: "Suspending or discontinuing a material does not disturb orders already
        confirmed against it, but it does block new confirmations: any line referencing a
        material that is not `ACTIVE` stops the confirm with `ERR_MATERIAL_NOT_SELLABLE`."

        PRD 3.4: "Everything monetary stays empty at this stage: `unit_price_cents`,
        `line_price_cents`, `final_line_price_cents` and `inventory_lot_id` are all null on
        a draft line, and `delivered_volume_cubic_yards` sits at 0.0."

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_suspended_material_then_allowed_after_reactivation
        """
        context = _frostline_suspended(api)
        account_id = context["account"]["id"]

        rejected = api.confirm_material_order(
            context["order"]["id"], headers=make_contractor_headers(account_id)
        )
        validate_error(rejected, ApiErrorId.MATERIAL_NOT_SELLABLE.value, 409)

        order = read_order(api, context["order"]["id"])
        assert order["fulfillment_status"] == "DRAFT"
        assert order["quoted_total_cents"] == 0
        assert order["quote_locked_at"] is None

        line = read_line(api, context["line"]["id"])
        assert line["unit_price_cents"] is None
        assert line["line_price_cents"] is None
        assert line["inventory_lot_id"] is None

        assert read_lot(api, context["lot"]["id"])["reserved_cubic_yards"] == pytest.approx(
            0.0, abs=CENTS
        )
        assert read_account(api, account_id)["credit_used_cents"] == 0

    def test_reactivating_the_material_makes_the_identical_confirm_price_the_order(self, api):
        """Every suppressed side effect appears at once on the retry.

        PRD 3.4: "The first hop writes the line pricing and the order assembly, sets
        `quote_locked_at` to the current logical clock, pins each line's
        `inventory_lot_id` to the earliest-created eligible available lot, and sets
        `fulfillment_status` to `CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_suspended_material_then_allowed_after_reactivation
        """
        context = _frostline_suspended(api)
        account_id = context["account"]["id"]
        headers = make_contractor_headers(account_id)

        validate_error(
            api.confirm_material_order(context["order"]["id"], headers=headers),
            ApiErrorId.MATERIAL_NOT_SELLABLE.value,
            409,
        )

        validate_success(
            api.patch_material(
                context["material"]["id"], {"status": "ACTIVE"}, headers=make_yard_admin_headers()
            ),
            200,
        )

        confirmed = validate_success(
            api.confirm_material_order(context["order"]["id"], headers=headers), 200
        )
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        # 20000 bulk + 7500 minimum-load fee + TRI_AXLE base 13500 on a zero-mile haul
        assert confirmed["quoted_total_cents"] == 41000
        assert_charge_assembly(confirmed, 41000)
        assert confirmed["quote_locked_at"] is not None

        assert read_line(api, context["line"]["id"])["inventory_lot_id"] == context["lot"]["id"]
        assert read_lot(api, context["lot"]["id"])["reserved_cubic_yards"] == pytest.approx(
            10.00, abs=CENTS
        )
        assert read_account(api, account_id)["credit_used_cents"] == 41000

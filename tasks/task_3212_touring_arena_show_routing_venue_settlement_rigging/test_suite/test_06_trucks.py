"""Truck moves: dock capacity boundary at dispatch."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_truck_move,
    setup_confirmed_engagement,
    validate_error,
    validate_success,
)

PE = TEST_USERS["production_engineer_headers"]
TM = TEST_USERS["tour_manager_headers"]


class TestDockDoorBoundary:
    def test_dock_door_boundary_exact_fit_vs_one_over(self):
        """PRD §3.5: "A scheduled move is born in `SCHEDULED`, and at creation
        the system computes `dock_doors_needed`: the truck count divided by 2
        and rounded up, because each dock door processes two trucks within a
        load-in window. The boundary matters when capacity is tight: a truck
        count exactly equal to twice the venue's `load_in_dock_doors` fits
        exactly, while one truck more than that exceeds the building and will be
        stopped at dispatch."
        PRD §3.5: "requires `dock_doors_needed` to fit within the venue's
        `load_in_dock_doors`; an overage is rejected with
        `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 422)"

        Design: Difficulty/boundary_precision_check/dock_door_boundary_exact_fit_vs_one_over
        """
        ctx = setup_confirmed_engagement(
            venue_overrides={"load_in_dock_doors": 4}
        )
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]

        move_fit = create_truck_move(ctx, cargo_kind="VEHICLES", truck_count=8)
        assert move_fit["dock_doors_needed"] == 4
        move_over = create_truck_move(ctx, cargo_kind="PROPS", truck_count=9)
        assert move_over["dock_doors_needed"] == 5

        fit = validate_success(api_client.dispatch_truck_move(tour_id, eng_id, move_fit["id"], PE))
        assert fit["status"] == "DISPATCHED"

        resp = api_client.dispatch_truck_move(tour_id, eng_id, move_over["id"], PE)
        validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED)

        move_over_now = validate_success(api_client.get_truck_move(tour_id, eng_id, move_over["id"], TM))
        assert move_over_now["status"] == "SCHEDULED"

    def test_dock_door_smaller_venue_rejects_earlier(self):
        """PRD §3.5: "A scheduled move is born in `SCHEDULED`, and at creation
        the system computes `dock_doors_needed`: the truck count divided by 2
        and rounded up, because each dock door processes two trucks within a
        load-in window. The boundary matters when capacity is tight: a truck
        count exactly equal to twice the venue's `load_in_dock_doors` fits
        exactly, while one truck more than that exceeds the building and will be
        stopped at dispatch."

        Design: Difficulty/boundary_precision_check/dock_door_boundary_exact_fit_vs_one_over
        """
        ctx = setup_confirmed_engagement(
            venue_overrides={"load_in_dock_doors": 1}
        )
        move_fit = create_truck_move(ctx, cargo_kind="VEHICLES", truck_count=2)
        assert move_fit["dock_doors_needed"] == 1
        move_over = create_truck_move(ctx, cargo_kind="PROPS", truck_count=3)
        assert move_over["dock_doors_needed"] == 2

        fit = validate_success(
            api_client.dispatch_truck_move(
                ctx["tour"]["id"], ctx["engagement"]["id"], move_fit["id"], PE
            )
        )
        assert fit["status"] == "DISPATCHED"

        resp = api_client.dispatch_truck_move(
            ctx["tour"]["id"], ctx["engagement"]["id"], move_over["id"], PE
        )
        validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED)

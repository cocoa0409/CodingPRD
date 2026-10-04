"""Demand adjustment lifecycle: cyclic ACTIVE/SUPERSEDED/RESCINDED states and
the recomputation of adjusted_quantity on live orders (queue A non_linear)."""
from test_helpers import (
    validate_success, get_success_data,
    setup_facility, setup_cxl_dough_type, setup_cafe, set_clock,
    place_and_submit_order, get_order, get_cafe,
)


class TestDemandAdjustmentSupersedeCycle:
    def test_supersede_then_rescind_then_third_adjustment_rewrites_adjusted_quantity(
            self, api, planner_headers):
        """PRD §3.3: "Creating a new one for a pair that already has an `ACTIVE`
        adjustment flips the older one to `SUPERSEDED` with its `superseded_by_id`
        pointing at the newcomer (the field is null until then)."
        PRD §3.3: "Every affected order for that cafe and date in `DRAFT`,
        `SUBMITTED`, or `LOCKED` then recomputes its `adjusted_quantity` from the
        newly active adjustment."
        PRD §3.3: "The adjusted figure is the requested `quantity` scaled by the
        active adjustment's percentage: the quantity is multiplied by one hundred
        plus the delta, divided by one hundred, and rounded down to a whole unit,
        with a floor of zero — so an adjustment can shrink a line to nothing but
        never below nothing."

        Design: Difficulty/non_linear_state_machine/demand_adjustment_supersede_cycle
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        order = place_and_submit_order(cafe, cxl, "2026-09-10", 100)

        adj1 = validate_success(api.create_demand_adjustment(
            {"cafe_id": cafe["id"], "production_date": "2026-09-10",
             "reason": "WEATHER", "demand_delta_pct": -40},
            planner_headers), 201)
        assert get_order(order["id"])["adjusted_quantity"] == 60, \
            "after A1 (-40%): floor(100 x 0.60) = 60"

        adj2 = validate_success(api.create_demand_adjustment(
            {"cafe_id": cafe["id"], "production_date": "2026-09-10",
             "reason": "EVENT", "demand_delta_pct": 20},
            planner_headers), 201)
        assert get_order(order["id"])["adjusted_quantity"] == 120, \
            "after A2 (+20%): floor(100 x 1.20) = 120"

        adj1_now = get_success_data(api.get_demand_adjustment(adj1["id"], planner_headers))
        assert adj1_now["status"] == "SUPERSEDED"
        assert adj1_now["superseded_by_id"] == adj2["id"]

        adj2_now = validate_success(
            api.rescind_demand_adjustment(adj2["id"], planner_headers), 200)
        assert adj2_now["status"] == "RESCINDED"
        assert get_order(order["id"])["adjusted_quantity"] == 100, \
            "after A2 rescinded: adjusted_quantity reverts to quantity"

        adj3 = validate_success(api.create_demand_adjustment(
            {"cafe_id": cafe["id"], "production_date": "2026-09-10",
             "reason": "EVENT", "demand_delta_pct": -10},
            planner_headers), 201)
        assert adj3["status"] == "ACTIVE"
        assert get_order(order["id"])["adjusted_quantity"] == 90, \
            "after A3 (-10%): floor(100 x 0.90) = 90"

    def test_superseded_adjustment_points_at_newcomer_and_revert_on_rescind(
            self, api, planner_headers):
        """PRD §3.3: "At most one adjustment may be `ACTIVE` per cafe and production
        date. Creating a new one for a pair that already has an `ACTIVE` adjustment
        flips the older one to `SUPERSEDED` with its `superseded_by_id` pointing at
        the newcomer (the field is null until then)."
        PRD §3.3: "A planner may also rescind an `ACTIVE` adjustment outright, moving
        it to `RESCINDED`; every affected order in `DRAFT`, `SUBMITTED`, or `LOCKED`
        then reverts to `adjusted_quantity` equal to its plain `quantity`."

        Design: Difficulty/non_linear_state_machine/demand_adjustment_supersede_cycle
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        order = place_and_submit_order(cafe, cxl, "2026-09-10", 100)

        adj1 = validate_success(api.create_demand_adjustment(
            {"cafe_id": cafe["id"], "production_date": "2026-09-10",
             "reason": "WEATHER", "demand_delta_pct": -40},
            planner_headers), 201)
        assert adj1["status"] == "ACTIVE"
        assert adj1["superseded_by_id"] is None

        adj2 = validate_success(api.create_demand_adjustment(
            {"cafe_id": cafe["id"], "production_date": "2026-09-10",
             "reason": "EVENT", "demand_delta_pct": 20},
            planner_headers), 201)
        adj1_now = get_success_data(api.get_demand_adjustment(adj1["id"], planner_headers))
        assert adj1_now["status"] == "SUPERSEDED"
        assert adj1_now["superseded_by_id"] == adj2["id"]

        adj2_now = validate_success(
            api.rescind_demand_adjustment(adj2["id"], planner_headers), 200)
        assert adj2_now["status"] == "RESCINDED"
        assert get_order(order["id"])["adjusted_quantity"] == 100

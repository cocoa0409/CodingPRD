"""Format selection, stem-cost variants, DC assignments, and route planning."""

import pytest

from test_helpers import (
    ApiErrorId,
    create_active_rollout,
    create_dc_assignment,
    create_distribution_center,
    create_qualified_trade_area,
    create_route_plan,
    create_store,
    get_success_data,
    read_store,
    screen_trade_area,
    select_format,
    set_volume_index,
    setup_store_with_format,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
REAL_ESTATE = TEST_USERS["real_estate_manager_headers"]
NETWORK = TEST_USERS["network_planner_headers"]


class TestFormatSelection:
    def test_format_selection_prefers_market_when_feasible(self, api):
        """PRD §3.3: "Candidates are evaluated in preference order — `DG_MARKET`
        first, then `DG_FRESH`, then `TRADITIONAL` — and the first feasible
        format wins."
        PRD §3.3: "`build_cost_cents`, the all-in build cost — 350,000,000 cents
        for `TRADITIONAL`, 500,000,000 cents for `DG_FRESH`, 700,000,000 cents
        for `DG_MARKET`."

        Design: Corner/calculations/format_selection_prefers_market_when_feasible
        """
        rollout = create_active_rollout(
            name="P", new_build_capital_budget_cents=3000000000
        )
        area = create_qualified_trade_area(
            rollout["id"], name="B", drive_time_minutes=10, household_count=5000,
            median_household_income_cents=5000000, grocery_gap_pct=40,
        )
        store = create_store(rollout["id"], area["id"], name="S")
        selected = select_format(rollout["id"], store["id"])
        assert selected["format_type"] == "DG_MARKET"
        # 5000 households * 640 dollars * (1 + 40/100) = 448,000,000 cents.
        assert selected["projected_revenue_cents"] == 448000000
        assert selected["build_cost_cents"] == 700000000
        assert selected["weekly_case_volume_base"] == 2600
        # Projected revenue is copied onto the trade area.
        refreshed = get_success_data(api.get_trade_area(area["id"], ADMIN))
        assert refreshed["projected_revenue_cents"] == 448000000

    def test_format_selection_no_feasible_format(self, api):
        """PRD §3.3: "If no format is feasible, the request fails with
        `ERR_NO_FEASIBLE_FORMAT` (HTTP 422)."
        PRD §3.3: "A format is feasible when its projected revenue meets its
        minimum bar: at least 40,000,000 cents for `TRADITIONAL`, at least
        90,000,000 cents for `DG_FRESH`, at least 220,000,000 cents for
        `DG_MARKET`."

        Design: Corner/calculations/format_selection_no_feasible_format
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(
            rollout["id"], name="D", drive_time_minutes=5, household_count=680,
            median_household_income_cents=4500000, grocery_gap_pct=40,
        )
        store = create_store(rollout["id"], area["id"], name="S")
        current = read_store(store["id"])
        # 680 * 420 * 1.40 = 39,984,000 cents < 40,000,000 -> no feasible format.
        resp = api.select_format(
            store["id"],
            {
                "rollout_program_id": rollout["id"],
                "expected_store_version": current["version"],
            },
            REAL_ESTATE,
        )
        validate_error(resp, ApiErrorId.ERR_NO_FEASIBLE_FORMAT)

    def test_occ_stale_store_version_on_format_select(self, api):
        """PRD §3.3: "For a pipeline store, format selection is a
        `REAL_ESTATE_MANAGER` operation with optimistic concurrency on the
        store: the request carries `rollout_program_id` and
        `expected_store_version`, and a mismatch with the store's current
        `version` rejects with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_store_version_on_format_select
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = create_store(rollout["id"], area["id"], name="S")
        original_version = store["version"]
        # The volume bump advances the store's version past the captured one.
        set_volume_index(rollout["id"], store["id"], 1.2)

        resp = api.select_format(
            store["id"],
            {
                "rollout_program_id": rollout["id"],
                "expected_store_version": original_version,
            },
            REAL_ESTATE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestStemCost:
    def test_stem_cost_low_volume_uplift(self, api):
        """PRD §3.5: "When the store's effective weekly case volume —
        `weekly_case_volume_base` multiplied by `volume_index` — is below 1,800
        cases, the store runs sub-truckload, and the low-volume variant applies:
        the standard cost multiplied by 1.25, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/stem_cost_low_volume_uplift
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = create_store(rollout["id"], area["id"], name="S")
        set_volume_index(rollout["id"], store["id"], 0.9)
        selected = select_format(rollout["id"], store["id"])
        assert selected["format_type"] == "TRADITIONAL"
        dc = create_distribution_center(rollout["id"], name="D", store_capacity=2)

        # 900 * 0.9 = 810 < 1800 -> low-volume: 120*2*285*2 * 1.25 = 171000.
        resp = api.create_dc_assignment(
            {
                "rollout_program_id": rollout["id"],
                "store_id": store["id"],
                "distribution_center_id": dc["id"],
                "stem_miles": 120,
                "deliveries_per_week": 2,
            },
            NETWORK,
        )
        assignment = validate_success(resp, 201)
        assert assignment["stem_cost_cents_per_week"] == 171000
        assert read_store(store["id"])["stem_miles"] == 120

    def test_stem_cost_low_volume_differs_from_standard(self, api):
        """PRD §3.5: "The standard cost is `stem_miles` doubled (round trip),
        multiplied by 285 cents per mile, multiplied by `deliveries_per_week`."
        PRD §3.5: "Stores at or above 1,800 effective weekly cases pay the plain
        standard rate."

        Design: Difficulty/dual_variant_calc/stem_cost_low_volume_uplift
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = create_store(rollout["id"], area["id"], name="S")
        set_volume_index(rollout["id"], store["id"], 0.9)
        select_format(rollout["id"], store["id"])
        dc = create_distribution_center(rollout["id"], name="D", store_capacity=2)
        assignment = create_dc_assignment(
            rollout["id"], store["id"], dc["id"], stem_miles=120, deliveries_per_week=2
        )
        # Standard variant for the same inputs would be 120*2*285*2 = 136800.
        assert assignment["stem_cost_cents_per_week"] != 136800
        assert assignment["stem_cost_cents_per_week"] == 171000

    def test_stem_cost_standard_variant_at_truckload(self, api):
        """PRD §3.5: "The standard cost is `stem_miles` doubled (round trip),
        multiplied by 285 cents per mile, multiplied by `deliveries_per_week`."
        PRD §3.5: "Stores at or above 1,800 effective weekly cases pay the
        plain standard rate."

        Design: Corner/calculations/stem_cost_standard_variant_at_truckload
        """
        rollout = create_active_rollout(
            name="P", new_build_capital_budget_cents=3000000000
        )
        area = create_qualified_trade_area(
            rollout["id"], name="B", drive_time_minutes=10, household_count=5000,
            median_household_income_cents=5000000, grocery_gap_pct=40,
        )
        store = create_store(rollout["id"], area["id"], name="S")
        selected = select_format(rollout["id"], store["id"])
        assert selected["format_type"] == "DG_MARKET"  # base 2600 >= 1800
        dc = create_distribution_center(rollout["id"], name="D", store_capacity=2)
        assignment = create_dc_assignment(
            rollout["id"], store["id"], dc["id"], stem_miles=120, deliveries_per_week=2
        )
        assert assignment["stem_cost_cents_per_week"] == 136800


class TestDcAssignmentSupersede:
    def test_dc_assignment_reverse_lookup(self, api):
        """PRD §3.5: "A store carries at most one `ACTIVE` assignment: creating
        a new assignment supersedes the prior `ACTIVE` one (its status becomes
        `SUPERSEDED` and the old DC's `assigned_store_count` decreases by 1),
        while the new assignment is born `ACTIVE`, the new DC's
        `assigned_store_count` increases by 1, and the store's `stem_miles` is
        copied from the assignment."
        PRD §2.3: "DC assignments filter by `store_id`,
        `distribution_center_id`, and `status`"

        Design: Corner/endpoints/dc_assignment_reverse_lookup
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        dc1 = create_distribution_center(rollout["id"], name="D1", store_capacity=2)
        dc2 = create_distribution_center(rollout["id"], name="D2", store_capacity=2)
        asg1 = create_dc_assignment(
            rollout["id"], store["id"], dc1["id"], stem_miles=90, deliveries_per_week=1
        )
        asg2 = create_dc_assignment(
            rollout["id"], store["id"], dc2["id"], stem_miles=70, deliveries_per_week=1
        )

        resp = api.list_dc_assignments(NETWORK, params={"store_id": store["id"]})
        assignments, _meta = validate_paginated(resp)
        by_id = {a["id"]: a for a in assignments}
        assert len(assignments) == 2
        assert by_id[asg1["id"]]["status"] == "SUPERSEDED"
        assert by_id[asg2["id"]]["status"] == "ACTIVE"

        dc1_after = get_success_data(api.get_distribution_center(dc1["id"], NETWORK))
        dc2_after = get_success_data(api.get_distribution_center(dc2["id"], NETWORK))
        assert dc1_after["assigned_store_count"] == 0
        assert dc2_after["assigned_store_count"] == 1
        assert read_store(store["id"])["stem_miles"] == 70

    def test_immediate_consistency_after_cascade(self, api):
        """PRD §3.5: "creating a new assignment supersedes the prior `ACTIVE`
        one (its status becomes `SUPERSEDED` and the old DC's
        `assigned_store_count` decreases by 1), while the new assignment is born
        `ACTIVE`, the new DC's `assigned_store_count` increases by 1"

        Design: Corner/consistency_model/immediate_consistency_after_cascade
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        dc1 = create_distribution_center(rollout["id"], name="D", store_capacity=2)
        dc2 = create_distribution_center(rollout["id"], name="D2", store_capacity=2)
        create_dc_assignment(
            rollout["id"], store["id"], dc1["id"], stem_miles=90, deliveries_per_week=1
        )
        create_dc_assignment(
            rollout["id"], store["id"], dc2["id"], stem_miles=70, deliveries_per_week=1
        )
        # The very next read reflects the cascaded counts.
        resp = api.list_distribution_centers(
            NETWORK, params={"rollout_program_id": rollout["id"]}
        )
        centers, _meta = validate_paginated(resp)
        by_id = {d["id"]: d for d in centers}
        assert by_id[dc1["id"]]["assigned_store_count"] == 0
        assert by_id[dc2["id"]]["assigned_store_count"] == 1

    def test_dc_capacity_exhausted_rejected(self, api):
        """PRD §3.5: "The DC reference must resolve inside the program, else
        `ERR_BAD_REFERENCE`, and the DC must have `remaining_capacity` of at
        least 1, else `ERR_DC_CAPACITY_EXCEEDED`."

        Design: Corner/validations/dc_capacity_exhausted_rejected
        """
        rollout = create_active_rollout(name="P")
        area1 = create_qualified_trade_area(rollout["id"], name="C1")
        store1 = setup_store_with_format(rollout["id"], area1["id"], name="S1")
        area2 = create_qualified_trade_area(rollout["id"], name="C2")
        store2 = setup_store_with_format(rollout["id"], area2["id"], name="S2")
        dc = create_distribution_center(rollout["id"], name="D", store_capacity=1)
        create_dc_assignment(
            rollout["id"], store1["id"], dc["id"], stem_miles=90, deliveries_per_week=1
        )

        resp = api.create_dc_assignment(
            {
                "rollout_program_id": rollout["id"],
                "store_id": store2["id"],
                "distribution_center_id": dc["id"],
                "stem_miles": 80,
                "deliveries_per_week": 1,
            },
            NETWORK,
        )
        validate_error(resp, ApiErrorId.ERR_DC_CAPACITY_EXCEEDED)
        dc_after = get_success_data(api.get_distribution_center(dc["id"], NETWORK))
        assert dc_after["assigned_store_count"] == 1
        assert dc_after["remaining_capacity"] == 0


class TestRoutePlanning:
    def test_route_planning_nested_ceil_fill_surcharge(self, api):
        """PRD §3.5: "`truck_fill_pct` is the cases per truck expressed as a
        percentage of the 1,800-case capacity, rounded half up to two decimal
        places. A weekly cost is assembled per delivery and multiplied by the
        delivery count: each delivery costs the round-trip mileage (`stem_miles`
        doubled, times 285 cents per mile) plus a 35,000-cent per-stop charge,
        plus a low-fill surcharge of 15,000 cents that applies to every delivery
        whenever `truck_fill_pct` falls below 55."

        Design: Difficulty/combinatorial_formula/route_planning_nested_ceil_fill_surcharge
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = create_store(rollout["id"], area["id"], name="S")
        set_volume_index(rollout["id"], store["id"], 2.1)
        selected = select_format(rollout["id"], store["id"])
        assert selected["format_type"] == "TRADITIONAL"
        dc = create_distribution_center(rollout["id"], name="D", store_capacity=2)
        create_dc_assignment(
            rollout["id"], store["id"], dc["id"], stem_miles=90, deliveries_per_week=1
        )

        resp = api.create_route_plan(
            {"rollout_program_id": rollout["id"], "store_id": store["id"]}, NETWORK
        )
        plan = validate_success(resp, 201)
        # weekly cases 900 * 2.1 = 1890 -> ceil(1890/1800) = 2 deliveries.
        assert plan["deliveries_per_week"] == 2
        # ceil(1890 / 2) = 945 cases per truck.
        assert plan["cases_per_truck"] == 945
        # 945/1800 = 52.5% < 55 -> surcharge applies.
        assert plan["truck_fill_pct"] == pytest.approx(52.5, abs=0.001)
        # 2 * (90*2*285 + 35000 + 15000) = 2 * 101300 = 202600.
        assert plan["weekly_cost_cents"] == 202600

    def test_route_plan_delivery_count_from_combined_inputs(self, api):
        """PRD §3.5: "The plan computes the store's effective weekly cases
        (`weekly_case_volume_base` times `volume_index`), then sets
        `deliveries_per_week` to the number of 1,800-case truckloads needed —
        the weekly cases divided by 1,800, rounded up to a whole number, but
        never fewer than 1 delivery per week."
        PRD §3.5: "`cases_per_truck` is the weekly cases divided by the planned
        delivery count, rounded up."

        Design: Difficulty/combinatorial_formula/route_planning_nested_ceil_fill_surcharge
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = create_store(rollout["id"], area["id"], name="S")
        set_volume_index(rollout["id"], store["id"], 2.1)
        select_format(rollout["id"], store["id"])
        dc = create_distribution_center(rollout["id"], name="D", store_capacity=2)
        create_dc_assignment(
            rollout["id"], store["id"], dc["id"], stem_miles=90, deliveries_per_week=1
        )
        plan = create_route_plan(rollout["id"], store["id"])
        assert plan["deliveries_per_week"] == 2
        assert plan["cases_per_truck"] == 945

    def test_route_plan_supersede_on_replan(self, api):
        """PRD §3.5: "Each store carries at most one `ACTIVE` route plan:
        replanning supersedes the prior `ACTIVE` plan and publishes the new one
        as `ACTIVE`."

        Design: Corner/calculations/route_plan_supersede_on_replan
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        dc = create_distribution_center(rollout["id"], name="D", store_capacity=2)
        create_dc_assignment(
            rollout["id"], store["id"], dc["id"], stem_miles=90, deliveries_per_week=1
        )
        plan1 = create_route_plan(rollout["id"], store["id"])
        # Same inputs: 900/1800 -> 1 delivery, 900 cases/truck, 50.0% fill
        # (below 55, so the low-fill surcharge applies):
        # 1 * (90*2*285 + 35000 + 15000) = 101300.
        plan2 = create_route_plan(rollout["id"], store["id"])

        first = get_success_data(api.get_route_plan(plan1["id"], NETWORK))
        assert first["status"] == "SUPERSEDED"
        assert first["deliveries_per_week"] == 1
        assert first["cases_per_truck"] == 900
        assert first["truck_fill_pct"] == pytest.approx(50.0, abs=0.001)
        assert first["weekly_cost_cents"] == 101300

        assert plan2["status"] == "ACTIVE"
        assert plan2["deliveries_per_week"] == 1
        assert plan2["cases_per_truck"] == 900
        assert plan2["truck_fill_pct"] == pytest.approx(50.0, abs=0.001)
        assert plan2["weekly_cost_cents"] == 101300

        resp = api.list_route_plans(
            NETWORK, params={"store_id": store["id"], "status": "ACTIVE"}
        )
        active_plans, _meta = validate_paginated(resp)
        assert len(active_plans) == 1
        assert active_plans[0]["id"] == plan2["id"]

    def test_error_no_active_assignment_on_route_plan(self, api):
        """PRD §3.5: "Planning or replanning a store requires an `ACTIVE` DC
        assignment — without one the request fails with
        `ERR_NO_ACTIVE_ASSIGNMENT`"

        Design: Corner/errors/error_no_active_assignment_on_route_plan
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        resp = api.create_route_plan(
            {"rollout_program_id": rollout["id"], "store_id": store["id"]}, NETWORK
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ASSIGNMENT)

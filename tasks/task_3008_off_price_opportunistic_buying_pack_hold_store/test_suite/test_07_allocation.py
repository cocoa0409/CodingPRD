"""Allocation plans: cluster coverage, supersede semantics, largest-remainder
allocation with capacity spill, and the season-open execution gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_allocation_plan_payload,
    get_lot,
    get_season,
    make_accepted_lot,
    make_allocation_plan,
    make_store,
    make_ticket,
    open_season,
    setup_base,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ALLOCATOR = TEST_USERS["allocation_manager_headers"]
PLANNER = TEST_USERS["planning_lead_headers"]


def _setup_plan_env(api, unit_count=100, total_units=100, weights=None, line_qty=100):
    """Season OPEN + accepted lot + ticket + one SUBURBAN_FAMILY store (cap 500)."""
    base = setup_base()
    open_season(base["season"])
    accepted = make_accepted_lot(
        base["vendor"]["id"], base["season"]["id"],
        unit_count=unit_count,
        line_overrides={"quantity": line_qty},
    )
    make_ticket(accepted["line"]["id"], zone_code="MT")
    store = make_store()
    weights = weights or {"SUBURBAN_FAMILY": 1.0}
    return {"base": base, "lot": accepted["lot"], "line": accepted["line"], "store": store,
            "weights": weights, "total_units": total_units}


class TestSupersedeAndConservation:
    def test_supersede_preserves_unit_conservation(self, api):
        """PRD §3.6: "Approving a plan supersedes every other `DRAFT` plan for
        the same lot: each such plan moves `DRAFT → SUPERSEDED` with
        `superseded_by_id` pointing at the newly approved plan and its `version`
        incremented."

        Design: Difficulty/compensating_invariant/allocation_supersede_preserves_unit_conservation
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"],
                                     line_overrides={"quantity": 100})
        make_ticket(accepted["line"]["id"], zone_code="MT")
        make_store(store_code="S1-UP", cluster_code="URBAN_PREMIUM", storage_capacity_units=60)
        make_store(store_code="S2-SF", cluster_code="SUBURBAN_FAMILY", storage_capacity_units=60)
        weights = {"URBAN_PREMIUM": 1.0, "SUBURBAN_FAMILY": 1.0}
        plan1 = make_allocation_plan(accepted["lot"]["id"], base["season"]["id"], 100, weights)
        plan2 = make_allocation_plan(accepted["lot"]["id"], base["season"]["id"], 100, weights)
        validate_success(api.approve_allocation_plan(plan2["id"], ALLOCATOR))
        plan1_after = validate_success(api.get_allocation_plan(plan1["id"], ALLOCATOR))
        assert plan1_after["status"] == "SUPERSEDED"
        assert plan1_after["superseded_by_id"] == plan2["id"]
        validate_success(api.execute_allocation_plan(plan2["id"], ALLOCATOR))
        skus, _meta = validate_paginated(api.list_allocation_plan_store_skus(plan2["id"], ALLOCATOR))
        assert sum(s["units_on_hand"] for s in skus) == 100
        up_units = sum(s["units_on_hand"] for s in skus
                       if s["store_id"] and validate_success(api.get_store(s["store_id"], ALLOCATOR))["cluster_code"] == "URBAN_PREMIUM")
        sf_units = sum(s["units_on_hand"] for s in skus
                       if s["store_id"] and validate_success(api.get_store(s["store_id"], ALLOCATOR))["cluster_code"] == "SUBURBAN_FAMILY")
        assert up_units == 50
        assert sf_units == 50

    def test_superseded_plan_places_nothing(self, api):
        """PRD §3.6: "Approving a plan supersedes every other `DRAFT` plan for
        the same lot" — the superseded plan never executes, so no StoreSku
        carries its id.

        Design: Difficulty/compensating_invariant/allocation_supersede_preserves_unit_conservation
        """
        env = _setup_plan_env(api)
        plan1 = make_allocation_plan(env["lot"]["id"], env["base"]["season"]["id"], 100, env["weights"])
        plan2 = make_allocation_plan(env["lot"]["id"], env["base"]["season"]["id"], 100, env["weights"])
        validate_success(api.approve_allocation_plan(plan2["id"], ALLOCATOR))
        validate_success(api.execute_allocation_plan(plan2["id"], ALLOCATOR))
        all_skus, _meta = validate_paginated(
            api.list_store_skus(ALLOCATOR, params={"season_id": env["base"]["season"]["id"]}))
        assert all(s["allocation_plan_id"] == plan2["id"] for s in all_skus)
        assert len(all_skus) > 0


class TestLargestRemainder:
    def test_placed_skus_initialized_from_ticket(self, api):
        """PRD §3.6: "Execution creates one **StoreSku** per (store, lot line)
        pair placed: `allocation_plan_id` set to the plan, `floor_date` stamped
        from the logical clock, `weeks_on_floor` zero, and `current_price_cents`
        initialized from the ticket for the store's zone."

        Design: Corner/calculations/cluster_allocation_largest_remainder_and_capacity_spill
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"],
                                     line_overrides={"target_retail_cents": 5_000})
        make_ticket(accepted["line"]["id"], zone_code="MT")
        make_store(store_code="UP1", cluster_code="URBAN_PREMIUM", storage_capacity_units=30)
        make_store(store_code="UP2", cluster_code="URBAN_PREMIUM", storage_capacity_units=100)
        make_store(store_code="SF1", cluster_code="SUBURBAN_FAMILY", storage_capacity_units=100)
        make_store(store_code="VR1", cluster_code="VALUE_RURAL", storage_capacity_units=100)
        weights = {"URBAN_PREMIUM": 1.0, "SUBURBAN_FAMILY": 1.0, "VALUE_RURAL": 1.0}
        plan = make_allocation_plan(accepted["lot"]["id"], base["season"]["id"], 101, weights)
        validate_success(api.approve_allocation_plan(plan["id"], ALLOCATOR))
        validate_success(api.execute_allocation_plan(plan["id"], ALLOCATOR))
        skus, _meta = validate_paginated(api.list_allocation_plan_store_skus(plan["id"], ALLOCATOR))
        assert all(s["current_price_cents"] == 4_999 for s in skus)
        assert all(s["weeks_on_floor"] == 0 for s in skus)


class TestClusterCoverage:
    def test_approve_rejects_uncovered_cluster(self, api):
        """PRD §3.6: "then cluster coverage — every cluster named in
        `cluster_weights` must have at least one store, and every cluster that
        has at least one store must be named in `cluster_weights`, otherwise
        `ERR_CLUSTER_UNCOVERED`".

        Design: Corner/validations/allocation_approve_rejects_uncovered_cluster
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"])
        make_ticket(accepted["line"]["id"], zone_code="MT")
        make_store(store_code="CU-UP", cluster_code="URBAN_PREMIUM")
        make_store(store_code="CU-VR", cluster_code="VALUE_RURAL")
        plan = make_allocation_plan(accepted["lot"]["id"], base["season"]["id"], 100,
                                    {"URBAN_PREMIUM": 1.0})
        res = api.approve_allocation_plan(plan["id"], ALLOCATOR)
        validate_error(res, ApiErrorId.ERR_CLUSTER_UNCOVERED)
        plan_after = validate_success(api.get_allocation_plan(plan["id"], ALLOCATOR))
        assert plan_after["status"] == "DRAFT"

    def test_approve_succeeds_with_full_coverage(self, api):
        """PRD §3.6: "every cluster that has at least one store must be named in
        `cluster_weights`" — full coverage admits approval.

        Design: Corner/validations/allocation_approve_rejects_uncovered_cluster
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"])
        make_ticket(accepted["line"]["id"], zone_code="MT")
        make_store(store_code="CU-UP", cluster_code="URBAN_PREMIUM")
        plan = make_allocation_plan(accepted["lot"]["id"], base["season"]["id"], 100,
                                    {"URBAN_PREMIUM": 1.0})
        approved = validate_success(api.approve_allocation_plan(plan["id"], ALLOCATOR))
        assert approved["status"] == "APPROVED"


class TestExecutionSeasonGate:
    def test_execute_rejected_while_selling_season_draft(self, api):
        """PRD §3.6: "**Execution** (`APPROVED → EXECUTED`) requires the plan's
        selling season to be `OPEN` (`ERR_SEASON_NOT_OPEN`, HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/allocation_execute_gated_by_season_open
        """
        base = setup_base()
        open_season(base["season"])
        target = validate_success(
            api.create_season(
                {"season_code": "FW2027-X", "start_date": "2027-08-01T00:00:00Z",
                 "end_date": "2027-12-31T00:00:00Z", "department_otb_budget_cents": 5_000_000,
                 "packaway_reserve_ratio": 0.20},
                PLANNER), 201)
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"])
        make_ticket(accepted["line"]["id"], zone_code="MT")
        make_store()
        plan = make_allocation_plan(accepted["lot"]["id"], target["id"], 100,
                                    {"SUBURBAN_FAMILY": 1.0})
        validate_success(api.approve_allocation_plan(plan["id"], ALLOCATOR))
        res = api.execute_allocation_plan(plan["id"], ALLOCATOR)
        validate_error(res, ApiErrorId.ERR_SEASON_NOT_OPEN)
        plan_after = validate_success(api.get_allocation_plan(plan["id"], ALLOCATOR))
        assert plan_after["status"] == "APPROVED"
        skus, _meta = validate_paginated(api.list_allocation_plan_store_skus(plan["id"], ALLOCATOR))
        assert len(skus) == 0

    def test_execute_succeeds_once_season_open(self, api):
        """PRD §3.6: "**Execution** (`APPROVED → EXECUTED`) requires the plan's
        selling season to be `OPEN` (`ERR_SEASON_NOT_OPEN`, HTTP 422) and runs
        the deterministic proportional allocation."

        Design: Difficulty/cross_entity_state_dependency/allocation_execute_gated_by_season_open
        """
        env = _setup_plan_env(api)
        plan = make_allocation_plan(env["lot"]["id"], env["base"]["season"]["id"], 100, env["weights"])
        validate_success(api.approve_allocation_plan(plan["id"], ALLOCATOR))
        executed = validate_success(api.execute_allocation_plan(plan["id"], ALLOCATOR))
        assert executed["status"] == "EXECUTED"
        skus, _meta = validate_paginated(api.list_allocation_plan_store_skus(plan["id"], ALLOCATOR))
        assert sum(s["units_on_hand"] for s in skus) == 100


class TestLotAllocationUniqueness:
    def test_second_approve_blocked_and_cancel_from_draft(self, api):
        """PRD §3.6: "then uniqueness of the live chain — no other plan for the
        same lot may be `APPROVED` or `EXECUTED` (`ERR_LOT_ALREADY_ALLOCATED`)".

        Design: Corner/state_machines/allocation_plan_cancel_from_draft_and_approve_block_on_second_plan
        """
        env = _setup_plan_env(api)
        plan1 = make_allocation_plan(env["lot"]["id"], env["base"]["season"]["id"], 100, env["weights"])
        plan2 = make_allocation_plan(env["lot"]["id"], env["base"]["season"]["id"], 100, env["weights"])
        validate_success(api.approve_allocation_plan(plan1["id"], ALLOCATOR))
        res = api.approve_allocation_plan(plan2["id"], ALLOCATOR)
        # PRD pins the uniqueness check (ERR_LOT_ALREADY_ALLOCATED) but its
        # precedence over the supersession side effect is not pinned: whether
        # plan2 is still DRAFT or already SUPERSEDED when the check runs is an
        # implementation choice, and both rejections are PRD-faithful.
        validate_error_is_one_of(res, [ApiErrorId.ERR_LOT_ALREADY_ALLOCATED,
                                       ApiErrorId.ERR_INVALID_STATE])
        plan1_after = validate_success(api.get_allocation_plan(plan1["id"], ALLOCATOR))
        assert plan1_after["status"] == "APPROVED"

    def test_cancel_from_draft_succeeds(self, api):
        """PRD §3.6: "A plan may be cancelled from `DRAFT` or `APPROVED`
        (`→ CANCELLED`)".

        Design: Corner/state_machines/allocation_plan_cancel_from_draft_and_approve_block_on_second_plan
        """
        env = _setup_plan_env(api)
        plan1 = make_allocation_plan(env["lot"]["id"], env["base"]["season"]["id"], 100, env["weights"])
        validate_success(api.approve_allocation_plan(plan1["id"], ALLOCATOR))
        # plan1 is APPROVED; create plan2 while plan1 is APPROVED (allowed at
        # create — the block is on approve) and cancel it from DRAFT.
        plan2 = make_allocation_plan(env["lot"]["id"], env["base"]["season"]["id"], 100, env["weights"])
        cancelled = validate_success(api.cancel_allocation_plan(plan2["id"], ALLOCATOR))
        assert cancelled["status"] == "CANCELLED"

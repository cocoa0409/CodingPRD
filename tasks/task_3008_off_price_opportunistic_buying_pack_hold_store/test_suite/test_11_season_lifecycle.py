"""Season lifecycle: the single-OPEN singleton, and the three close gates."""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    accept_lot,
    create_target_season_payload,
    evaluate_lot,
    get_season,
    make_accepted_lot,
    make_allocation_plan,
    make_approved_packaway_lot,
    make_hold,
    make_lot,
    make_store,
    make_ticket,
    make_warehouse,
    open_season,
    setup_base,
    set_clock,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["planning_lead_headers"]
BUYER = TEST_USERS["buyer_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]


class TestSingleOpenSeason:
    def test_opening_second_season_rejected_even_with_disjoint_windows(self, api):
        """PRD §2.10: "at most one season may be `OPEN` at any moment; opening
        a second is rejected with `ERR_SEASON_ALREADY_OPEN`."

        Design: Difficulty/resource_temporal_overlap/single_open_season_interval_exclusion
        """
        base = setup_base()
        open_season(base["season"])
        fw2028 = validate_success(
            api.create_season(
                {"season_code": "FW2028", "start_date": "2028-08-01T00:00:00Z",
                 "end_date": "2028-12-31T00:00:00Z", "department_otb_budget_cents": 5_000_000,
                 "packaway_reserve_ratio": 0.20},
                PLANNER), 201)
        res = api.open_season(fw2028["id"], PLANNER)
        validate_error(res, ApiErrorId.ERR_SEASON_ALREADY_OPEN)
        fw_after = validate_success(api.get_season(fw2028["id"], PLANNER))
        assert fw_after["status"] == "DRAFT"

    def test_first_season_remains_open_after_rejected_second_open(self, api):
        """PRD §3.1: "Opening is a `PlanningLead` action permitted only from
        `DRAFT` and only while no other season is `OPEN` (otherwise
        `ERR_SEASON_ALREADY_OPEN`)".

        Design: Difficulty/resource_temporal_overlap/single_open_season_interval_exclusion
        """
        base = setup_base()
        opened = open_season(base["season"])
        second = validate_success(
            api.create_season(create_target_season_payload(), PLANNER), 201)
        validate_error(api.open_season(second["id"], PLANNER),
                       ApiErrorId.ERR_SEASON_ALREADY_OPEN)
        first_after = validate_success(api.get_season(base["season"]["id"], PLANNER))
        assert first_after["status"] == "OPEN"


class TestSeasonCloseGates:
    def test_close_blocked_by_offered_lot(self, api):
        """PRD §3.1: "no lot of the season may still be `OFFERED` or
        `EVALUATED` (`ERR_OPEN_LOTS_REMAIN`)".

        Design: Corner/validations/season_close_blocked_by_open_lots
        """
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=1_000_000,
                       unit_count=10)
        res = api.close_season(base["season"]["id"], PLANNER)
        validate_error(res, ApiErrorId.ERR_OPEN_LOTS_REMAIN)

    def test_close_admitted_after_lot_passed(self, api):
        """PRD §3.1: "no lot of the season may still be `OFFERED` or
        `EVALUATED` (`ERR_OPEN_LOTS_REMAIN`)" — adjudicating the lot unblocks
        the close.

        Design: Corner/validations/season_close_blocked_by_open_lots
        """
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=1_000_000,
                       unit_count=10)
        evaluate_lot(lot["id"])
        validate_success(api.pass_lot(lot["id"], BUYER))
        closed = validate_success(api.close_season(base["season"]["id"], PLANNER))
        assert closed["status"] == "CLOSED"

    def test_close_blocked_by_active_hold(self, api):
        """PRD §3.1: "every packaway hold bought against the season must be
        `RELEASED` or `LIQUIDATED` (`ERR_PACKAWAY_HOLDS_ACTIVE`)".

        Design: Corner/validations/season_close_blocked_by_active_packaway_holds
        """
        base = setup_base()
        open_season(base["season"])
        target = validate_success(api.create_season(create_target_season_payload(), PLANNER), 201)
        accepted = make_approved_packaway_lot(base["vendor"]["id"], base["season"]["id"],
                                              target["id"], asking_price_cents=1_000_000)
        warehouse = make_warehouse(zone_code="MT", pallet_capacity=50)
        make_hold(accepted["lot"]["id"], warehouse["id"], pallet_count=1)
        res = api.close_season(base["season"]["id"], PLANNER)
        validate_error(res, ApiErrorId.ERR_PACKAWAY_HOLDS_ACTIVE)
        season_after = get_season(base["season"]["id"])
        assert season_after["status"] == "OPEN"

    def test_close_blocked_by_unexecuted_plan(self, api):
        """PRD §3.1: "no allocation plan of the season may still be `DRAFT` or
        `APPROVED` (`ERR_PLAN_NOT_EXECUTABLE`)".

        Design: Corner/errors/plan_not_executable_blocks_season_close
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"])
        make_ticket(accepted["line"]["id"], zone_code="MT")
        make_store()
        plan = make_allocation_plan(accepted["lot"]["id"], base["season"]["id"], 100,
                                    {"SUBURBAN_FAMILY": 1.0})
        validate_success(api.approve_allocation_plan(plan["id"], ALLOCATOR))
        res = api.close_season(base["season"]["id"], PLANNER)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_EXECUTABLE)
        season_after = get_season(base["season"]["id"])
        assert season_after["status"] == "OPEN"

"""Optimistic concurrency: stale season/hold/lot versions rejected with 412."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_lot,
    create_target_season_payload,
    evaluate_lot,
    get_hold,
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
    validate_paginated,
    validate_success,
)

BUYER = TEST_USERS["buyer_headers"]
PLANNER = TEST_USERS["planning_lead_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]
INVENTORY = TEST_USERS["inventory_planner_headers"]


class TestSeasonOccOnLotAccept:
    def test_second_accept_with_stale_season_version_rejected(self, api):
        """PRD §2.8: "**Accepting a lot** requires `expected_season_version`
        matching the buying season's current `version`. Acceptance commits
        budget against the season and bumps the season's version, so a client
        whose view of the season predates the latest commitment holds a stale
        open-to-buy picture and the accept is rejected rather than committing
        against obsolete figures."

        Design: Corner/cross_cutting_layers/occ_stale_season_version_on_lot_accept
        """
        base = setup_base()
        open_season(base["season"])
        stale_version = get_season(base["season"]["id"])["version"]
        lot1 = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=100_000,
                        unit_count=10)
        evaluate_lot(lot1["id"])
        lot2 = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=100_000,
                        unit_count=10)
        evaluate_lot(lot2["id"])
        validate_success(
            api.accept_lot(lot1["id"], {"expected_season_version": stale_version}, BUYER))
        season = get_season(base["season"]["id"])
        assert season["version"] == stale_version + 1
        res = api.accept_lot(lot2["id"], {"expected_season_version": stale_version}, BUYER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_retry_with_current_version_succeeds(self, api):
        """PRD §2.8: "a mismatch rejects the write with `ERR_STALE_VERSION`
        (HTTP 412)" — re-reading the current version admits the accept.

        Design: Corner/cross_cutting_layers/occ_stale_season_version_on_lot_accept
        """
        base = setup_base()
        open_season(base["season"])
        lot1 = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=100_000,
                        unit_count=10)
        evaluate_lot(lot1["id"])
        lot2 = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=100_000,
                        unit_count=10)
        evaluate_lot(lot2["id"])
        accept_lot(lot1["id"], base["season"]["id"])
        accepted2 = accept_lot(lot2["id"], base["season"]["id"])
        assert accepted2["status"] == "ACCEPTED"
        season = get_season(base["season"]["id"])
        # 100000 + 150000 freight per lot, twice.
        assert season["committed_forward_cents"] == 500_000


class TestHoldOccOnRelease:
    def test_release_with_stale_hold_version_rejected(self, api):
        """PRD §2.8: "**Releasing a packaway hold** requires
        `expected_hold_version` matching the hold's current `version`. Release
        finalizes accrued holding cost, and aging reviews advance the hold's
        version as they recompute accrual, so a client releasing against an
        unobserved review is rejected."

        Design: Corner/cross_cutting_layers/occ_stale_hold_version_on_release
        """
        base = setup_base()
        target = validate_success(api.create_season(
            create_target_season_payload(start_date="2026-12-01T00:00:00Z"), PLANNER), 201)
        accepted = make_approved_packaway_lot(base["vendor"]["id"], base["season"]["id"],
                                              target["id"], asking_price_cents=100_000,
                                              unit_count=50)
        warehouse = make_warehouse(zone_code="MT", pallet_capacity=100)
        hold = make_hold(accepted["lot"]["id"], warehouse["id"], pallet_count=2,
                         release_window_start="2026-12-01T00:00:00Z",
                         release_window_end="2027-01-31T00:00:00Z")
        # The buying season never opens, so the target can open while the hold
        # ages in storage.
        open_season(target)
        stale_version = hold["version"]
        set_clock("2026-12-15T00:00:00Z")
        validate_success(api.aging_review(hold["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY))
        validate_success(api.aging_review(hold["id"], {"trigger_reason": "DECISION_KEEP"}, INVENTORY))
        res = api.release_hold(hold["id"], {"expected_hold_version": stale_version}, INVENTORY)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_release_retry_with_current_version_succeeds(self, api):
        """PRD §2.8: "**Releasing a packaway hold** requires
        `expected_hold_version` matching the hold's current `version`." — the
        retry with the observed current version succeeds and stamps
        `release_date`.

        Design: Corner/cross_cutting_layers/occ_stale_hold_version_on_release
        """
        base = setup_base()
        target = validate_success(api.create_season(
            create_target_season_payload(start_date="2026-12-01T00:00:00Z"), PLANNER), 201)
        accepted = make_approved_packaway_lot(base["vendor"]["id"], base["season"]["id"],
                                              target["id"], asking_price_cents=100_000,
                                              unit_count=50)
        warehouse = make_warehouse(zone_code="MT", pallet_capacity=100)
        hold = make_hold(accepted["lot"]["id"], warehouse["id"], pallet_count=2,
                         release_window_start="2026-12-01T00:00:00Z",
                         release_window_end="2027-01-31T00:00:00Z")
        # The buying season never opens, so the target can open while the hold
        # ages in storage.
        open_season(target)
        stale_version = hold["version"]
        set_clock("2026-12-15T00:00:00Z")
        validate_success(api.aging_review(hold["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY))
        validate_success(api.aging_review(hold["id"], {"trigger_reason": "DECISION_KEEP"}, INVENTORY))
        validate_error(
            api.release_hold(hold["id"], {"expected_hold_version": stale_version}, INVENTORY),
            ApiErrorId.ERR_STALE_VERSION)
        current = get_hold(hold["id"])
        released = validate_success(
            api.release_hold(hold["id"], {"expected_hold_version": current["version"]}, INVENTORY))
        assert released["status"] == "RELEASED"
        assert released["release_date"].startswith("2026-12-15")
        assert released["accrued_holding_cost_cents"] == 35_000


class TestLotOccOnPlanCreate:
    def test_second_plan_create_with_stale_lot_version_rejected(self, api):
        """PRD §3.6: "Creation carries the lot-level OCC gate of §2.8:
        `expected_lot_version` must match the lot's current `version`, else
        `ERR_STALE_VERSION` (412); a successful create bumps the lot's
        `version`, because under the product rule a newly approved plan
        legitimately supersedes the lot's prior draft."

        Design: Corner/validations/occ_stale_lot_version_on_allocation_plan_create
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"])
        make_ticket(accepted["line"]["id"], zone_code="MT")
        make_store()
        from test_helpers import get_lot
        stale_version = get_lot(accepted["lot"]["id"])["version"]
        validate_success(
            api.create_allocation_plan(
                {"lot_id": accepted["lot"]["id"], "season_id": base["season"]["id"],
                 "total_units": 100, "cluster_weights": {"SUBURBAN_FAMILY": 1.0},
                 "expected_lot_version": stale_version},
                ALLOCATOR), 201)
        res = api.create_allocation_plan(
            {"lot_id": accepted["lot"]["id"], "season_id": base["season"]["id"],
             "total_units": 50, "cluster_weights": {"SUBURBAN_FAMILY": 1.0},
             "expected_lot_version": stale_version},
            ALLOCATOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_rejected_plan_create_leaves_single_plan(self, api):
        """PRD §3.6: "`expected_lot_version` must match the lot's current
        `version`, else `ERR_STALE_VERSION` (412)" — the rejected create adds
        no plan.

        Design: Corner/validations/occ_stale_lot_version_on_allocation_plan_create
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"])
        make_ticket(accepted["line"]["id"], zone_code="MT")
        make_store()
        from test_helpers import get_lot
        stale_version = get_lot(accepted["lot"]["id"])["version"]
        validate_success(
            api.create_allocation_plan(
                {"lot_id": accepted["lot"]["id"], "season_id": base["season"]["id"],
                 "total_units": 100, "cluster_weights": {"SUBURBAN_FAMILY": 1.0},
                 "expected_lot_version": stale_version},
                ALLOCATOR), 201)
        validate_error(
            api.create_allocation_plan(
                {"lot_id": accepted["lot"]["id"], "season_id": base["season"]["id"],
                 "total_units": 50, "cluster_weights": {"SUBURBAN_FAMILY": 1.0},
                 "expected_lot_version": stale_version},
                ALLOCATOR),
            ApiErrorId.ERR_STALE_VERSION)
        plans, _meta = validate_paginated(api.list_lot_allocation_plans(accepted["lot"]["id"], ALLOCATOR))
        assert len(plans) == 1

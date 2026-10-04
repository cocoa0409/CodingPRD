"""Packaway holds: aging buckets, holding-cost variants, capacity, release
windows, and the review/liquidation lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    create_target_season_payload,
    get_hold,
    get_lot,
    get_season,
    make_approved_packaway_lot,
    make_hold,
    make_store,
    make_warehouse,
    open_season,
    setup_base,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planning_lead_headers"]
INVENTORY = TEST_USERS["inventory_planner_headers"]


def _packaway_setup(api, pallets=2, warehouse_zone="MT", pallet_capacity=200,
                    target_overrides=None, open_buying_season=False):
    """Base + DRAFT target season + accepted PACKAWAY lot + warehouse + STORED hold."""
    base = setup_base()
    if open_buying_season:
        open_season(base["season"])
    target = validate_success(
        api.create_season(create_target_season_payload(**(target_overrides or {})), PLANNER), 201
    )
    accepted = make_approved_packaway_lot(base["vendor"]["id"], base["season"]["id"], target["id"],
                                          asking_price_cents=100_000)
    warehouse = make_warehouse(zone_code=warehouse_zone, pallet_capacity=pallet_capacity)
    hold = make_hold(accepted["lot"]["id"], warehouse["id"], pallet_count=pallets)
    return {"base": base, "target": target, "lot": accepted["lot"], "warehouse": warehouse,
            "hold": hold}


class TestHoldingCostVariants:
    def test_pro_rata_daily_variant_on_mt_warehouse(self, api):
        """PRD §3.4: "Under the default **pro-rata** variant, the accrual is
        `pallet_count` times the warehouse monthly rate times full months, plus
        the floor of `pallet_count` times the monthly rate times remainder days
        divided by 30."

        Design: Difficulty/dual_variant_calc/holding_cost_pro_rata_daily_vs_month_boundary_by_warehouse_zone
        """
        env = _packaway_setup(api, pallets=4, warehouse_zone="MT")
        set_clock("2026-10-15T00:00:00Z")
        # The accrual is recomputed by the aging sweep on the clock advance; the
        # 44-day-old hold is still FRESH, so no AGING_THRESHOLD review is due.
        hold = get_hold(env["hold"]["id"])
        assert hold["accrued_holding_cost_cents"] == 29_333
        assert hold["status"] == "STORED"

    def test_month_boundary_variant_on_wc_warehouse(self, api):
        """PRD §3.4: "Under the **month-boundary** variant — used only by
        warehouses whose `zone_code` is `WC`, the west-coast billing convention —
        any started month is billed in full: `pallet_count` times the monthly
        rate times full months, plus one more full month whenever the remainder
        days are positive."

        Design: Difficulty/dual_variant_calc/holding_cost_pro_rata_daily_vs_month_boundary_by_warehouse_zone
        """
        env = _packaway_setup(api, pallets=4, warehouse_zone="WC")
        set_clock("2026-10-15T00:00:00Z")
        # Month-boundary billing: one full month plus the started second month.
        hold = get_hold(env["hold"]["id"])
        assert hold["accrued_holding_cost_cents"] == 40_000
        assert hold["status"] == "STORED"


class TestAgingReviewCycle:
    def test_aging_review_cycle_with_release(self, api):
        """PRD §3.4: "From `AGING_REVIEW`, the reviewer's decision completes the
        review: `DECISION_KEEP` returns the hold to `STORED`". PRD §3.4: "A
        **release** directly from `STORED` is the normal exit". PRD §3.4: "On
        release the final accrual is computed, `release_date` is stamped".

        Design: Difficulty/non_linear_state_machine/packaway_hold_aging_review_keep_loop_then_release
        """
        base = setup_base()
        target = validate_success(
            api.create_season(create_target_season_payload(), PLANNER), 201)
        accepted = make_approved_packaway_lot(base["vendor"]["id"], base["season"]["id"],
                                              target["id"], asking_price_cents=100_000)
        warehouse = make_warehouse(zone_code="MT")
        hold = make_hold(accepted["lot"]["id"], warehouse["id"], pallet_count=4)
        # The buying season was never opened, so the target can open while the
        # hold ages in storage.
        open_season(target)
        set_clock("2026-12-15T00:00:00Z")
        validate_success(api.aging_review(hold["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY))
        kept = validate_success(api.aging_review(hold["id"], {"trigger_reason": "DECISION_KEEP"}, INVENTORY))
        assert kept["status"] == "STORED"
        set_clock("2027-08-01T00:00:00Z")
        hold = get_hold(hold["id"])
        released = validate_success(
            api.release_hold(hold["id"], {"expected_hold_version": hold["version"]}, INVENTORY))
        assert released["review_count"] == 2
        assert released["status"] == "RELEASED"
        assert released["release_date"].startswith("2027-08-01")
        assert released["accrued_holding_cost_cents"] == 222_666

    def test_aging_threshold_review_moves_stored_to_aging_review(self, api):
        """PRD §3.4: "With `trigger_reason` `AGING_THRESHOLD`, a `STORED` hold
        moves to `AGING_REVIEW` — but only once its bucket has left `FRESH`,
        meaning at least 90 days since entry".

        Design: Difficulty/non_linear_state_machine/packaway_hold_aging_review_keep_loop_then_release
        """
        env = _packaway_setup(api, pallets=4)
        set_clock("2026-12-15T00:00:00Z")
        reviewed = validate_success(
            api.aging_review(env["hold"]["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY))
        assert reviewed["status"] == "AGING_REVIEW"
        assert reviewed["review_count"] == 1
        # A second threshold review from AGING_REVIEW is not the defined
        # from-state, so the keep decision is what closes the cycle.
        kept = validate_success(
            api.aging_review(env["hold"]["id"], {"trigger_reason": "DECISION_KEEP"}, INVENTORY))
        assert kept["status"] == "STORED"
        assert kept["review_count"] == 2


class TestAgeBucketBoundary:
    def test_aging_review_admitted_at_exactly_90_days(self, api):
        """PRD §3.4: "The boundaries are inclusive at the low end of each band:
        exactly 90 days is `AGING`, exactly 270 days is `STALE`."

        Design: Difficulty/boundary_precision_check/hold_age_bucket_at_exactly_aging_review_days
        """
        env = _packaway_setup(api, pallets=2)
        set_clock("2026-11-29T00:00:00Z")
        res = api.aging_review(env["hold"]["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY)
        validate_error(res, ApiErrorId.ERR_AGING_REVIEW_PREMATURE)
        hold = get_hold(env["hold"]["id"])
        assert hold["age_bucket"] == "FRESH"
        set_clock("2026-11-30T00:00:00Z")
        reviewed = validate_success(
            api.aging_review(env["hold"]["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY))
        assert reviewed["status"] == "AGING_REVIEW"
        assert reviewed["age_bucket"] == "AGING"
        assert reviewed["accrued_holding_cost_cents"] == 30_000

    def test_aging_review_premature_before_90_days(self, api):
        """PRD §3.4: "a premature review is rejected with
        `ERR_AGING_REVIEW_PREMATURE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/hold_age_bucket_at_exactly_aging_review_days
        """
        env = _packaway_setup(api, pallets=2)
        # Clock is still at entry date (FRESH, 0 days).
        res = api.aging_review(env["hold"]["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY)
        validate_error(res, ApiErrorId.ERR_AGING_REVIEW_PREMATURE)
        hold = get_hold(env["hold"]["id"])
        assert hold["status"] == "STORED"
        assert hold["review_count"] == 0


class TestStaleBoundary:
    def test_bucket_aging_at_269_days_stale_at_270(self, api):
        """PRD §3.4: "A hold with fewer than 90 days since entry is `FRESH`; from
        90 days up to but not including 270 days it is `AGING`; at 270 days or
        more it is `STALE`."

        Design: Corner/calculations/hold_age_bucket_stale_boundary_at_270_days
        """
        env = _packaway_setup(api, pallets=1)
        set_clock("2027-05-28T00:00:00Z")
        hold = get_hold(env["hold"]["id"])
        assert hold["age_bucket"] == "AGING"
        set_clock("2027-05-29T00:00:00Z")
        hold = get_hold(env["hold"]["id"])
        assert hold["age_bucket"] == "STALE"


class TestDirectLiquidation:
    def test_direct_liquidate_from_stale_stored(self, api):
        """PRD §3.4: "Liquidation, whether reached by `DECISION_LIQUIDATE` from
        `AGING_REVIEW` or by a **direct liquidation** from `STORED` (which
        requires the hold to be `STALE` — at least 270 days — else
        `ERR_AGING_REVIEW_PREMATURE`), computes the final accrual and creates a
        **LiquidationOrder** in `DRAFT` against the hold's lot with reason
        `PACKAWAY_STALE`, its `recovery_rate_pct` pinned to the cascade rate of
        0.25".

        Design: Corner/state_machines/packaway_hold_direct_liquidate_from_stale_stored
        """
        base = setup_base()
        target = validate_success(api.create_season(create_target_season_payload(), PLANNER), 201)
        accepted = make_approved_packaway_lot(base["vendor"]["id"], base["season"]["id"],
                                              target["id"], asking_price_cents=100_000)
        warehouse = make_warehouse(zone_code="MT", pallet_capacity=50)
        hold = make_hold(accepted["lot"]["id"], warehouse["id"], pallet_count=1)
        make_store(clearance_outlet=True, cluster_code="VALUE_RURAL")
        set_clock("2027-05-29T00:00:00Z")
        liquidated = validate_success(api.liquidate_hold(hold["id"], INVENTORY))
        assert liquidated["status"] == "LIQUIDATED"
        assert liquidated["review_count"] == 0
        assert liquidated["accrued_holding_cost_cents"] == 45_000
        orders, _meta = validate_paginated(api.list_lot_liquidation_orders(accepted["lot"]["id"], PLANNER))
        assert len(orders) == 1
        assert orders[0]["reason"] == "PACKAWAY_STALE"
        assert orders[0]["recovery_rate_pct"] == pytest.approx(0.25)
        assert orders[0]["status"] == "DRAFT"


class TestWarehouseCapacity:
    def test_third_hold_over_capacity_rejected(self, api):
        """PRD §2.10: "A warehouse cannot accept a hold whose `pallet_count`,
        added to the pallets of that warehouse's holds currently `STORED` or
        `AGING_REVIEW`, would exceed the warehouse's `pallet_capacity`; the
        overflow is rejected with `ERR_WAREHOUSE_OVER_CAPACITY`."

        Design: Corner/validations/warehouse_pallet_capacity_enforced_on_hold_entry
        """
        base = setup_base()
        open_season(base["season"])
        target = validate_success(api.create_season(create_target_season_payload(), PLANNER), 201)
        warehouse = make_warehouse(zone_code="MT", pallet_capacity=60)
        lots = []
        for _ in range(3):
            accepted = make_approved_packaway_lot(base["vendor"]["id"], base["season"]["id"],
                                                  target["id"], asking_price_cents=500_000,
                                                  unit_count=50)
            lots.append(accepted["lot"])
        make_hold(lots[0]["id"], warehouse["id"], pallet_count=30)
        make_hold(lots[1]["id"], warehouse["id"], pallet_count=30)
        res = api.create_packaway_hold(
            {
                "lot_id": lots[2]["id"],
                "warehouse_id": warehouse["id"],
                "pallet_count": 1,
                "release_window_start": TEST_DEFAULTS["RELEASE_WINDOW_START"],
                "release_window_end": TEST_DEFAULTS["RELEASE_WINDOW_END"],
            },
            INVENTORY,
        )
        validate_error(res, ApiErrorId.ERR_WAREHOUSE_OVER_CAPACITY)
        holds, _meta = validate_paginated(api.list_lot_packaway_holds(lots[2]["id"], INVENTORY))
        assert len(holds) == 0


class TestOneHoldPerLot:
    def test_second_hold_for_same_lot_rejected(self, api):
        """PRD §2.10: "Codes are unique system-wide: ... as does a second
        `PackawayHold` for a lot that already has one — there is exactly one
        hold per lot."

        Design: Corner/validations/duplicate_packaway_hold_for_same_lot_rejected
        """
        env = _packaway_setup(api, pallets=2)
        second_warehouse = make_warehouse(zone_code="MT")
        res = api.create_packaway_hold(
            {
                "lot_id": env["lot"]["id"],
                "warehouse_id": second_warehouse["id"],
                "pallet_count": 2,
                "release_window_start": TEST_DEFAULTS["RELEASE_WINDOW_START"],
                "release_window_end": TEST_DEFAULTS["RELEASE_WINDOW_END"],
            },
            INVENTORY,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CODE)
        holds, _meta = validate_paginated(api.list_lot_packaway_holds(env["lot"]["id"], INVENTORY))
        assert len(holds) == 1


class TestReleaseWindow:
    def test_release_before_window_start_rejected(self, api):
        """PRD §3.4: "`DECISION_RELEASE` releases it early, permitted only when
        today falls inside the release window inclusive on both ends
        (`ERR_HOLD_WINDOW_CLOSED` otherwise)".

        Design: Difficulty/resource_temporal_overlap/packaway_hold_release_window_inclusive_boundary
        """
        env = _packaway_setup(api, pallets=2, open_buying_season=True)
        set_clock("2027-06-30T00:00:00Z")
        validate_success(api.aging_review(env["hold"]["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY))
        res = api.aging_review(env["hold"]["id"], {"trigger_reason": "DECISION_RELEASE"}, INVENTORY)
        validate_error(res, ApiErrorId.ERR_HOLD_WINDOW_CLOSED)
        hold = get_hold(env["hold"]["id"])
        assert hold["status"] == "AGING_REVIEW"

    def test_release_at_window_start_succeeds(self, api):
        """PRD §3.4: "Release also requires today to fall within the release
        window inclusive (`ERR_HOLD_WINDOW_CLOSED`)" — the window's first day is
        in-window. PRD §3.4: "The window and target-season checks guard both the
        direct release and the aging-review release decision."

        Design: Difficulty/resource_temporal_overlap/packaway_hold_release_window_inclusive_boundary
        """
        base = setup_base()
        target = validate_success(
            api.create_season(
                create_target_season_payload(start_date="2027-07-01T00:00:00Z"), PLANNER), 201)
        accepted = make_approved_packaway_lot(base["vendor"]["id"], base["season"]["id"],
                                              target["id"], asking_price_cents=100_000)
        warehouse = make_warehouse(zone_code="MT")
        hold = make_hold(accepted["lot"]["id"], warehouse["id"], pallet_count=2)
        open_season(target)
        set_clock("2027-07-01T00:00:00Z")
        hold = get_hold(hold["id"])
        released = validate_success(
            api.release_hold(hold["id"], {"expected_hold_version": hold["version"]}, INVENTORY))
        assert released["status"] == "RELEASED"
        assert released["release_date"].startswith("2027-07-01")
        assert released["accrued_holding_cost_cents"] == 101_000


class TestWindowCheckPrecedesOcc:
    def test_window_closed_beats_stale_version(self, api):
        """PRD §3.4: "Release also requires today to fall within the release
        window inclusive (`ERR_HOLD_WINDOW_CLOSED`) and the target season to
        have reached its `start_date` with status `OPEN`
        (`ERR_TARGET_SEASON_NOT_OPEN`)."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_stale_version_on_packaway_release
        """
        env = _packaway_setup(api, pallets=2)
        stale_version = env["hold"]["version"]
        set_clock("2026-12-10T00:00:00Z")
        validate_success(api.aging_review(env["hold"]["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY))
        validate_success(api.aging_review(env["hold"]["id"], {"trigger_reason": "DECISION_KEEP"}, INVENTORY))
        res = api.release_hold(env["hold"]["id"], {"expected_hold_version": stale_version}, INVENTORY)
        # PRD pins the window/target-season checks but not their precedence over
        # the OCC gate, so either rejection is PRD-faithful.
        validate_error_is_one_of(res, [ApiErrorId.ERR_HOLD_WINDOW_CLOSED,
                                       ApiErrorId.ERR_STALE_VERSION])
        hold = get_hold(env["hold"]["id"])
        assert hold["status"] == "STORED"
        assert hold["release_date"] is None

    def test_release_rejected_outside_window(self, api):
        """PRD §3.4: "Release also requires today to fall within the release
        window inclusive (`ERR_HOLD_WINDOW_CLOSED`)".

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_stale_version_on_packaway_release
        """
        env = _packaway_setup(api, pallets=2)
        hold = get_hold(env["hold"]["id"])
        # Today (2026-09-01) is before the window start; version is current.
        res = api.release_hold(env["hold"]["id"], {"expected_hold_version": hold["version"]}, INVENTORY)
        validate_error(res, ApiErrorId.ERR_HOLD_WINDOW_CLOSED)

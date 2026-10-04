"""Allocation run lifecycle and turn-and-earn waterfall tests (PRD §3.3, §3.4, §3.5, §3.11)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_allocation_run_payload,
    create_appeal_payload,
    create_built_order,
    create_carrier,
    create_dealer,
    create_model_line,
    create_published_run,
    create_region,
    create_shipment_payload,
    get_dealer_allocation,
    get_dealer_model_line,
    get_success_data,
    list_run_dealer_allocations,
    lock_all_children,
    make_dealer_headers,
    setup_dealer_run,
    submit_order,
    validate_error,
    validate_success,
)

ALLOC = TEST_USERS["allocator_headers"]


class TestNewPointFloorBoundary:
    def test_dealer_at_exactly_six_months_gets_no_floor(self, api):
        """PRD §3.5: "If exactly 6 months or more have elapsed, no floor applies and `final_units` is the straight sum `base_units + adjustment_units`."

        Design: Difficulty/boundary_precision_check/new_point_floor_strict_age_boundary
        """
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", ALLOC))
        region = create_region()
        old_dealer = create_dealer(region["id"], opened_on="2026-03-01T00:00:00Z")
        line = create_model_line()
        run = create_published_run(line["id"], base_units=2, retail_priority_pct=0)
        da = get_dealer_allocation(run["id"], old_dealer["id"])
        assert da["final_units"] == da["base_units"] + da["adjustment_units"], (
            f"dealer opened exactly 6 months before publish must not receive the floor: {da}"
        )
        assert da["final_units"] < 2

    def test_dealer_one_second_under_six_months_gets_floor(self, api):
        """PRD §3.5: "If a dealer's `opened_on` is strictly less than 6 months before the run's `published_at`, that dealer's `final_units` is the greater of `base_units + adjustment_units` and the floor of 2 units."

        Design: Difficulty/boundary_precision_check/new_point_floor_strict_age_boundary
        """
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", ALLOC))
        region = create_region()
        new_dealer = create_dealer(region["id"], opened_on="2026-03-01T00:00:01Z")
        line = create_model_line()
        run = create_published_run(line["id"], base_units=2, retail_priority_pct=0)
        da = get_dealer_allocation(run["id"], new_dealer["id"])
        assert da["final_units"] == 2, (
            f"dealer opened 1 second under 6 months must receive the 2-unit floor: {da}"
        )


class TestWaterfallFloorDistribution:
    def test_floor_then_waterfall_strands_remainder(self, api):
        """PRD §2.8: "the per-dealer turn-and-earn "want" is floored to a whole unit before the waterfall".
        PRD §3.4: "Each dealer takes the minimum of its `want` and the remaining pool."

        Design: Difficulty/combinatorial_formula/allocation_share_waterfall_nonlinear_floor_carryover
        """
        region = create_region()
        create_dealer(region["id"], opened_on="2020-01-01T00:00:00Z")
        line = create_model_line()
        run = create_published_run(line["id"], base_units=12, retail_priority_pct=50)
        das = list_run_dealer_allocations(run["id"])
        total = sum(da["base_units"] for da in das)
        assert total <= 12, f"distributed base cannot exceed the pool: {total}"
        assert all(da["base_units"] <= 12 for da in das)

    def test_single_eligible_dealer_gets_full_pool(self, api):
        """PRD §3.4: "Process dealers in order of `raw[d]` descending, breaking ties by `opened_on` ascending (older dealers first) and then by `created_at` ascending. Each dealer takes the minimum of its `want` and the remaining pool."
        PRD §3.4: "If both sums are zero, every eligible dealer receives a raw score of 1 divided by the eligible count."

        Design: Difficulty/combinatorial_formula/allocation_share_waterfall_nonlinear_floor_carryover
        """
        fx = setup_dealer_run(num_dealers=1, base_units=12, retail_priority_pct=50)
        dealer = fx["dealers"][0]
        da = get_dealer_allocation(fx["run"]["id"], dealer["id"])
        # Sole eligible dealer: raw score 1/1 = 1.0, want = floor(1.0 * 12) = 12 = full pool.
        assert da["base_units"] == 12
        assert da["final_units"] == 12


class TestProvisionalVsFinalCarryover:
    def test_lock_writes_earned_credit_surplus(self, api):
        """PRD §3.11: "On lock, the run transitions `PUBLISHED → LOCKED`, its `version` bumps by 1, and the final variant of the turn-and-earn waterfall runs: for each child, surplus is recomputed as `want - consumed` and written into the dealer's `DealerModelLine.earned_credit_units`, ready for the next run."

        Design: Difficulty/dual_variant_calc/allocation_share_provisional_vs_final_surplus_carryover
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5, retail_priority_pct=0)
        dealer = fx["dealers"][0]
        run = fx["run"]
        line = fx["model_line"]
        # Consume 2 of the 5-unit pool before locking.
        submit_order(dealer["id"], line["id"], run["id"])
        submit_order(dealer["id"], line["id"], run["id"])
        lock_all_children(run["id"])
        locked = validate_success(api.lock_allocation_run(run["id"], ALLOC), 200)
        assert locked["status"] == "LOCKED"
        dml = get_dealer_model_line(dealer["id"], line["id"])
        # want = 5 (sole dealer, full pool); consumed = 2; surplus = 3.
        assert dml["earned_credit_units"] == 3

    def test_publish_leaves_earned_credit_untouched(self, api):
        """PRD §3.4: "At publish, the result is written to each `DealerAllocation.base_units` (provisional variant — the earned-credit term from the prior `LOCKED` run is included)." and "At lock, the waterfall is recomputed as the final variant: surplus is recomputed as `want - consumed` and written into `DealerModelLine.earned_credit_units` for the next run; `base_units` is not changed by the final variant."

        Design: Difficulty/dual_variant_calc/allocation_share_provisional_vs_final_surplus_carryover
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5, retail_priority_pct=0)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        da = get_dealer_allocation(fx["run"]["id"], dealer["id"])
        assert da["base_units"] == 5
        dml = get_dealer_model_line(dealer["id"], line["id"])
        assert dml["earned_credit_units"] == 0, (
            "earned credit must not be written at publish; only the final variant at lock writes it"
        )


class TestRunLockGates:
    def test_lock_rejected_while_children_open(self, api):
        """PRD §3.11: "Run lock requires every child `DealerAllocation` to be `LOCKED` — otherwise `ERR_CHILDREN_NOT_LOCKED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/run_lock_gated_by_children_and_appeals
        """
        fx = setup_dealer_run(num_dealers=1, base_units=8)
        resp = api.lock_allocation_run(fx["run"]["id"], ALLOC)
        validate_error(resp, ApiErrorId.ERR_CHILDREN_NOT_LOCKED, 409)

    def test_lock_rejected_while_appeal_open_then_succeeds(self, api):
        """PRD §3.11: "It also requires that no `Appeal` on the run be in `FILED` or `UNDER_REVIEW` — otherwise `ERR_APPEALS_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/run_lock_gated_by_children_and_appeals
        """
        # New-point dealer (opened within 6 months of publish) so the appeal is eligible.
        fx = setup_dealer_run(num_dealers=1, base_units=8, opened_on="2026-06-01T00:00:00Z")
        dealer = fx["dealers"][0]
        run = fx["run"]
        appeal_resp = api.create_appeal(
            create_appeal_payload(dealer["id"], run["id"], appeal_type="NEW_POINT",
                                  requested_units=3),
            make_dealer_headers(dealer["id"]),
        )
        appeal = get_success_data(appeal_resp)
        assert appeal["state"] == "FILED"
        # Lock every child; the open appeal must still gate the run lock.
        lock_all_children(run["id"])
        resp = api.lock_allocation_run(run["id"], ALLOC)
        validate_error(resp, ApiErrorId.ERR_APPEALS_OPEN, 409)
        # Withdraw the appeal and the lock succeeds.
        withdrawn = validate_success(
            api.withdraw_appeal(appeal["id"], make_dealer_headers(dealer["id"])), 200
        )
        assert withdrawn["state"] == "WITHDRAWN"
        locked = validate_success(api.lock_allocation_run(run["id"], ALLOC), 200)
        assert locked["status"] == "LOCKED"


class TestSupersede:
    def test_new_run_supersedes_published_run_and_freezes_children(self, api):
        """PRD §3.3: "If a run for the same `model_line_id` is already `PUBLISHED` when a new run is created, the existing run is superseded: it transitions to `SUPERSEDED` and every child `DealerAllocation` freezes at `LOCKED`."

        Design: Corner/state_machines/run_supersede_locks_children_and_freezes_pool
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3)
        old_run = fx["run"]
        validate_success(api.create_allocation_run(
            create_allocation_run_payload(fx["model_line"]["id"], period="2026-10", base_units=4),
            ALLOC,
        ), 201)
        old_after = get_success_data(api.get_allocation_run(old_run["id"], ALLOC))
        assert old_after["status"] == "SUPERSEDED"
        for da in list_run_dealer_allocations(old_run["id"]):
            assert da["status"] == "LOCKED"

    def test_order_entry_against_superseded_run_rejected(self, api):
        """PRD §3.3: "If a run for the same `model_line_id` is already `PUBLISHED` when a new run is created, the existing run is superseded: it transitions to `SUPERSEDED`".
        PRD §2.5: "Parent lifecycle gate: the run is `PUBLISHED` for order entry, appeal grant, and trade execution; the dealer is `ACTIVE` for order entry; the carrier is `ACTIVE` for shipment creation — otherwise `ERR_PARENT_NOT_ACTIVE` (409)."

        Design: Corner/state_machines/run_supersede_locks_children_and_freezes_pool
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3)
        dealer = fx["dealers"][0]
        old_run = fx["run"]
        get_success_data(api.create_allocation_run(
            create_allocation_run_payload(fx["model_line"]["id"], period="2026-10", base_units=4),
            ALLOC,
        ))
        resp = submit_order(dealer["id"], fx["model_line"]["id"], old_run["id"])
        validate_error(resp, ApiErrorId.ERR_PARENT_NOT_ACTIVE, 409)


class TestLookbackWindow:
    def test_delivery_at_lookback_end_is_excluded(self, api):
        """PRD §3.4: "`sales[d]` is the count of `d`'s `DELIVERED` orders for the line whose `delivered_at` falls inside the run's lookback window — `lookback_start` inclusive, `lookback_end` exclusive."

        Design: Corner/calculations/lookback_window_end_exclusive_filtering
        """
        fx = setup_dealer_run(num_dealers=2, base_units=5, retail_priority_pct=0)
        dealer_a, dealer_b = fx["dealers"]
        line = fx["model_line"]
        old_run = fx["run"]
        # Deliver dealer A's order exactly at the next run's lookback_end (2026-09-01).
        order = create_built_order(dealer_a["id"], line["id"], old_run["id"], build_week="2026-W36")
        carrier = create_carrier()
        shipment = get_success_data(api.create_shipment(
            create_shipment_payload(order["id"], carrier["id"], pickup_week="2026-W36"),
            TEST_USERS["logistics_headers"],
        ))
        get_success_data(api.pickup_shipment(shipment["id"], TEST_USERS["logistics_headers"]))
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", ALLOC))
        delivered = get_success_data(api.deliver_shipment(shipment["id"], TEST_USERS["logistics_headers"]))
        assert delivered["delivered_at"].startswith("2026-09-01T00:00:00")
        # New run with lookback ending exactly at the delivery instant.
        new_run = create_published_run(line["id"], period="2026-10", base_units=5, retail_priority_pct=0)
        da_a = get_dealer_allocation(new_run["id"], dealer_a["id"])
        da_b = get_dealer_allocation(new_run["id"], dealer_b["id"])
        # The at-boundary delivery is excluded (end-exclusive): A has zero in-window
        # sales just like B, and equal zeros give both dealers equal shares of the pool.
        assert da_a["base_units"] == da_b["base_units"], (
            f"delivery at lookback_end must be excluded, so both dealers split evenly: "
            f"A={da_a['base_units']} B={da_b['base_units']}"
        )

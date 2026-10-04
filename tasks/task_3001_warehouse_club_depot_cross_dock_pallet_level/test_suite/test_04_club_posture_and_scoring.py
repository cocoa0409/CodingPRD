"""Club posture ladder (capacity thresholds) and allocation priority scoring."""
import pytest

from test_helpers import (
    allocate_many,
    allocate_pallet,
    assert_club_invariants,
    book_appointment,
    check_in_appointment,
    create_active_item,
    create_club,
    create_depot,
    create_member,
    create_open_run,
    create_region,
    create_vendor,
    get_success_data,
    receive_pallet,
    record_purchase,
    setup_received_pallets,
    validate_success,
)
from test_helpers.fixtures import DP, RO


class TestPostureThresholdBoundary:
    def test_exactly_at_threshold_stays_normal(self, api):
        """PRD §3.4: "Short of that, it is `CONSTRAINED` when `allocated_slot_count` is strictly greater than
        the 80-percent threshold. Otherwise it is `NORMAL`."

        Design: Difficulty/boundary_precision_check/club_constrained_threshold_strict_greater_boundary
        """
        # Capacity 10: threshold = floor(10*80/100) = 8; 8 slots must keep NORMAL.
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=8, club_capacity=10)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        allocate_many(run["id"], run["version"], ctx["pallets"], ctx["club"]["id"])
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["allocated_slot_count"] == 8
        assert club["posture"] == "NORMAL", "8 is not strictly greater than 8"
        assert_club_invariants(club)

    def test_one_above_threshold_flips_to_constrained(self, api):
        """PRD §3.4: "Short of that, it is `CONSTRAINED` when `allocated_slot_count` is strictly greater than
        the 80-percent threshold. Otherwise it is `NORMAL`."

        Design: Difficulty/boundary_precision_check/club_constrained_threshold_strict_greater_boundary
        """
        # The 9th allocation lands while the club is still NORMAL, so no approval
        # flag is needed; the recompute then flips the club to CONSTRAINED.
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=9, club_capacity=10)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        allocate_many(run["id"], run["version"], ctx["pallets"], ctx["club"]["id"])
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["allocated_slot_count"] == 9
        assert club["posture"] == "CONSTRAINED", "9 > 8 must flip the club to CONSTRAINED"
        assert_club_invariants(club)


class TestPostureWalk:
    def test_posture_walks_normal_constrained_frozen_and_back(self, api):
        """PRD §3.4: "a club climbs and descends the ladder freely: `NORMAL` to `CONSTRAINED` when it crosses
        above the threshold, `CONSTRAINED` back to `NORMAL` when it falls to the
        threshold or below, `CONSTRAINED` to `FROZEN` at full capacity, `FROZEN` to
        `CONSTRAINED` when it drops strictly below capacity while remaining above the
        threshold, and `FROZEN` to `NORMAL` when it falls to the threshold or below."

        Design: Difficulty/non_linear_state_machine/club_posture_three_state_threshold_machine
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=10, club_capacity=10)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        # 8 allocations: still NORMAL (8 not > 8). 9th and 10th need the approval flag.
        allocs, version = allocate_many(run["id"], run["version"], ctx["pallets"], ctx["club"]["id"],
                                        approved_from_index=8)
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["posture"] == "FROZEN", "10 slots of capacity 10"
        assert club["allocated_slot_count"] == 10
        # Voiding one allocation drops the club to CONSTRAINED (9 > 8, < 10).
        validate_success(api.void_allocation(allocs[9]["id"], DP, payload={"void_reason": "free one slot"}))
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["posture"] == "CONSTRAINED", "FROZEN -> CONSTRAINED after the void"
        assert club["allocated_slot_count"] == 9
        assert_club_invariants(club)

    def test_posture_returns_to_normal_at_threshold(self, api):
        """PRD §3.4: "`CONSTRAINED` back to `NORMAL` when it falls to the threshold or below"

        Design: Difficulty/non_linear_state_machine/club_posture_three_state_threshold_machine
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=9, club_capacity=10)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        allocs, version = allocate_many(run["id"], run["version"], ctx["pallets"], ctx["club"]["id"],
                                        approved_from_index=8)
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["posture"] == "CONSTRAINED"
        # Void back down to exactly the threshold (8 of 10): posture returns to NORMAL.
        validate_success(api.void_allocation(allocs[8]["id"], DP, payload={"void_reason": "release"}))
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["posture"] == "NORMAL"
        assert club["allocated_slot_count"] == 8
        assert_club_invariants(club)


class TestAllocationScoring:
    def test_regular_item_uses_seven_day_velocity_window(self, api, regional_ops_headers):
        """PRD §3.3: "The **velocity** input is the total `unit_qty` over `COMPLETED` purchases of
        the pallet's item at the destination club whose `cap_window` falls within the trailing
        window — the seven days ending the day before `run_date` for a `REGULAR` item, or the
        three days ending the day before `run_date` for a `TREASURE_HUNT` item, whose shallower
        history demands the shorter window."
        PRD §3.3: "The `allocation_score` is the sum of velocity and a base of 10, multiplied by
        both factors, rounded half-up to four decimal places with intermediates unrounded."

        Design: Difficulty/dual_variant_calc/allocation_score_standard_vs_conservative_velocity_window
        """
        region = create_region(avg_member_income_cents=9000000)
        vendor = create_vendor()
        club = create_club(region["id"], member_base=100000)
        depot = create_depot(region["id"])
        item = create_active_item(vendor["id"])
        member = create_member(club["id"])
        # 10 units on 2026-09-03 (inside the 7-day window for a 2026-09-08 run)
        # plus 4 units on 2026-09-07: velocity 14 -> (14+10) * 1.25 * 1.135 = 34.05.
        api.set_clock("2026-09-03T12:00:00Z", regional_ops_headers)
        record_purchase(member["id"], club["id"], item["id"], 10)
        api.set_clock("2026-09-07T12:00:00Z", regional_ops_headers)
        record_purchase(member["id"], club["id"], item["id"], 4)
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-08", pallet_count=1)
        api.set_clock("2026-09-08T09:05:00Z", regional_ops_headers)
        check_in_appointment(appt["id"])
        pallet = receive_pallet(appt["id"], item["id"], 480)
        run = create_open_run(depot["id"], run_date="2026-09-08")
        alloc = allocate_pallet(run["id"], pallet["id"], club["id"], run["version"])
        assert alloc["allocation_score"] == pytest.approx(34.05, abs=1e-4), (
            f"(14 + 10) * 1.25 * 1.135 = 34.05, got {alloc['allocation_score']}"
        )

    def test_treasure_hunt_item_uses_three_day_velocity_window(self, api, regional_ops_headers):
        """PRD §3.3: "The **velocity** input is the total `unit_qty` over `COMPLETED` purchases of
        the pallet's item at the destination club whose `cap_window` falls within the trailing
        window — the seven days ending the day before `run_date` for a `REGULAR` item, or the
        three days ending the day before `run_date` for a `TREASURE_HUNT` item, whose shallower
        history demands the shorter window."
        PRD §3.3: "The `allocation_score` is the sum of velocity and a base of 10, multiplied by
        both factors, rounded half-up to four decimal places with intermediates unrounded."

        Design: Difficulty/dual_variant_calc/allocation_score_standard_vs_conservative_velocity_window
        """
        region = create_region(avg_member_income_cents=9000000)
        vendor = create_vendor()
        club = create_club(region["id"], member_base=100000)
        depot = create_depot(region["id"])
        item = create_active_item(vendor["id"], item_type="TREASURE_HUNT",
                                  exit_window_date="2026-09-30")
        member = create_member(club["id"])
        # The 10 units bought on 2026-09-03 fall OUTSIDE the 3-day window
        # (2026-09-05..2026-09-07) for a 2026-09-08 run; only the 4 units from
        # 2026-09-07 count: velocity 4 -> (4+10) * 1.25 * 1.135 = 19.8625.
        api.set_clock("2026-09-03T12:00:00Z", regional_ops_headers)
        record_purchase(member["id"], club["id"], item["id"], 10)
        api.set_clock("2026-09-07T12:00:00Z", regional_ops_headers)
        record_purchase(member["id"], club["id"], item["id"], 4)
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-08", pallet_count=1)
        api.set_clock("2026-09-08T09:05:00Z", regional_ops_headers)
        check_in_appointment(appt["id"])
        pallet = receive_pallet(appt["id"], item["id"], 480)
        run = create_open_run(depot["id"], run_date="2026-09-08")
        alloc = allocate_pallet(run["id"], pallet["id"], club["id"], run["version"])
        assert alloc["allocation_score"] == pytest.approx(19.8625, abs=1e-4), (
            f"(4 + 10) * 1.25 * 1.135 = 19.8625, got {alloc['allocation_score']}"
        )


class TestAllocationScoreCaps:
    def _setup_cap_pair(self, api, regional_ops_headers):
        """Two clubs at cap and one-below-cap on both inputs, two pallets, one OPEN run."""
        region_cap = create_region(avg_member_income_cents=20000000)
        region_under = create_region(avg_member_income_cents=19999999)
        vendor = create_vendor()
        club_cap = create_club(region_cap["id"], member_base=200000)
        club_under = create_club(region_under["id"], member_base=199999)
        depot = create_depot(region_cap["id"])
        item = create_active_item(vendor["id"])
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-08", pallet_count=2)
        api.set_clock("2026-09-08T09:05:00Z", regional_ops_headers)
        check_in_appointment(appt["id"])
        pallets = [receive_pallet(appt["id"], item["id"], 480) for _ in range(2)]
        run = create_open_run(depot["id"], run_date="2026-09-08")
        return club_cap, club_under, pallets, run

    def test_score_at_both_caps(self, api, regional_ops_headers):
        """PRD §3.3: "The **demographics factor** is 1 plus one-half times the club's
        `member_base` capped at 200000 members, divided by that cap. The **income factor** is 1
        plus three-tenths times the owning region's `avg_member_income_cents` capped at 20000000
        cents, divided by that cap. The `allocation_score` is the sum of velocity and a base of
        10, multiplied by both factors, rounded half-up to four decimal places with intermediates
        unrounded."

        Design: Difficulty/combinatorial_formula/allocation_score_multi_input_nonlinear_interaction
        """
        club_cap, club_under, pallets, run = self._setup_cap_pair(api, regional_ops_headers)
        alloc = allocate_pallet(run["id"], pallets[0]["id"], club_cap["id"], run["version"])
        # Zero velocity: (0+10) * 1.5 * 1.3 = 19.5 exactly at both caps.
        assert alloc["allocation_score"] == pytest.approx(19.5, abs=1e-4)

    def test_score_one_below_both_caps(self, api, regional_ops_headers):
        """PRD §3.3: "The **demographics factor** is 1 plus one-half times the club's
        `member_base` capped at 200000 members, divided by that cap. The **income factor** is 1
        plus three-tenths times the owning region's `avg_member_income_cents` capped at 20000000
        cents, divided by that cap. The `allocation_score` is the sum of velocity and a base of
        10, multiplied by both factors, rounded half-up to four decimal places with intermediates
        unrounded."

        Design: Difficulty/combinatorial_formula/allocation_score_multi_input_nonlinear_interaction
        """
        club_cap, club_under, pallets, run = self._setup_cap_pair(api, regional_ops_headers)
        alloc = allocate_pallet(run["id"], pallets[0]["id"], club_under["id"], run["version"])
        # (0+10) * (1 + (199999/200000)*0.5) * (1 + (19999999/20000000)*0.3) = 19.4999 (4 dp).
        assert alloc["allocation_score"] == pytest.approx(19.4999, abs=1e-4)

"""Cross-dock runs and allocations: commit/cancel lifecycles, cutoff, same-day
rule, capacity ladder, safety gates, OCC on run version, and immediate
consistency of allocation side effects."""
from test_helpers import (
    ApiErrorId,
    allocate_many,
    allocate_pallet,
    assert_club_invariants,
    create_active_item,
    create_club,
    create_depot,
    create_open_run,
    create_region,
    create_vendor,
    setup_received_pallets,
    setup_run_with_allocations,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DM, DP, RO


class TestRunCommit:
    def test_commit_transitions_allocations_and_pallets(self, api):
        """PRD §3.3: "Phase one moves every `PROPOSED` allocation to `COMMITTED`, locking each club's slot
        reservation — but if any destination club's posture is `FROZEN`, the entire
        commit fails with `ERR_CLUB_FROZEN` and no allocation transitions at all. Phase
        two then moves every `COMMITTED` allocation to `SHIPPED`, processing them in
        descending `allocation_score` with `created_at` ascending as the tie-break, and
        each shipped allocation's pallet moves from `ALLOCATED` to `SHIPPED`. The run
        itself lands in `COMMITTED`, `committed_at` is set, and the run's `version`
        increments by 1."

        Design: Corner/state_machines/run_commit_transitions_allocations_and_pallets
        """
        ctx = setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1)
        committed = validate_success(api.commit_run(ctx["run"]["id"], DP))
        assert committed["status"] == "COMMITTED"
        assert committed["committed_at"] is not None
        alloc = validate_success(api.get_allocation(ctx["allocations"][0]["id"], DP))
        assert alloc["status"] == "SHIPPED", f"PROPOSED -> COMMITTED -> SHIPPED, got {alloc['status']}"
        pallet = validate_success(api.get_pallet(ctx["pallets"][0]["id"], DP))
        assert pallet["status"] == "SHIPPED"


class TestRunCancel:
    def test_cancel_voids_proposed_allocations_and_frees_pallets(self, api):
        """PRD §3.3: "Cancelling an `OPEN` run moves it to `CANCELLED`, voids every `PROPOSED` allocation with
        `void_reason` set to the string `RUN_CANCELLED`, returns those pallets from
        `ALLOCATED` to `RECEIVED`, and decrements club slot counts with postures
        recomputed."

        Design: Corner/state_machines/run_cancel_voids_proposed_allocations_and_frees_pallets
        """
        ctx = setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1)
        cancelled = validate_success(api.cancel_run(ctx["run"]["id"], DP))
        assert cancelled["status"] == "CANCELLED"
        alloc = validate_success(api.get_allocation(ctx["allocations"][0]["id"], DP))
        assert alloc["status"] == "VOIDED"
        assert alloc["void_reason"] == "RUN_CANCELLED"
        pallet = validate_success(api.get_pallet(ctx["pallets"][0]["id"], DP))
        assert pallet["status"] == "RECEIVED"


class TestCutoff:
    def test_after_cutoff_allocation_and_commit_rejected(self, api, regional_ops_headers):
        """PRD §3.3: "The current logical time on the run date must be at or before the run's `cutoff_time` —
        equality is allowed — else `ERR_CUTOFF_PASSED` (HTTP 422); after the cutoff the
        run accepts neither allocations nor commits."

        Design: Corner/validations/cutoff_passed_rejects_allocation_and_commit
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=1)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02", cutoff_time="16:00")
        api.set_clock("2026-09-02T16:01:00Z", regional_ops_headers)
        resp = api.create_allocation(
            run["id"],
            {"pallet_id": ctx["pallets"][0]["id"], "club_id": ctx["club"]["id"],
             "expected_cross_dock_run_version": run["version"]},
            DP,
        )
        validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED)
        validate_error(api.commit_run(run["id"], DP), ApiErrorId.ERR_CUTOFF_PASSED)

    def test_exactly_at_cutoff_allocation_and_commit_allowed(self, api, regional_ops_headers):
        """PRD §3.3: "The current logical time on the run date must be at or before the run's `cutoff_time` —
        equality is allowed — else `ERR_CUTOFF_PASSED` (HTTP 422); after the cutoff the
        run accepts neither allocations nor commits."

        Design: Corner/validations/cutoff_passed_rejects_allocation_and_commit
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=1)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02", cutoff_time="16:00")
        api.set_clock("2026-09-02T16:00:00Z", regional_ops_headers)
        alloc = allocate_pallet(run["id"], ctx["pallets"][0]["id"], ctx["club"]["id"], run["version"])
        assert alloc["status"] == "PROPOSED"
        committed = validate_success(api.commit_run(run["id"], DP))
        assert committed["status"] == "COMMITTED"


class TestSameDayRule:
    def test_allocation_requires_same_day_run(self, api):
        """PRD §3.3: "The pallet's `received_date` must equal the run's `run_date` — same-day cross-dock only,
        no overnight holds — else `ERR_SAME_DAY_ONLY` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/pallet_allocation_requires_same_day_run_and_received_pallet
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=1)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-03")
        resp = api.create_allocation(
            run["id"],
            {"pallet_id": ctx["pallets"][0]["id"], "club_id": ctx["club"]["id"],
             "expected_cross_dock_run_version": run["version"]},
            DP,
        )
        validate_error(resp, ApiErrorId.ERR_SAME_DAY_ONLY)
        pallet = validate_success(api.get_pallet(ctx["pallets"][0]["id"], DP))
        assert pallet["status"] == "RECEIVED", "no allocation created; pallet stays RECEIVED"

    def test_same_day_allocation_succeeds(self, api):
        """PRD §3.3: "The pallet's `received_date` must equal the run's `run_date` — same-day cross-dock only,
        no overnight holds — else `ERR_SAME_DAY_ONLY` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/pallet_allocation_requires_same_day_run_and_received_pallet
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=1)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        alloc = allocate_pallet(run["id"], ctx["pallets"][0]["id"], ctx["club"]["id"], run["version"])
        assert alloc["status"] == "PROPOSED"
        pallet = validate_success(api.get_pallet(ctx["pallets"][0]["id"], DP))
        assert pallet["status"] == "ALLOCATED"


class TestStatePrecedence:
    def test_committed_run_allocation_returns_invalid_state_over_frozen_club(self, api):
        """PRD §2.9: "then state-machine admissibility (`ERR_INVALID_STATE`), and only then the
        business gates — safety gates, department enablement, frozen-club posture"
        PRD §3.3: "the run must be `OPEN` and the pallet must be `RECEIVED`, else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_allocation_on_committed_run_to_frozen_club
        """
        # Build a normal run with one allocation to a non-frozen club, commit it.
        ctx = setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1,
                                         club_capacity=10)
        committed = validate_success(api.commit_run(ctx["run"]["id"], DP))
        # Separately construct a FROZEN club (capacity 1, one allocation landing at capacity).
        frozen_ctx = setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1,
                                                club_capacity=1)
        frozen_club = validate_success(api.get_club(frozen_ctx["club"]["id"], DP))
        assert frozen_club["posture"] == "FROZEN"
        # Receive a fresh pallet under a new appointment on the run's date.
        from test_helpers import book_appointment, check_in_appointment, receive_pallet
        appt2 = book_appointment(ctx["depot"]["id"], ctx["vendor"]["id"], "2026-09-02",
                                 start_time="09:30", end_time="10:00", pallet_count=1)
        check_in_appointment(appt2["id"])
        pallet2 = receive_pallet(appt2["id"], ctx["item"]["id"], 480)
        # Allocation on the COMMITTED run to the FROZEN club must surface
        # ERR_INVALID_STATE (state machine gate) ahead of ERR_CLUB_FROZEN.
        resp = api.create_allocation(
            ctx["run"]["id"],
            {"pallet_id": pallet2["id"], "club_id": frozen_club["id"],
             "expected_cross_dock_run_version": committed["version"],
             "regional_ops_approved": True},
            DP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        pallet_after = validate_success(api.get_pallet(pallet2["id"], DP))
        assert pallet_after["status"] == "RECEIVED"

    def test_committed_run_rejects_allocation_even_to_normal_club(self, api):
        """PRD §2.9: "then state-machine admissibility (`ERR_INVALID_STATE`), and only then the
        business gates — safety gates, department enablement, frozen-club posture"
        PRD §3.3: "the run must be `OPEN` and the pallet must be `RECEIVED`, else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_allocation_on_committed_run_to_frozen_club
        """
        ctx = setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1)
        committed = validate_success(api.commit_run(ctx["run"]["id"], DP))
        from test_helpers import book_appointment, check_in_appointment, receive_pallet
        appt2 = book_appointment(ctx["depot"]["id"], ctx["vendor"]["id"], "2026-09-02",
                                 start_time="09:30", end_time="10:00", pallet_count=1)
        check_in_appointment(appt2["id"])
        pallet2 = receive_pallet(appt2["id"], ctx["item"]["id"], 480)
        resp = api.create_allocation(
            ctx["run"]["id"],
            {"pallet_id": pallet2["id"], "club_id": ctx["club"]["id"],
             "expected_cross_dock_run_version": committed["version"]},
            DP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAggregateCapacity:
    def test_allocation_above_capacity_rejected_landing_at_capacity_allowed(self, api):
        """PRD §3.3: "Finally, the allocation must not push the club's `allocated_slot_count` above its
        `floor_slot_capacity`; landing exactly at capacity is allowed, but exceeding it
        is rejected with `ERR_CLUB_CAPACITY_EXCEEDED` (HTTP 422) because there is no
        backroom."
        PRD §3.4: "A club is `FROZEN` when its `allocated_slot_count` is at least its
        `floor_slot_capacity`."

        Design: Difficulty/resource_temporal_overlap/club_floor_slot_aggregate_capacity_overlap
        """
        # Oversized item: 48x48 footprint -> pallets_per_slot 2, pallet_qty 8.
        ctx = setup_received_pallets(
            delivery_date="2026-09-02", num_pallets=2, club_capacity=3,
            item_overrides={"case_pack_qty": 2, "pallet_length_in": 48, "pallet_width_in": 48,
                            "cases_per_layer": 2, "max_layers": 2},
        )
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        alloc1 = allocate_pallet(run["id"], ctx["pallets"][0]["id"], ctx["club"]["id"], run["version"])
        assert alloc1["floor_slots_reserved"] == 2, "48x48 = 2304 > 1920 standard slot"
        # Second big pallet would reach 2 + 2 = 4 > 3: rejected.
        resp = api.create_allocation(
            run["id"],
            {"pallet_id": ctx["pallets"][1]["id"], "club_id": ctx["club"]["id"],
             "expected_cross_dock_run_version": alloc1["run_version"]},
            DP,
        )
        validate_error(resp, ApiErrorId.ERR_CLUB_CAPACITY_EXCEEDED)
        # The failed allocation did not advance the run version, so the small
        # pallet reuses the same expected version and lands exactly at capacity.
        ctx2_item = create_active_item(ctx["vendor"]["id"])  # pallets_per_slot 1
        from test_helpers import receive_pallet
        small = receive_pallet(ctx["appointment"]["id"], ctx2_item["id"], 480)
        alloc2 = allocate_pallet(run["id"], small["id"], ctx["club"]["id"], alloc1["run_version"])
        assert alloc2["floor_slots_reserved"] == 1
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["allocated_slot_count"] == 3
        assert club["posture"] == "FROZEN"
        assert_club_invariants(club)

    def test_failed_allocation_does_not_consume_capacity(self, api):
        """PRD §3.3: "Finally, the allocation must not push the club's `allocated_slot_count` above its
        `floor_slot_capacity`; landing exactly at capacity is allowed, but exceeding it
        is rejected with `ERR_CLUB_CAPACITY_EXCEEDED` (HTTP 422) because there is no
        backroom."

        Design: Difficulty/resource_temporal_overlap/club_floor_slot_aggregate_capacity_overlap
        """
        ctx = setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1,
                                         club_capacity=1)
        run = ctx["run"]
        # First allocation took the single slot. A second pallet over capacity is rejected.
        from test_helpers import book_appointment, check_in_appointment, receive_pallet
        appt2 = book_appointment(ctx["depot"]["id"], ctx["vendor"]["id"], "2026-09-02",
                                 start_time="09:30", end_time="10:00", pallet_count=1)
        check_in_appointment(appt2["id"])
        pallet2 = receive_pallet(appt2["id"], ctx["item"]["id"], 480)
        resp = api.create_allocation(
            run["id"],
            {"pallet_id": pallet2["id"], "club_id": ctx["club"]["id"],
             "expected_cross_dock_run_version": ctx["run_version"]},
            DP,
        )
        validate_error(resp, ApiErrorId.ERR_CLUB_FROZEN)


class TestConstrainedSafetyGate:
    def test_constrained_club_requires_regional_ops_approval(self, api):
        """PRD §3.3: "If the destination club is `CONSTRAINED`, the request must carry `regional_ops_approved`
        set to true, else `ERR_SAFETY_GATE` (HTTP 422)."
        PRD §3.4: "Short of that, it is `CONSTRAINED` when `allocated_slot_count` is strictly greater than
        the 80-percent threshold."

        Design: Corner/validations/allocation_to_constrained_club_requires_approval_flag
        """
        # Capacity 10: 9 allocations put the club at CONSTRAINED (9 > floor(10*80/100) = 8).
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=10, club_capacity=10)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        allocs, version = allocate_many(run["id"], run["version"], ctx["pallets"][:9],
                                        ctx["club"]["id"])
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["posture"] == "CONSTRAINED"
        # Without the approval flag the 10th allocation is gated.
        resp = api.create_allocation(
            run["id"],
            {"pallet_id": ctx["pallets"][9]["id"], "club_id": ctx["club"]["id"],
             "expected_cross_dock_run_version": version},
            DP,
        )
        validate_error(resp, ApiErrorId.ERR_SAFETY_GATE)
        # With the flag it succeeds and the club becomes FROZEN at 10 slots.
        alloc10 = allocate_pallet(run["id"], ctx["pallets"][9]["id"], ctx["club"]["id"],
                                  version, regional_ops_approved=True)
        assert alloc10["status"] == "PROPOSED"
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["posture"] == "FROZEN"
        assert club["allocated_slot_count"] == 10


class TestRunVersionOcc:
    def test_stale_run_version_rejected(self, api):
        """PRD §2.7: "When proposing an allocation into a cross-dock run (identified by the `run_id` path
        parameter), the request must carry `expected_cross_dock_run_version` holding the
        client-observed `version` of the parent run. If the run's current `version`
        differs — because another writer has since added an allocation, voided one, or
        committed the run — the request is rejected with `ERR_STALE_RUN_VERSION` (HTTP
        412), since the client's view of remaining club capacity is stale."

        Design: Corner/endpoints/stale_run_version_occ_conflict
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=2)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        allocate_pallet(run["id"], ctx["pallets"][0]["id"], ctx["club"]["id"], run["version"])
        resp = api.create_allocation(
            run["id"],
            {"pallet_id": ctx["pallets"][1]["id"], "club_id": ctx["club"]["id"],
             "expected_cross_dock_run_version": run["version"]},
            DP,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_RUN_VERSION)

    def test_run_version_increments_on_allocation_and_commit(self, api):
        """PRD §3.3: "Three cascades fire atomically with the proposal: the pallet moves from `RECEIVED` to
        `ALLOCATED`; the club's `allocated_slot_count` increases by
        `floor_slots_reserved` and its `posture` is recomputed (§3.4); and the parent
        run's `version` increments by 1."
        PRD §3.3: "The run itself lands in `COMMITTED`, `committed_at` is set, and the run's `version`
        increments by 1."
        PRD §2.4: "a `version` integer that starts at 1 and increments by exactly 1 on every mutation of
        that entity."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=1)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        assert run["version"] == 1, f"run version starts at 1, got {run['version']}"
        alloc = allocate_pallet(run["id"], ctx["pallets"][0]["id"], ctx["club"]["id"], run["version"])
        assert alloc["run_version"] == 2, (
            f"run_version echoes the parent run's version after this write, got {alloc['run_version']}"
        )
        committed = validate_success(api.commit_run(run["id"], DP))
        assert committed["version"] == 3, f"commit increments the run version, got {committed['version']}"


class TestImmediateConsistency:
    def test_allocation_side_effects_visible_immediately(self, api):
        """PRD §3.3: "Three cascades fire atomically with the proposal: the pallet moves from `RECEIVED` to
        `ALLOCATED`; the club's `allocated_slot_count` increases by
        `floor_slots_reserved` and its `posture` is recomputed (§3.4); and the parent
        run's `version` increments by 1."

        Design: Corner/consistency_model/immediate_consistency_of_cascade_effects
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=1)
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        allocate_pallet(run["id"], ctx["pallets"][0]["id"], ctx["club"]["id"], run["version"])
        pallet = validate_success(api.get_pallet(ctx["pallets"][0]["id"], DP))
        assert pallet["status"] == "ALLOCATED", "visible on the very next read"
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["allocated_slot_count"] == 1, "slot count incremented with no consistency lag"
        assert_club_invariants(club)

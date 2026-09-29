"""Coil lots, roll-forming line time and the steel mass ledger: the quarantine gate,
half-open line windows with their coating changeover buffer, and the void compensation."""

import pytest
from test_helpers import (
    LOGISTICS,
    PLANNER,
    assert_coil_lot_status_follows_ledger,
    assert_coil_mass_conservation,
    assert_empty_load_totals,
    assert_version_advanced_by,
    complete_run,
    complete_run_payload,
    create_design,
    create_design_under_review,
    create_freight_load_payload,
    create_roll_forming_run_payload,
    determine_failure,
    place_order,
    read_coil_lot,
    read_dealer,
    read_order,
    read_run,
    receive_coil_lot,
    setup_coating_quarantine_chain,
    setup_depleted_coil_lot,
    setup_line_window_anchor,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
    void_run,
)


def runs_on_lot(api, lot_id):
    """Every run standing against one coil lot, newest page first."""
    return validate_paginated(
        api.list_roll_forming_runs(
            PLANNER, {"coil_lot_id": lot_id, "limit": 10, "offset": 0}
        )
    )


class TestQuarantinedLotBlocksRunScheduling:
    def test_a_coating_determination_quarantines_the_lot_and_bars_the_next_run(
        self, api
    ):
        """PRD §3.9: "`COATING_INADEQUATE` quarantines coil: every lot whose `coating_spec_id`
        equals the failed design's `coating_spec_id` and whose `status` is `AVAILABLE` or `DEPLETED`
        moves to `QUARANTINED` as the first hop, and `QUARANTINED` is terminal for a lot regardless
        of how much mass it still holds."
        PRD §3.9: "The second hop, caused by each lot entering `QUARANTINED`, moves every one of
        that lot's runs whose `status` is `SCHEDULED` to `VOIDED`; the third hop drops each voided
        run's `planned_kg` out of that lot's `reserved_kg` and recomputes `remaining_kg`, so the
        conservation identity still holds afterwards."
        PRD §3.9: "First, a `CORROSION_PERFORATION` yields `COATING_INADEQUATE` when the
        `corrosion_verdict` is `EXCEEDS_CLASS`, and `OVERLOAD_MISUSE` otherwise."
        PRD §3.7: "The lot's `status` must be `AVAILABLE`; a `DEPLETED` or `QUARANTINED` lot is
        refused with `ERR_COIL_LOT_NOT_AVAILABLE`."
        PRD §3.9: "The `corrosion_verdict` is `EXCEEDS_CLASS` when the `measured_coating_loss_pct`
        is strictly greater than the loss limit for the design's coating class, and `WITHIN_CLASS`
        otherwise; the limits are 25.0 percent for `C2`, 40.0 for `C3`, 55.0 for `C4` and 70.0 for
        `C5`, and a loss exactly equal to the limit is `WITHIN_CLASS`."

        Design: Difficulty/cross_entity_state_dependency/roll_forming_run_create_blocked_when_coil_lot_is_quarantined_by_a_coating_determination
        """
        env = setup_coating_quarantine_chain()
        ref, order, lot, run = env["ref"], env["order"], env["matched_lot"], env["run"]
        before = read_coil_lot(lot["id"])
        assert before["status"] == "AVAILABLE"
        assert before["reserved_kg"] == pytest.approx(6600.0, abs=0.005)
        assert before["remaining_kg"] == pytest.approx(13400.0, abs=0.005)
        assert read_run(run["id"])["status"] == "SCHEDULED"
        assert read_run(run["id"])["coating_code"] == "G115"
        assert env["failure"]["corrosion_verdict"] == "EXCEEDS_CLASS"
        assert env["failure"]["structural_verdict"] == "WITHIN_DESIGN"

        determined = determine_failure(env["failure"])
        assert determined["determined_cause"] == "COATING_INADEQUATE"

        quarantined = read_coil_lot(lot["id"])
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["reserved_kg"] == pytest.approx(0.0, abs=0.005)
        assert quarantined["remaining_kg"] == pytest.approx(20000.0, abs=0.005)
        assert_coil_mass_conservation(quarantined)
        assert read_run(run["id"])["status"] == "VOIDED"

        # The gate reads the lot's status alone: gauge and mass are both fine.
        rejected = api.create_roll_forming_run(
            create_roll_forming_run_payload(
                ref["lines"]["LINE_A"]["id"],
                lot["id"],
                order["id"],
                "2026-08-04T08:00:00Z",
                "2026-08-04T12:00:00Z",
                6600,
            ),
            PLANNER,
        )
        validate_error(rejected, "ERR_COIL_LOT_NOT_AVAILABLE", 409)
        after = read_coil_lot(lot["id"])
        assert after["status"] == "QUARANTINED"
        assert after["remaining_kg"] == pytest.approx(20000.0, abs=0.005)
        assert read_order(order["id"])["production_status"] == "QUEUED"

    def test_the_quarantine_is_coating_scoped_so_the_other_lot_still_takes_a_run(
        self, api
    ):
        """PRD §3.9: "`COATING_INADEQUATE` quarantines coil: every lot whose `coating_spec_id`
        equals the failed design's `coating_spec_id` and whose `status` is `AVAILABLE` or `DEPLETED`
        moves to `QUARANTINED` as the first hop, and `QUARANTINED` is terminal for a lot regardless
        of how much mass it still holds."
        PRD §3.7: "The lot's coating designation is copied onto the run as `coating_code` at
        creation and is used thereafter for changeover comparisons rather than re-reading the
        coating specification."
        PRD §3.7: "A newly booked run begins with `status` `SCHEDULED` and with `consumed_kg` and
        `scrap_kg` both 0; nothing has yet been drawn from the coil, only reserved."
        PRD §3.7: "The `reserved_kg` is the sum of `planned_kg` over that lot's runs whose `status`
        is `SCHEDULED`, rounded half up to 2 decimal places."

        Design: Difficulty/cross_entity_state_dependency/roll_forming_run_create_blocked_when_coil_lot_is_quarantined_by_a_coating_determination
        """
        env = setup_coating_quarantine_chain()
        ref, order = env["ref"], env["order"]
        other = env["other_lot"]
        determine_failure(env["failure"])

        untouched = read_coil_lot(other["id"])
        assert untouched["status"] == "AVAILABLE"
        assert untouched["remaining_kg"] == pytest.approx(20000.0, abs=0.005)

        scheduled = validate_success(
            api.create_roll_forming_run(
                create_roll_forming_run_payload(
                    ref["lines"]["LINE_A"]["id"],
                    other["id"],
                    order["id"],
                    "2026-08-04T08:00:00Z",
                    "2026-08-04T12:00:00Z",
                    6600,
                ),
                PLANNER,
            ),
            201,
        )
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["coating_code"] == "G90"
        assert scheduled["consumed_kg"] == pytest.approx(0.0, abs=0.005)
        assert scheduled["scrap_kg"] == pytest.approx(0.0, abs=0.005)

        reserved = read_coil_lot(other["id"])
        assert reserved["reserved_kg"] == pytest.approx(6600.0, abs=0.005)
        assert reserved["remaining_kg"] == pytest.approx(13400.0, abs=0.005)
        assert reserved["status"] == "AVAILABLE"
        assert_coil_mass_conservation(reserved)
        assert read_order(order["id"])["production_status"] == "QUEUED"


class TestLineWindowAdjacencyAndChangeover:
    def test_same_coating_touches_at_both_ends_but_a_true_overlap_still_conflicts(
        self, api
    ):
        """PRD §3.7: "A new run's window must not intersect the half-open window of any run already
        on the same line whose `status` is `SCHEDULED` or `COMPLETED`; voided runs release their line
        time and are ignored."
        PRD §3.7: "Because the intervals are half-open, zero-gap adjacency is geometrically legal: a
        new run may start at the exact instant an existing run ends, or end at the exact instant an
        existing run starts."
        PRD §3.7: "That adjacency is permitted **only when the two runs carry the same**
        `coating_code`."
        PRD §3.7: "A conflict of either kind, an overlap or an under-buffered changeover, is refused
        with `ERR_LINE_WINDOW_CONFLICT`."
        PRD §3.7: "The `reserved_kg` is the sum of `planned_kg` over that lot's runs whose `status`
        is `SCHEDULED`, rounded half up to 2 decimal places."

        Design: Difficulty/resource_temporal_overlap/roll_forming_line_half_open_adjacency_allowed_within_a_coating_but_changeover_buffer_required_across_coatings
        """
        env = setup_line_window_anchor()
        ref, order, lot = env["ref"], env["order"], env["same_lot"]
        line_id = ref["lines"]["LINE_A"]["id"]

        def book(start, end, kg=6600, coil=None):
            return api.create_roll_forming_run(
                create_roll_forming_run_payload(
                    line_id, (coil or lot)["id"], order["id"], start, end, kg
                ),
                PLANNER,
            )

        # Strictly interior to the anchor: an overlap, regardless of matching coating.
        validate_error(
            book("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z"),
            "ERR_LINE_WINDOW_CONFLICT",
            409,
        )
        assert read_coil_lot(lot["id"])["reserved_kg"] == pytest.approx(
            6600.0, abs=0.005
        )

        # Starts at the exact instant the anchor ends, same coating: legal.
        tail = validate_success(
            book("2026-08-03T12:00:00Z", "2026-08-03T16:00:00Z"), 201
        )
        assert tail["status"] == "SCHEDULED"
        assert tail["coating_code"] == "G115"
        after_tail = read_coil_lot(lot["id"])
        assert after_tail["reserved_kg"] == pytest.approx(13200.0, abs=0.005)
        assert after_tail["remaining_kg"] == pytest.approx(6800.0, abs=0.005)
        assert_coil_mass_conservation(after_tail)

        # Ends at the exact instant the anchor starts, same coating: also legal.
        head = validate_success(
            book("2026-08-03T04:00:00Z", "2026-08-03T08:00:00Z"), 201
        )
        assert head["status"] == "SCHEDULED"
        final = read_coil_lot(lot["id"])
        assert final["reserved_kg"] == pytest.approx(19800.0, abs=0.005)
        assert final["remaining_kg"] == pytest.approx(200.0, abs=0.005)
        assert final["status"] == "AVAILABLE"
        assert_coil_lot_status_follows_ledger(final)

        rows, meta = runs_on_lot(api, lot["id"])
        assert meta["total_count"] == 3
        assert all(r["status"] == "SCHEDULED" for r in rows)

    def test_a_different_coating_must_clear_its_own_changeover_buffer_to_the_minute(
        self, api
    ):
        """PRD §3.7: "When the coatings differ, the line needs a purge, and a gap of at least the
        incoming run's coating `changeover_minutes` is required on the touching side — the effective
        forbidden zone is the existing window expanded by that changeover buffer."
        PRD §3.7: "That adjacency is permitted **only when the two runs carry the same**
        `coating_code`."
        PRD §3.7: "A conflict of either kind, an overlap or an under-buffered changeover, is refused
        with `ERR_LINE_WINDOW_CONFLICT`."
        PRD §3.7: "The lot's coating designation is copied onto the run as `coating_code` at
        creation and is used thereafter for changeover comparisons rather than re-reading the
        coating specification."

        Design: Difficulty/resource_temporal_overlap/roll_forming_line_half_open_adjacency_allowed_within_a_coating_but_changeover_buffer_required_across_coatings
        """
        env = setup_line_window_anchor()
        ref, order = env["ref"], env["order"]
        other = env["other_lot"]
        line_id = ref["lines"]["LINE_A"]["id"]
        assert ref["coating_specs"]["G90"]["changeover_minutes"] == 90

        def book(start, end):
            return api.create_roll_forming_run(
                create_roll_forming_run_payload(
                    line_id, other["id"], order["id"], start, end, 6600
                ),
                PLANNER,
            )

        # Zero-gap on the trailing side would be legal within one coating; across
        # coatings it lands inside the anchor's 90-minute purge extension.
        validate_error(
            book("2026-08-03T12:00:00Z", "2026-08-03T16:00:00Z"),
            "ERR_LINE_WINDOW_CONFLICT",
            409,
        )
        # Zero-gap on the leading side is refused for the same reason.
        validate_error(
            book("2026-08-03T04:00:00Z", "2026-08-03T08:00:00Z"),
            "ERR_LINE_WINDOW_CONFLICT",
            409,
        )
        # 89 minutes after the anchor ends: one minute short of the buffer.
        validate_error(
            book("2026-08-03T13:29:00Z", "2026-08-03T17:29:00Z"),
            "ERR_LINE_WINDOW_CONFLICT",
            409,
        )
        assert read_coil_lot(other["id"])["reserved_kg"] == pytest.approx(
            0.0, abs=0.005
        )

        # Exactly 90 minutes clears the purge.
        purged = validate_success(
            book("2026-08-03T13:30:00Z", "2026-08-03T17:30:00Z"), 201
        )
        assert purged["status"] == "SCHEDULED"
        assert purged["coating_code"] == "G90"
        booked = read_coil_lot(other["id"])
        assert booked["reserved_kg"] == pytest.approx(6600.0, abs=0.005)
        assert booked["remaining_kg"] == pytest.approx(13400.0, abs=0.005)
        assert_coil_mass_conservation(booked)

        rows, meta = validate_paginated(
            api.list_roll_forming_runs(
                PLANNER,
                {"roll_forming_line_id": line_id, "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2
        assert sorted(r["coating_code"] for r in rows) == ["G115", "G90"]


class TestVoidRestoresTheCoilMassLedger:
    def test_voiding_a_scheduled_run_lifts_the_lot_out_of_depleted_and_spares_the_order(
        self, api
    ):
        """PRD §3.7: "A run in `SCHEDULED` moving to `VOIDED` releases only its reservation: the
        lot's `reserved_kg` drops by that run's `planned_kg` and `remaining_kg` is recomputed, and
        the order is deliberately left alone because a merely scheduled run never advanced it to
        `KITTED`; only the run and the lot bump `version`."
        PRD §3.7: "Otherwise the lot is `DEPLETED` when `remaining_kg` has reached exactly 0 and
        `AVAILABLE` whenever `remaining_kg` is above 0."
        PRD §3.7: "The two directions are both live system transitions: a scheduling or completion
        recomputation that drives `remaining_kg` to 0 moves the lot `AVAILABLE` to `DEPLETED`, and a
        void recomputation that lifts `remaining_kg` back above 0 moves it `DEPLETED` to
        `AVAILABLE`."
        PRD §3.7: "After every forward and every compensating action the conservation identity must
        hold with zero drift: a lot's `received_kg` equals the sum of its `remaining_kg`,
        `reserved_kg`, `consumed_kg` and `scrap_kg`."

        Design: Difficulty/compensating_invariant/voiding_a_completed_run_restores_the_coil_lot_steel_mass_conservation_identity_with_zero_drift
        """
        env = setup_depleted_coil_lot()
        lot_before = read_coil_lot(env["lot"]["id"])
        assert lot_before["received_kg"] == pytest.approx(20000.0, abs=0.005)
        assert lot_before["reserved_kg"] == pytest.approx(20000.0, abs=0.005)
        assert lot_before["consumed_kg"] == pytest.approx(0.0, abs=0.005)
        assert lot_before["scrap_kg"] == pytest.approx(0.0, abs=0.005)
        assert lot_before["remaining_kg"] == pytest.approx(0.0, abs=0.005)
        assert lot_before["status"] == "DEPLETED"
        assert_coil_mass_conservation(lot_before)
        order_before = read_order(env["order"]["id"])
        assert order_before["production_status"] == "QUEUED"

        voided = void_run(env["second_run"])
        assert voided["status"] == "VOIDED"
        assert voided["planned_kg"] == pytest.approx(13400.0, abs=0.005)
        assert_version_advanced_by(voided, env["second_run"], 1, "run")

        lot_after = read_coil_lot(env["lot"]["id"])
        assert lot_after["reserved_kg"] == pytest.approx(6600.0, abs=0.005)
        assert lot_after["remaining_kg"] == pytest.approx(13400.0, abs=0.005)
        assert lot_after["consumed_kg"] == pytest.approx(0.0, abs=0.005)
        assert lot_after["scrap_kg"] == pytest.approx(0.0, abs=0.005)
        assert lot_after["status"] == "AVAILABLE"
        assert_coil_mass_conservation(lot_after)
        assert_coil_lot_status_follows_ledger(lot_after)

        # The scheduled-void path never touches the order.
        order_after = read_order(env["order"]["id"])
        assert order_after["production_status"] == "QUEUED"
        assert order_after["version"] == order_before["version"]
        assert read_run(env["first_run"]["id"])["status"] == "SCHEDULED"

    def test_voiding_a_completed_run_returns_both_masses_and_then_admits_nothing(
        self, api
    ):
        """PRD §3.7: "A run in `COMPLETED` moving to `VOIDED` has its `consumed_kg` and `scrap_kg`
        reset to 0, releases both its consumption and its reservation back into the lot's ledger, and
        reverts its order's `production_status` from `KITTED` back to `QUEUED`; the run, the lot and
        the order all bump `version` by 1."
        PRD §3.7: "On success the run moves `SCHEDULED` to `COMPLETED`, the two masses are stored on
        the run, the lot's ledger is recomputed, and the run's order advances its
        `production_status` from `QUEUED` to `KITTED`."
        PRD §3.7: "Voided runs contribute nothing to any of the four sums, because voiding both
        zeroes the two posted masses and removes the row from the scheduled set."
        PRD §3.7: "After every forward and every compensating action the conservation identity must
        hold with zero drift: a lot's `received_kg` equals the sum of its `remaining_kg`,
        `reserved_kg`, `consumed_kg` and `scrap_kg`."
        PRD §3.7: "A run already in `VOIDED` admits nothing and is refused with
        `ERR_RUN_STATE_INVALID`."

        Design: Difficulty/compensating_invariant/voiding_a_completed_run_restores_the_coil_lot_steel_mass_conservation_identity_with_zero_drift
        """
        env = setup_depleted_coil_lot()
        lot_id, order_id = env["lot"]["id"], env["order"]["id"]
        void_run(env["second_run"])

        completed = complete_run(env["first_run"], 6410.4, 152.3)
        assert completed["status"] == "COMPLETED"
        assert completed["consumed_kg"] == pytest.approx(6410.4, abs=0.005)
        assert completed["scrap_kg"] == pytest.approx(152.3, abs=0.005)
        kitted_lot = read_coil_lot(lot_id)
        assert kitted_lot["reserved_kg"] == pytest.approx(0.0, abs=0.005)
        assert kitted_lot["consumed_kg"] == pytest.approx(6410.4, abs=0.005)
        assert kitted_lot["scrap_kg"] == pytest.approx(152.3, abs=0.005)
        assert kitted_lot["remaining_kg"] == pytest.approx(13437.3, abs=0.005)
        assert kitted_lot["status"] == "AVAILABLE"
        assert_coil_mass_conservation(kitted_lot)
        kitted_order = read_order(order_id)
        assert kitted_order["production_status"] == "KITTED"

        reverted = void_run(completed)
        assert reverted["status"] == "VOIDED"
        assert reverted["consumed_kg"] == pytest.approx(0.0, abs=0.005)
        assert reverted["scrap_kg"] == pytest.approx(0.0, abs=0.005)
        # The reservation intent survives on the run; only the ledger sums drop it.
        assert reverted["planned_kg"] == pytest.approx(6600.0, abs=0.005)
        assert_version_advanced_by(reverted, completed, 1, "run")

        restored = read_coil_lot(lot_id)
        assert restored["reserved_kg"] == pytest.approx(0.0, abs=0.005)
        assert restored["consumed_kg"] == pytest.approx(0.0, abs=0.005)
        assert restored["scrap_kg"] == pytest.approx(0.0, abs=0.005)
        assert restored["remaining_kg"] == pytest.approx(20000.0, abs=0.005)
        assert restored["status"] == "AVAILABLE"
        assert_coil_mass_conservation(restored)
        assert_coil_lot_status_follows_ledger(restored)
        back = read_order(order_id)
        assert back["production_status"] == "QUEUED"
        assert_version_advanced_by(back, kitted_order, 1, "order")

        replay = api.void_roll_forming_run(completed["id"], PLANNER)
        validate_error(replay, "ERR_RUN_STATE_INVALID", 409)
        assert read_coil_lot(lot_id)["remaining_kg"] == pytest.approx(
            20000.0, abs=0.005
        )


class TestSchedulingGateOrder:
    def test_a_gauge_mismatch_is_reported_before_the_line_cannot_carry_the_gauge(
        self, api
    ):
        """PRD §3.7: "The lot's `gauge_mm` must equal the `sheet_gauge_mm` of the design behind the
        named order, and a mismatch is refused with `ERR_COIL_GAUGE_MISMATCH` — the plant does not
        form a 1.6 millimetre design out of 2.0 millimetre coil even though the heavier coil would be
        stronger."
        PRD §3.7: "The design's `sheet_gauge_mm` must be no greater than the line's `max_gauge_mm`,
        or the request is refused with `ERR_GAUGE_EXCEEDS_LINE_CAPACITY`."
        PRD §2.11: "18. Coil gauge against the design's required sheet gauge, on run scheduling —
        `ERR_COIL_GAUGE_MISMATCH`, 422."
        PRD §2.11: "25. Sheet gauge against line capability, on run scheduling —
        `ERR_GAUGE_EXCEEDS_LINE_CAPACITY`, 422."
        PRD §3.7: "Runs may be listed and narrowed by `roll_forming_line_id`, `coil_lot_id` or
        `dealer_order_id`."

        Design: Corner/validations/coil_gauge_match_outranks_the_line_gauge_capacity_check
        """
        env = setup_line_window_anchor()
        ref, order = env["ref"], env["order"]
        assert env["design"]["sheet_gauge_mm"] == pytest.approx(1.6, abs=1e-9)
        assert ref["lines"]["LINE_LOW"]["max_gauge_mm"] == pytest.approx(1.3, abs=1e-9)
        thick = receive_coil_lot(ref, coating="G115", heat_number="H-99", gauge_mm=2.0)
        thin = receive_coil_lot(ref, coating="G115", heat_number="H-98", gauge_mm=1.6)

        def book(line, coil):
            return api.create_roll_forming_run(
                create_roll_forming_run_payload(
                    ref["lines"][line]["id"],
                    coil["id"],
                    order["id"],
                    "2026-08-05T08:00:00Z",
                    "2026-08-05T12:00:00Z",
                    6600,
                ),
                PLANNER,
            )

        # Both defects at once — the 2.0 mm coil does not match the 1.6 mm design and
        # the 1.6 mm design overruns LINE_LOW's 1.3 mm ceiling. Step 18 wins.
        validate_error(book("LINE_LOW", thick), "ERR_COIL_GAUGE_MISMATCH", 422)
        # With the gauge matched the line capability check finally surfaces.
        validate_error(book("LINE_LOW", thin), "ERR_GAUGE_EXCEEDS_LINE_CAPACITY", 422)
        assert read_coil_lot(thin["id"])["reserved_kg"] == pytest.approx(0.0, abs=0.005)

        booked = validate_success(book("LINE_A", thin), 201)
        assert booked["status"] == "SCHEDULED"
        assert booked["coating_code"] == "G115"
        held = read_coil_lot(thin["id"])
        assert held["reserved_kg"] == pytest.approx(6600.0, abs=0.005)
        assert held["remaining_kg"] == pytest.approx(13400.0, abs=0.005)
        assert_coil_mass_conservation(held)

        rows, meta = runs_on_lot(api, thin["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == booked["id"]
        assert runs_on_lot(api, thick["id"])[1]["total_count"] == 0


class TestWindowOrderSemanticsDifferByResource:
    def test_a_zero_length_line_window_is_illegal_while_a_zero_length_yard_window_is_not(
        self, api
    ):
        """PRD §3.7: "The `window_end` must be strictly after the `window_start`, or the request is
        refused with `ERR_WINDOW_ORDER_INVALID`."
        PRD §3.8: "The `yard_window_end` must be at or after the `yard_window_start` — note that a
        zero-length yard window is legal, unlike a zero-length line window — and an inverted window
        is refused with `ERR_WINDOW_ORDER_INVALID`."
        PRD §2.11: "19. Window endpoint ordering, on run scheduling and freight load planning —
        `ERR_WINDOW_ORDER_INVALID`, 400."
        PRD §3.8: "A new load is written with those two capacities and with `assigned_cube_m3`,
        `assigned_weight_kg`, `cube_utilization_pct`, `linehaul_cost_cents` and `order_count` all
        initialised to 0 and `status` `PLANNED`."

        Design: Corner/validations/window_order_is_strict_for_line_runs_and_inclusive_for_yard_windows
        """
        ref = setup_reference_data()
        design = create_design(ref)
        order = place_order(ref, design)
        lot = receive_coil_lot(ref, coating="G115", heat_number="H-55")

        def book(start, end, kg=6600):
            return api.create_roll_forming_run(
                create_roll_forming_run_payload(
                    ref["lines"]["LINE_A"]["id"], lot["id"], order["id"], start, end, kg
                ),
                PLANNER,
            )

        # Zero length on a line. The over-reservation (step 31) is masked by step 19.
        validate_error(
            book("2026-08-06T08:00:00Z", "2026-08-06T08:00:00Z", 30000.0),
            "ERR_WINDOW_ORDER_INVALID",
            400,
        )
        # Frankly inverted on a line.
        validate_error(
            book("2026-08-06T12:00:00Z", "2026-08-06T08:00:00Z"),
            "ERR_WINDOW_ORDER_INVALID",
            400,
        )
        assert read_coil_lot(lot["id"])["reserved_kg"] == pytest.approx(0.0, abs=0.005)

        dealer = read_dealer(ref["alpha"]["id"])
        # Inverted on a yard is refused by the same code.
        validate_error(
            api.create_freight_load(
                create_freight_load_payload(
                    dealer["id"],
                    dealer["version"],
                    yard_window_start="2026-08-12T17:00:00Z",
                    yard_window_end="2026-08-10T08:00:00Z",
                ),
                LOGISTICS,
            ),
            "ERR_WINDOW_ORDER_INVALID",
            400,
        )
        # Zero length on a yard is admitted.
        load = validate_success(
            api.create_freight_load(
                create_freight_load_payload(
                    dealer["id"],
                    dealer["version"],
                    yard_window_start="2026-08-10T08:00:00Z",
                    yard_window_end="2026-08-10T08:00:00Z",
                ),
                LOGISTICS,
            ),
            201,
        )
        assert load["status"] == "PLANNED"
        assert_empty_load_totals(load)


class TestRunMassGates:
    def test_over_reservation_and_over_consumption_are_refused_but_exact_equality_posts(
        self, api
    ):
        """PRD §3.7: "And the `planned_kg` must be no greater than the lot's `remaining_kg` at the
        moment of scheduling, or the request is refused with `ERR_COIL_INSUFFICIENT_MASS`."
        PRD §3.7: "The planner supplies the actual `consumed_kg` and `scrap_kg`, whose sum must be no
        greater than the run's `planned_kg`, or the posting is refused with
        `ERR_RUN_MASS_EXCEEDS_RESERVED`."
        PRD §3.7: "On success the run moves `SCHEDULED` to `COMPLETED`, the two masses are stored on
        the run, the lot's ledger is recomputed, and the run's order advances its
        `production_status` from `QUEUED` to `KITTED`."
        PRD §3.7: "The `remaining_kg` is the `received_kg` minus `reserved_kg` minus `consumed_kg`
        minus `scrap_kg`, rounded half up to 2 decimal places."
        PRD §3.6: "Confirmation is untouched by the financial dimension — the order's
        `financial_status` remains whatever it was, typically `AWAITING_DEPOSIT`."

        Design: Corner/validations/run_mass_gates_reject_over_reservation_and_over_consumption_but_admit_exact_equality
        """
        ref = setup_reference_data()
        design = create_design_under_review(ref)
        order = place_order(ref, design)
        order = validate_success(api.confirm_dealer_order(order["id"], ref["alpha_headers"]))
        assert order["production_status"] == "QUEUED"
        lot = receive_coil_lot(ref, coating="G115", heat_number="H-44")

        def book(kg):
            return api.create_roll_forming_run(
                create_roll_forming_run_payload(
                    ref["lines"]["LINE_A"]["id"],
                    lot["id"],
                    order["id"],
                    "2026-08-07T08:00:00Z",
                    "2026-08-07T12:00:00Z",
                    kg,
                ),
                PLANNER,
            )

        # 30000.0 exceeds the 20000.0 the lot actually holds.
        validate_error(book(30000.0), "ERR_COIL_INSUFFICIENT_MASS", 422)
        assert read_coil_lot(lot["id"])["reserved_kg"] == pytest.approx(0.0, abs=0.005)

        run = validate_success(book(6600.0), 201)
        reserved = read_coil_lot(lot["id"])
        assert reserved["reserved_kg"] == pytest.approx(6600.0, abs=0.005)
        assert reserved["remaining_kg"] == pytest.approx(13400.0, abs=0.005)

        # 6410.4 + 300.0 = 6710.4, over the 6600.0 reservation by 110.4 kg.
        validate_error(
            api.complete_roll_forming_run(
                run["id"], complete_run_payload(6410.4, 300.0), PLANNER
            ),
            "ERR_RUN_MASS_EXCEEDS_RESERVED",
            422,
        )
        still = read_run(run["id"])
        assert still["status"] == "SCHEDULED"
        assert still["consumed_kg"] == pytest.approx(0.0, abs=0.005)
        assert still["scrap_kg"] == pytest.approx(0.0, abs=0.005)
        assert read_coil_lot(lot["id"])["reserved_kg"] == pytest.approx(
            6600.0, abs=0.005
        )

        # 6410.4 + 189.6 = 6600.0 exactly: "no greater than" admits equality.
        posted = complete_run(run, 6410.4, 189.6)
        assert posted["status"] == "COMPLETED"
        assert posted["consumed_kg"] == pytest.approx(6410.4, abs=0.005)
        assert posted["scrap_kg"] == pytest.approx(189.6, abs=0.005)
        ledger = read_coil_lot(lot["id"])
        assert ledger["reserved_kg"] == pytest.approx(0.0, abs=0.005)
        assert ledger["consumed_kg"] == pytest.approx(6410.4, abs=0.005)
        assert ledger["scrap_kg"] == pytest.approx(189.6, abs=0.005)
        assert ledger["remaining_kg"] == pytest.approx(13400.0, abs=0.005)
        assert ledger["status"] == "AVAILABLE"
        assert_coil_mass_conservation(ledger)
        assert_coil_lot_status_follows_ledger(ledger)

        kitted = read_order(order["id"])
        assert kitted["production_status"] == "KITTED"
        assert kitted["financial_status"] == "AWAITING_DEPOSIT"
        assert_version_advanced_by(kitted, order, 1, "order")

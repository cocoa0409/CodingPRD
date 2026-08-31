"""Filling lines and packaging runs: gates, closed-interval capacity and the recall cascade."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_claim,
    create_active_config,
    create_packaging_line,
    create_packaging_run_payload,
    read_batch,
    read_line,
    read_run,
    read_tank,
    release,
    schedule_run,
    setup_qc_passed_batch,
    setup_released_batch_with_line,
    setup_scheduled_run,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["product_manager_headers"]
OPERATOR = TEST_USERS["blend_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestBatchReleaseGate:
    def test_run_cannot_be_scheduled_against_a_merely_blended_batch(self, api):
        """PRD 3.7: "Four gates guard scheduling, in the ladder order of §2.6. The batch's
        `production_status` must be `RELEASED`, or `ERR_BATCH_NOT_RELEASED` applies —
        quarantined, blended and still-charging material may not be packed."
        PRD 3.7: "Every scheduling recomputes the line's `scheduled_run_count`, which is simply
        the number of runs on that line whose status is `SCHEDULED` or `RUNNING`."

        Design: Difficulty/cross_entity_state_dependency/packaging_run_depends_on_blend_batch_production_status
        """
        world = setup_qc_passed_batch(retains=2)
        config = create_active_config(world["spec"]["id"])
        line = create_packaging_line()
        assert world["batch"]["production_status"] == "BLENDED"

        response = api.create_packaging_run(
            create_packaging_run_payload(world["batch"]["id"], config["id"], line["id"]),
            OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_BATCH_NOT_RELEASED.value, 409)
        assert read_line(line["id"])["scheduled_run_count"] == 0

    def test_run_is_scheduled_once_the_batch_reaches_released(self, api):
        """PRD 3.7: "Four gates guard scheduling, in the ladder order of §2.6. The batch's
        `production_status` must be `RELEASED`, or `ERR_BATCH_NOT_RELEASED` applies —
        quarantined, blended and still-charging material may not be packed."
        PRD 3.7: "The run opens `SCHEDULED` with `produced_units` null and `cancel_reason`
        null."
        PRD 3.5: "It moves the batch `BLENDED → RELEASED` and requires four things: the
        `production_status` is `BLENDED`; the `qc_status` is either `PASSED` or `WAIVED`; the
        batch holds at least two retain jars, or the release is refused with
        `ERR_INSUFFICIENT_RETAINS` — the zero-jar case included; and the caller's `X-User-ID`
        matches no `technician_user_id` on any result of the batch, or the release is refused
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/cross_entity_state_dependency/packaging_run_depends_on_blend_batch_production_status
        """
        world = setup_qc_passed_batch(retains=2)
        config = create_active_config(world["spec"]["id"])
        line = create_packaging_line()

        refused = api.create_packaging_run(
            create_packaging_run_payload(world["batch"]["id"], config["id"], line["id"]),
            OPERATOR,
        )
        validate_error(refused, ApiErrorId.ERR_BATCH_NOT_RELEASED.value, 409)

        release(world)
        assert world["batch"]["production_status"] == "RELEASED"

        run = validate_success(
            api.create_packaging_run(
                create_packaging_run_payload(world["batch"]["id"], config["id"], line["id"]),
                OPERATOR,
            ),
            201,
        )
        assert run["status"] == "SCHEDULED"
        assert run["produced_units"] is None
        assert run["cancel_reason"] is None
        assert read_line(line["id"])["scheduled_run_count"] == 1


class TestClosedIntervalCapacity:
    @staticmethod
    def _line_with_two_overlapping_runs():
        world = setup_released_batch_with_line()
        schedule_run(
            world,
            window_start="2026-08-03T10:00:00Z",
            window_end="2026-08-03T12:00:00Z",
            planned_units=100,
        )
        schedule_run(
            world,
            window_start="2026-08-03T11:00:00Z",
            window_end="2026-08-03T13:00:00Z",
            planned_units=100,
        )
        return world

    def test_touching_windows_collide_yet_still_fit_below_the_head_count(self, api):
        """PRD 3.7: "Line capacity is aggregate rather than exclusive, and — in deliberate
        contrast to the vessel rule of §3.4 — packaging windows are **closed** intervals, so
        runs that merely touch at an endpoint *do* collide."
        PRD 3.7: "Count the runs on the same line whose status is `SCHEDULED` or `RUNNING` and
        whose window overlaps the requested one, where overlap means the requested
        `window_start` is at or before the existing run's `window_end` **and** the existing run's
        `window_start` is at or before the requested `window_end`."
        PRD 3.7: "If that count has already reached the line's `max_concurrent_runs`, the
        scheduling is refused with `ERR_LINE_CAPACITY_EXCEEDED`; the line tolerates overlaps
        strictly below that number."
        PRD 3.7: "Every scheduling recomputes the line's `scheduled_run_count`, which is simply
        the number of runs on that line whose status is `SCHEDULED` or `RUNNING`."

        Design: Difficulty/resource_temporal_overlap/packaging_line_closed_interval_aggregate_capacity
        """
        world = self._line_with_two_overlapping_runs()

        # [13:00, 15:00] touches the second run's end at 13:00, so it counts as one
        # overlap — below the two filling heads.
        third = validate_success(
            api.create_packaging_run(
                create_packaging_run_payload(
                    world["batch"]["id"],
                    world["config"]["id"],
                    world["line"]["id"],
                    window_start="2026-08-03T13:00:00Z",
                    window_end="2026-08-03T15:00:00Z",
                    planned_units=100,
                ),
                OPERATOR,
            ),
            201,
        )
        assert third["status"] == "SCHEDULED"
        assert read_line(world["line"]["id"])["scheduled_run_count"] == 3

    def test_a_window_overlapping_all_three_runs_exhausts_the_filling_heads(self, api):
        """PRD 3.7: "If that count has already reached the line's `max_concurrent_runs`, the
        scheduling is refused with `ERR_LINE_CAPACITY_EXCEEDED`; the line tolerates overlaps
        strictly below that number."
        PRD 3.7: "A **filling line** is registered by a `PlatformAdmin` with a `line_code`
        unique across every line and a `max_concurrent_runs` count of filling heads, which
        defaults to 2 and must be at least 1."
        PRD 3.7: "Completed and cancelled runs free their slot immediately and are never
        counted."

        Design: Difficulty/resource_temporal_overlap/packaging_line_closed_interval_aggregate_capacity
        """
        world = self._line_with_two_overlapping_runs()
        validate_success(
            api.create_packaging_run(
                create_packaging_run_payload(
                    world["batch"]["id"],
                    world["config"]["id"],
                    world["line"]["id"],
                    window_start="2026-08-03T13:00:00Z",
                    window_end="2026-08-03T15:00:00Z",
                    planned_units=100,
                ),
                OPERATOR,
            ),
            201,
        )

        response = api.create_packaging_run(
            create_packaging_run_payload(
                world["batch"]["id"],
                world["config"]["id"],
                world["line"]["id"],
                window_start="2026-08-03T12:00:00Z",
                window_end="2026-08-03T14:00:00Z",
                planned_units=100,
            ),
            OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value, 409)

        assert read_line(world["line"]["id"])["scheduled_run_count"] == 3
        rows, _ = validate_paginated(
            api.list_packaging_runs(OPERATOR, {"packaging_line_id": world["line"]["id"]})
        )
        assert len(rows) == 3


class TestRunLifecycleAndLineAvailability:
    def test_completing_a_run_frees_its_filling_head(self, api):
        """PRD 3.7: "Starting a run moves it `SCHEDULED → RUNNING` and re-checks two things at
        the moment of the start: the line must still be `AVAILABLE` and the configuration must
        still be `ACTIVE`."
        PRD 3.7: "Completing a running run moves it `RUNNING → COMPLETED`, records the
        `produced_units` actually filled from the request, and recomputes the line's
        `scheduled_run_count`, which decreases by one."
        PRD 3.7: "Every scheduling recomputes the line's `scheduled_run_count`, which is simply
        the number of runs on that line whose status is `SCHEDULED` or `RUNNING`."

        Design: Corner/state_machines/packaging_run_complete_decrements_scheduled_run_count
        """
        world = setup_scheduled_run()
        assert read_line(world["line"]["id"])["scheduled_run_count"] == 1

        started = validate_success(api.start_packaging_run(world["run"]["id"], OPERATOR))
        assert started["status"] == "RUNNING"
        assert read_line(world["line"]["id"])["scheduled_run_count"] == 1, (
            "a RUNNING run still occupies a filling head"
        )

        completed = validate_success(
            api.complete_packaging_run(world["run"]["id"], {"produced_units": 480}, OPERATOR)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["produced_units"] == 480
        assert read_line(world["line"]["id"])["scheduled_run_count"] == 0

        rows, _ = validate_paginated(
            api.list_packaging_runs(OPERATOR, {"blend_batch_id": world["batch"]["id"]})
        )
        assert len(rows) == 1

    def test_scheduling_onto_a_line_that_is_out_of_service_is_refused(self, api):
        """PRD 3.7: "The line must be `AVAILABLE`, or `ERR_LINE_NOT_AVAILABLE` applies."
        PRD 3.7: "Taking a line out of service or returning it to service is also a
        `PlatformAdmin` action, driven by a `target_status` of either `AVAILABLE` or `DOWN`; the
        line moves `AVAILABLE → DOWN` or `DOWN → AVAILABLE` accordingly and advances its
        `version`."
        PRD 3.7: "The run opens `SCHEDULED` with `produced_units` null and `cancel_reason`
        null."

        Design: Corner/errors/packaging_run_on_down_line_returns_line_not_available
        """
        world = setup_released_batch_with_line()
        downed = validate_success(
            api.set_packaging_line_service_status(
                world["line"]["id"], {"target_status": "DOWN"}, ADMIN
            )
        )
        assert downed["status"] == "DOWN"

        response = api.create_packaging_run(
            create_packaging_run_payload(
                world["batch"]["id"], world["config"]["id"], world["line"]["id"]
            ),
            OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_LINE_NOT_AVAILABLE.value, 409)
        assert read_line(world["line"]["id"])["scheduled_run_count"] == 0

        restored = validate_success(
            api.set_packaging_line_service_status(
                world["line"]["id"], {"target_status": "AVAILABLE"}, ADMIN
            )
        )
        assert restored["status"] == "AVAILABLE"

        run = validate_success(
            api.create_packaging_run(
                create_packaging_run_payload(
                    world["batch"]["id"], world["config"]["id"], world["line"]["id"]
                ),
                OPERATOR,
            ),
            201,
        )
        assert run["status"] == "SCHEDULED"
        assert read_line(world["line"]["id"])["scheduled_run_count"] == 1

    def test_claim_bearing_label_may_not_be_filled_from_an_ineligible_batch(self, api):
        """PRD 3.7: "And claim substantiation must hold: where the configuration's `claim_codes`
        array is non-empty, the batch's `claim_eligible` must be true, or the scheduling is
        refused with `ERR_CLAIM_NOT_SUBSTANTIATED`."
        PRD 3.7: "A configuration with an empty `claim_codes` array imposes no such requirement
        and may be filled from any released batch."
        PRD 3.4: "The batch's `claim_eligible` is set true only when all three of the following
        hold: the `heel_ratio_actual` is at or below 0.001000 for a cross-family heel, at or
        below 0.010000 for a same-family heel, or unconstrained where the vessel's heel family
        is `NONE`; every component lot touched by a draw of this charge has
        `coa_viscosity_verified` true; and the recipe's `spec_revision_pinned` equals the
        specification's `revision` at charge time."

        Design: Corner/errors/claim_bearing_configuration_cannot_be_packed_from_an_ineligible_batch
        """
        world = setup_released_batch_with_line(
            config_overrides={"label_brand": "Plain Drum", "package_type": "DRUM_205L",
                              "fill_volume_l": 205.0},
        )
        assert world["batch"]["claim_eligible"] is False
        assert world["batch"]["heel_ratio_actual"] == pytest.approx(0.005000, abs=0.0000005)

        create_active_claim(world["spec"]["id"])
        claimed_config = create_active_config(
            world["spec"]["id"], label_brand="Claimed Pail", claim_codes=["API SP"]
        )

        refused = api.create_packaging_run(
            create_packaging_run_payload(
                world["batch"]["id"], claimed_config["id"], world["line"]["id"]
            ),
            OPERATOR,
        )
        validate_error(refused, ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED.value, 422)

        plain_run = validate_success(
            api.create_packaging_run(
                create_packaging_run_payload(
                    world["batch"]["id"], world["config"]["id"], world["line"]["id"],
                    planned_units=50,
                ),
                OPERATOR,
            ),
            201,
        )
        assert plain_run["status"] == "SCHEDULED"
        assert read_line(world["line"]["id"])["scheduled_run_count"] == 1


class TestBatchRecallCascade:
    def test_recalling_a_released_batch_cancels_its_scheduled_runs(self, api):
        """PRD 2.9: "**Cascade B** is the batch-quarantine cascade: a batch entering quarantine
        (link 1) cancels every scheduled or running packaging run against it (link 2), which
        recomputes the affected filling lines' scheduled run counts (link 3), and — only where
        the vessel is still charged by that batch — quarantines the vessel too (link 4)."
        PRD 3.5: "From `RELEASED` — a market recall of material already handed over — the batch
        moves `RELEASED → QUARANTINED` and the packaging-run cancellations and line
        recomputations fire exactly as before, but the vessel hop is skipped: the vessel was
        already handed back at release, so its status is left untouched."
        PRD 3.7: "The same cancellation, with `cancel_reason` set to `BATCH_QUARANTINED`, is
        driven by the system as link 2 of cascade B whenever the batch being packed enters
        quarantine, and link 3 of that cascade is exactly the `scheduled_run_count`
        recomputation just described."

        Design: Difficulty/transitive_cascade/batch_recall_three_hop_cascade_to_line_run_count
        """
        world = setup_scheduled_run()
        assert read_line(world["line"]["id"])["scheduled_run_count"] == 1

        recalled = validate_success(
            api.quarantine_blend_batch(
                world["batch"]["id"], {"reason": "FIELD_COMPLAINT"}, QM
            )
        )
        assert recalled["production_status"] == "QUARANTINED"

        run = read_run(world["run"]["id"])
        assert run["status"] == "CANCELLED"
        assert run["cancel_reason"] == "BATCH_QUARANTINED"

        assert read_line(world["line"]["id"])["scheduled_run_count"] == 0

    def test_recall_leaves_the_vessel_and_the_quality_dimension_untouched(self, api):
        """PRD 3.5: "From `RELEASED` — a market recall of material already handed over — the
        batch moves `RELEASED → QUARANTINED` and the packaging-run cancellations and line
        recomputations fire exactly as before, but the vessel hop is skipped: the vessel was
        already handed back at release, so its status is left untouched."
        PRD 3.5: "Release hands the vessel back `CHARGED → AVAILABLE` and, unlike a cancelled
        charge, **rewrites** the vessel's heel from this batch: `heel_volume_l` becomes the
        batch's `charge_volume_l` multiplied by a heel retention rate of 0.5 percent, rounded
        half up to three decimal places; `heel_additive_family` becomes the released batch's
        specification `additive_family`; and `heel_product_code` becomes that specification's
        `product_code`."
        PRD 3.4: "The batch is born with `production_status` `PLANNED` and `qc_status`
        `PENDING` — two dimensions that evolve entirely independently of one another for the
        rest of the batch's life."

        Design: Difficulty/transitive_cascade/batch_recall_three_hop_cascade_to_line_run_count
        """
        world = setup_scheduled_run()

        validate_success(
            api.quarantine_blend_batch(
                world["batch"]["id"], {"reason": "FIELD_COMPLAINT"}, QM
            )
        )

        tank = read_tank(world["tank"]["id"])
        assert tank["status"] == "AVAILABLE"
        assert tank["heel_volume_l"] == pytest.approx(9.950, abs=0.001)
        assert tank["heel_additive_family"] == "ZDDP_PCMO"

        batch = read_batch(world["batch"]["id"])
        assert batch["production_status"] == "QUARANTINED"
        assert batch["qc_status"] == "PASSED", (
            "the recall touches only the production dimension"
        )

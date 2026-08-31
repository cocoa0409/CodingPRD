"""The quality dimension: laboratory results, retain jars, waivers and disposition."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    CLOCK_BASE_ISO,
    QC_TECH_ALT_ID,
    QC_TECH_ID,
    QUALITY_MANAGER_ID,
    ApiErrorId,
    TEST_USERS,
    add_retains,
    assert_qc_result,
    charge,
    complete_blend,
    create_active_claim,
    create_batch,
    list_batch_draws,
    make_qc_technician_headers,
    make_quality_manager_headers,
    read_batch,
    read_lot,
    read_retain,
    read_tank,
    record_qc_results,
    set_clock,
    setup_active_formulation,
    setup_blended_batch,
    setup_charging_batch,
    setup_planned_batch,
    setup_qc_passed_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["blend_operator_headers"]
QC = make_qc_technician_headers(QC_TECH_ID)
QM = make_quality_manager_headers(QUALITY_MANAGER_ID)


class TestParallelStateDimensions:
    def test_batch_reaches_blended_while_the_quality_dimension_is_still_pending(self, api):
        """PRD 3.4: "The batch is born with `production_status` `PLANNED` and `qc_status`
        `PENDING` — two dimensions that evolve entirely independently of one another for the
        rest of the batch's life."
        PRD 3.5: "The `qc_status` dimension runs in parallel with production and is driven
        exclusively by a `QCTechnician` recording laboratory results and by a `QualityManager`
        exercising disposition authority."
        PRD 3.4: "It is reachable from two originating states: `CHARGING → BLENDED`, which moves
        every `RESERVED` draw on the batch to `CONSUMED` and computes `component_cost_cents` by
        the consumption-layer method of §3.3; and `REWORKED → BLENDED`, permitted only while the
        batch's `qc_status` is `PENDING`, which recomputes `component_cost_cents` over the
        unchanged set of `CONSUMED` draws — the figure comes out identical, because rework
        consumes no additional material — and closes the quarantine-rework loop."

        Design: Difficulty/non_linear_state_machine/blend_batch_production_and_qc_dimensions_advance_independently
        """
        world = setup_charging_batch()
        assert world["batch"]["production_status"] == "CHARGING"
        assert world["batch"]["qc_status"] == "PENDING"

        blended = validate_success(api.complete_blend(world["batch"]["id"], OPERATOR))
        assert blended["production_status"] == "BLENDED"
        assert blended["qc_status"] == "PENDING", (
            "completing the blend must not touch the quality dimension"
        )

    def test_quality_dimension_walks_to_passed_without_moving_production(self, api):
        """PRD 3.5: "The first result on a batch, when it passes, moves the batch
        `PENDING → SAMPLED`; this is permitted only while the batch's `production_status` is
        `CHARGING`, `BLENDED` or `REWORKED`, and it leaves the production dimension entirely
        untouched."
        PRD 3.5: "A subsequent result that completes the required test set moves the batch
        `SAMPLED → PASSED`; that transition requires the batch's results to cover both of the
        required tests — `KV100` and `TBN` — with every one of them carrying `PASS`."
        PRD 3.5: "A `KV100` result also writes `measured_kv100_cst` onto the batch, which
        therefore always reflects the most recent `KV100` reading."
        PRD 3.5: "The stored result carries the `blend_batch_id` under test, the computed
        `result`, a `tested_at` instant stamped from the logical clock, and `technician_user_id`
        stamped from the recording caller's `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/blend_batch_production_and_qc_dimensions_advance_independently
        """
        world = setup_blended_batch()

        tbn = validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "TBN", "measured_value": 8.9}, QC
            ),
            201,
        )
        assert_qc_result(tbn)
        assert tbn["result"] == "PASS"
        after_tbn = read_batch(world["batch"]["id"])
        assert after_tbn["qc_status"] == "SAMPLED"
        assert after_tbn["production_status"] == "BLENDED"

        kv = validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "KV100", "measured_value": 7.610}, QC
            ),
            201,
        )
        assert kv["result"] == "PASS"
        after_kv = read_batch(world["batch"]["id"])
        assert after_kv["qc_status"] == "PASSED"
        assert after_kv["production_status"] == "BLENDED"
        assert after_kv["measured_kv100_cst"] == pytest.approx(7.610, abs=0.0005)

        rows, meta = validate_paginated(api.list_qc_results(world["batch"]["id"], QC))
        assert meta["total_count"] == 2 and len(rows) == 2
        assert all(row["technician_user_id"] == QC_TECH_ID for row in rows)


class TestViscosityBandBoundary:
    def test_reading_exactly_on_the_upper_band_endpoint_passes(self, api):
        """PRD 3.5: "The lower endpoint is the target multiplied by one minus the tolerance
        divided by one hundred; the upper endpoint is the target multiplied by one plus the
        tolerance divided by one hundred; each endpoint is rounded half up to three decimal
        places."
        PRD 3.5: "The `result` is `PASS` when the `measured_value` is at or above the lower
        endpoint and at or below the upper endpoint, both ends inclusive, and `FAIL` otherwise;
        the `measured_value` itself is compared exactly as supplied, with no rounding."
        PRD 3.5: "A `KV100` result also writes `measured_kv100_cst` onto the batch, which
        therefore always reflects the most recent `KV100` reading."

        Design: Difficulty/boundary_precision_check/qc_kv100_upper_band_inclusive_then_one_step_above_fails
        """
        world = setup_blended_batch()

        # 7.600 at 3.0 percent gives the band 7.372 .. 7.828.
        result = validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "KV100", "measured_value": 7.828}, QC
            ),
            201,
        )
        assert result["result"] == "PASS"

        refreshed = read_batch(world["batch"]["id"])
        assert refreshed["qc_status"] == "SAMPLED"
        assert refreshed["measured_kv100_cst"] == pytest.approx(7.828, abs=0.0005)
        assert refreshed["production_status"] == "BLENDED"

    def test_reading_one_thousandth_above_the_band_fails_and_quarantines(self, api):
        """PRD 3.5: "The `result` is `PASS` when the `measured_value` is at or above the lower
        endpoint and at or below the upper endpoint, both ends inclusive, and `FAIL` otherwise;
        the `measured_value` itself is compared exactly as supplied, with no rounding."
        PRD 3.5: "A failing result moves the batch to `FAILED` from either `PENDING` or
        `SAMPLED`."
        PRD 3.5: "Where a failing result lands on a batch whose `production_status` is
        `BLENDED`, cascade B fires in the same operation and the batch also moves
        `BLENDED → QUARANTINED`."
        PRD 3.5: "From `BLENDED`, a `QualityManager` quarantining the batch — with a `reason` —
        moves it `BLENDED → QUARANTINED`, cancels every packaging run against the batch whose
        status is `SCHEDULED` or `RUNNING` with `cancel_reason` `BATCH_QUARANTINED`, recomputes
        each affected filling line's `scheduled_run_count`, and moves the vessel
        `CHARGED → QUARANTINED`."

        Design: Difficulty/boundary_precision_check/qc_kv100_upper_band_inclusive_then_one_step_above_fails
        """
        world = setup_blended_batch()
        validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "KV100", "measured_value": 7.828}, QC
            ),
            201,
        )

        failing = validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "KV100", "measured_value": 7.829}, QC
            ),
            201,
        )
        assert failing["result"] == "FAIL"

        refreshed = read_batch(world["batch"]["id"])
        assert refreshed["qc_status"] == "FAILED"
        assert refreshed["measured_kv100_cst"] == pytest.approx(7.829, abs=0.0005)
        assert refreshed["production_status"] == "QUARANTINED"
        assert read_tank(world["tank"]["id"])["status"] == "QUARANTINED"

        _, meta = validate_paginated(api.list_qc_results(world["batch"]["id"], QC))
        assert meta["total_count"] == 2


class TestRetainJarsAndRelease:
    def test_release_is_refused_below_two_retain_jars(self, api):
        """PRD 3.5: "It moves the batch `BLENDED → RELEASED` and requires four things: the
        `production_status` is `BLENDED`; the `qc_status` is either `PASSED` or `WAIVED`; the
        batch holds at least two retain jars, or the release is refused with
        `ERR_INSUFFICIENT_RETAINS` — the zero-jar case included; and the caller's `X-User-ID`
        matches no `technician_user_id` on any result of the batch, or the release is refused
        with `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.5: "Booking a jar recomputes the batch's `retain_count`, which is the number of
        jars on the batch whose status is `HELD`, and advances the batch's `version`."

        Design: Difficulty/boundary_precision_check/release_retain_count_boundary_zero_one_two
        """
        world = setup_qc_passed_batch(retains=0)
        assert world["batch"]["retain_count"] == 0

        first_attempt = api.release_blend_batch(world["batch"]["id"], QM)
        validate_error(first_attempt, ApiErrorId.ERR_INSUFFICIENT_RETAINS.value, 422)

        add_retains(world, count=1)
        assert read_batch(world["batch"]["id"])["retain_count"] == 1

        second_attempt = api.release_blend_batch(world["batch"]["id"], QM)
        validate_error(second_attempt, ApiErrorId.ERR_INSUFFICIENT_RETAINS.value, 422)
        assert read_batch(world["batch"]["id"])["production_status"] == "BLENDED"

    def test_release_succeeds_at_exactly_two_retain_jars(self, api):
        """PRD 3.5: "It moves the batch `BLENDED → RELEASED` and requires four things: the
        `production_status` is `BLENDED`; the `qc_status` is either `PASSED` or `WAIVED`; the
        batch holds at least two retain jars, or the release is refused with
        `ERR_INSUFFICIENT_RETAINS` — the zero-jar case included; and the caller's `X-User-ID`
        matches no `technician_user_id` on any result of the batch, or the release is refused
        with `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.5: "The retention window depends on whether the batch's specification carries
        approval claims: if any approval claim on that specification has status `ACTIVE` at the
        instant the jar is booked, the window is 1,095 calendar days from `retained_at`;
        otherwise it is 365 calendar days."
        PRD 3.5: "Release hands the vessel back `CHARGED → AVAILABLE` and, unlike a cancelled
        charge, **rewrites** the vessel's heel from this batch: `heel_volume_l` becomes the
        batch's `charge_volume_l` multiplied by a heel retention rate of 0.5 percent, rounded
        half up to three decimal places; `heel_additive_family` becomes the released batch's
        specification `additive_family`; and `heel_product_code` becomes that specification's
        `product_code`."

        Design: Difficulty/boundary_precision_check/release_retain_count_boundary_zero_one_two
        """
        world = setup_qc_passed_batch(retains=2)
        assert world["batch"]["retain_count"] == 2

        released = validate_success(api.release_blend_batch(world["batch"]["id"], QM))
        assert released["production_status"] == "RELEASED"
        assert released["retain_count"] == 2

        first_retain = read_retain(world["retains"][0]["id"], world["batch"]["id"])
        assert first_retain["retention_until"] == "2027-08-02T06:00:00.000Z", (
            "with no ACTIVE claim on the specification the window is 365 calendar days"
        )

        tank = read_tank(world["tank"]["id"])
        assert tank["status"] == "AVAILABLE"
        assert tank["heel_volume_l"] == pytest.approx(9.950, abs=0.001)
        assert tank["heel_additive_family"] == "ZDDP_PCMO"

    def test_claim_bearing_specification_extends_the_retention_window(self, api):
        """PRD 3.5: "The retention window depends on whether the batch's specification carries
        approval claims: if any approval claim on that specification has status `ACTIVE` at the
        instant the jar is booked, the window is 1,095 calendar days from `retained_at`;
        otherwise it is 365 calendar days."
        PRD 3.5: "The jar records the `blend_batch_id` it was drawn from, a `retained_at`
        instant stamped from the logical clock, a `status` beginning at `HELD`, and a computed
        `retention_until`."
        PRD 3.5: "Booking a jar recomputes the batch's `retain_count`, which is the number of
        jars on the batch whose status is `HELD`, and advances the batch's `version`."

        Design: Corner/calculations/retain_retention_window_extends_to_1095_days_when_a_claim_is_active
        """
        world = setup_charging_batch()
        create_active_claim(world["spec"]["id"])

        retain = validate_success(
            api.create_retain_sample(
                world["batch"]["id"], {"retain_code": "R-0001-A", "volume_ml": 250.0}, QC
            ),
            201,
        )
        assert retain["retained_at"] == CLOCK_BASE_ISO
        assert retain["retention_until"] == "2029-08-01T06:00:00.000Z"
        assert retain["retention_until"] != "2027-08-02T06:00:00.000Z"
        assert retain["status"] == "HELD"
        assert read_batch(world["batch"]["id"])["retain_count"] == 1

    def test_retain_disposal_waits_for_the_retention_window_to_elapse(self, api):
        """PRD 3.5: "A `QualityManager` may dispose of a jar, moving it `HELD → DISPOSED` with a
        `reason`; the disposal is refused with `ERR_RETENTION_WINDOW_ACTIVE` until the logical
        clock has reached the jar's `retention_until`, and a successful disposal recomputes the
        batch's `retain_count` and advances the jar's own `version`."
        PRD 2.6: "27. Retention window — the logical clock has reached the jar's
        `retention_until`; otherwise `ERR_RETENTION_WINDOW_ACTIVE` (422). Guards retain
        disposal."

        Design: Corner/validations/retain_disposal_before_retention_until_rejected_then_allowed_after_clock_advance
        """
        world = setup_charging_batch()
        add_retains(world, count=2)
        first, second = world["retains"][0], world["retains"][1]
        assert first["retention_until"] == "2027-08-02T06:00:00.000Z"

        set_clock("2027-08-01T06:00:00Z")
        early = api.dispose_retain_sample(
            first["id"], {"reason": "ROUTINE_CLEAROUT"}, QM
        )
        validate_error(early, ApiErrorId.ERR_RETENTION_WINDOW_ACTIVE.value, 422)
        assert read_retain(first["id"], world["batch"]["id"])["status"] == "HELD"
        assert read_batch(world["batch"]["id"])["retain_count"] == 2

        set_clock("2027-08-02T06:00:00Z")
        disposed = validate_success(
            api.dispose_retain_sample(first["id"], {"reason": "ROUTINE_CLEAROUT"}, QM)
        )
        assert disposed["status"] == "DISPOSED"
        assert read_batch(world["batch"]["id"])["retain_count"] == 1
        assert read_retain(second["id"], world["batch"]["id"])["status"] == "HELD"


class TestSegregationOfDutiesAndWaivers:
    def test_the_testing_technician_may_not_dispose_of_the_batch_they_tested(self, api):
        """PRD 2.10: "When a batch is later released, or when its quality gate is waived, the
        acting `QualityManager`'s `X-User-ID` is compared against the `technician_user_id` of
        every laboratory result on that batch; if it matches any of them, the operation is
        refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
        PRD 2.10: "The check is a pure identity comparison and applies regardless of how many
        results the batch carries or how long ago they were recorded."
        PRD 3.5: "Release hands the vessel back `CHARGED → AVAILABLE` and, unlike a cancelled
        charge, **rewrites** the vessel's heel from this batch: `heel_volume_l` becomes the
        batch's `charge_volume_l` multiplied by a heel retention rate of 0.5 percent, rounded
        half up to three decimal places; `heel_additive_family` becomes the released batch's
        specification `additive_family`; and `heel_product_code` becomes that specification's
        `product_code`."

        Design: Corner/validations/segregation_of_duties_blocks_release_by_the_testing_technician
        """
        world = setup_qc_passed_batch(retains=2, technician_user_id=QC_TECH_ID)

        conflicted = api.release_blend_batch(
            world["batch"]["id"], make_quality_manager_headers(QC_TECH_ID)
        )
        validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        assert read_batch(world["batch"]["id"])["production_status"] == "BLENDED"
        assert read_tank(world["tank"]["id"])["status"] == "CHARGED"

        released = validate_success(
            api.release_blend_batch(
                world["batch"]["id"], make_quality_manager_headers(QUALITY_MANAGER_ID)
            )
        )
        assert released["production_status"] == "RELEASED"

        tank = read_tank(world["tank"]["id"])
        assert tank["status"] == "AVAILABLE"
        assert tank["heel_volume_l"] == pytest.approx(9.950, abs=0.001)

    def test_waiver_is_refused_on_a_claim_eligible_batch(self, api):
        """PRD 3.5: "It is available only when the batch's `claim_eligible` is false; attempting
        to waive a claim-eligible batch is refused with `ERR_CLAIM_NOT_SUBSTANTIATED`, on the
        principle that material intended to carry an approval mark can never be released on a
        waiver."
        PRD 3.4: "The batch's `claim_eligible` is set true only when all three of the following
        hold: the `heel_ratio_actual` is at or below 0.001000 for a cross-family heel, at or
        below 0.010000 for a same-family heel, or unconstrained where the vessel's heel family
        is `NONE`; every component lot touched by a draw of this charge has
        `coa_viscosity_verified` true; and the recipe's `spec_revision_pinned` equals the
        specification's `revision` at charge time."
        PRD 3.5: "Where a failing result lands on a batch whose `production_status` is
        `BLENDED`, cascade B fires in the same operation and the batch also moves
        `BLENDED → QUARANTINED`."

        Design: Corner/validations/waive_qc_refused_on_a_claim_eligible_batch
        """
        world = setup_blended_batch(
            tank_overrides={"tank_code": "TK-02", "heel_volume_l": 0.0,
                            "heel_additive_family": "NONE"}
        )
        assert world["batch"]["heel_ratio_actual"] == pytest.approx(0.0, abs=0.0000005)
        assert world["batch"]["claim_eligible"] is True

        validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "KV100", "measured_value": 7.900}, QC
            ),
            201,
        )
        failed = read_batch(world["batch"]["id"])
        assert failed["qc_status"] == "FAILED"
        assert failed["production_status"] == "QUARANTINED"

        response = api.waive_qc(
            world["batch"]["id"], {"justification": "customer accepts off-spec"}, QM
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED.value, 422)

        unchanged = read_batch(world["batch"]["id"])
        assert unchanged["qc_status"] == "FAILED"
        assert unchanged["production_status"] == "QUARANTINED"


class TestQuarantineExits:
    def test_rework_loop_returns_a_failed_batch_to_blended_and_passed(self, api):
        """PRD 3.5: "A `BlendOperator` may send a quarantined, QC-failed batch back for rework,
        supplying a `reason`; that requires the `production_status` to be `QUARANTINED` and the
        `qc_status` to be `FAILED`, moves the batch `QUARANTINED → REWORKED`, resets the quality
        dimension `FAILED → PENDING` and clears `measured_kv100_cst` back to null."
        PRD 3.4: "It is reachable from two originating states: `CHARGING → BLENDED`, which moves
        every `RESERVED` draw on the batch to `CONSUMED` and computes `component_cost_cents` by
        the consumption-layer method of §3.3; and `REWORKED → BLENDED`, permitted only while the
        batch's `qc_status` is `PENDING`, which recomputes `component_cost_cents` over the
        unchanged set of `CONSUMED` draws — the figure comes out identical, because rework
        consumes no additional material — and closes the quarantine-rework loop."
        PRD 3.5: "A subsequent result that completes the required test set moves the batch
        `SAMPLED → PASSED`; that transition requires the batch's results to cover both of the
        required tests — `KV100` and `TBN` — with every one of them carrying `PASS`."

        Design: Corner/state_machines/quarantined_batch_rework_cycle_returns_to_blended
        """
        world = setup_blended_batch()
        validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "KV100", "measured_value": 7.900}, QC
            ),
            201,
        )

        reworked = validate_success(
            api.rework_blend_batch(
                world["batch"]["id"], {"reason": "TOP_UP_BASE_OIL"}, OPERATOR
            )
        )
        assert reworked["production_status"] == "REWORKED"
        assert reworked["qc_status"] == "PENDING"
        assert reworked["measured_kv100_cst"] is None

        blended_again = validate_success(api.complete_blend(world["batch"]["id"], OPERATOR))
        assert blended_again["production_status"] == "BLENDED"
        assert blended_again["component_cost_cents"] == 546024

        alt = make_qc_technician_headers(QC_TECH_ALT_ID)
        validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "KV100", "measured_value": 7.610}, alt
            ),
            201,
        )
        sampled = read_batch(world["batch"]["id"])
        assert sampled["qc_status"] == "SAMPLED"
        assert sampled["measured_kv100_cst"] == pytest.approx(7.610, abs=0.0005)

        validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "TBN", "measured_value": 8.9}, alt
            ),
            201,
        )
        assert read_batch(world["batch"]["id"])["qc_status"] == "PASSED"

        _, meta = validate_paginated(api.list_qc_results(world["batch"]["id"], QC))
        assert meta["total_count"] == 3

    def test_disposed_batch_is_terminal_and_returns_no_mass(self, api):
        """PRD 3.5: "Alternatively a `QualityManager` may scrap the batch with a `reason`,
        moving it `QUARANTINED → DISPOSED`, which is terminal; disposal returns no mass to any
        lot, and the batch's draws stay `CONSUMED`."
        PRD 2.6: "10. Own-state legality — the target resource sits in a declared originating
        state for the requested transition; otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/disposed_batch_is_terminal_and_rejects_rework
        """
        world = setup_blended_batch()
        validate_success(
            api.create_qc_result(
                world["batch"]["id"], {"test_type": "KV100", "measured_value": 7.900}, QC
            ),
            201,
        )
        disposed = validate_success(
            api.dispose_blend_batch(
                world["batch"]["id"], {"reason": "OFF_SPEC_UNRECOVERABLE"}, QM
            )
        )
        assert disposed["production_status"] == "DISPOSED"
        assert disposed["qc_status"] == "FAILED"

        response = api.rework_blend_batch(
            world["batch"]["id"], {"reason": "SECOND_ATTEMPT"}, OPERATOR
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        assert read_batch(world["batch"]["id"])["production_status"] == "DISPOSED"

        lot_b1 = read_lot(world["lots"]["lot_b1"]["id"])
        assert lot_b1["available_kg"] == pytest.approx(0.000, abs=0.001)
        assert lot_b1["status"] == "DEPLETED"

        draws = list_batch_draws(world["batch"]["id"])
        assert len(draws) == 4
        assert all(d["status"] == "CONSUMED" for d in draws)

    def test_release_on_a_planned_batch_is_decided_on_its_own_state(self, api):
        """PRD 2.6: "10. Own-state legality — the target resource sits in a declared originating
        state for the requested transition; otherwise `ERR_INVALID_STATE` (409)."
        PRD 2.6: "23. Retain floor — the batch holds at least the required number of retain
        jars; otherwise `ERR_INSUFFICIENT_RETAINS` (422). Guards batch release."
        PRD 3.5: "It moves the batch `BLENDED → RELEASED` and requires four things: the
        `production_status` is `BLENDED`; the `qc_status` is either `PASSED` or `WAIVED`; the
        batch holds at least two retain jars, or the release is refused with
        `ERR_INSUFFICIENT_RETAINS` — the zero-jar case included; and the caller's `X-User-ID`
        matches no `technician_user_id` on any result of the batch, or the release is refused
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/release_from_planned_returns_invalid_state
        """
        world = setup_active_formulation(with_lots=False)
        batch = create_batch(world["recipe"]["id"])
        assert batch["retain_count"] == 0

        response = api.release_blend_batch(batch["id"], QM)
        error = validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_RETAINS.value

        assert read_batch(batch["id"])["production_status"] == "PLANNED"

"""Rounding boundaries, candidate-set filtering and the constants that clamp.

Every case here fixes the inputs so that a plausible shortcut — classifying from
an unrounded quotient, counting defects instead of weighting them, de-duplicating
overlapping refill coverage — produces a visibly different answer.
"""

from test_helpers import (
    ApiErrorId,
    BMD_FEMORAL_NECK_OSTEOPENIC,
    BMD_FOREARM_LOW,
    BMD_LUMBAR_OSTEOPENIC,
    BMD_TOTAL_HIP_OSTEOPENIC,
    CLOCK_SCAN_DAY,
    CLOCK_SETUP,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_HEADERS,
    assert_four_decimals,
    assert_qc_scoring,
    assert_review_outcome,
    assert_score_one_decimal,
    assert_three_decimals,
    assert_two_decimals,
    get_success_data,
    scan_order_payload,
    scan_session_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestScoresAreRoundedBeforeAnythingReadsThem:
    """A raw quotient of −2.0166… must be stored, and classified, as −2.0."""

    def test_the_one_decimal_value_drives_the_diagnosis_and_the_interval(
        self, world: ProgramWorld
    ):
        """Classifying from the unrounded quotient would report osteoporosis instead.

        "Each accepted row computes `t_score` as the measured density minus
        `reference_mean_bmd_g_cm2` divided by `reference_sd_g_cm2`, rounded half up
        to **one** decimal place, and `z_score` the same way against
        `age_matched_mean_bmd_g_cm2` and `age_matched_sd_g_cm2`. That one-decimal
        value, not the unrounded quotient, is what diagnosis and fracture-risk
        scoring consume downstream." "`OSTEOPOROSIS` at −2.5 or below, `OSTEOPENIA`
        above −2.5 and at or below −1.0"

        Design: Corner/calculations/t_and_z_scores_round_to_one_decimal_before_every_downstream_read
        """
        pipeline = world.build(
            stop_after="drafted",
            sites=[
                ("LUMBAR_SPINE", BMD_LUMBAR_OSTEOPENIC),
                ("TOTAL_HIP", BMD_TOTAL_HIP_OSTEOPENIC),
            ],
        )
        lumbar, total_hip = pipeline.measurements

        assert_score_one_decimal(lumbar["t_score"], -1.7, "lumbar t_score")
        assert_score_one_decimal(lumbar["z_score"], -0.4, "lumbar z_score")
        assert lumbar["valid_vertebral_count"] == 4
        assert lumbar["site_usable_for_diagnosis"] is True

        assert_score_one_decimal(total_hip["t_score"], -2.0, "total hip t_score")
        assert_score_one_decimal(total_hip["z_score"], -0.8, "total hip z_score")
        assert total_hip["valid_vertebral_count"] == 0

        session = world.read_session(pipeline.session_id)
        assert session["measured_site_count"] == 2
        assert_score_one_decimal(session["lowest_t_score"], -2.0, "lowest_t_score")
        assert session["lowest_t_score_site"] == "TOTAL_HIP"
        assert_score_one_decimal(session["lowest_z_score"], -0.8, "lowest_z_score")

        report = pipeline.report
        assert report["patient_age_years"] == 67
        assert report["classification_basis"] == "T_SCORE_WHO"
        assert report["diagnostic_category"] == "OSTEOPENIA"
        assert report["clinical_interval_months"] == 12


class TestForearmNeverCompetesWithACentralSite:
    """The lowest number on the session is deliberately not the diagnostic one."""

    def test_the_lowest_forearm_reading_is_ignored_and_precedence_breaks_the_tie(
        self, world: ProgramWorld
    ):
        """Two central sites tie at −2.0; the winner is fixed by site, not by entry order.

        "Only when that set is empty do non-superseded `FOREARM_33` rows become the
        candidate set — the forearm is a fallback skeletal site, never a competitor
        to a central one, so a session with a central measurement never diagnoses off
        the forearm even when the forearm reads lower." "with ties broken by the
        fixed precedence `LUMBAR_SPINE`, then `FEMORAL_NECK`, then `TOTAL_HIP`, then
        `FOREARM_33` — never by `created_at` and never by `id`" "`lowest_z_score` is
        the minimum `z_score` over that same candidate set and may well come from a
        different site than the one that supplied the lowest T-score."

        Design: Corner/calculations/forearm_is_excluded_from_the_candidate_set_and_precedence_breaks_the_tie
        """
        pipeline = world.build(
            stop_after="submitted",
            sites=[
                ("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC),
                ("TOTAL_HIP", BMD_TOTAL_HIP_OSTEOPENIC),
                ("FOREARM_33", BMD_FOREARM_LOW),
            ],
        )
        femoral_neck, total_hip, forearm = pipeline.measurements

        assert_score_one_decimal(forearm["t_score"], -3.0, "forearm t_score")
        assert_score_one_decimal(total_hip["t_score"], -2.0, "total hip t_score")
        assert_score_one_decimal(femoral_neck["t_score"], -2.0, "femoral neck t_score")
        assert_score_one_decimal(femoral_neck["z_score"], -0.5, "femoral neck z_score")

        session = pipeline.session
        assert session["measured_site_count"] == 3
        assert_score_one_decimal(session["lowest_t_score"], -2.0, "lowest_t_score")
        assert session["lowest_t_score_site"] == "FEMORAL_NECK"
        assert_score_one_decimal(session["lowest_z_score"], -0.8, "lowest_z_score")


BASELINE_PHANTOM = 1.0000
WITHIN_TOLERANCE_PHANTOM = 1.0090
EXCESSIVE_DRIFT_PHANTOM = 1.0600


def _run_calibration_event(world: ProgramWorld, device_id: str, new_density: float):
    """Three runs on each side of one software upgrade, closed and adjudicated."""
    event = world.open_calibration_event(device_id, change_note="vendor patch 7.3")
    world.record_cross_cal_runs(
        device_id, event["id"], "CROSS_CAL_BASELINE", BASELINE_PHANTOM, 3
    )
    new_runs = world.record_cross_cal_runs(
        device_id, event["id"], "CROSS_CAL_NEW", new_density, 3
    )
    closed = world.close_calibration_event(event["id"])
    adjudicated = world.adjudicate_calibration_event(event["id"])
    return closed, adjudicated, new_runs


class TestCrossCalibrationBracketsBothToleranceEdges:
    """Below one percent forces a factor of exactly one; above five refuses outright."""

    def test_a_within_tolerance_event_pins_the_factor_at_one_and_bumps_the_generation(
        self, world: ProgramWorld
    ):
        """The raw ratio of the two means is not one, and the stored factor still is.

        "an absolute percent difference **below** 1.00 is
        `WITHIN_TOLERANCE_NO_FACTOR` with `proposed_cross_cal_factor` set to exactly
        1.0000" "the device's `cross_cal_factor` is set to exactly 1.0 when the
        `outcome_code` is `WITHIN_TOLERANCE_NO_FACTOR` ...; the device's
        `calibration_generation` increments by one; the device returns from
        `CROSS_CAL_PENDING` to `ACTIVE`" "Cross-calibration runs behave differently in
        exactly two respects: they are scored identically but never change the
        device's `status` or its `consecutive_qc_pass_count`"

        Design: Corner/calculations/cross_calibration_constants_bracket_the_no_factor_and_excessive_drift_edges
        """
        world.set_clock(CLOCK_SETUP)
        device = world.create_device()

        closed, adjudicated, _ = _run_calibration_event(
            world, device["id"], WITHIN_TOLERANCE_PHANTOM
        )

        assert closed["required_phantom_runs"] == 3
        assert closed["baseline_run_count"] == 3
        assert closed["new_run_count"] == 3
        assert_four_decimals(
            closed["baseline_mean_bmd_g_cm2"], 1.0000, "baseline_mean_bmd_g_cm2"
        )
        assert_four_decimals(closed["new_mean_bmd_g_cm2"], 1.0090, "new_mean_bmd_g_cm2")
        assert_two_decimals(closed["percent_difference"], 0.90, "percent_difference")
        assert closed["outcome_code"] == "WITHIN_TOLERANCE_NO_FACTOR"
        assert_four_decimals(
            closed["proposed_cross_cal_factor"], 1.0000, "proposed_cross_cal_factor"
        )

        assert adjudicated["status"] == "APPROVED"

        stored = world.read_device(device["id"])
        assert stored["cross_cal_factor"] == 1.0
        assert stored["calibration_generation"] == 2
        assert stored["status"] == "ACTIVE"
        assert stored["consecutive_qc_pass_count"] == 0

    def test_an_excessive_drift_event_is_rejected_and_strands_the_device(
        self, world: ProgramWorld
    ):
        """Six percent leaves the factor null, the generation flat and the device unusable.

        "an absolute percent difference above 5.00 is `REJECTED_EXCESSIVE_DRIFT` with
        a null `proposed_cross_cal_factor`" "there is no generation bump, no change to
        `cross_cal_factor`, and no return to `ACTIVE`. The device stays in
        `CROSS_CAL_PENDING`" "an absolute value greater than 1.500 is a `FAIL`"

        Design: Corner/calculations/cross_calibration_constants_bracket_the_no_factor_and_excessive_drift_edges
        """
        world.set_clock(CLOCK_SETUP)
        device = world.create_device()
        _run_calibration_event(world, device["id"], WITHIN_TOLERANCE_PHANTOM)

        closed, adjudicated, failing_runs = _run_calibration_event(
            world, device["id"], EXCESSIVE_DRIFT_PHANTOM
        )

        assert_two_decimals(closed["percent_difference"], 6.00, "percent_difference")
        assert closed["outcome_code"] == "REJECTED_EXCESSIVE_DRIFT"
        assert closed["proposed_cross_cal_factor"] is None
        assert adjudicated["status"] == "REJECTED"

        for run in failing_runs:
            assert_qc_scoring(run, 0.0600, 6.000, "FAIL")

        stranded = world.read_device(device["id"])
        assert stranded["status"] == "CROSS_CAL_PENDING"
        assert stranded["qc_hold_reason_code"] is None
        assert stranded["calibration_generation"] == 2
        assert stranded["cross_cal_factor"] == 1.0
        assert stranded["consecutive_qc_pass_count"] == 0


class TestDefectWeightsAreSummedNotCounted:
    """One light defect plus one medium defect reaches the threshold; the light one alone does not."""

    def test_a_scoring_three_pair_repeats_and_a_scoring_one_single_accepts(
        self, world: ProgramWorld
    ):
        """Two defects can outweigh one, so the sum — not the count — decides.

        "`severity_score` is the weighted sum over the distinct codes present ...
        `ABDUCTION_FEMUR`, `SPINE_NOT_STRAIGHT` and `MOTION_ARTIFACT` weigh two each;
        and `ARTIFACT_IN_FIELD` weighs one." "`repeat_criterion_met` is true when
        `severity_score` reaches three, so any single heavy defect is enough on its
        own, while two light defects — an artefact in the field plus a motion
        artefact, scoring three together — reach the threshold jointly." "when the
        criterion is not met the outcome is `ACCEPTED`"

        Design: Corner/calculations/positioning_defect_weights_sum_to_the_threshold_then_fall_below_it
        """
        pipeline = world.build(stop_after="submitted")

        first = world.review_positioning(
            pipeline.session_id,
            ["ARTIFACT_IN_FIELD", "MOTION_ARTIFACT"],
            reviewer_note="artifact plus motion",
        )
        assert_review_outcome(first, 3, True, "REPEAT_REQUIRED")

        world.repeat(pipeline.session_id)
        world.measure(
            pipeline.session_id, "FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC
        )
        world.submit(pipeline.session_id)

        second = world.review_positioning(
            pipeline.session_id,
            ["ARTIFACT_IN_FIELD"],
            reviewer_note="minor artifact only",
        )
        assert_review_outcome(second, 1, False, "ACCEPTED")

        session = world.read_session(pipeline.session_id)
        assert session["review_status"] == "ACCEPTED"
        assert session["repeat_count"] == 1


PLAN_START = "2026-04-01"
REVIEW_CLOCK = "2026-07-01T10:00:00Z"
FILL_DAYS = 50


class TestOverlappingRefillsAreClampedRatherThanDeduplicated:
    """Two hundred supplied days inside ninety-one must not read as 2.198."""

    def test_the_ratio_is_capped_and_still_classifies_the_patient_adherent(
        self, world: ProgramWorld
    ):
        """Four identical fifty-day fills all count in full, and the cap absorbs the excess.

        "Overlapping coverage is deliberately **not** de-duplicated: two refills
        covering the same calendar days both count in full, which is exactly why the
        ratio is capped. `medication_possession_ratio` is `covered_days_supplied`
        divided by `adherence_window_days`, clamped to a maximum of 1.5, and then
        rounded half up to three decimal places ... Two hundred supplied days across a
        ninety-one-day window therefore reads 1.500, not 2.198." "The row computes
        `source_weight` — 1.0 for a pharmacy claim and 0.5 for a patient report — and
        `coverage_end_date`, the `dispensed_date` advanced by `days_supplied` days."

        Design: Corner/calculations/overlapping_refills_are_not_deduplicated_but_are_clamped_at_the_mpr_cap
        """
        pipeline = world.build_treatment_pipeline()
        assert pipeline.plan["start_date"] == PLAN_START

        world.set_clock(REVIEW_CLOCK)
        refills = [
            world.record_refill(
                pipeline.plan_id,
                dispensed_date=PLAN_START,
                days_supplied=FILL_DAYS,
                source="PHARMACY_CLAIM",
            )
            for _ in range(4)
        ]
        assert refills[0]["source_weight"] == 1.0
        assert refills[0]["coverage_end_date"] == "2026-05-21"

        reviewed = validate_success(
            world.api.create_adherence_review(
                pipeline.plan_id, {"note": "four overlapping fills"}, PHYSICIAN_HEADERS
            ),
            200,
        )

        assert reviewed["adherence_window_days"] == 91
        assert reviewed["covered_days_supplied"] == 200.0
        assert_three_decimals(
            reviewed["medication_possession_ratio"], 1.500, "medication_possession_ratio"
        )
        assert reviewed["adherence_status"] == "ADHERENT"
        assert reviewed["status"] == "ON_THERAPY"
        assert reviewed["consecutive_nonadherent_reviews"] == 0
        assert reviewed["adherence_review_count"] == 1
        assert reviewed["last_review_date"] == "2026-07-01"
        assert reviewed["next_followup_due_date"] == "2026-10-01"
        assert reviewed["denosumab_gap_days"] is None
        assert reviewed["holiday_eligible"] is False


SECOND_SCAN_DAY = "2026-03-11T09:05:00Z"


def _draft_prior_then_second_session(world: ProgramWorld):
    """One accepted study whose only report is still a draft, then a second study."""
    pipeline = world.foundation(clock=CLOCK_SETUP)
    first_order = world.create_order(
        pipeline.patient_id, requested_scan_date="2026-03-10"
    )
    first_slot = world.book(first_order["id"], pipeline.device_id)
    second_order = world.create_order(
        pipeline.patient_id, requested_scan_date="2026-03-11"
    )
    second_slot = world.book(
        second_order["id"],
        pipeline.device_id,
        start_utc="2026-03-11T09:00:00Z",
        end_utc="2026-03-11T09:30:00Z",
    )

    world.set_clock(CLOCK_SCAN_DAY)
    first_session = world.start_session(first_slot["id"])
    world.measure(first_session["id"], "FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC)
    world.submit(first_session["id"])
    world.review_positioning(first_session["id"])
    report = world.draft_report(first_session["id"])
    assert report["status"] == "DRAFT"

    world.set_clock(SECOND_SCAN_DAY)
    return pipeline, second_order, second_slot, report


class TestOnlyAFinalizedStudyCanBecomeAPrior:
    """A draft report keeps its session out of the pool, permanently."""

    def test_the_second_session_is_a_baseline_and_stays_one_after_the_finalize(
        self, world: ProgramWorld
    ):
        """Finalizing afterwards reaches the order but never rewrites the frozen choice.

        "The candidate pool is every other session of the same patient whose
        `acquisition_status` is `SUBMITTED` or `ARCHIVED`, whose `review_status` is
        `ACCEPTED` or `ACCEPTED_WITH_LIMITATION`, and which carries at least one
        report in `status` `FINALIZED` — an unreviewed, repeat-required or unreported
        study is not a clinical prior no matter how recent." "The comparison prior is
        also fixed at creation, by a three-stage waterfall, and it is never recomputed
        afterwards." "any whose verdict is now `INELIGIBLE_TOO_SOON` or
        `INELIGIBLE_LIFETIME_CAP` moves to `DENIED` — with `denial_reason_code`
        `INTERVAL_REVISED_BY_REPORT` for a too-soon verdict"

        Design: Corner/calculations/a_prior_session_whose_report_is_still_draft_is_invisible_and_the_choice_is_frozen
        """
        pipeline, second_order, second_slot, report = _draft_prior_then_second_session(
            world
        )

        second_session = validate_success(
            world.api.create_scan_session(
                second_slot["id"], scan_session_payload(), TECHNOLOGIST_HEADERS
            ),
            201,
        )
        assert second_session["prior_session_id"] is None
        assert second_session["prior_comparison_status"] == "BASELINE_NO_PRIOR"
        assert_four_decimals(
            second_session["applied_lsc_g_cm2"], 0.0277, "applied_lsc_g_cm2"
        )

        validate_success(
            world.api.finalize_diagnostic_report(report["id"], PHYSICIAN_HEADERS), 200
        )

        unchanged = world.read_session(second_session["id"])
        assert unchanged["prior_session_id"] is None
        assert unchanged["prior_comparison_status"] == "BASELINE_NO_PRIOR"

        patient = world.read_patient(pipeline.patient_id)
        assert patient["next_eligible_scan_date"] == "2028-03-10"

        denied = get_success_data(
            world.api.get_scan_order(second_order["id"], PHYSICIAN_HEADERS)
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason_code"] == "INTERVAL_REVISED_BY_REPORT"


class TestTheGraceWindowIsInclusiveToTheDay:
    """Thirty grace days admit 2028-02-09 and refuse 2028-02-08."""

    def test_the_boundary_date_is_granted_grace_and_one_day_earlier_is_refused(
        self, world: ProgramWorld
    ):
        """The refused request persists nothing, so the worklist still holds two orders.

        "earlier than it but no earlier than that date less the policy's
        `repeat_scan_grace_days` whole days the verdict is `ELIGIBLE_WITH_GRACE`;
        earlier still the verdict is `INELIGIBLE_TOO_SOON`. Both comparisons are
        inclusive, so a request landing exactly on `earliest_allowed_date` is plainly
        eligible and one landing exactly the full grace window before it still
        qualifies for grace, while one day earlier than that does not." "When
        `appeal_allowed` is false the request is rejected outright with
        `ERR_PAYER_FREQUENCY_LIMIT` for a too-soon verdict ... and no order is
        persisted."

        Design: Corner/calculations/grace_window_admits_the_exact_boundary_date_and_rejects_one_day_earlier
        """
        pipeline = world.build(stop_after="finalized")
        assert pipeline.patient["next_eligible_scan_date"] == "2028-03-10"

        granted = validate_success(
            world.api.create_scan_order(
                scan_order_payload(
                    pipeline.patient_id,
                    indication="SERIAL_MONITORING",
                    requested_scan_date="2028-02-09",
                ),
                SCHEDULER_HEADERS,
            ),
            201,
        )
        assert granted["status"] == "REQUESTED"
        assert granted["frequency_eligibility"] == "ELIGIBLE_WITH_GRACE"
        assert granted["earliest_allowed_date"] == "2028-03-10"
        assert granted["denial_reason_code"] is None

        refused = world.api.create_scan_order(
            scan_order_payload(
                pipeline.patient_id,
                indication="SERIAL_MONITORING",
                requested_scan_date="2028-02-08",
            ),
            SCHEDULER_HEADERS,
        )
        validate_error(refused, ApiErrorId.PAYER_FREQUENCY_LIMIT.value, 402)

        orders, meta = validate_paginated(
            world.api.list_scan_orders(
                SCHEDULER_HEADERS, {"patient_id": pipeline.patient_id}
            )
        )
        assert meta["total_count"] == 2
        assert granted["id"] in {order["id"] for order in orders}

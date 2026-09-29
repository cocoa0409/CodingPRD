"""Values sitting exactly on a published edge, and their nearest neighbours.

Every pair below is one ten-thousandth or one hundredth apart, and each edge is
declared inclusive on one side only. An implementation that uses a strict
comparison, or that classifies the unrounded quotient, moves the verdict.
"""

from test_helpers import (
    ProgramWorld,
    assert_four_decimals,
    assert_instant_equals,
    assert_qc_scoring,
    assert_score_one_decimal,
    assert_three_decimals,
    assert_two_decimals,
)

QC_BOUNDARY_CLOCK = "2026-03-05T08:00:00Z"
PHANTOM_AT_THE_LIMIT = 1.0150
PHANTOM_ONE_TEN_THOUSANDTH_OVER = 1.0151


def _qc_boundary_device(world: ProgramWorld):
    """A fresh device whose control-limit unit is one hundredth of a gram."""
    world.set_clock(QC_BOUNDARY_CLOCK)
    device = world.create_device(
        phantom_baseline_bmd_g_cm2=1.0000, phantom_baseline_sd_g_cm2=0.0100
    )
    assert device["status"] == "ACTIVE"
    assert device["consecutive_qc_pass_count"] == 0
    return device["id"]


class TestQcDeviationSitsOnTheWarnFailEdge:
    """Exactly 1.500 standard deviations warns; 1.510 stops the instrument."""

    def test_exactly_at_the_limit_warns_and_leaves_the_device_active(
        self, world: ProgramWorld
    ):
        """A deviation of exactly 1.500 is a warning, not a failure.

        "an absolute value of at most 1.000 is a `PASS`, an absolute value greater
        than 1.000 but at most 1.500 is a `WARN`, and an absolute value greater
        than 1.500 is a `FAIL`. Both boundaries are inclusive on the gentler side,
        so exactly 1.000 passes and exactly 1.500 warns rather than failing."

        Design: Difficulty/boundary_precision_check/qc_deviation_exactly_at_fail_limit_is_warn_and_one_thousandth_over_is_fail
        """
        device_id = _qc_boundary_device(world)

        warning = world.record_qc_run(
            device_id, phantom_bmd_g_cm2=PHANTOM_AT_THE_LIMIT
        )

        assert_qc_scoring(warning, 0.0150, 1.500, "WARN")
        assert warning["shift_detected"] is False

        device = world.read_device(device_id)
        assert device["status"] == "ACTIVE"
        assert device["qc_hold_reason_code"] is None
        assert device["consecutive_qc_pass_count"] == 0

    def test_one_ten_thousandth_over_the_limit_fails_and_holds_the_device(
        self, world: ProgramWorld
    ):
        """1.0151 scores 1.510 once rounded, which is past the limit.

        "The `result` then reads the **already-rounded** three-decimal figure,
        never the raw quotient." "A `FAIL` drives `status` from `ACTIVE` to
        `QC_HOLD` with `qc_hold_reason_code` `OUT_OF_CONTROL_FAIL`,
        `qc_hold_started_at` set to the run's `performed_at_utc`, and
        `consecutive_qc_pass_count` reset to zero."

        Design: Difficulty/boundary_precision_check/qc_deviation_exactly_at_fail_limit_is_warn_and_one_thousandth_over_is_fail
        """
        device_id = _qc_boundary_device(world)
        world.record_qc_run(device_id, phantom_bmd_g_cm2=PHANTOM_AT_THE_LIMIT)

        failing = world.record_qc_run(
            device_id, phantom_bmd_g_cm2=PHANTOM_ONE_TEN_THOUSANDTH_OVER
        )

        assert_qc_scoring(failing, 0.0151, 1.510, "FAIL")
        assert failing["shift_detected"] is False

        device = world.read_device(device_id)
        assert device["status"] == "QC_HOLD"
        assert device["qc_hold_reason_code"] == "OUT_OF_CONTROL_FAIL"
        assert_instant_equals(
            device["qc_hold_started_at"], QC_BOUNDARY_CLOCK, "qc_hold_started_at"
        )
        assert device["last_qc_result"] == "FAIL"


PRIOR_HIP_BMD = 0.7000
FOLLOWUP_HIP_BMD_ON_THE_EDGE = 0.6723


def _serial_pair_on_the_lsc_edge(world: ProgramWorld):
    """A total-hip follow-up whose change equals the least significant change exactly."""
    baseline = world.build(
        stop_after="finalized", sites=[("TOTAL_HIP", PRIOR_HIP_BMD)]
    )

    world.set_clock("2028-03-12T08:00:00Z")
    followup_order = world.create_order(
        baseline.patient_id,
        indication="SERIAL_MONITORING",
        requested_sites=["TOTAL_HIP"],
        requested_scan_date="2028-03-15",
    )
    followup_slot = world.book(
        followup_order["id"],
        baseline.device_id,
        start_utc="2028-03-15T09:00:00Z",
        end_utc="2028-03-15T09:30:00Z",
    )
    world.set_clock("2028-03-15T09:05:00Z")
    session = world.start_session(followup_slot["id"])
    world.measure(session["id"], "TOTAL_HIP", FOLLOWUP_HIP_BMD_ON_THE_EDGE)
    world.submit(session["id"])
    world.review_positioning(session["id"], [])
    session = world.read_session(session["id"])
    report = world.draft_report(session["id"])
    return baseline, session, report


class TestBmdChangeExactlyEqualToTheLsc:
    """A change of exactly the negated LSC is a loss; one ten-thousandth less is not."""

    def test_the_follow_up_session_carries_the_uncorrected_comparison(
        self, world: ProgramWorld
    ):
        """Same instrument, no recalibration, so the prior is carried at 1.0.

        "`prior_bmd_used_g_cm2` is the prior session's density at that site
        multiplied by the cross-calibration factor — 1.0000 unless
        `prior_comparison_status` is `PRIOR_CROSS_CAL_ADJUSTED` ..." "A study reporting
        0.0100 therefore certifies a least significant change of 0.0277."

        Design: Difficulty/boundary_precision_check/bmd_change_exactly_equal_to_lsc_is_significant_loss
        """
        baseline, session, _ = _serial_pair_on_the_lsc_edge(world)

        device = world.read_device(baseline.device_id)
        assert_four_decimals(device["lsc_g_cm2"], 0.0277, "lsc_g_cm2")
        assert device["precision_degrees_of_freedom"] == 30

        assert_four_decimals(
            session["applied_lsc_g_cm2"], 0.0277, "applied_lsc_g_cm2"
        )
        assert session["applied_cross_cal_factor"] == 1.0
        assert session["prior_session_id"] == baseline.session_id
        assert session["prior_comparison_status"] == "COMPARABLE_SAME_DEVICE"
        assert_score_one_decimal(session["lowest_t_score"], -2.2, "lowest_t_score")

    def test_the_change_on_the_edge_reads_significant_loss_and_caps_the_interval(
        self, world: ProgramWorld
    ):
        """The loss branch is inclusive, and the verdict then caps the interval.

        "A change of exactly −0.0277 against an LSC of 0.0277 is a
        `SIGNIFICANT_LOSS`; −0.0276 is not." "Then, if `lsc_interpretation` is
        `SIGNIFICANT_LOSS`, the interval is capped at twelve months." "Failing
        that, a `SIGNIFICANT_LOSS` yields `REFER_SECONDARY_WORKUP`."

        Design: Difficulty/boundary_precision_check/bmd_change_exactly_equal_to_lsc_is_significant_loss
        """
        _, _, report = _serial_pair_on_the_lsc_edge(world)

        assert_four_decimals(
            report["prior_bmd_used_g_cm2"], 0.7000, "prior_bmd_used_g_cm2"
        )
        assert_four_decimals(
            report["current_bmd_used_g_cm2"], 0.6723, "current_bmd_used_g_cm2"
        )
        assert_four_decimals(report["bmd_change_g_cm2"], -0.0277, "bmd_change_g_cm2")
        assert_two_decimals(report["bmd_change_pct"], -3.96, "bmd_change_pct")
        assert report["lsc_interpretation"] == "SIGNIFICANT_LOSS"
        assert report["diagnostic_category"] == "OSTEOPENIA"
        assert report["clinical_interval_months"] == 12
        assert report["payer_floor_months"] == 24
        assert report["recommended_interval_months"] == 24
        assert report["recommended_action"] == "REFER_SECONDARY_WORKUP"


def _plan_on_the_adherent_edge(world: ProgramWorld):
    """Seventy-two covered days recorded a day before the review date."""
    pipeline = world.build(
        stop_after="finalized", sites=[("FEMORAL_NECK", 0.5500)]
    )
    assert pipeline.report["recommended_action"] == "INITIATE_TREATMENT"

    plan = world.create_plan(
        pipeline.patient_id,
        pipeline.report_id,
        drug_class="BISPHOSPHONATE_ORAL",
        start_date="2026-04-01",
        adherence_source_policy="CLAIMS_ONLY",
    )
    assert plan["next_followup_due_date"] == "2026-07-01"

    world.set_clock("2026-06-29T08:00:00Z")
    world.record_refill(
        plan["id"],
        dispensed_date="2026-04-01",
        days_supplied=42,
        source="PHARMACY_CLAIM",
    )
    world.record_refill(
        plan["id"],
        dispensed_date="2026-05-15",
        days_supplied=30,
        source="PHARMACY_CLAIM",
    )
    world.set_clock("2026-06-30T08:00:00Z")
    return plan


class TestMprExactlyAtTheAdherentMinimum:
    """A ratio of exactly 0.800 is adherent, and the early window admits the day before."""

    def test_the_review_is_accepted_one_day_inside_the_early_window(
        self, world: ProgramWorld
    ):
        """Six days early is inside the one-week window, and the window is half-open.

        "A review is accepted only when the logical clock date is at or after
        `next_followup_due_date` less seven days — a one-week early window."
        "`adherence_window_days` is the whole number of days from the plan's
        `start_date` to the clock date at review time."

        Design: Difficulty/boundary_precision_check/mpr_exactly_at_adherent_minimum_is_adherent
        """
        plan = _plan_on_the_adherent_edge(world)

        reviewed = world.review_adherence(
            plan["id"], requested_action="AUTO", note="boundary review"
        )

        assert reviewed["adherence_window_days"] == 90
        assert reviewed["covered_days_supplied"] == 72.0
        assert reviewed["adherence_review_count"] == 1
        assert reviewed["last_review_date"] == "2026-06-30"
        assert reviewed["next_followup_due_date"] == "2026-09-30"
        assert reviewed["denosumab_gap_days"] is None

    def test_a_ratio_of_exactly_the_minimum_reads_adherent(self, world: ProgramWorld):
        """Seventy-two over ninety is exactly 0.800, which is the inclusive edge.

        "`adherence_status` reads the rounded ratio: `ADHERENT` at 0.800 or above,
        `PARTIAL` from 0.500 up to but not including 0.800, and `NON_ADHERENT`
        below 0.500. Exactly 0.800 is adherent and 0.799 is partial ... A
        ninety-day window with forty-two plus thirty claimed days lands on exactly
        0.800."

        Design: Difficulty/boundary_precision_check/mpr_exactly_at_adherent_minimum_is_adherent
        """
        plan = _plan_on_the_adherent_edge(world)

        reviewed = world.review_adherence(
            plan["id"], requested_action="AUTO", note="boundary review"
        )

        assert_three_decimals(
            reviewed["medication_possession_ratio"], 0.800, "medication_possession_ratio"
        )
        assert reviewed["adherence_status"] == "ADHERENT"
        assert reviewed["status"] == "ON_THERAPY"
        assert reviewed["consecutive_nonadherent_reviews"] == 0


BMD_AT_THE_OSTEOPOROSIS_EDGE = 0.6000
BMD_ONE_HUNDREDTH_ABOVE_THE_EDGE = 0.6100


def _two_patients_either_side_of_the_edge(world: ProgramWorld):
    """Two studies on one device, one hundredth of a gram apart."""
    first = world.build(
        stop_after="drafted", sites=[("FEMORAL_NECK", BMD_AT_THE_OSTEOPOROSIS_EDGE)]
    )

    second_patient = world.create_patient(first.policy_id)
    second_order = world.create_order(
        second_patient["id"],
        requested_sites=["FEMORAL_NECK"],
        requested_scan_date="2026-03-11",
    )
    second_slot = world.book(
        second_order["id"],
        first.device_id,
        start_utc="2026-03-11T09:00:00Z",
        end_utc="2026-03-11T09:30:00Z",
    )
    world.set_clock("2026-03-11T09:05:00Z")
    second_session = world.start_session(second_slot["id"])
    second_measurement = world.measure(
        second_session["id"], "FEMORAL_NECK", BMD_ONE_HUNDREDTH_ABOVE_THE_EDGE
    )
    world.submit(second_session["id"])
    world.review_positioning(second_session["id"], [])
    second_report = world.draft_report(second_session["id"])
    return first, second_measurement, second_report


class TestTScoreOnTheOsteoporosisEdge:
    """Exactly −2.5 is osteoporosis; −2.4 is osteopenia."""

    def test_exactly_minus_two_point_five_is_osteoporosis(self, world: ProgramWorld):
        """The severe side of the boundary is inclusive.

        "`diagnostic_category` reads the session's `lowest_t_score`:
        `OSTEOPOROSIS` at −2.5 or below, `OSTEOPENIA` above −2.5 and at or below
        −1.0, and `NORMAL` above −1.0. Both boundaries are inclusive on the more
        severe side, so exactly −2.5 is osteoporosis and exactly −1.0 is
        osteopenia." "`OSTEOPOROSIS` gives twelve months."

        Design: Difficulty/boundary_precision_check/t_score_exactly_minus_two_point_five_is_osteoporosis_and_minus_two_point_four_is_osteopenia
        """
        first, _, _ = _two_patients_either_side_of_the_edge(world)

        measurement = first.measurements[0]
        assert_score_one_decimal(measurement["t_score"], -2.5, "t_score")
        assert_score_one_decimal(measurement["z_score"], -1.0, "z_score")
        assert measurement["site_usable_for_diagnosis"] is True
        assert measurement["valid_vertebral_count"] == 0

        report = first.report
        assert report["classification_basis"] == "T_SCORE_WHO"
        assert report["diagnostic_category"] == "OSTEOPOROSIS"
        assert report["clinical_interval_months"] == 12
        assert report["recommended_interval_months"] == 24
        assert report["recommended_action"] == "INITIATE_TREATMENT"

    def test_one_hundredth_of_a_gram_higher_is_osteopenia(self, world: ProgramWorld):
        """A t_score of −2.4 crosses out of the osteoporosis band entirely.

        "`OSTEOPENIA` gives twelve months when `lowest_t_score` is at or below
        −2.0 and twenty-four otherwise, so exactly −2.0 takes the shorter branch."
        "Failing that, a `recommended_interval_months` greater than
        `clinical_interval_months` yields `PAYER_LIMITED_INTERVAL`."

        Design: Difficulty/boundary_precision_check/t_score_exactly_minus_two_point_five_is_osteoporosis_and_minus_two_point_four_is_osteopenia
        """
        _, measurement, report = _two_patients_either_side_of_the_edge(world)

        assert_score_one_decimal(measurement["t_score"], -2.4, "t_score")
        assert_score_one_decimal(measurement["z_score"], -0.9, "z_score")

        assert report["diagnostic_category"] == "OSTEOPENIA"
        assert report["clinical_interval_months"] == 12
        assert report["recommended_interval_months"] == 24
        assert report["recommended_action"] == "PAYER_LIMITED_INTERVAL"

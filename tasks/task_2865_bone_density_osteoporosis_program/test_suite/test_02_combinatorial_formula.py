"""Single answers assembled from several interacting inputs.

Each figure here is the product of a chain of terms or of a fixed order of
operations, so getting any one link wrong moves the published number.
"""

import pytest

from test_helpers import (
    BMD_FEMORAL_NECK_OSTEOPOROTIC,
    ProgramWorld,
    assert_four_decimals,
    assert_score_one_decimal,
    assert_two_decimals,
)

HEAVY_PROFILE = {
    "height_cm": 160.0,
    "weight_kg": 48.0,
    "prior_fragility_fracture": True,
    "parental_hip_fracture": True,
    "current_smoker": True,
    "glucocorticoid_use": True,
    "rheumatoid_arthritis": True,
    "secondary_osteoporosis": True,
    "alcohol_units_per_day": 4.0,
}


def _heavy_risk_world(world: ProgramWorld):
    """An eighty-year-old with every risk factor set and a femoral-neck t_score of -3.0."""
    return world.build(
        stop_after="submitted",
        with_profile=True,
        profile_overrides=HEAVY_PROFILE,
        patient_overrides={
            "birth_date": "1945-05-12",
            "sex": "FEMALE",
            "postmenopausal": True,
            "baseline_height_cm": 165.0,
        },
        sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPOROTIC)],
    )


class TestFraxTermStackAndClamp:
    """Five terms feed one raw score, and the raw score feeds two clamped lines."""

    def test_every_points_term_is_rounded_before_the_sum(self, world: ProgramWorld):
        """The BMI tier, the seven-way risk sum and the signed BMD term all land.

        "`bmi_points` reads it in three tiers: 0.80 points below 20.00 ..."
        "`clinical_risk_points` is the sum of the weights of the risk factors
        that are true on the profile: 1.90 for `prior_fragility_fracture`, 1.30
        for `parental_hip_fracture`, 0.90 for `current_smoker`, 1.60 for
        `glucocorticoid_use`, 1.20 for `rheumatoid_arthritis`, 0.80 for
        `secondary_osteoporosis`, and 1.00 when `alcohol_units_per_day` is at or
        above 3.0."

        Design: Difficulty/combinatorial_formula/frax_heavy_profile_stacks_bmi_tier_crf_sum_and_major_cap_clamp
        """
        pipeline = _heavy_risk_world(world)

        assert pipeline.profile["clinical_risk_factor_count"] == 7
        assert_two_decimals(pipeline.profile["bmi"], 18.75, "bmi")

        assessment = world.assess_frax(
            pipeline.patient_id, pipeline.profile_id, pipeline.session_id
        )

        assert assessment["age_years"] == 80
        assert_two_decimals(assessment["bmi_used"], 18.75, "bmi_used")
        assert_two_decimals(assessment["age_points"], 3.00, "age_points")
        assert_two_decimals(assessment["sex_points"], 0.60, "sex_points")
        assert_two_decimals(assessment["bmi_points"], 0.80, "bmi_points")
        assert_two_decimals(
            assessment["clinical_risk_points"], 8.70, "clinical_risk_points"
        )
        assert_two_decimals(assessment["bmd_points"], 3.60, "bmd_points")
        assert_two_decimals(assessment["raw_score"], 16.70, "raw_score")

    def test_major_probability_is_capped_while_the_hip_probability_is_not(
        self, world: ProgramWorld
    ):
        """A raw score of 16.70 implies 103.2 for the major line, so the cap fires.

        "`major_osteoporotic_10yr_pct` is 3.0 plus 6.0 times the raw score,
        floored at 0.5 and capped at 60.0; `hip_fracture_10yr_pct` is 0.4 plus
        1.6 times the raw score, floored at 0.1 and capped at 30.0. The clamps
        are applied before the final rounding, never after."

        Design: Difficulty/combinatorial_formula/frax_heavy_profile_stacks_bmi_tier_crf_sum_and_major_cap_clamp
        """
        pipeline = _heavy_risk_world(world)

        assessment = world.assess_frax(
            pipeline.patient_id, pipeline.profile_id, pipeline.session_id
        )

        assert_score_one_decimal(
            assessment["major_osteoporotic_10yr_pct"],
            60.0,
            "major_osteoporotic_10yr_pct",
        )
        assert_score_one_decimal(
            assessment["hip_fracture_10yr_pct"], 27.1, "hip_fracture_10yr_pct"
        )
        assert assessment["treatment_threshold_met"] is True
        assert assessment["threshold_basis"] == "BOTH"


PRIOR_TOTAL_HIP_BMD = 0.7000
FOLLOWUP_TOTAL_HIP_BMD = 0.6700


def _cross_calibrated_serial_pair(world: ProgramWorld):
    """A finalized total-hip baseline, an approved software upgrade, then a follow-up.

    Returns the pipeline of the baseline study, the calibration event, the
    follow-up session and the follow-up draft report.
    """
    pipeline = world.build(
        stop_after="finalized",
        sites=[("TOTAL_HIP", PRIOR_TOTAL_HIP_BMD)],
    )

    event = world.open_calibration_event(
        pipeline.device_id, change_type="SOFTWARE_UPGRADE"
    )
    world.record_cross_cal_runs(
        pipeline.device_id, event["id"], "CROSS_CAL_BASELINE", 1.0000, 3
    )
    world.record_cross_cal_runs(
        pipeline.device_id, event["id"], "CROSS_CAL_NEW", 1.0200, 3
    )
    closed = world.close_calibration_event(event["id"])
    approved = world.adjudicate_calibration_event(event["id"])

    world.set_clock("2028-03-12T08:00:00Z")
    followup_order = world.create_order(
        pipeline.patient_id,
        indication="SERIAL_MONITORING",
        requested_sites=["TOTAL_HIP"],
        requested_scan_date="2028-03-15",
    )
    followup_appointment = world.book(
        followup_order["id"],
        pipeline.device_id,
        start_utc="2028-03-15T09:00:00Z",
        end_utc="2028-03-15T09:30:00Z",
    )
    world.set_clock("2028-03-15T09:05:00Z")
    session = world.start_session(followup_appointment["id"])
    world.measure(session["id"], "TOTAL_HIP", FOLLOWUP_TOTAL_HIP_BMD)
    world.submit(session["id"])
    world.review_positioning(session["id"], [])
    session = world.read_session(session["id"])
    report = world.draft_report(session["id"])
    return pipeline, closed, approved, session, report


class TestCrossCalibrationOrderOfOperations:
    """Round the means, derive the factor, adjust the prior, only then subtract."""

    def test_phantom_means_are_rounded_before_the_factor_is_derived(
        self, world: ProgramWorld
    ):
        """A 1.0000 baseline against a 1.0200 new mean gives 2.00 and 0.9804.

        "Both means are rounded **before** anything is derived from them." "A
        baseline mean of 1.0000 against a new mean of 1.0200 therefore gives a
        percent difference of 2.00, a `FACTOR_APPLIED` outcome, and a factor of
        0.9804."

        Design: Difficulty/combinatorial_formula/lsc_verdict_requires_adjust_then_round_then_difference_ordering
        """
        pipeline, closed, approved, session, _ = _cross_calibrated_serial_pair(world)

        assert_four_decimals(
            closed["baseline_mean_bmd_g_cm2"], 1.0000, "baseline_mean_bmd_g_cm2"
        )
        assert_four_decimals(
            closed["new_mean_bmd_g_cm2"], 1.0200, "new_mean_bmd_g_cm2"
        )
        assert_two_decimals(closed["percent_difference"], 2.00, "percent_difference")
        assert_four_decimals(
            closed["proposed_cross_cal_factor"], 0.9804, "proposed_cross_cal_factor"
        )
        assert closed["outcome_code"] == "FACTOR_APPLIED"
        assert approved["status"] == "APPROVED"

        device = world.read_device(pipeline.device_id)
        assert device["calibration_generation"] == 2
        assert_four_decimals(device["cross_cal_factor"], 0.9804, "cross_cal_factor")

        assert session["prior_session_id"] == pipeline.session_id
        assert session["prior_comparison_status"] == "PRIOR_CROSS_CAL_ADJUSTED"
        assert_four_decimals(
            session["applied_cross_cal_factor"], 0.9804, "applied_cross_cal_factor"
        )
        assert session["calibration_generation"] == 2

    def test_adjusted_prior_is_rounded_before_differencing_and_reads_no_change(
        self, world: ProgramWorld
    ):
        """The adjusted prior 0.6863 turns a naive -0.0300 loss into -0.0163.

        "A prior total-hip density of 0.7000 carried at a cross-calibration
        factor of 0.9804 gives an adjusted prior of 0.6863, so a current 0.6700
        is a change of -0.0163 against an LSC of 0.0277 and reads
        `NO_SIGNIFICANT_CHANGE` - whereas differencing against the unadjusted
        0.7000 would have wrongly reported -0.0300 and declared a significant
        loss."

        Design: Difficulty/combinatorial_formula/lsc_verdict_requires_adjust_then_round_then_difference_ordering
        """
        _, _, _, session, report = _cross_calibrated_serial_pair(world)

        assert report["lsc_site_code"] == "TOTAL_HIP"
        assert_four_decimals(
            report["prior_bmd_used_g_cm2"], 0.6863, "prior_bmd_used_g_cm2"
        )
        assert_four_decimals(
            report["current_bmd_used_g_cm2"], 0.6700, "current_bmd_used_g_cm2"
        )
        assert_four_decimals(
            report["bmd_change_g_cm2"], -0.0163, "bmd_change_g_cm2"
        )
        assert_two_decimals(report["bmd_change_pct"], -2.38, "bmd_change_pct")
        assert_four_decimals(
            session["applied_lsc_g_cm2"], 0.0277, "applied_lsc_g_cm2"
        )
        assert report["lsc_interpretation"] == "NO_SIGNIFICANT_CHANGE"
        assert report["diagnostic_category"] == "OSTEOPENIA"
        assert report["clinical_interval_months"] == 12
        assert report["payer_floor_months"] == 24
        assert report["recommended_interval_months"] == 24
        assert report["recommended_action"] == "PAYER_LIMITED_INTERVAL"


class TestIntervalAndActionStepOrdering:
    """Six ordered steps feed one another and the last stops at its first match."""

    def test_clinical_interval_and_payer_floor_combine_by_maximum(
        self, world: ProgramWorld
    ):
        """A twelve-month clinical interval under a twenty-four-month floor reads 24.

        "**Step five** sets `recommended_interval_months` to the larger of the
        clinical interval and the payer floor, so the payer can delay a rescan
        but never bring one forward."

        Design: Difficulty/combinatorial_formula/interval_action_six_step_order_pins_initiate_treatment_over_payer_limited
        """
        pipeline = world.build(
            stop_after="drafted",
            sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPOROTIC)],
            policy_overrides={"baseline_screening_min_interval_months": 24},
        )
        session = world.read_session(pipeline.session_id)
        report = pipeline.report

        assert session["lowest_t_score"] == pytest.approx(-3.0, abs=0.01)
        assert session["lowest_t_score_site"] == "FEMORAL_NECK"
        assert session["lowest_z_score"] == pytest.approx(-1.5, abs=0.01)

        assert report["classification_basis"] == "T_SCORE_WHO"
        assert report["diagnostic_category"] == "OSTEOPOROSIS"
        assert report["lsc_interpretation"] == "NO_PRIOR"
        assert report["bmd_change_g_cm2"] is None
        assert report["clinical_interval_months"] == 12
        assert report["payer_floor_months"] == 24
        assert report["recommended_interval_months"] == 24

    def test_osteoporosis_branch_wins_over_the_payer_limited_branch(
        self, world: ProgramWorld
    ):
        """A longer recommended interval does not demote the treatment action.

        "Because the branches are ordered, an osteoporotic patient held to a
        twenty-four-month payer floor still reads `INITIATE_TREATMENT` rather
        than `PAYER_LIMITED_INTERVAL`."

        Design: Difficulty/combinatorial_formula/interval_action_six_step_order_pins_initiate_treatment_over_payer_limited
        """
        pipeline = world.build(
            stop_after="drafted",
            sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPOROTIC)],
            policy_overrides={"baseline_screening_min_interval_months": 24},
        )
        report = pipeline.report

        assert (
            report["recommended_interval_months"] > report["clinical_interval_months"]
        )
        assert report["recommended_action"] == "INITIATE_TREATMENT"
        assert report["required_elements_complete"] is True
        assert report["missing_element_codes"] == []
        assert report["status"] == "DRAFT"
        assert report["frax_assessment_id"] is None

"""Two stored inputs, two variants, two different answers.

A FRAX assessment reads the same patient and the same active risk factor
profile whether or not a scan session is supplied, and a treatment plan reads
the same refill rows whatever its adherence source policy. In both places the
divergence has to come from the variant selector alone.
"""

import pytest

from test_helpers import (
    BMD_FEMORAL_NECK_OSTEOPENIC,
    BMD_FEMORAL_NECK_OSTEOPOROTIC,
    ProgramWorld,
    assert_score_one_decimal,
    assert_three_decimals,
    assert_two_decimals,
)

# The worked example in the specification: a sixty-seven-year-old female with a
# bmi_used of 20.31, no clinical risk factors and a femoral-neck t_score of -2.0.
FRAX_BIRTH_DATE = "1958-05-12"
FRAX_PROFILE = {"height_cm": 160.0, "weight_kg": 52.0}


def _frax_world(world: ProgramWorld):
    """A submitted femoral-neck study on a patient carrying an active profile."""
    return world.build(
        stop_after="submitted",
        with_profile=True,
        profile_overrides=FRAX_PROFILE,
        patient_overrides={
            "birth_date": FRAX_BIRTH_DATE,
            "sex": "FEMALE",
            "postmenopausal": True,
            "baseline_height_cm": 165.0,
        },
        sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC)],
    )


class TestFraxVariantDivergence:
    """The presence of scan_session_id alone selects the variant."""

    def test_with_bmd_variant_adds_the_signed_bmd_term(self, world: ProgramWorld):
        """A supplied session produces WITH_BMD and a positive bmd_points term.

        "That last field alone selects between the two variants: supplying it
        produces `variant` `WITH_BMD`, omitting it produces `WITHOUT_BMD`."
        "`bmd_points` is 0.00 for the `WITHOUT_BMD` variant, and for `WITH_BMD`
        it is the femoral-neck `t_score` multiplied by -1.20."

        Design: Difficulty/dual_variant_calc/frax_with_bmd_versus_without_bmd_diverges_on_identical_risk_profile
        """
        pipeline = _frax_world(world)

        assessment = world.assess_frax(
            pipeline.patient_id, pipeline.profile_id, pipeline.session_id
        )

        assert assessment["variant"] == "WITH_BMD"
        assert assessment["age_years"] == 67
        assert_two_decimals(assessment["bmi_used"], 20.31, "bmi_used")
        assert_two_decimals(assessment["age_points"], 1.70, "age_points")
        assert_two_decimals(assessment["sex_points"], 0.60, "sex_points")
        assert_two_decimals(assessment["bmi_points"], 0.00, "bmi_points")
        assert_two_decimals(
            assessment["clinical_risk_points"], 0.00, "clinical_risk_points"
        )
        assert_two_decimals(assessment["bmd_points"], 2.40, "bmd_points")
        assert_two_decimals(assessment["raw_score"], 4.70, "raw_score")
        assert_score_one_decimal(
            assessment["major_osteoporotic_10yr_pct"],
            31.2,
            "major_osteoporotic_10yr_pct",
        )
        assert_score_one_decimal(
            assessment["hip_fracture_10yr_pct"], 7.9, "hip_fracture_10yr_pct"
        )
        assert assessment["treatment_threshold_met"] is True
        assert assessment["threshold_basis"] == "BOTH"

    def test_without_bmd_variant_drops_the_term_and_lowers_both_probabilities(
        self, world: ProgramWorld
    ):
        """Omitting the session zeroes bmd_points and moves threshold_basis to HIP.

        "The same patient assessed `WITHOUT_BMD` scores a `raw_score` of 2.30, a
        major probability of 16.8 and a hip probability of 4.1 - still
        treatment-eligible, but on the hip threshold alone."

        Design: Difficulty/dual_variant_calc/frax_with_bmd_versus_without_bmd_diverges_on_identical_risk_profile
        """
        pipeline = _frax_world(world)

        with_bmd = world.assess_frax(
            pipeline.patient_id, pipeline.profile_id, pipeline.session_id
        )
        without_bmd = world.assess_frax(pipeline.patient_id, pipeline.profile_id)

        assert without_bmd["variant"] == "WITHOUT_BMD"
        assert_two_decimals(without_bmd["bmd_points"], 0.00, "bmd_points")
        assert_two_decimals(without_bmd["raw_score"], 2.30, "raw_score")
        assert_score_one_decimal(
            without_bmd["major_osteoporotic_10yr_pct"],
            16.8,
            "major_osteoporotic_10yr_pct",
        )
        assert_score_one_decimal(
            without_bmd["hip_fracture_10yr_pct"], 4.1, "hip_fracture_10yr_pct"
        )
        assert without_bmd["treatment_threshold_met"] is True
        assert without_bmd["threshold_basis"] == "HIP"

        # Byte-identical stored inputs, and the whole gap is the BMD term.
        delta = (
            with_bmd["major_osteoporotic_10yr_pct"]
            - without_bmd["major_osteoporotic_10yr_pct"]
        )
        assert delta == pytest.approx(14.4, abs=0.01)
        assert without_bmd["age_points"] == pytest.approx(
            with_bmd["age_points"], abs=0.01
        )
        assert without_bmd["clinical_risk_points"] == pytest.approx(
            with_bmd["clinical_risk_points"], abs=0.01
        )


REFILL_ROWS = [
    {"dispensed_date": "2026-04-01", "days_supplied": 30, "source": "PHARMACY_CLAIM"},
    {"dispensed_date": "2026-05-01", "days_supplied": 30, "source": "PHARMACY_CLAIM"},
    {"dispensed_date": "2026-06-01", "days_supplied": 30, "source": "PATIENT_REPORT"},
]


def _two_plans_with_identical_refills(world: ProgramWorld):
    """One patient, two plans differing only in adherence_source_policy."""
    pipeline = world.build(
        stop_after="finalized",
        sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPOROTIC)],
    )
    assert pipeline.report["recommended_action"] == "INITIATE_TREATMENT"

    claims_plan = world.create_plan(
        pipeline.patient_id,
        pipeline.report_id,
        drug_class="BISPHOSPHONATE_ORAL",
        start_date="2026-04-01",
        adherence_source_policy="CLAIMS_ONLY",
    )
    weighted_plan = world.create_plan(
        pipeline.patient_id,
        pipeline.report_id,
        drug_class="BISPHOSPHONATE_ORAL",
        start_date="2026-04-01",
        adherence_source_policy="ALL_SOURCES_WEIGHTED",
    )

    world.set_clock("2026-06-15T08:00:00Z")
    for plan in (claims_plan, weighted_plan):
        for row in REFILL_ROWS:
            world.record_refill(plan["id"], **row)

    world.set_clock("2026-07-01T08:00:00Z")
    return claims_plan, weighted_plan


class TestAdherenceSourcePolicyDivergence:
    """The very same refill rows, scored twice under two source policies."""

    def test_claims_only_drops_patient_reported_days_and_lands_on_partial(
        self, world: ProgramWorld
    ):
        """A patient-reported refill contributes nothing under CLAIMS_ONLY.

        "Under `CLAIMS_ONLY`, rows whose `source` is `PATIENT_REPORT` are
        **dropped entirely**." "A ninety-one-day window holding two thirty-day
        pharmacy claims and one thirty-day patient report reads 0.659 and
        `PARTIAL` under `CLAIMS_ONLY`."

        Design: Difficulty/dual_variant_calc/mpr_claims_only_versus_all_sources_weighted_flips_adherence_status
        """
        claims_plan, _ = _two_plans_with_identical_refills(world)

        reviewed = world.review_adherence(
            claims_plan["id"], requested_action="AUTO", note="quarterly review"
        )

        assert reviewed["adherence_window_days"] == 91
        assert reviewed["covered_days_supplied"] == pytest.approx(60.0, abs=0.05)
        assert_three_decimals(
            reviewed["medication_possession_ratio"], 0.659, "medication_possession_ratio"
        )
        assert reviewed["adherence_status"] == "PARTIAL"
        assert reviewed["status"] == "ON_THERAPY"
        assert reviewed["next_followup_due_date"] == "2026-10-01"
        assert reviewed["denosumab_gap_days"] is None
        assert reviewed["holiday_eligible"] is False

    def test_all_sources_weighted_halves_patient_reported_days_and_lands_on_adherent(
        self, world: ProgramWorld
    ):
        """Half-weighting the same row crosses the adherent minimum.

        "Under `ALL_SOURCES_WEIGHTED` they contribute half of their supplied
        days." "... but 0.824 and `ADHERENT` under `ALL_SOURCES_WEIGHTED` -
        identical rows, different verdict, decided solely by the policy chosen
        when the plan was opened."

        Design: Difficulty/dual_variant_calc/mpr_claims_only_versus_all_sources_weighted_flips_adherence_status
        """
        claims_plan, weighted_plan = _two_plans_with_identical_refills(world)

        claims_reviewed = world.review_adherence(
            claims_plan["id"], requested_action="AUTO", note="quarterly review"
        )
        weighted_reviewed = world.review_adherence(
            weighted_plan["id"], requested_action="AUTO", note="quarterly review"
        )

        assert weighted_reviewed["adherence_window_days"] == 91
        assert weighted_reviewed["covered_days_supplied"] == pytest.approx(
            75.0, abs=0.05
        )
        assert_three_decimals(
            weighted_reviewed["medication_possession_ratio"],
            0.824,
            "medication_possession_ratio",
        )
        assert weighted_reviewed["adherence_status"] == "ADHERENT"
        assert weighted_reviewed["status"] == "ON_THERAPY"

        # Same window, same stored rows, opposite verdict.
        assert (
            weighted_reviewed["adherence_window_days"]
            == claims_reviewed["adherence_window_days"]
        )
        assert claims_reviewed["adherence_status"] == "PARTIAL"

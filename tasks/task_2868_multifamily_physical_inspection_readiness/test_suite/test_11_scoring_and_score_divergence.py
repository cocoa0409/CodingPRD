"""Publishing the score: two variants, one call, and the safety gate first.

The provisional variant divides the dwelling-unit sum by the units actually
entered while the final variant divides the penalised sum by the whole sample,
so one scoring call writes two different numbers onto the same row.
"""

from test_helpers import (
    ApiErrorId,
    assert_area_points,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_ok,
    assert_one_decimal,
    assert_scores,
    assert_two_decimals,
    constants as K,
    factories as F,
    fixtures as X,
)

CEDAR_UNIT = [
    {"unit_number": "101", "bedroom_count": 1, "occupancy_status": "OCCUPIED"}
]
MAPLE_TWO_OCCUPIED = [
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    },
    {"unit_number": "102", "bedroom_count": 1, "occupancy_status": "OCCUPIED"},
]
FOUR_DEFINITIONS = ("LT_GAS", "SEV_WINDOW", "MOD_HANDRAIL", "LOW_TRASH")
LIFE_THREATENING_CORRECTED_AT = "2026-09-10T12:00:00.000Z"


def _inside_finding_only(api):
    """One INSIDE moderate finding of 4.80 points and nothing else."""
    bundle = X.ready_to_record(
        api, K.CEDAR_WALK, CEDAR_UNIT, ("LT_GAS", "MOD_HANDRAIL")
    )
    recorded = X.record_deficiencies(
        api,
        bundle["inspection_id"],
        [
            {
                "defect_definition_id": bundle["definition_ids"]["MOD_HANDRAIL"],
                "inspectable_area": "INSIDE",
                "observed_at": K.OBSERVED_AT_1,
            }
        ],
    )
    bundle["deficiencies"] = recorded["deficiencies"]
    return bundle


def _refused_unit_with_four_findings(api):
    """One entered unit, one unreplaceable refusal, and four deficiencies."""
    bundle = X.adopted_standard(api, FOUR_DEFINITIONS)
    bundle.update(X.property_with_units(api, K.MAPLE_COURT, MAPLE_TWO_OCCUPIED))
    bundle.update(
        X.inspection_with_access(
            api,
            bundle["property_id"],
            bundle["standard_id"],
            access_results={bundle["unit_ids"]["102"]: "REFUSED"},
        )
    )
    recorded = X.record_deficiencies(
        api,
        bundle["inspection_id"],
        [
            {
                "defect_definition_id": bundle["definition_ids"]["SEV_WINDOW"],
                "unit_id": bundle["unit_ids"]["101"],
                "observed_at": K.OBSERVED_AT_1,
            },
            {
                "defect_definition_id": bundle["definition_ids"]["LT_GAS"],
                "unit_id": bundle["unit_ids"]["101"],
                "observed_at": K.OBSERVED_AT_2,
            },
            {
                "defect_definition_id": bundle["definition_ids"]["MOD_HANDRAIL"],
                "inspectable_area": "INSIDE",
                "observed_at": K.OBSERVED_AT_3,
            },
            {
                "defect_definition_id": bundle["definition_ids"]["LOW_TRASH"],
                "inspectable_area": "OUTSIDE",
                "observed_at": K.OBSERVED_AT_4,
            },
        ],
    )
    bundle["deficiencies"] = recorded["deficiencies"]
    assert_ok(
        api.record_correction(
            recorded["deficiencies"][1]["id"],
            F.correction_payload(
                corrected_at=LIFE_THREATENING_CORRECTED_AT,
                note="Connector replaced the same afternoon",
            ),
            bundle["owner_headers"],
        )
    )
    return bundle


def _blocked_on_both_gates(api):
    """An unentered slot and an uncorrected life-threatening finding at once."""
    bundle = X.adopted_standard(api, ("LT_GAS",))
    bundle.update(X.property_with_units(api, K.MAPLE_COURT, MAPLE_TWO_OCCUPIED))
    bundle.update(
        X.in_progress_inspection(api, bundle["property_id"], bundle["standard_id"])
    )
    bundle["unentered_slot"] = bundle["slots"][bundle["unit_ids"]["102"]]
    assert_ok(
        api.record_access(
            bundle["slots"][bundle["unit_ids"]["101"]]["id"],
            F.access_payload("GRANTED", recorded_at=K.ACCESS_RECORDED_AT),
            X.INSPECTOR,
        )
    )
    recorded = X.record_deficiencies(
        api,
        bundle["inspection_id"],
        [
            {
                "defect_definition_id": bundle["definition_ids"]["LT_GAS"],
                "unit_id": bundle["unit_ids"]["101"],
                "observed_at": K.OBSERVED_AT_1,
            }
        ],
    )
    bundle["life_threatening_id"] = recorded["deficiencies"][0]["id"]
    return bundle


class TestTheWeightedSumRounding:
    """Three two-decimal products are summed, then rounded once."""

    def test_a_single_inside_finding_publishes_ninety_eight_point_six(self, api):
        """50.00 plus 28.56 plus 20.00 is 98.56, published as 98.6.

        PRD: "each of those three weighted products is rounded half up to two
        decimal places individually, the three rounded products are then added
        together, and only that sum is rounded half up to one decimal place to
        give the published score."

        PRD: "sets `appeal_deadline_at` to the `scored_at` instant advanced by 360
        hours - fifteen days."

        Design: Corner/calculations/inspection_score_rounds_the_weighted_sum_to_one_decimal
        """
        bundle = _inside_finding_only(api)

        response = api.score_inspection(
            bundle["inspection_id"],
            F.score_payload(scored_at=K.SCORED_AT),
            X.INSPECTOR,
        )

        scored = assert_ok(response)
        assert_area_points(scored, 0.00, 4.80, 0.00)
        assert_two_decimals(
            scored["total_points_deducted"], 4.80, "total_points_deducted"
        )
        assert_scores(scored, 98.6, 98.6)
        assert_instant(
            scored["appeal_deadline_at"], K.APPEAL_DEADLINE_AT, "appeal_deadline_at"
        )
        owning_property = X.read_property(api, bundle["property_id"])
        assert_one_decimal(
            owning_property["last_final_score"], 98.6, "last_final_score"
        )
        assert_fields(owning_property, readiness_posture="READY")


class TestProvisionalAgainstFinal:
    """An unreplaced refusal splits the two published scores.

    The provisional variant sees one entered unit; the final variant sees the
    whole sample of two plus a refusal penalty.
    """

    def test_one_scoring_call_writes_two_different_scores(self, api):
        """72.3 provisional against 82.3 final on the same row.

        PRD: "For the **final** variant, the per-unit dwelling figure is the unit
        raw sum plus 12.00 refusal-penalty points for each refused unit - that is,
        `12.00` multiplied by `refused_unit_count` - divided by `sample_size`,
        rounded half up to two decimal places"

        PRD: "For the **provisional** variant, the per-unit dwelling figure is the
        unit raw sum divided by `inspected_unit_count`, rounded half up to two
        decimal places, or `0.00` when `inspected_unit_count` is zero."

        Design: Difficulty/dual_variant_calc/inspection_score_provisional_vs_final_diverge_on_unreplaced_refusal
        """
        bundle = _refused_unit_with_four_findings(api)

        response = api.score_inspection(
            bundle["inspection_id"],
            F.score_payload(scored_at=K.SCORED_AT),
            X.INSPECTOR,
        )

        scored = assert_ok(response)
        assert_fields(scored, status="SCORED")
        assert_scores(scored, 72.3, 82.3)
        assert scored["provisional_score"] != scored["final_score"]
        assert_instant(
            scored["appeal_deadline_at"], K.APPEAL_DEADLINE_AT, "appeal_deadline_at"
        )

    def test_the_two_denominators_are_both_carried_on_the_row(self, api):
        """The refusal stays in `sample_size` while `inspected_unit_count` is 1.

        PRD: "Because `sample_size` still counts refusals that were never
        replaced, and because the penalty is added into the numerator, the same
        deficiency data yields a different number from the provisional variant
        whenever `refused_unit_count` is at least 1."

        PRD: "The property's `last_final_score` is set to the new `final_score`
        and its `readiness_posture` is re-derived"

        Design: Difficulty/dual_variant_calc/inspection_score_provisional_vs_final_diverge_on_unreplaced_refusal
        """
        bundle = _refused_unit_with_four_findings(api)

        response = api.score_inspection(
            bundle["inspection_id"],
            F.score_payload(scored_at=K.SCORED_AT),
            X.INSPECTOR,
        )

        scored = assert_ok(response)
        assert_integer(
            scored["inspected_unit_count"], 1, "inspected_unit_count"
        )
        assert_integer(scored["refused_unit_count"], 1, "refused_unit_count")
        assert_integer(scored["sample_size"], 2, "sample_size")
        assert_area_points(scored, 52.00, 4.80, 1.20)
        assert_two_decimals(
            scored["total_points_deducted"], 58.00, "total_points_deducted"
        )
        assert_one_decimal(
            X.read_property(api, bundle["property_id"])["last_final_score"],
            82.3,
            "last_final_score",
        )


class TestTheScoringGateOrder:
    """Two 409s collide and the life-safety rule answers first."""

    def test_the_life_threatening_gate_answers_before_the_access_gate(self, api):
        """Unit 102 was never entered, but unit 101's gas leak wins.

        PRD: "The life-safety gate is evaluated before the access gate, so an
        inspection failing both reports the life-threatening error."

        PRD: "no deficiency of the inspection may have `severity`
        `LIFE_THREATENING` together with a `status` of `OPEN` or `OVERDUE`; if one
        does, the request is rejected with `ERR_LIFE_THREATENING_UNCORRECTED`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/score_rejected_with_life_threatening_error_not_access_not_recorded
        """
        bundle = _blocked_on_both_gates(api)

        response = api.score_inspection(
            bundle["inspection_id"],
            F.score_payload(scored_at=K.SCORED_AT),
            X.INSPECTOR,
        )

        rejection = assert_error(response, ApiErrorId.LIFE_THREATENING_UNCORRECTED)
        assert rejection["error_id"] != ApiErrorId.ACCESS_NOT_RECORDED
        assert_fields(
            X.read_selection(api, bundle["unentered_slot"]["id"]),
            access_status="NOTIFIED",
            selection_status="ACTIVE",
        )
        assert_fields(
            X.read_deficiency(api, bundle["life_threatening_id"]), status="OPEN"
        )

    def test_the_refused_scoring_publishes_nothing(self, api):
        """No score, no deadline, and the inspection stays on site.

        PRD: "A successful scoring moves the inspection `IN_PROGRESS -> SCORED`,
        stamps `scored_at`, writes the provisional variant to `provisional_score`
        and the final variant to `final_score`"

        Design: Difficulty/priority_pair_validation_conflict/score_rejected_with_life_threatening_error_not_access_not_recorded
        """
        bundle = _blocked_on_both_gates(api)

        response = api.score_inspection(
            bundle["inspection_id"],
            F.score_payload(scored_at=K.SCORED_AT),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.LIFE_THREATENING_UNCORRECTED)
        unchanged = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(unchanged, status="IN_PROGRESS")
        assert_null(
            unchanged,
            "scored_at",
            "provisional_score",
            "final_score",
            "appeal_deadline_at",
        )

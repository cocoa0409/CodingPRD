"""Two configuration-selected calculation variants that disagree on one input set.

Both the settlement evaluation methods of a foundation package and the dry-film
acceptance methods of a coating application store the same measurements and then
reach opposite conclusions from them.
"""

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_money,
    assert_settlement,
    assert_tank_state,
)
from test_helpers.constants import (
    COATING_DFT_RECORDED,
    DFT_FAIL,
    DFT_INDIVIDUAL_GAUGE_MIN,
    DFT_PASS,
    DFT_SPOT_AVERAGE_80_120,
    METHOD_ADJACENT_PAIR,
    METHOD_COSINE_BEST_FIT,
    NC_NOT_APPLICABLE,
    NC_OPEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    SURVEY_ROLE_MONITORING,
    VERDICT_OUT_OF_TOLERANCE,
    VERDICT_WITHIN_TOLERANCE,
)

# The same cosine-shaped settlement pattern shot against two packages whose only
# difference is which differential metric governs their verdict.
SPOT_READINGS_ONE_THIN_GAUGE = [[8.0, 10.0, 12.0], [10.0, 11.0, 12.0], [9.0, 10.0, 11.0]]


def _two_packages_with_divergent_methods(api):
    """Two tanks whose packages differ only in `settlement_evaluation_method`."""
    cosine = X.tank_with_baseline(
        api,
        tank_kwargs={"tank_tag": "TK-101"},
        package_kwargs={"settlement_evaluation_method": METHOD_COSINE_BEST_FIT},
    )
    adjacent = X.tank_with_baseline(
        api,
        tank_kwargs={"tank_tag": "TK-102"},
        package_kwargs={"settlement_evaluation_method": METHOD_ADJACENT_PAIR},
    )
    cosine.survey = X.create_survey(api, cosine.package_id, X.COSINE_PATTERN, 50.0)
    adjacent.survey = X.create_survey(api, adjacent.package_id, X.COSINE_PATTERN, 50.0)
    return cosine, adjacent


class TestSettlementMethodDivergence:
    def test_both_differential_metrics_are_stored_on_every_survey(self, api):
        """A survey records the cosine-fit and adjacent-pair metrics side by side.

        PRD: "Two differential metrics are then computed and **both** are stored
        on every survey row."

        Design: Difficulty/dual_variant_calc/settlement_method_cosine_vs_adjacent_pair_divergence
        """
        cosine, adjacent = _two_packages_with_divergent_methods(api)

        for label, survey in (("cosine", cosine.survey), ("adjacent", adjacent.survey)):
            assert survey["survey_role"] == SURVEY_ROLE_MONITORING
            assert_settlement(survey["uniform_settlement_in"], 5.000, f"{label} uniform")
            assert_settlement(survey["max_out_of_plane_in"], 0.000, f"{label} out of plane")
            assert_settlement(
                survey["max_adjacent_differential_in"], 2.828, f"{label} adjacent pair"
            )

    def test_governing_metric_and_verdict_follow_the_packages_configured_method(self, api):
        """The package picks the governing metric, so one verdict flips.

        PRD: "Which metric governs is the package's decision, not the survey's."

        Design: Difficulty/dual_variant_calc/settlement_method_cosine_vs_adjacent_pair_divergence
        """
        cosine, adjacent = _two_packages_with_divergent_methods(api)

        assert_settlement(cosine.survey["governing_metric_in"], 0.000, "cosine governing")
        assert cosine.survey["verdict"] == VERDICT_WITHIN_TOLERANCE

        assert_settlement(adjacent.survey["governing_metric_in"], 2.828, "adjacent governing")
        assert adjacent.survey["verdict"] == VERDICT_OUT_OF_TOLERANCE

    def test_only_the_adjacent_pair_tank_opens_a_nonconformance(self, api):
        """The refused round degrades its own tank's posture and nothing else.

        PRD: "An `OUT_OF_TOLERANCE` monitoring survey instead moves to `OPEN`,
        which raises the tank's `open_nonconformance_count` and triggers the
        posture recomputation and the suspension cascade of §2.8"

        Design: Difficulty/dual_variant_calc/settlement_method_cosine_vs_adjacent_pair_divergence
        """
        cosine, adjacent = _two_packages_with_divergent_methods(api)

        assert cosine.survey["nonconformance_state"] == NC_NOT_APPLICABLE
        assert adjacent.survey["nonconformance_state"] == NC_OPEN

        assert_tank_state(
            X.read_tank(api, cosine.tank_id), posture=POSTURE_OPEN, nonconformance_count=0
        )
        assert_tank_state(
            X.read_tank(api, adjacent.tank_id),
            posture=POSTURE_RESTRICTED,
            nonconformance_count=1,
        )


def _two_applications_with_divergent_methods(api):
    """One tank carrying two applications that differ only in acceptance method."""
    X.set_clock(api, "2026-08-10T00:00:00Z")
    tank = X.create_tank(api)
    band = X.create_coating(
        api, tank["id"], dft_acceptance_method=DFT_SPOT_AVERAGE_80_120, specified_min_dft_mils=10.0
    )
    floor = X.create_coating(
        api,
        tank["id"],
        dft_acceptance_method=DFT_INDIVIDUAL_GAUGE_MIN,
        specified_min_dft_mils=10.0,
    )
    X.surface_prep(api, band["id"])
    X.surface_prep(api, floor["id"])
    band = X.dft_readings(api, band["id"], SPOT_READINGS_ONE_THIN_GAUGE)
    floor = X.dft_readings(api, floor["id"], SPOT_READINGS_ONE_THIN_GAUGE)
    return tank, band, floor


class TestDftAcceptanceMethodDivergence:
    def test_every_dft_aggregate_is_identical_under_either_acceptance_method(self, api):
        """The aggregates are computed from the payload alone, not from the method.

        PRD: "every aggregate is recomputed from scratch over the submitted
        payload alone."

        Design: Difficulty/dual_variant_calc/coating_dft_spot_average_vs_individual_gauge_divergence
        """
        _, band, floor = _two_applications_with_divergent_methods(api)

        for label, application in (("band", band), ("floor", floor)):
            assert application["spot_count"] == 3, label
            assert_money(
                application["computed_spot_average_min_mils"], 10.00, f"{label} min spot average"
            )
            assert_money(
                application["computed_spot_average_max_mils"], 11.00, f"{label} max spot average"
            )
            assert_money(
                application["computed_overall_average_mils"], 10.33, f"{label} overall average"
            )
            assert_money(
                application["computed_min_gauge_reading_mils"], 8.00, f"{label} min gauge"
            )

    def test_spot_average_band_passes_what_the_individual_gauge_floor_fails(self, api):
        """One thin gauge inside an acceptable spot decides the whole verdict.

        PRD: "while a set of readings with one thin outlier that
        `SPOT_AVERAGE_80_120` would accept fails here."

        Design: Difficulty/dual_variant_calc/coating_dft_spot_average_vs_individual_gauge_divergence
        """
        _, band, floor = _two_applications_with_divergent_methods(api)

        assert band["dft_verdict"] == DFT_PASS
        assert floor["dft_verdict"] == DFT_FAIL

    def test_the_diverging_verdict_leaves_both_applications_in_dft_recorded(self, api):
        """The verdict is a field, not a state: both applications sit at the same step.

        PRD: "The application then moves `PREP_ACCEPTED → DFT_RECORDED`."

        Design: Difficulty/dual_variant_calc/coating_dft_spot_average_vs_individual_gauge_divergence
        """
        _, band, floor = _two_applications_with_divergent_methods(api)

        assert band["status"] == COATING_DFT_RECORDED
        assert floor["status"] == COATING_DFT_RECORDED
        assert X.read_coating(api, band["id"])["status"] == COATING_DFT_RECORDED
        assert X.read_coating(api, floor["id"])["status"] == COATING_DFT_RECORDED

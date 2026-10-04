"""Two competing calculation routes computed side by side on one evidence set."""
import pytest

from test_helpers import api_client, validate_success, COMPLIANCE, create_migration_event_payload, setup_migration_calibration_fixture, setup_cross_bureau_study


def _record_event(from_variant_id, to_variant_id, old_cutoff_score=640,
                  evidence_ref="WS-2026-014"):
    return api_client.create_migration_event(
        create_migration_event_payload(
            from_score_variant_id=from_variant_id, to_score_variant_id=to_variant_id,
            event_type="RECALIBRATED", old_cutoff_score=old_cutoff_score,
            evidence_ref=evidence_ref),
        COMPLIANCE)


class TestCutoffRecalibration:

    def test_score_preserving_route_holds_the_rank_of_the_old_cutoff(self, api):
        """PRD §3.9: "The score-preserving route holds the rank of the old cut-off
        and ignores both odds curves entirely: the new cut-off is the old cut-off
        plus the difference between the target's `ref_score` and the source's
        `ref_score`, clamped between the target model's `score_floor` and
        `score_ceiling`."
        PRD §3.9: "A recalibration event additionally computes both competing cut-off
        conversions and echoes them for the reviewer without applying either to any
        stored score."

        Design: Difficulty/dual_variant_calc/dual_variant_cutoff_recalibration_paths
        """
        _, _, v1, _, v2 = setup_migration_calibration_fixture()
        data = validate_success(_record_event(v1["id"], v2["id"], old_cutoff_score=660), 201)
        assert data["new_cutoff_score_preserving"] == 640, (
            f"expected the rank-preserving cut-off 640, got {data['new_cutoff_score_preserving']}"
        )

    def test_odds_preserving_route_holds_the_breakeven_odds(self, api):
        """PRD §3.9: "The odds-preserving route holds the breakeven odds and lets
        the score move: the old cut-off is first re-expressed as odds under the
        source curve, by taking the source's `base_odds` multiplied by two raised
        to the power of the old cut-off minus the source anchor divided by the
        source `double_odds_points`; that odds figure is then inverted under the
        target curve, by taking the target's `double_odds_points` multiplied by the
        base-two logarithm of the odds divided by the target's `base_odds`, which
        yields an implied point shift; and the new cut-off is the target anchor
        plus that shift, rounded half-up to a whole point"

        Design: Difficulty/dual_variant_calc/dual_variant_cutoff_recalibration_paths
        """
        _, _, v1, _, v2 = setup_migration_calibration_fixture()
        data = validate_success(_record_event(v1["id"], v2["id"], old_cutoff_score=660), 201)
        assert data["new_cutoff_odds_preserving"] == 628, (
            f"expected the odds-preserving cut-off 628, got {data['new_cutoff_odds_preserving']}"
        )

    def test_the_two_routes_really_disagree_on_a_widening_curve(self, api):
        """PRD §3.9: "The disagreement between the two routes — the score-preserving
        cut-off minus the odds-preserving cut-off — is reported as
        `cutoff_disagreement_points` and is never by itself a reason to reject the
        request."
        PRD §3.9: "When the target's `double_odds_points` exceeds the source's, the
        odds-preserving route lands above the score-preserving one, the disagreement
        is positive, and the two recalibrations genuinely disagree."

        Note: the fixture's target `double_odds_points` is 40 against the source's
        35, so the routes diverge and the two echoed cut-offs must differ.

        Design: Difficulty/dual_variant_calc/dual_variant_cutoff_recalibration_paths
        """
        _, _, v1, _, v2 = setup_migration_calibration_fixture()
        data = validate_success(_record_event(v1["id"], v2["id"]), 201)
        assert data["new_cutoff_score_preserving"] != data["new_cutoff_odds_preserving"], (
            "the two recalibration routes must not collapse to the same integer"
        )

    def test_credited_delta_is_the_target_minus_source_anchor(self, api):
        """PRD §3.9: "The `credited_delta_bps` carried by the event is derived as
        the target variant's `ref_score` minus the source variant's `ref_score`"

        Design: Difficulty/dual_variant_calc/dual_variant_cutoff_recalibration_paths
        """
        _, _, v1, _, v2 = setup_migration_calibration_fixture()
        data = validate_success(_record_event(v1["id"], v2["id"]), 201)
        assert data["credited_delta_bps"] == v2["ref_score"] - v1["ref_score"]
        assert data["credited_delta_bps"] == -20


class TestBureauWeightedComposite:

    def test_weighted_composite_rounds_each_product_before_summing(self, api):
        """PRD §3.4: "The bureau-weighted composite multiplies each posting's
        `effective_score` by its variant weight, rounds each of those products
        half-up to two decimal places *before* summing them, and then rounds the
        resulting sum half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/dual_variant_weighted_and_unweighted_composites
        """
        capture, study = setup_cross_bureau_study()
        assert study["weighted_composite"] == pytest.approx(699.91, abs=0.001), (
            f"expected 699.91, got {study['weighted_composite']}"
        )

    def test_unweighted_composite_truncates_the_mean_before_rounding(self, api):
        """PRD §3.4: "The unweighted composite deliberately ignores the weights
        entirely: it sums the `effective_score` values, divides by the count of
        postings, multiplies that mean by one hundred, truncates the result toward
        zero to a whole-hundredth increment, divides by one hundred again, and
        finally rounds half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/dual_variant_weighted_and_unweighted_composites
        """
        capture, study = setup_cross_bureau_study()
        assert study["unweighted_composite"] == pytest.approx(699.66, abs=0.001), (
            f"expected 699.66, got {study['unweighted_composite']}"
        )

    def test_reconciliation_variance_is_the_gap_between_the_two_routes(self, api):
        """PRD §3.4: "The `reconciliation_variance` reported is the absolute
        difference between the two composites, and it is this quantity that exposes
        calibration differences between the bureaus."

        Design: Difficulty/dual_variant_calc/dual_variant_weighted_and_unweighted_composites
        """
        capture, study = setup_cross_bureau_study()
        assert study["reconciliation_variance"] == pytest.approx(0.25, abs=0.001), (
            f"expected a 0.25-point gap, got {study['reconciliation_variance']}"
        )

    def test_the_two_routes_do_not_agree_on_one_capture(self, api):
        """PRD §3.4: "The bureau-weighted composite multiplies each posting's
        `effective_score` by its variant weight, rounds each of those products
        half-up to two decimal places *before* summing them, and then rounds the
        resulting sum half-up to two decimal places. The unweighted composite
        deliberately ignores the weights entirely"
        PRD §3.4: "It takes the poster's own consumer's non-voided postings,
        restricted to the poster's own score model version and excluding the poster
        itself, including any negative-scoring results."

        Design: Difficulty/dual_variant_calc/dual_variant_weighted_and_unweighted_composites
        """
        capture, study = setup_cross_bureau_study()
        assert study["weighted_composite"] != study["unweighted_composite"], (
            "the weighted and unweighted routes must be observably different"
        )

    def test_effective_scores_feed_the_capture_directly(self, api):
        """PRD §3.8: "Then the provisional score is formed by adding the variant's
        `segment_offsets` entry for that band to the raw score and clamping the
        result between the model's `score_floor` and `score_ceiling`. Only then is
        the rounding penalty computed, as the variant's `rounding_penalty_pct`
        applied to the already-clamped provisional score and rounded up to a whole
        point, and subtracted from the provisional score to give the stored
        `effective_score`."

        The worked derivation for the CREDIT-DUAL-V1 AUTO curve is
        `ceil(715 * 0.02) = 15`, leaving 700.

        Design: Difficulty/dual_variant_calc/dual_variant_weighted_and_unweighted_composites
        """
        capture, study = setup_cross_bureau_study()
        results = capture["results"]
        assert results["AUTO"]["effective_score"] == 700
        assert results["BANKCARD"]["effective_score"] == 702
        assert results["MORTGAGE"]["effective_score"] == 697
        for posting in results.values():
            assert posting["effective_score"] != posting["raw_posted_score"], (
                "the raw score must not be echoed back as the effective score"
            )
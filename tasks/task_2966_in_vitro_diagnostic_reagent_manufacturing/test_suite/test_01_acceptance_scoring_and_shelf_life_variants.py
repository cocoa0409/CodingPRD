"""Acceptance scoring, shelf-life variants, pinned rounding order and the
non-linear paths through the quality state machines.

Every test builds the state it needs from scratch: the harness restarts the
server and empties the database before each one.
"""
import pytest

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)

from test_helpers import assertions, factories, fixtures
from test_helpers.constants import DEFAULT_CLOCK_UTC, add_calendar_months
from test_helpers.test_users import (DISTRIBUTION_PLANNER, QA_RELEASER,
                                     QA_RELEASER_2_USER_ID,
                                     QA_RELEASER_USER_ID, QC_ANALYST,
                                     REGULATORY_AFFAIRS)

# ---------------------------------------------------------------------------
# Shared acceptance bounds.  One specification body, used twice with the two
# different acceptance modes so the measurement set can be byte-identical.
# ---------------------------------------------------------------------------
_ACCEPTANCE_BOUNDS = {
    "potency_min_pct": 90.0,
    "potency_max_pct": 110.0,
    "purity_min_pct": 95.0,
    "endotoxin_max_eu_per_ml": 2.0,
    "required_test_codes": ["POTENCY", "PURITY", "ENDOTOXIN", "IDENTITY"],
}

# POTENCY 111.00 sits 1.00 above the 110.0 ceiling, so its outcome is FAIL and
# its sub-score is 1 - 1.00 / 5.0 = 0.8.  PURITY 100.00 scores 100 / 100 = 1.0,
# ENDOTOXIN 0.40 scores 1 - 0.40 / 2.0 = 0.8, IDENTITY 1.00 scores 1.0.
_DIVERGENT_MEASUREMENTS = (
    ("POTENCY", 111.00),
    ("PURITY", 100.00),
    ("ENDOTOXIN", 0.40),
    ("IDENTITY", 1.00),
)
_DIVERGENT_OUTCOMES = ["FAIL", "PASS", "PASS", "PASS"]
# 0.45 * 0.8 + 0.30 * 1.0 + 0.15 * 0.8 + 0.10 * 1.0 = 0.88, divided by the full
# weight sum 1.00 and multiplied by 100.
_DIVERGENT_SCORE = 88.00


def _material_lot_with(api, acceptance_mode, measurements, **spec_overrides):
    """A raw material lot with one measurement per supplied pair, recorded in
    the order given.  Returns ``(spec, lot, results)`` with the lot re-read."""
    overrides = dict(_ACCEPTANCE_BOUNDS)
    overrides.update(spec_overrides)
    spec = fixtures.create_material_specification(
        api, acceptance_mode=acceptance_mode, **overrides)
    lot = fixtures.create_material_lot(api, spec["id"])
    results = [fixtures.record_material_measurement(api, lot["id"], code, value)
               for code, value in measurements]
    return spec, fixtures.ok(api.get_material_lot(lot["id"], QC_ANALYST)), results


def _qualify(api, lot_id, headers=QA_RELEASER):
    return api.disposition_material_lot(
        lot_id, factories.material_lot_disposition_payload("QUALIFY"), headers)


def _investigate(api, lot_id, headers=QA_RELEASER):
    return api.disposition_material_lot(
        lot_id, factories.material_lot_disposition_payload("INVESTIGATE"), headers)


def _reject(api, lot_id, headers=QA_RELEASER):
    return api.disposition_material_lot(
        lot_id, factories.material_lot_disposition_payload("REJECT"), headers)


class TestAcceptanceModeDivergence:
    """One identical measurement set decided by each of the two algorithms."""

    def test_weighted_score_qualifies_the_lot_all_pass_refuses(self, api):
        """PRD §3.1: "Under `ALL_PASS`, the verdict is `ACCEPT` only when every
        code in `required_test_codes` has a latest measurement whose `outcome` is
        `PASS`; a single out-of-bound measurement rejects the lot no matter how
        well the other tests scored, and `acceptance_score` stays null
        throughout."
        PRD §3.1: "Under `WEIGHTED_SCORE`, the verdict is `ACCEPT` when
        `acceptance_score` is at least 85.00 — the boundary is inclusive — **and**
        no present code produced a zero sub-score; an individual `FAIL` outcome
        does not block acceptance by itself, so a measurement slightly outside its
        bound is tolerated when the weighted score still reaches 85.00, and
        identical measurements that `ALL_PASS` would reject are qualified here."
        PRD §3.1: "When the verdict is not `ACCEPT`, or when a required code still
        has no result, the disposition is refused with
        `ERR_ACCEPTANCE_CRITERIA_NOT_MET`."

        Design: Difficulty/dual_variant_calc/material_acceptance_all_pass_versus_weighted_score_divergence
        """
        _, strict_lot, _ = _material_lot_with(api, "ALL_PASS",
                                              _DIVERGENT_MEASUREMENTS)
        _, weighted_lot, _ = _material_lot_with(api, "WEIGHTED_SCORE",
                                                _DIVERGENT_MEASUREMENTS)

        assert strict_lot["qualification_status"] == "UNDER_TEST"
        assert weighted_lot["qualification_status"] == "UNDER_TEST"

        refused = _qualify(api, strict_lot["id"])
        validate_error(refused, "ERR_ACCEPTANCE_CRITERIA_NOT_MET")
        still_under_test = fixtures.ok(
            api.get_material_lot(strict_lot["id"], QA_RELEASER))
        assert still_under_test["qualification_status"] == "UNDER_TEST"
        assert still_under_test["acceptance_score"] is None
        assert still_under_test["dispositioned_by_user_id"] is None
        assert still_under_test["dispositioned_at"] is None

        qualified = validate_success(_qualify(api, weighted_lot["id"]))
        assertions.assert_material_lot(qualified)
        assert qualified["qualification_status"] == "QUALIFIED"
        assert qualified["acceptance_score"] == pytest.approx(_DIVERGENT_SCORE,
                                                              abs=1e-6)
        assert qualified["dispositioned_by_user_id"] == QA_RELEASER_USER_ID
        assertions.assert_same_instant(qualified["dispositioned_at"],
                                       DEFAULT_CLOCK_UTC)
        assert qualified["available_quantity_units"] == pytest.approx(
            qualified["received_quantity_units"], abs=1e-6)

        persisted = fixtures.ok(
            api.get_material_lot(weighted_lot["id"], QA_RELEASER))
        assert persisted["qualification_status"] == "QUALIFIED"
        assert persisted["acceptance_score"] == pytest.approx(_DIVERGENT_SCORE,
                                                              abs=1e-6)

    def test_identical_measurements_yield_identical_outcomes_but_one_score(self, api):
        """PRD §3.1: "Only the record being written and the governing
        specification participate in that decision; no other measurement on the
        lot is consulted."
        PRD §3.1: "On each such record the server sets `first_oos_at` to that
        record's `performed_at` when the record's `outcome` is `FAIL` and
        `first_oos_at` was still null — the earliest failure anchors the retest
        clock and is never overwritten by a later failure."
        PRD §3.1: "Under `ALL_PASS`, the verdict is `ACCEPT` only when every code
        in `required_test_codes` has a latest measurement whose `outcome` is
        `PASS`; a single out-of-bound measurement rejects the lot no matter how
        well the other tests scored, and `acceptance_score` stays null
        throughout."

        Design: Difficulty/dual_variant_calc/material_acceptance_all_pass_versus_weighted_score_divergence
        """
        _, strict_lot, strict_results = _material_lot_with(
            api, "ALL_PASS", _DIVERGENT_MEASUREMENTS)
        _, weighted_lot, weighted_results = _material_lot_with(
            api, "WEIGHTED_SCORE", _DIVERGENT_MEASUREMENTS)

        # Per-measurement adjudication reads only the record and the bounds, so
        # the two modes must produce the very same outcomes.
        assert [r["outcome"] for r in strict_results] == _DIVERGENT_OUTCOMES
        assert [r["outcome"] for r in weighted_results] == _DIVERGENT_OUTCOMES
        for record in strict_results + weighted_results:
            assertions.assert_test_result(record)
            assert record["subject_type"] == "MATERIAL_LOT"

        # The single FAIL was recorded first on both lots, so both anchor their
        # retest clock on the very same instant.
        assertions.assert_same_instant(strict_lot["first_oos_at"],
                                       DEFAULT_CLOCK_UTC)
        assertions.assert_same_instant(weighted_lot["first_oos_at"],
                                       DEFAULT_CLOCK_UTC)
        assertions.assert_same_instant(strict_results[0]["performed_at"],
                                       strict_lot["first_oos_at"])
        assert strict_lot["retest_count"] == 0
        assert weighted_lot["retest_count"] == 0

        # The whole divergence lives in the aggregation, not in the records.
        assert strict_lot["acceptance_score"] is None
        assert weighted_lot["acceptance_score"] == pytest.approx(
            _DIVERGENT_SCORE, abs=1e-6)


class TestStabilityShelfLifeVariants:
    """The same conforming curve concluded as a real-time and as an
    accelerated study."""

    def test_same_conforming_prefix_yields_two_and_eighteen_months(self, api):
        """PRD §3.6: "For a `REAL_TIME` study, `established_shelf_life_months` is
        the lesser of `last_conforming_month` and the product's
        `shelf_life_months_claim`, and `shelf_life_method` is recorded as
        `REAL_TIME_LAST_CONFORMING`; there is no extrapolation, so a real-time
        shelf life can never exceed the protocol time actually elapsed."
        PRD §3.6: "It then computes an acceleration factor as 2 raised to the
        power of the quotient of two quantities — the study's `storage_temp_c`
        minus that reference temperature, divided by 10."
        PRD §3.6: "The chamber-months are multiplied by that factor:
        `established_shelf_life_months` is `last_conforming_month` multiplied by
        the acceleration factor, taken down to the next whole month, and then
        capped at `shelf_life_months_claim`, whichever is smaller;
        `shelf_life_method` is recorded as `ACCELERATED_Q10`."

        Design: Difficulty/dual_variant_calc/stability_shelf_life_real_time_versus_accelerated_divergence
        """
        product = fixtures.create_product_specification(
            api, shelf_life_months_claim=24, storage_condition="TWO_TO_EIGHT_C")
        lot = fixtures.create_reagent_lot(api, product["id"])

        real_time = fixtures.complete_stability_study(
            api, product["id"], lot["id"], conforming_months=(0, 1, 2),
            study_overrides={"study_type": "REAL_TIME", "storage_temp_c": 5.0,
                             "planned_timepoints_months": [0, 1, 2, 3]})
        accelerated = fixtures.complete_stability_study(
            api, product["id"], lot["id"], conforming_months=(0, 1, 2),
            study_overrides={"study_type": "ACCELERATED", "storage_temp_c": 37.0,
                             "planned_timepoints_months": [0, 1, 2, 3]})

        for study in (real_time, accelerated):
            assertions.assert_stability_study(study)
            assert study["status"] == "COMPLETE"
            assert study["last_conforming_month"] == 2
            assert study["timepoint_count"] == 3

        # Real time takes the prefix itself: min(2, 24).
        assert real_time["established_shelf_life_months"] == 2
        assert real_time["shelf_life_method"] == "REAL_TIME_LAST_CONFORMING"

        # Accelerated at 37.0 C against a 5.0 C reference: 2 ** ((37.0 - 5.0) /
        # 10) = 9.18958684..., so 2 * 9.18958684... = 18.3791..., floored to 18,
        # and the 24-month claim does not bind.
        assert accelerated["established_shelf_life_months"] == 18
        assert accelerated["shelf_life_method"] == "ACCELERATED_Q10"

        persisted = fixtures.ok(
            api.get_stability_study(accelerated["id"], REGULATORY_AFFAIRS))
        assert persisted["established_shelf_life_months"] == 18
        assert persisted["shelf_life_method"] == "ACCELERATED_Q10"

    def test_accelerated_extrapolation_is_floored_then_capped_at_the_claim(self, api):
        """PRD §3.6: "For an `ACCELERATED` study, the system first fixes a
        reference temperature from the product's `storage_condition`: 5.0 degrees
        Celsius when it is `TWO_TO_EIGHT_C`, and minus 20.0 degrees Celsius when
        it is `MINUS_TWENTY_C`."
        PRD §3.6: "Flooring happens after the extrapolation and before the cap."
        PRD §3.6: "For a `REAL_TIME` study, `established_shelf_life_months` is the
        lesser of `last_conforming_month` and the product's
        `shelf_life_months_claim`, and `shelf_life_method` is recorded as
        `REAL_TIME_LAST_CONFORMING`; there is no extrapolation, so a real-time
        shelf life can never exceed the protocol time actually elapsed."

        Design: Difficulty/dual_variant_calc/stability_shelf_life_real_time_versus_accelerated_divergence
        """
        product = fixtures.create_product_specification(
            api, shelf_life_months_claim=12, storage_condition="MINUS_TWENTY_C")
        lot = fixtures.create_reagent_lot(api, product["id"])

        real_time = fixtures.complete_stability_study(
            api, product["id"], lot["id"], conforming_months=(0, 3, 6),
            study_overrides={"study_type": "REAL_TIME", "storage_temp_c": -20.0,
                             "planned_timepoints_months": [0, 3, 6]})
        accelerated = fixtures.complete_stability_study(
            api, product["id"], lot["id"], conforming_months=(0, 3, 6),
            study_overrides={"study_type": "ACCELERATED", "storage_temp_c": 0.0,
                             "planned_timepoints_months": [0, 3, 6]})

        for study in (real_time, accelerated):
            assert study["status"] == "COMPLETE"
            assert study["last_conforming_month"] == 6

        # The claim is 12 months.  Real time takes min(6, 12) = 6 and never
        # extrapolates.
        assert real_time["established_shelf_life_months"] == 6
        assert real_time["shelf_life_method"] == "REAL_TIME_LAST_CONFORMING"

        # Accelerated at 0.0 C against a minus 20.0 C reference: 2 ** ((0.0 -
        # -20.0) / 10) = 4.0, so 6 * 4.0 = 24.0 months of extrapolated life,
        # which the 12-month claim caps back to 12.
        assert accelerated["established_shelf_life_months"] == 12
        assert accelerated["shelf_life_method"] == "ACCELERATED_Q10"

        persisted = fixtures.ok(
            api.get_stability_study(real_time["id"], REGULATORY_AFFAIRS))
        assert persisted["established_shelf_life_months"] == 6


class TestWeightedScoreDenominatorAndVeto:
    """The present-set denominator and the zero sub-score veto acting on one
    weighted specification."""

    def test_absent_code_shrinks_the_denominator_yet_blocks_qualification(self, api):
        """PRD §3.1: "Each present code's sub-score is multiplied by that code's
        weight — 0.45 for potency, 0.30 for purity, 0.15 for endotoxin, 0.10 for
        identity — and those products are summed; that sum is divided by the sum
        of the weights of the present codes only, so the denominator shrinks when
        codes are missing rather than treating an absent code as a zero."
        PRD §3.1: "Purity scores its `measured_value` divided by 100, capped at
        1."
        PRD §3.1: "Endotoxin scores 1 minus the quotient of its `measured_value`
        and `endotoxin_max_eu_per_ml`, floored at 0."
        PRD §3.1: "`QUALIFY` requires the lot to be `UNDER_TEST`, requires every
        code in `required_test_codes` to have at least one measurement on the lot,
        and requires the acceptance verdict to be `ACCEPT`."

        Design: Difficulty/combinatorial_formula/acceptance_score_present_set_denominator_and_zero_subscore_veto
        """
        _, lot, results = _material_lot_with(
            api, "WEIGHTED_SCORE",
            (("POTENCY", 100.00), ("PURITY", 96.00), ("ENDOTOXIN", 0.20)))

        assert [r["outcome"] for r in results] == ["PASS", "PASS", "PASS"]

        # Sub-scores 1.0, 0.96 and 0.9 weighted by 0.45, 0.30 and 0.15 sum to
        # 0.873.  Dividing by the present weights only (0.90) gives 0.97, so the
        # score is 97.00 — treating the absent IDENTITY code as a zero would have
        # divided by 1.00 and produced 87.30 instead.
        assert lot["acceptance_score"] == pytest.approx(97.00, abs=1e-6)
        assert lot["qualification_status"] == "UNDER_TEST"

        # A score far above 85.00 still cannot carry a lot whose IDENTITY code
        # has no result at all.
        refused = _qualify(api, lot["id"])
        validate_error(refused, "ERR_ACCEPTANCE_CRITERIA_NOT_MET")
        after = fixtures.ok(api.get_material_lot(lot["id"], QA_RELEASER))
        assert after["qualification_status"] == "UNDER_TEST"
        assert after["acceptance_score"] == pytest.approx(97.00, abs=1e-6)
        assert after["dispositioned_at"] is None

    def test_zero_subscore_vetoes_a_score_above_the_threshold(self, api):
        """PRD §3.1: "Identity scores 1 when its value is at least 1.0 and 0
        otherwise."
        PRD §3.1: "Sub-scores themselves are never rounded — only the final
        percentage is."
        PRD §3.1: "Under `WEIGHTED_SCORE`, the verdict is `ACCEPT` when
        `acceptance_score` is at least 85.00 — the boundary is inclusive — **and**
        no present code produced a zero sub-score; an individual `FAIL` outcome
        does not block acceptance by itself, so a measurement slightly outside its
        bound is tolerated when the weighted score still reaches 85.00, and
        identical measurements that `ALL_PASS` would reject are qualified here."
        PRD §3.1: "The system also tracks, alongside the score, whether any
        present code produced a sub-score of exactly 0."

        Design: Difficulty/combinatorial_formula/acceptance_score_present_set_denominator_and_zero_subscore_veto
        """
        _, lot, results = _material_lot_with(
            api, "WEIGHTED_SCORE",
            (("POTENCY", 100.00), ("PURITY", 96.00), ("ENDOTOXIN", 0.20),
             ("IDENTITY", 0.00)))

        assert [r["outcome"] for r in results] == ["PASS", "PASS", "PASS", "FAIL"]

        # All four codes are now present, so the denominator is the full 1.00 and
        # the identity contribution is 0.10 * 0 = 0: the score is 87.30, which
        # clears the 85.00 threshold on its own.
        assert lot["acceptance_score"] == pytest.approx(87.30, abs=1e-6)

        # The zero sub-score is an independent veto, so the disposition is still
        # refused.
        refused = _qualify(api, lot["id"])
        validate_error(refused, "ERR_ACCEPTANCE_CRITERIA_NOT_MET")
        after = fixtures.ok(api.get_material_lot(lot["id"], QA_RELEASER))
        assert after["qualification_status"] == "UNDER_TEST"
        assert after["acceptance_score"] == pytest.approx(87.30, abs=1e-6)

    def test_a_later_identity_record_lifts_the_veto_and_raises_the_score(self, api):
        """PRD §3.1: "The score reads, for each code in `required_test_codes`, the
        single latest measurement on this lot bearing that code, ranked by
        `performed_at` descending and then by `created_at` descending; a code with
        no measurement at all is simply absent from the calculation, and a code's
        own `outcome` is irrelevant here — only its `measured_value` matters, and a
        retest naturally replaces an earlier record because it is later."
        PRD §2.4: "For those two, `updated_at` and `version` are absent from the
        payload entirely — not null, absent — because once a measurement has been
        recorded it is never edited; a superseding measurement is a new record, not
        a revision of an old one."

        Design: Difficulty/combinatorial_formula/acceptance_score_present_set_denominator_and_zero_subscore_veto
        """
        _, lot, results = _material_lot_with(
            api, "WEIGHTED_SCORE",
            (("POTENCY", 100.00), ("PURITY", 96.00), ("ENDOTOXIN", 0.20),
             ("IDENTITY", 0.00)))
        assert lot["acceptance_score"] == pytest.approx(87.30, abs=1e-6)

        # A strictly later instant makes the ranking unambiguous.
        fixtures.set_clock(api, "2026-08-05T00:00:00.000Z")
        superseding = fixtures.record_material_measurement(
            api, lot["id"], "IDENTITY", 1.00)
        assert superseding["outcome"] == "PASS"
        assertions.assert_absent_or_none(superseding, "version")

        # Only the latest IDENTITY record counts: 0.873 + 0.10 * 1.0 = 0.973 over
        # a denominator of 1.00, so the score is 97.30 and no present code scores
        # zero any more.
        rescored = fixtures.ok(api.get_material_lot(lot["id"], QA_RELEASER))
        assert rescored["acceptance_score"] == pytest.approx(97.30, abs=1e-6)

        qualified = validate_success(_qualify(api, lot["id"]))
        assert qualified["qualification_status"] == "QUALIFIED"
        assert qualified["acceptance_score"] == pytest.approx(97.30, abs=1e-6)
        assertions.assert_same_instant(qualified["dispositioned_at"],
                                       "2026-08-05T00:00:00.000Z")

        # The superseded record is still on file; it was replaced, not edited.
        rows, meta = validate_paginated(api.list_test_results(
            QC_ANALYST, params={"material_lot_id": lot["id"],
                                "test_code": "IDENTITY"}))
        assert meta["total_count"] == 2
        assert sorted(r["measured_value"] for r in rows) == [0.00, 1.00]
        assert sorted(r["outcome"] for r in rows) == ["FAIL", "PASS"]


class TestReleaseBiasRoundingOrder:
    """The per-test bias roll-ups, whose rounding order is pinned before the
    aggregation."""

    def test_three_thousandths_biases_sum_to_three_not_three_point_zero_one(self, api):
        """PRD §3.5: "For a release measurement the server first computes
        `bias_pct`: take the absolute difference between `measured_value` and
        `reference_measured_value`, divide it by `reference_measured_value`,
        multiply by 100, and round the result half-up to two decimal places."
        PRD §3.5: "Each of those measurements contributes its **already rounded**
        two-decimal bias."
        PRD §3.5: "Rounding is applied once per test, before any aggregation, and
        the aggregate is never re-rounded — summing unrounded biases and rounding
        the total at the end is explicitly the wrong answer and will differ from
        the required one whenever the discarded thousandths accumulate."
        PRD §2.7: "Second, **rounding order is pinned before aggregation**: where a
        rule aggregates per-test figures, each per-test figure is rounded to two
        decimal places first and the aggregate is computed over the rounded
        figures — never the other way round."

        Design: Difficulty/combinatorial_formula/release_bias_rounding_order_pinned_per_test_then_sum
        """
        bundle = fixtures.filled_reagent_lot(
            api, product_overrides={"release_test_codes":
                                    ["ACTIVITY", "PRECISION", "LINEARITY"]})
        lot_id = bundle["lot"]["id"]
        assert bundle["lot"]["disposition_status"] == "FILLED"

        # Each raw bias is 1.004 percent, which rounds to 1.00 on its own.
        records = [fixtures.record_release_measurement(api, lot_id, code,
                                                       101.004, 100.00)
                   for code in ("ACTIVITY", "PRECISION", "LINEARITY")]
        for record in records:
            assertions.assert_test_result(record)
            assert record["bias_pct"] == pytest.approx(1.00, abs=1e-6)
            assert record["outcome"] == "PASS"
            assert record["recovery_pct"] is None

        lot = fixtures.ok(api.get_reagent_lot(lot_id, QA_RELEASER))
        assertions.assert_reagent_lot(lot)
        assert lot["release_bias_max_pct"] == pytest.approx(1.00, abs=1e-6)
        # Three rounded 1.00 figures sum to exactly 3.00.  Summing the unrounded
        # 1.004 figures and rounding the 3.012 total would give 3.01 instead.
        assert lot["release_bias_sum_pct"] == pytest.approx(3.00, abs=1e-6)
        assert abs(lot["release_bias_sum_pct"] - 3.01) > 1e-6

        # The measurements moved the quality axis only.
        assert lot["disposition_status"] == "UNDER_RELEASE_TEST"
        assert lot["distribution_status"] == "WITHHELD"

    def test_only_the_latest_record_per_code_feeds_the_roll_ups(self, api):
        """PRD §3.5: "For each code in the product's `release_test_codes`, the
        system takes the single latest release measurement on this lot bearing that
        code, ranked by `performed_at` descending and then by `created_at`
        descending; codes with no measurement are skipped, and measurements whose
        `test_code` is outside `release_test_codes` never enter."
        PRD §3.5: "`release_bias_max_pct` is the largest of those rounded per-test
        biases and is null when the set is empty; `release_bias_sum_pct` is the sum
        of those rounded per-test biases and is 0.00 when the set is empty."
        PRD §3.5: "Rounding is applied once per test, before any aggregation, and
        the aggregate is never re-rounded — summing unrounded biases and rounding
        the total at the end is explicitly the wrong answer and will differ from
        the required one whenever the discarded thousandths accumulate."

        Design: Difficulty/combinatorial_formula/release_bias_rounding_order_pinned_per_test_then_sum
        """
        bundle = fixtures.filled_reagent_lot(
            api, product_overrides={"release_test_codes":
                                    ["ACTIVITY", "PRECISION", "LINEARITY"]})
        lot_id = bundle["lot"]["id"]

        superseded = fixtures.record_release_measurement(api, lot_id, "ACTIVITY",
                                                         105.004, 100.00)
        precision = fixtures.record_release_measurement(api, lot_id, "PRECISION",
                                                        103.004, 100.00)
        linearity = fixtures.record_release_measurement(api, lot_id, "LINEARITY",
                                                        104.004, 100.00)
        assert superseded["bias_pct"] == pytest.approx(5.00, abs=1e-6)
        assert precision["bias_pct"] == pytest.approx(3.00, abs=1e-6)
        assert linearity["bias_pct"] == pytest.approx(4.00, abs=1e-6)

        # A strictly later instant makes the latest-per-code ranking unambiguous.
        fixtures.set_clock(api, "2026-08-02T00:00:00.000Z")
        latest = fixtures.record_release_measurement(api, lot_id, "ACTIVITY",
                                                     102.004, 100.00)
        assert latest["bias_pct"] == pytest.approx(2.00, abs=1e-6)

        lot = fixtures.ok(api.get_reagent_lot(lot_id, QA_RELEASER))
        # The latest set is 2.00, 3.00 and 4.00.
        assert lot["release_bias_max_pct"] == pytest.approx(4.00, abs=1e-6)
        assert lot["release_bias_sum_pct"] == pytest.approx(9.00, abs=1e-6)
        # Not 5.00: the superseded ACTIVITY record no longer enters the maximum.
        assert abs(lot["release_bias_max_pct"] - 5.00) > 1e-6
        # Not 9.01: the 2.004, 3.004 and 4.004 thousandths are discarded per test
        # rather than accumulated into the total.
        assert abs(lot["release_bias_sum_pct"] - 9.01) > 1e-6

        # All four records remain on file; the fourth superseded the first.
        rows, meta = validate_paginated(api.list_test_results(
            QC_ANALYST, params={"reagent_lot_id": lot_id}))
        assert meta["total_count"] == 4
        assert sorted(r["bias_pct"] for r in rows) == [2.00, 3.00, 4.00, 5.00]


# ---------------------------------------------------------------------------
# Four finished lots of one cleared product, released at four different fill
# instants so their expiry dates differ.  The product's shelf-life claim is 24
# months and its own shipping floor is 90 days, and the allocation runs at
# 2028-05-01, which leaves 92, 93, 94 and 85 whole days of shelf life.
# ---------------------------------------------------------------------------
_FEFO_FILL_INSTANTS = {
    "early": "2026-08-01T00:00:00.000Z",
    "middle": "2026-08-02T00:00:00.000Z",
    "late": "2026-08-03T00:00:00.000Z",
    "short": "2026-07-25T00:00:00.000Z",
}
_FEFO_FILLED_UNITS = {"early": 100, "middle": 200, "late": 500, "short": 400}
_FEFO_ALLOCATION_CLOCK = "2028-05-01T00:00:00.000Z"
_FEFO_SHIP_BY = "2028-06-01T00:00:00.000Z"


def _released_lot_filled_at(api, setup, fill_instant, filled_units):
    """A finished lot of the shared product, released on the claim basis after a
    run that completed at ``fill_instant``."""
    fixtures.set_clock(api, fill_instant)
    bundle = fixtures.released_reagent_lot(api, setup=setup,
                                           filled_units=filled_units)
    return bundle["lot"]


def _four_fefo_lots(api):
    """One cleared product with four released, available lots, and the logical
    clock parked on the allocation instant.  Returns ``(setup, lots)``."""
    setup = fixtures.manufacturing_setup(api)
    lots = {}
    for name in ("early", "middle", "late", "short"):
        lots[name] = _released_lot_filled_at(api, setup,
                                             _FEFO_FILL_INSTANTS[name],
                                             _FEFO_FILLED_UNITS[name])
    fixtures.set_clock(api, _FEFO_ALLOCATION_CLOCK)
    return setup, lots


def _assert_units(api, lot, available, allocated):
    fresh = fixtures.ok(api.get_reagent_lot(lot["id"], QA_RELEASER))
    assertions.assert_reagent_lot(fresh)
    assert fresh["available_units"] == available
    assert fresh["allocated_units"] == allocated
    return fresh


class TestFefoWaterfall:
    """The four pinned phases of the allocation waterfall."""

    def test_waterfall_draws_three_lots_in_expiry_order(self, api):
        """PRD §3.9: "A finished lot enters the pool only when all five of the
        following hold: its `product_specification_id` equals the order's, its
        `disposition_status` is `RELEASED`, its `distribution_status` is
        `AVAILABLE`, its `available_units` is greater than 0, and its remaining
        shelf life in whole days is at least `floor_days` — the boundary is
        inclusive, so a lot with exactly `floor_days` remaining is eligible."
        PRD §3.9: "Candidates are ordered first-expiry-first-out: by `expiry_date`
        ascending, with `created_at` ascending as the tie-break."
        PRD §3.9: "From each candidate it takes the smaller of the outstanding need
        and that candidate's `available_units`, records the pair of candidate and
        quantity taken, assigns `sequence_index` values 1, 2, 3 and so on in draw
        order, and reduces the need by the quantity taken."
        PRD §3.9: "It also defines a lot's remaining shelf life in whole days as
        the difference between that lot's `expiry_date` and the logical clock,
        expressed in seconds, divided by 86,400 seconds per day, and taken down to
        the next whole day."

        Design: Difficulty/combinatorial_formula/fefo_waterfall_four_phase_order_with_filtered_earliest_lot
        """
        setup, lots = _four_fefo_lots(api)
        for name, lot in lots.items():
            assert lot["disposition_status"] == "RELEASED"
            assert lot["distribution_status"] == "AVAILABLE"
            assertions.assert_same_instant(
                lot["expiry_date"],
                add_calendar_months(_FEFO_FILL_INSTANTS[name], 24))

        order = fixtures.create_distribution_order(
            api, setup["product"]["id"], requested_units=500,
            required_min_shelf_life_days=0, ship_by=_FEFO_SHIP_BY)
        assert order["status"] == "DRAFT"
        assert order["allocation_policy"] == "FEFO_STRICT"

        allocated = fixtures.allocate_order(api, order["id"])
        assertions.assert_distribution_order(allocated)
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_units"] == 500
        assert allocated["shortfall_units"] == 0

        rows = sorted(fixtures.order_allocations(api, order["id"]),
                      key=lambda row: row["sequence_index"])
        assert [row["sequence_index"] for row in rows] == [1, 2, 3]
        # The 85-day lot expires first of all but is filtered out by the 90-day
        # floor, so the draw starts at the earliest *eligible* expiry.
        assert [row["reagent_lot_id"] for row in rows] == [
            lots["early"]["id"], lots["middle"]["id"], lots["late"]["id"]]
        assert [row["allocated_units"] for row in rows] == [100, 200, 200]
        for row in rows:
            assertions.assert_allocation(row)
            assert row["status"] == "RESERVED"
            assert row["cold_chain_status"] == "INTACT"
            assert row["cumulative_excursion_minutes"] == 0
            assert row["shipped_at"] is None
            assert row["max_excursion_temp_c"] is None
            assert row["quarantine_reason"] is None

        _assert_units(api, lots["early"], 0, 100)
        _assert_units(api, lots["middle"], 0, 200)
        _assert_units(api, lots["late"], 300, 200)
        _assert_units(api, lots["short"], 400, 0)
        assert fixtures.ok(api.list_reagent_lot_allocations(
            lots["short"]["id"], QA_RELEASER)) == []

    def test_customer_floor_raises_the_bar_and_the_boundary_is_inclusive(self, api):
        """PRD §3.9: "Before phase 1, the system fixes a single shelf-life floor
        for this allocation: `floor_days` is the greater of the order's
        `required_min_shelf_life_days` and the product's
        `min_shelf_life_days_at_ship`, so a customer can raise the bar but never
        lower it below the product's own floor."
        PRD §3.9: "A finished lot enters the pool only when all five of the
        following hold: its `product_specification_id` equals the order's, its
        `disposition_status` is `RELEASED`, its `distribution_status` is
        `AVAILABLE`, its `available_units` is greater than 0, and its remaining
        shelf life in whole days is at least `floor_days` — the boundary is
        inclusive, so a lot with exactly `floor_days` remaining is eligible."
        PRD §3.9: "Candidates are ordered first-expiry-first-out: by `expiry_date`
        ascending, with `created_at` ascending as the tie-break."

        Design: Difficulty/combinatorial_formula/fefo_waterfall_four_phase_order_with_filtered_earliest_lot
        """
        setup, lots = _four_fefo_lots(api)

        # The customer asks for 93 days, so floor_days becomes 93 rather than the
        # product's own 90.  The 92-day lot drops out and the 93-day lot sits
        # exactly on the inclusive boundary.
        order = fixtures.create_distribution_order(
            api, setup["product"]["id"], requested_units=300,
            required_min_shelf_life_days=93, ship_by=_FEFO_SHIP_BY)
        allocated = fixtures.allocate_order(api, order["id"])
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_units"] == 300
        assert allocated["shortfall_units"] == 0

        rows = sorted(fixtures.order_allocations(api, order["id"]),
                      key=lambda row: row["sequence_index"])
        assert [row["sequence_index"] for row in rows] == [1, 2]
        assert [row["reagent_lot_id"] for row in rows] == [
            lots["middle"]["id"], lots["late"]["id"]]
        assert [row["allocated_units"] for row in rows] == [200, 100]

        _assert_units(api, lots["middle"], 0, 200)
        _assert_units(api, lots["late"], 400, 100)
        # The 92-day lot would have led the draw under the product's own floor.
        _assert_units(api, lots["early"], 100, 0)
        _assert_units(api, lots["short"], 400, 0)

    def test_strict_policy_rejects_the_shortfall_and_persists_nothing(self, api):
        """PRD §3.9: "If need remains and the order's `allocation_policy` is
        `FEFO_STRICT`, the request is rejected with `ERR_ALLOCATION_SHORTFALL` and
        **nothing whatsoever is persisted**: no reservation row is created, no lot
        counter moves, and the order stays in `DRAFT` with `allocated_units` 0."
        PRD §3.9: "That policy defaults to `FEFO_STRICT`, under which a shortfall
        rejects the whole allocation, and may instead be `FEFO_WITH_SHORTFALL`,
        under which a partial allocation is persisted."

        Design: Difficulty/combinatorial_formula/fefo_waterfall_four_phase_order_with_filtered_earliest_lot
        """
        setup, lots = _four_fefo_lots(api)

        # The eligible pool holds 100 + 200 + 500 = 800 units; the 400 units of
        # the short-dated lot are unreachable, so 900 cannot be met.
        order = fixtures.create_distribution_order(
            api, setup["product"]["id"], requested_units=900,
            required_min_shelf_life_days=0, ship_by=_FEFO_SHIP_BY,
            allocation_policy="FEFO_STRICT")
        refused = api.allocate_distribution_order(order["id"],
                                                  DISTRIBUTION_PLANNER)
        validate_error(refused, "ERR_ALLOCATION_SHORTFALL")

        after = fixtures.ok(api.get_distribution_order(order["id"],
                                                       DISTRIBUTION_PLANNER))
        assert after["status"] == "DRAFT"
        assert after["allocated_units"] == 0
        assert after["shortfall_units"] == 0
        assert fixtures.order_allocations(api, order["id"]) == []

        # Not one counter moved on any of the four lots.
        _assert_units(api, lots["early"], 100, 0)
        _assert_units(api, lots["middle"], 200, 0)
        _assert_units(api, lots["late"], 500, 0)
        _assert_units(api, lots["short"], 400, 0)

    def test_shortfall_policy_persists_the_partial_draw(self, api):
        """PRD §3.9: "The order's `allocated_units` becomes the total drawn, its
        `shortfall_units` becomes `requested_units` minus the total drawn but never
        below 0, and its `status` leaves `DRAFT` for `ALLOCATED` when the need was
        fully met and for `PARTIALLY_ALLOCATED` when any need remained — the second
        outcome is reachable only under `FEFO_WITH_SHORTFALL`."
        PRD §3.9: "From each candidate it takes the smaller of the outstanding need
        and that candidate's `available_units`, records the pair of candidate and
        quantity taken, assigns `sequence_index` values 1, 2, 3 and so on in draw
        order, and reduces the need by the quantity taken."

        Design: Difficulty/combinatorial_formula/fefo_waterfall_four_phase_order_with_filtered_earliest_lot
        """
        setup, lots = _four_fefo_lots(api)

        order = fixtures.create_distribution_order(
            api, setup["product"]["id"], requested_units=900,
            required_min_shelf_life_days=0, ship_by=_FEFO_SHIP_BY,
            allocation_policy="FEFO_WITH_SHORTFALL")
        allocated = fixtures.allocate_order(api, order["id"])
        assertions.assert_distribution_order(allocated)
        assert allocated["status"] == "PARTIALLY_ALLOCATED"
        assert allocated["allocated_units"] == 800
        assert allocated["shortfall_units"] == 100

        rows = sorted(fixtures.order_allocations(api, order["id"]),
                      key=lambda row: row["sequence_index"])
        assert [row["sequence_index"] for row in rows] == [1, 2, 3]
        assert [row["reagent_lot_id"] for row in rows] == [
            lots["early"]["id"], lots["middle"]["id"], lots["late"]["id"]]
        assert [row["allocated_units"] for row in rows] == [100, 200, 500]

        _assert_units(api, lots["early"], 0, 100)
        _assert_units(api, lots["middle"], 0, 200)
        _assert_units(api, lots["late"], 0, 500)
        # The short-dated lot never entered the pool, so its units are still free.
        _assert_units(api, lots["short"], 400, 0)


# ---------------------------------------------------------------------------
# One specification for the out-of-specification investigation cycle: two
# acceptance codes, the default single retest and the default 30-day window.
# ---------------------------------------------------------------------------
_OOS_BOUNDS = {
    "potency_min_pct": 90.0,
    "potency_max_pct": 110.0,
    "purity_min_pct": 95.0,
    "required_test_codes": ["POTENCY", "PURITY"],
}


def _lot_in_oos_investigation(api, spec):
    """A lot of ``spec`` driven RECEIVED -> UNDER_TEST -> OOS_INVESTIGATION by a
    passing potency result and a failing purity result."""
    lot = fixtures.create_material_lot(api, spec["id"])
    fixtures.record_material_measurement(api, lot["id"], "POTENCY", 100.00)
    fixtures.record_material_measurement(api, lot["id"], "PURITY", 85.00)
    return validate_success(_investigate(api, lot["id"]))


class TestOosInvestigationCycle:
    """The raw material lot's cycle out of and back into UNDER_TEST."""

    def test_retest_returns_the_lot_to_under_test_and_then_it_qualifies(self, api):
        """PRD §3.1: "`INVESTIGATE` is accepted only from `UNDER_TEST` and only
        when at least one measurement on the lot has `outcome` `FAIL`; it moves the
        lot to `OOS_INVESTIGATION` and increases `version` by 1."
        PRD §3.1: "From `OOS_INVESTIGATION`, a `QCAnalyst` closes the investigation
        by recording a measurement with `is_retest` set true, which returns the lot
        to `UNDER_TEST`."
        PRD §3.1: "A successful retest creates the measurement with `is_retest`
        true, increases `retest_count` by 1, returns `qualification_status` to
        `UNDER_TEST`, recomputes `acceptance_score` over the latest record per
        `test_code`, and increases the lot's `version` by 1."
        PRD §3.1: "Both hops require the lot to be in the state they start from
        (`RECEIVED` for the first, `UNDER_TEST` for the loop) and refuse anything
        else with `ERR_MATERIAL_LOT_STATE_INVALID`, and both require the `test_code`
        to be in `required_test_codes`."

        Design: Difficulty/non_linear_state_machine/material_lot_oos_investigation_cycles_back_to_under_test
        """
        spec = fixtures.create_material_specification(api, **_OOS_BOUNDS)
        lot = fixtures.create_material_lot(api, spec["id"])
        assert lot["qualification_status"] == "RECEIVED"
        assert lot["first_oos_at"] is None

        first = fixtures.record_material_measurement(api, lot["id"], "POTENCY",
                                                     100.00)
        assert first["outcome"] == "PASS"
        moved = fixtures.ok(api.get_material_lot(lot["id"], QC_ANALYST))
        assert moved["qualification_status"] == "UNDER_TEST"

        failing = fixtures.record_material_measurement(api, lot["id"], "PURITY",
                                                       85.00)
        assert failing["outcome"] == "FAIL"
        under_test = fixtures.ok(api.get_material_lot(lot["id"], QC_ANALYST))
        assert under_test["qualification_status"] == "UNDER_TEST"
        assertions.assert_same_instant(under_test["first_oos_at"],
                                       DEFAULT_CLOCK_UTC)

        # The verdict is not ACCEPT while the latest purity result is a FAIL.
        validate_error(_qualify(api, lot["id"]), "ERR_ACCEPTANCE_CRITERIA_NOT_MET")

        investigated = validate_success(_investigate(api, lot["id"]))
        assert investigated["qualification_status"] == "OOS_INVESTIGATION"
        assert investigated["retest_count"] == 0

        # Neither a qualification nor a plain non-retest measurement is available
        # from the investigation state.
        validate_error(_qualify(api, lot["id"]), "ERR_MATERIAL_LOT_STATE_INVALID")
        plain = api.create_test_result(
            factories.material_test_result_payload(lot["id"], "PURITY", 98.00),
            QC_ANALYST)
        validate_error(plain, "ERR_MATERIAL_LOT_STATE_INVALID")

        # The window runs to 2026-08-31, so a retest on 2026-08-20 is in time.
        fixtures.set_clock(api, "2026-08-20T00:00:00.000Z")
        retest = fixtures.record_material_measurement(api, lot["id"], "PURITY",
                                                     98.00, is_retest=True)
        assert retest["outcome"] == "PASS"
        assert retest["is_retest"] is True

        cycled = fixtures.ok(api.get_material_lot(lot["id"], QC_ANALYST))
        assert cycled["qualification_status"] == "UNDER_TEST"
        assert cycled["retest_count"] == 1
        # The anchor is the first failure, never the retest.
        assertions.assert_same_instant(cycled["first_oos_at"], DEFAULT_CLOCK_UTC)
        assert cycled["acceptance_score"] is None

        qualified = validate_success(_qualify(api, lot["id"]))
        assert qualified["qualification_status"] == "QUALIFIED"
        assert qualified["retest_count"] == 1
        assertions.assert_same_instant(qualified["dispositioned_at"],
                                       "2026-08-20T00:00:00.000Z")
        assert qualified["dispositioned_by_user_id"] == QA_RELEASER_USER_ID

    def test_the_second_cycle_exhausts_the_budget_and_only_rejection_remains(self, api):
        """PRD §3.1: "The cycle from `OOS_INVESTIGATION` to `UNDER_TEST` and back
        may repeat until `retest_count` reaches `max_retests`, at which point only
        `REJECT` remains available."
        PRD §3.1: "A retest recorded past that instant is refused with
        `ERR_RETEST_WINDOW_EXPIRED`; a retest attempted when `retest_count` has
        already reached `max_retests` is refused with `ERR_MAX_RETESTS_EXCEEDED`;
        and because the window rung sits above the budget rung, a retest that is
        both late and over budget is reported as out of window."
        PRD §3.1: "It moves the lot to the terminal `REJECTED` state, forces
        `available_quantity_units` to 0, records `dispositioned_by_user_id` and
        `dispositioned_at`, and increases `version` by 1."
        PRD §3.1: "On each such record the server sets `first_oos_at` to that
        record's `performed_at` when the record's `outcome` is `FAIL` and
        `first_oos_at` was still null — the earliest failure anchors the retest
        clock and is never overwritten by a later failure."

        Design: Difficulty/non_linear_state_machine/material_lot_oos_investigation_cycles_back_to_under_test
        """
        spec = fixtures.create_material_specification(api, **_OOS_BOUNDS)
        investigated = _lot_in_oos_investigation(api, spec)
        lot_id = investigated["id"]

        # First cycle: back into UNDER_TEST on the single budgeted retest.
        fixtures.set_clock(api, "2026-08-20T00:00:00.000Z")
        fixtures.record_material_measurement(api, lot_id, "PURITY", 98.00,
                                             is_retest=True)

        # A fresh non-retest failure sends the same lot round again.
        second_failure = fixtures.record_material_measurement(api, lot_id,
                                                             "POTENCY", 120.00)
        assert second_failure["outcome"] == "FAIL"
        assert second_failure["is_retest"] is False
        looped = validate_success(_investigate(api, lot_id))
        assert looped["qualification_status"] == "OOS_INVESTIGATION"
        assert looped["retest_count"] == 1
        # Anchored on the 2026-08-01 failure, not on the 2026-08-20 one.
        assertions.assert_same_instant(looped["first_oos_at"], DEFAULT_CLOCK_UTC)

        # The clock still sits inside the 30-day window, so the budget rung is the
        # one that answers: retest_count 1 has reached the default max_retests 1.
        over_budget = api.create_test_result(
            factories.material_test_result_payload(lot_id, "POTENCY", 100.00,
                                                   is_retest=True),
            QC_ANALYST)
        validate_error(over_budget, "ERR_MAX_RETESTS_EXCEEDED")
        stuck = fixtures.ok(api.get_material_lot(lot_id, QC_ANALYST))
        assert stuck["qualification_status"] == "OOS_INVESTIGATION"
        assert stuck["retest_count"] == 1

        # QUALIFY has no move from OOS_INVESTIGATION; only REJECT is left.
        validate_error(_qualify(api, lot_id), "ERR_MATERIAL_LOT_STATE_INVALID")
        rejected = validate_success(_reject(api, lot_id))
        assertions.assert_material_lot(rejected)
        assert rejected["qualification_status"] == "REJECTED"
        assert rejected["available_quantity_units"] == pytest.approx(0.0,
                                                                    abs=1e-6)
        assert rejected["dispositioned_by_user_id"] == QA_RELEASER_USER_ID
        assert rejected["version"] == stuck["version"] + 1

        persisted = fixtures.ok(api.get_material_lot(lot_id, QA_RELEASER))
        assert persisted["qualification_status"] == "REJECTED"
        assert persisted["retest_count"] == 1

    def test_the_retest_window_boundary_instant_is_still_inside_the_window(self, api):
        """PRD §3.1: "Three preconditions apply: the lot must actually be in
        `OOS_INVESTIGATION`, its `retest_count` must still be strictly below the
        specification's `max_retests`, and the logical clock must be no later than
        `first_oos_at` plus `retest_window_days` days — the boundary instant is
        still inside the window."
        PRD §3.1: "A successful retest creates the measurement with `is_retest`
        true, increases `retest_count` by 1, returns `qualification_status` to
        `UNDER_TEST`, recomputes `acceptance_score` over the latest record per
        `test_code`, and increases the lot's `version` by 1."

        Design: Difficulty/non_linear_state_machine/material_lot_oos_investigation_cycles_back_to_under_test
        """
        spec = fixtures.create_material_specification(api, **_OOS_BOUNDS)
        # Both lots fail at the default clock, so both anchor first_oos_at at
        # 2026-08-01T00:00:00.000Z and both windows close 30 days later, at
        # 2026-08-31T00:00:00.000Z.
        on_time = _lot_in_oos_investigation(api, spec)
        too_late = _lot_in_oos_investigation(api, spec)
        assertions.assert_same_instant(on_time["first_oos_at"], DEFAULT_CLOCK_UTC)
        assertions.assert_same_instant(too_late["first_oos_at"], DEFAULT_CLOCK_UTC)

        fixtures.set_clock(api, "2026-08-31T00:00:00.000Z")
        boundary = fixtures.record_material_measurement(api, on_time["id"],
                                                       "PURITY", 98.00,
                                                       is_retest=True)
        assert boundary["is_retest"] is True
        cycled = fixtures.ok(api.get_material_lot(on_time["id"], QC_ANALYST))
        assert cycled["qualification_status"] == "UNDER_TEST"
        assert cycled["retest_count"] == 1
        assert cycled["version"] == on_time["version"] + 1

        # One millisecond past the boundary the same request is out of window.
        fixtures.set_clock(api, "2026-08-31T00:00:00.001Z")
        expired = api.create_test_result(
            factories.material_test_result_payload(too_late["id"], "PURITY",
                                                   98.00, is_retest=True),
            QC_ANALYST)
        validate_error(expired, "ERR_RETEST_WINDOW_EXPIRED")
        frozen = fixtures.ok(api.get_material_lot(too_late["id"], QC_ANALYST))
        assert frozen["qualification_status"] == "OOS_INVESTIGATION"
        assert frozen["retest_count"] == 0


# ---------------------------------------------------------------------------
# The finished lot is filled at this instant, so a 12-month claim pins the
# expiry exactly twelve calendar months later.
# ---------------------------------------------------------------------------
_FILL_INSTANT = "2026-08-10T10:00:00.000Z"
_TWELVE_MONTH_EXPIRY = "2027-08-10T10:00:00.000Z"


def _lot_awaiting_disposition(api, claim_months=12):
    fixtures.set_clock(api, _FILL_INSTANT)
    bundle = fixtures.lot_under_release_test(
        api, product_overrides={"shelf_life_months_claim": claim_months})
    assert bundle["lot"]["disposition_status"] == "UNDER_RELEASE_TEST"
    assert bundle["lot"]["distribution_status"] == "WITHHELD"
    return bundle


def _try_distribution_status(api, lot_id, target, headers=QA_RELEASER):
    return api.set_reagent_lot_distribution_status(
        lot_id, factories.distribution_status_payload(target), headers)


class TestQualityAndAvailabilityAxes:
    """The finished lot's two state dimensions and how they move."""

    def test_release_moves_both_axes_then_availability_moves_alone(self, api):
        """PRD §2.8: "The two axes evolve independently, have different actors,
        and have different terminal semantics; a single request may advance one
        axis, or both."
        PRD §3.5: "Hop 2: because the lot became `RELEASED`, its
        `distribution_status` moves from `WITHHELD` to `AVAILABLE` automatically,
        without a second request."
        PRD §3.5: "When `shelf_life_basis` is `CLAIM`, `assigned_shelf_life_months`
        takes the product's `shelf_life_months_claim` and `shelf_life_basis_study_id`
        stays null."
        PRD §3.5: "`AVAILABLE` to `BLOCKED` requires only that the current
        `distribution_status` is `AVAILABLE`; it makes the lot ineligible for
        allocation but deliberately leaves every existing reservation on that lot
        untouched — blocking a lot is not a recall."
        PRD §3.5: "`BLOCKED` back to `AVAILABLE` requires both that the current
        `distribution_status` is `BLOCKED` and that `disposition_status` is still
        `RELEASED`."

        Design: Difficulty/non_linear_state_machine/reagent_lot_disposition_and_distribution_dimensions_move_independently
        """
        bundle = _lot_awaiting_disposition(api)
        lot_id = bundle["lot"]["id"]

        # The availability axis cannot run ahead of the quality axis.
        premature = _try_distribution_status(api, lot_id, "AVAILABLE")
        validate_error(premature, "ERR_REAGENT_LOT_STATE_INVALID")
        held = fixtures.ok(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert held["disposition_status"] == "UNDER_RELEASE_TEST"
        assert held["distribution_status"] == "WITHHELD"

        released = fixtures.disposition_reagent_lot(api, lot_id, "RELEASE")
        assertions.assert_reagent_lot(released)
        # One request advanced both axes.
        assert released["disposition_status"] == "RELEASED"
        assert released["distribution_status"] == "AVAILABLE"
        assert released["assigned_shelf_life_months"] == 12
        assert released["shelf_life_basis"] == "CLAIM"
        assertions.assert_absent_or_none(released, "shelf_life_basis_study_id")
        assert released["released_by_user_id"] == QA_RELEASER_USER_ID
        assertions.assert_same_instant(released["released_at"], _FILL_INSTANT)
        assertions.assert_same_instant(released["fill_completed_at"],
                                       _FILL_INSTANT)
        assertions.assert_same_instant(released["expiry_date"],
                                       _TWELVE_MONTH_EXPIRY)

        blocked = fixtures.set_distribution_status(api, lot_id, "BLOCKED")
        assert blocked["distribution_status"] == "BLOCKED"
        # The quality axis did not budge.
        assert blocked["disposition_status"] == "RELEASED"
        assert blocked["version"] == released["version"] + 1

        unblocked = fixtures.set_distribution_status(api, lot_id, "AVAILABLE")
        assert unblocked["distribution_status"] == "AVAILABLE"
        assert unblocked["disposition_status"] == "RELEASED"
        assert unblocked["version"] == blocked["version"] + 1
        assert unblocked["assigned_shelf_life_months"] == 12

        persisted = fixtures.ok(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert persisted["distribution_status"] == "AVAILABLE"
        assert persisted["disposition_status"] == "RELEASED"
        assertions.assert_same_instant(persisted["expiry_date"],
                                       _TWELVE_MONTH_EXPIRY)

    def test_rejection_leaves_the_availability_axis_withheld_for_good(self, api):
        """PRD §3.5: "It sets `disposition_status` to the terminal `REJECTED`,
        forces `available_units` to 0, leaves `distribution_status` at `WITHHELD`,
        and increases `version` by 1."
        PRD §3.5: "`WITHHELD` to `AVAILABLE` requires `disposition_status` to be
        `RELEASED` and is the same move the release cascade performs
        automatically."
        PRD §3.5: "Every one of the three increases the lot's `version` by 1, and
        any move whose starting state does not match — including an attempt to make
        a lot `AVAILABLE` when its `disposition_status` is not `RELEASED` — is
        refused with `ERR_REAGENT_LOT_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/reagent_lot_disposition_and_distribution_dimensions_move_independently
        """
        bundle = _lot_awaiting_disposition(api)
        lot_id = bundle["lot"]["id"]
        before = bundle["lot"]

        rejected = fixtures.disposition_reagent_lot(api, lot_id, "REJECT")
        assertions.assert_reagent_lot(rejected)
        assert rejected["disposition_status"] == "REJECTED"
        # The rejection moved the quality axis alone.
        assert rejected["distribution_status"] == "WITHHELD"
        assert rejected["available_units"] == 0
        assert rejected["version"] == before["version"] + 1
        assertions.assert_absent_or_none(rejected, "released_at")

        # Availability can never be granted, because the quality axis is terminal
        # and is not RELEASED.
        refused = _try_distribution_status(api, lot_id, "AVAILABLE")
        validate_error(refused, "ERR_REAGENT_LOT_STATE_INVALID")
        persisted = fixtures.ok(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert persisted["disposition_status"] == "REJECTED"
        assert persisted["distribution_status"] == "WITHHELD"
        assert persisted["available_units"] == 0
        assert persisted["version"] == rejected["version"]


# ---------------------------------------------------------------------------
# A complaint booked at the default clock is measured from 2026-08-01, so a
# thirty-day reporting deadline falls on 2026-08-31.
# ---------------------------------------------------------------------------
_REPORT_DUE_AT = "2026-08-31T00:00:00.000Z"
_REPORT_FILED_AT = "2026-08-30T00:00:00.000Z"
_REPORT_REF = "MDR-2026-000731"


def _complaint_on_released_lot(api, **overrides):
    bundle = fixtures.released_reagent_lot(api)
    complaint = fixtures.create_complaint(api, bundle["lot"]["id"], **overrides)
    assertions.assert_complaint(complaint)
    assert complaint["status"] == "RECEIVED"
    return bundle, complaint


class TestComplaintForkAndJoin:
    """The two branches out of a triaged complaint and the closure that rejoins
    them."""

    def test_field_action_first_then_the_report_closes_the_complaint(self, api):
        """PRD §3.8: "From `TRIAGED` the complaint forks into two independent
        branches that may run in either order and rejoin at closure."
        PRD §3.8: "`report_due_at` is `received_at` advanced by 5 days when
        `device_related_death_or_injury` is true and by 30 days otherwise, and it
        is null whenever `reportable` is false."
        PRD §3.8: "A `field_action` of `NONE` or `ADVISORY` stops there."
        PRD §3.8: "The complaint's `status` becomes `MALFUNCTION_REPORTED` when it
        was `TRIAGED`, and **stays** `FIELD_ACTION_DECIDED` when the other branch
        has already run, so the field-action outcome is never overwritten by the
        report."
        PRD §3.8: "And when `reportable` is true, `reported_at` must not be null,
        so the reporting branch must also have run; a close attempted on a
        reportable complaint whose `reported_at` is still null is refused with
        `ERR_MALFUNCTION_REPORT_PENDING`."
        PRD §3.8: "A `RegulatoryAffairs` user closes the complaint, which is
        admitted while `status` is `TRIAGED`, `MALFUNCTION_REPORTED` or
        `FIELD_ACTION_DECIDED` — a close on a `RECEIVED` or already `CLOSED`
        complaint is refused with `ERR_COMPLAINT_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/complaint_fork_join_requires_both_branches_in_either_order
        """
        bundle, complaint = _complaint_on_released_lot(api)
        complaint_id = complaint["id"]
        assertions.assert_same_instant(complaint["received_at"],
                                       DEFAULT_CLOCK_UTC)
        assertions.assert_absent_or_none(complaint, "field_action")

        # Nothing may close before triage has even happened.
        validate_error(api.close_complaint(complaint_id, REGULATORY_AFFAIRS),
                       "ERR_COMPLAINT_STATE_INVALID")

        triaged = fixtures.triage_complaint(api, complaint_id, "HIGH", True)
        assert triaged["status"] == "TRIAGED"
        assert triaged["reportable"] is True
        # 2026-08-01 plus 30 days, because no death or injury was alleged.
        assertions.assert_same_instant(triaged["report_due_at"], _REPORT_DUE_AT)
        assertions.assert_absent_or_none(triaged, "reported_at")

        # Branch one: the field action runs first and stops at an advisory.
        decided = fixtures.decide_field_action(api, complaint_id, "ADVISORY")
        assertions.assert_complaint(decided)
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        assert decided["field_action"] == "ADVISORY"
        assert decided["field_action_decided_by_user_id"] == QA_RELEASER_2_USER_ID
        assertions.assert_same_instant(decided["field_action_decided_at"],
                                       DEFAULT_CLOCK_UTC)
        assertions.assert_absent_or_none(decided, "reported_at")
        # An advisory fires no recall, so the implicated lot is untouched.
        lot = fixtures.ok(api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))
        assert lot["disposition_status"] == "RELEASED"
        assert lot["distribution_status"] == "AVAILABLE"

        # The join refuses to complete while the reporting branch has not run.
        validate_error(api.close_complaint(complaint_id, REGULATORY_AFFAIRS),
                       "ERR_MALFUNCTION_REPORT_PENDING")

        fixtures.set_clock(api, _REPORT_FILED_AT)
        reported = fixtures.file_malfunction_report(api, complaint_id,
                                                   report_ref=_REPORT_REF)
        # Branch two does not overwrite the state branch one reached.
        assert reported["status"] == "FIELD_ACTION_DECIDED"
        assert reported["field_action"] == "ADVISORY"
        assert reported["report_ref"] == _REPORT_REF
        assertions.assert_same_instant(reported["reported_at"], _REPORT_FILED_AT)
        # Filed on 2026-08-30, a day inside the deadline.
        assert reported["report_late"] is False

        closed = validate_success(api.close_complaint(complaint_id,
                                                      REGULATORY_AFFAIRS))
        assert closed["status"] == "CLOSED"
        assert closed["version"] == reported["version"] + 1

        persisted = fixtures.ok(api.get_complaint(complaint_id,
                                                  REGULATORY_AFFAIRS))
        assert persisted["status"] == "CLOSED"
        assert persisted["field_action"] == "ADVISORY"
        assert persisted["report_ref"] == _REPORT_REF

    def test_report_first_then_the_field_action_closes_the_complaint(self, api):
        """PRD §3.8: "It requires `reportable` to be true and requires the
        complaint's `status` to be either `TRIAGED` or `FIELD_ACTION_DECIDED`; a
        report against a complaint still in `RECEIVED`, or against one already in
        `MALFUNCTION_REPORTED` or `CLOSED`, is refused with
        `ERR_COMPLAINT_STATE_INVALID`."
        PRD §3.8: "The `field_action` must not be null, so the field-action branch
        must have run; a close attempted while `field_action` is still null is
        refused with `ERR_COMPLAINT_STATE_INVALID`."
        PRD §3.8: "Whichever of the two admitted starting states applies, the
        effect is identical: `field_action`, `field_action_decided_by_user_id` and
        `field_action_decided_at` are stored, `status` becomes
        `FIELD_ACTION_DECIDED`, `version` increases by 1, and any result already
        produced by the reporting branch is preserved intact."
        PRD §3.8: "A reportable complaint therefore closes only once **both**
        branches have run, in whichever order they ran."

        Design: Difficulty/non_linear_state_machine/complaint_fork_join_requires_both_branches_in_either_order
        """
        bundle, complaint = _complaint_on_released_lot(api)
        complaint_id = complaint["id"]
        fixtures.triage_complaint(api, complaint_id, "HIGH", True)

        # Branch two runs first this time.
        fixtures.set_clock(api, _REPORT_FILED_AT)
        reported = fixtures.file_malfunction_report(api, complaint_id,
                                                   report_ref=_REPORT_REF)
        assertions.assert_complaint(reported)
        assert reported["status"] == "MALFUNCTION_REPORTED"
        assert reported["report_late"] is False
        assertions.assert_absent_or_none(reported, "field_action")

        # A second filing has no admitted starting state left.
        refiled = api.file_malfunction_report(
            complaint_id, factories.malfunction_report_payload(),
            REGULATORY_AFFAIRS)
        validate_error(refiled, "ERR_COMPLAINT_STATE_INVALID")

        # The join refuses to complete while the field action is still null.
        validate_error(api.close_complaint(complaint_id, REGULATORY_AFFAIRS),
                       "ERR_COMPLAINT_STATE_INVALID")

        decided = fixtures.decide_field_action(api, complaint_id, "NONE")
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        assert decided["field_action"] == "NONE"
        # The earlier branch's results survived the second branch intact.
        assert decided["report_ref"] == _REPORT_REF
        assertions.assert_same_instant(decided["reported_at"], _REPORT_FILED_AT)
        assert decided["report_late"] is False
        assert decided["version"] == reported["version"] + 1

        closed = validate_success(api.close_complaint(complaint_id,
                                                      REGULATORY_AFFAIRS))
        assert closed["status"] == "CLOSED"
        assert closed["field_action"] == "NONE"
        assert closed["report_ref"] == _REPORT_REF

        lot = fixtures.ok(api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))
        assert lot["disposition_status"] == "RELEASED"

    def test_a_non_reportable_complaint_closes_on_one_branch_alone(self, api):
        """PRD §3.8: "`reportable` is true when `malfunction_suspected` is true
        **and** at least one of the following holds:
        `device_related_death_or_injury` is true, or `severity` is `HIGH`."
        PRD §3.8: "A suspected malfunction on a `LOW` or `MEDIUM` complaint with no
        alleged death or injury is therefore not reportable, and neither is a
        `HIGH`-severity complaint whose triage found no malfunction."
        PRD §3.8: "`report_due_at` is `received_at` advanced by 5 days when
        `device_related_death_or_injury` is true and by 30 days otherwise, and it
        is null whenever `reportable` is false."
        PRD §3.8: "On success `status` becomes the terminal `CLOSED` and `version`
        increases by 1."

        Design: Difficulty/non_linear_state_machine/complaint_fork_join_requires_both_branches_in_either_order
        """
        bundle, complaint = _complaint_on_released_lot(api)
        lot_id = bundle["lot"]["id"]

        # A suspected malfunction, but only MEDIUM severity and no alleged harm.
        triaged = fixtures.triage_complaint(api, complaint["id"], "MEDIUM", True)
        assert triaged["severity"] == "MEDIUM"
        assert triaged["malfunction_suspected"] is True
        assert triaged["reportable"] is False
        assertions.assert_absent_or_none(triaged, "report_due_at")

        # The other half of the rule: HIGH severity without a suspected
        # malfunction is not reportable either.
        second = fixtures.create_complaint(api, lot_id)
        other = fixtures.triage_complaint(api, second["id"], "HIGH", False)
        assert other["reportable"] is False
        assertions.assert_absent_or_none(other, "report_due_at")

        # The field-action branch is still mandatory.
        validate_error(api.close_complaint(complaint["id"], REGULATORY_AFFAIRS),
                       "ERR_COMPLAINT_STATE_INVALID")

        decided = fixtures.decide_field_action(api, complaint["id"], "NONE")
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        assertions.assert_absent_or_none(decided, "reported_at")

        closed = validate_success(api.close_complaint(complaint["id"],
                                                      REGULATORY_AFFAIRS))
        assertions.assert_complaint(closed)
        assert closed["status"] == "CLOSED"
        assert closed["version"] == decided["version"] + 1
        # It closed with the reporting branch never having run at all.
        assertions.assert_absent_or_none(closed, "reported_at")
        assertions.assert_absent_or_none(closed, "report_ref")

        persisted = fixtures.ok(api.get_complaint(complaint["id"],
                                                  REGULATORY_AFFAIRS))
        assert persisted["status"] == "CLOSED"
        assert persisted["reportable"] is False

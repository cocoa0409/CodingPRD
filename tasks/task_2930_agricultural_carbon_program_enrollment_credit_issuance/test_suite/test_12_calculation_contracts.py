"""Variant-specific constants, input-set filtering and an opinion-conditional gate.

The two baseline variants clamp their uncertainty at two different floors, the
quantification input set admits only quality-passed packets regardless of coverage, and
the material-discrepancy tolerance gates a positive opinion while letting a far larger
restatement through as qualified.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import ERR_MATERIAL_DISCREPANCY_EXCEEDED
from test_helpers.assertions import (
    assert_acres,
    assert_pct,
    assert_rate,
    assert_tonnes,
)
from test_helpers.constants import (
    BASELINE_HISTORICAL_DATA,
    BASELINE_MODELED,
    BASELINE_PROPOSED,
    BASELINE_SUPERSEDED,
    CLOCK_2026,
    COMPLETENESS_COMPLETE,
    COMPLETENESS_PARTIAL,
    CROP_YEAR_2026,
    EVIDENCE_EQUIPMENT_TELEMETRY,
    EVIDENCE_FARM_RECORD,
    EVIDENCE_REMOTE_SENSING,
    METHOD_MODEL,
    OPINION_PENDING,
    OPINION_POSITIVE,
    OPINION_QUALIFIED,
    PRACTICE_REDUCED_TILLAGE,
    QC_PASSED,
    QC_PENDING,
    RUN_SUBMITTED,
    RUN_VERIFIED,
    SOIL_CLAY,
)
from test_helpers.factories import opinion_payload, resample_payload
from test_helpers.test_users import ADMIN_HEADERS

#: A five-year reduced-tillage evidence base whose every row is baseline-admissible, so
#: the qualifying-year count is five rather than the reference set's four.
ADMISSIBLE_HISTORY = (
    (2021, EVIDENCE_FARM_RECORD, True, 200.00, 0.1000),
    (2022, EVIDENCE_FARM_RECORD, True, 500.00, 0.1200),
    (2023, EVIDENCE_FARM_RECORD, False, 0.00, 0.1500),
    (2024, EVIDENCE_EQUIPMENT_TELEMETRY, False, 0.00, 0.1600),
    (2025, EVIDENCE_FARM_RECORD, False, 0.00, 0.1700),
)


def test_the_two_baseline_variants_clamp_uncertainty_at_their_own_floors(scenario):
    """With a base uncertainty of 8.00 and five qualifying years both variants fall below
    their floors and are clamped to two different values, 5.00 and 12.00, so one shared
    minimum cannot satisfy both; the displaced proposal keeps its figures.

    PRD §3.4: "For the uncertainty deduction, take the standard's `uncertainty_base_pct`,
    subtract 2.0 percentage points for each qualifying year, round half up to two decimal
    places, and then raise the result to 5.00 if it fell below that floor; the outcome is
    `uncertainty_pct`."

    PRD §3.4: "For the uncertainty deduction, take the standard's `uncertainty_base_pct`,
    add a flat 10.0 percentage-point modelling adder, subtract 1.5 percentage points for
    each qualifying year, round half up to two decimal places, and then raise the result
    to 12.00 if it fell below that floor; the outcome is `uncertainty_pct`."

    Design: Corner/calculations/baseline_uncertainty_clamps_at_both_variant_floors
    """
    scenario.set_clock(CLOCK_2026)
    scenario.publish_standard(
        practice_code=PRACTICE_REDUCED_TILLAGE,
        uncertainty_base_pct=8.00,
        telemetry_required=False,
    )
    scenario.create_grower()
    scenario.mapped_field(soil_group=SOIL_CLAY, gross_acres=1000.00)
    for crop_year, source, adopted, acres, rate in ADMISSIBLE_HISTORY:
        scenario.file_history(
            crop_year,
            practice_code=PRACTICE_REDUCED_TILLAGE,
            evidence_source=source,
            adopted=adopted,
            acres=acres,
            observed_emissions_per_acre=rate,
        )
    scenario.create_per_acre_enrollment()
    scenario.submit_enrollment()
    accepted = scenario.screen_enrollment("ACCEPT")

    assert_pct(accepted["prior_adoption_pct"], 14.00)
    assert accepted["documented_years"] == 5
    assert_pct(accepted["additionality_score"], 89.00)

    historical = scenario.propose_baseline(BASELINE_HISTORICAL_DATA)

    assert historical["qualifying_years"] == 5
    assert_rate(historical["historical_mean_rate"], 0.1400)
    assert_tonnes(historical["baseline_emissions_t"], 140.000)
    # 8.00 - 2.0 * 5 = -2.00, clamped up to the historical floor.
    assert_pct(historical["uncertainty_pct"], 5.00)

    modeled = scenario.propose_baseline(BASELINE_MODELED)

    assert modeled["historical_mean_rate"] is None
    assert modeled["qualifying_years"] == 5
    assert_tonnes(modeled["baseline_emissions_t"], 180.000)
    # 8.00 + 10.0 - 1.5 * 5 = 10.50, clamped up to the modelled floor.
    assert_pct(modeled["uncertainty_pct"], 12.00)
    assert modeled["status"] == BASELINE_PROPOSED
    # Two different floors, so neither is a single shared programme minimum.
    assert modeled["uncertainty_pct"] != historical["uncertainty_pct"]

    displaced = get_success_data(
        scenario.api.get_baseline(historical["id"], ADMIN_HEADERS)
    )
    assert displaced["status"] == BASELINE_SUPERSEDED
    # Superseding neither recomputes nor blanks the older proposal.
    assert_tonnes(displaced["baseline_emissions_t"], 140.000)
    assert_pct(displaced["uncertainty_pct"], 5.00)


def test_the_model_input_set_admits_only_quality_passed_packets(scenario):
    """Two passed packets — one complete, one partial — and one pending packet coexist for
    the same crop year, and the run averages exactly the two passed ones, so the pending
    row is provably excluded while the partial row is provably included.

    PRD §3.6: "Collect every data packet whose `enrollment_id` is the run's enrollment,
    whose `crop_year` equals the run's `crop_year`, and whose `qc_status` is `PASSED`."

    PRD §3.6: "Packets that are `PENDING`, `FLAGGED` or `REJECTED` are excluded, and a
    packet's `completeness_status` plays no part in this filter — a `PARTIAL` packet that
    passed quality control is admitted exactly like a `COMPLETE` one."

    PRD §3.6: "Add together the `reported_acres` of the included packets and take the
    smaller of that sum and the enrollment's `enrolled_acres`; the result, at two decimal
    places, is `verified_acres`."

    Design: Corner/calculations/quantification_input_set_admits_only_passed_packets
    """
    scenario.active_enrollment()

    farm_record = scenario.file_packet(
        CROP_YEAR_2026, source=EVIDENCE_FARM_RECORD, coverage_pct=92.00
    )
    assert_pct(farm_record["qc_score"], 88.00)
    assert farm_record["completeness_status"] == COMPLETENESS_COMPLETE
    scenario.qc_packet(farm_record["id"], "PASS")

    telemetry = scenario.file_packet(
        CROP_YEAR_2026, source=EVIDENCE_EQUIPMENT_TELEMETRY, coverage_pct=55.00
    )
    assert_pct(telemetry["qc_score"], 77.50)
    assert telemetry["completeness_status"] == COMPLETENESS_PARTIAL
    passed_partial = scenario.qc_packet(telemetry["id"], "PASS")
    # 77.50 clears the 70.00 floor even though the coverage axis says PARTIAL.
    assert passed_partial["qc_status"] == QC_PASSED
    assert passed_partial["completeness_status"] == COMPLETENESS_PARTIAL

    ignored = scenario.file_packet(
        CROP_YEAR_2026, source=EVIDENCE_REMOTE_SENSING, coverage_pct=100.00
    )
    assert ignored["qc_status"] == QC_PENDING

    run = scenario.create_run(METHOD_MODEL)

    assert run["packet_count"] == 2
    assert_pct(run["mean_coverage_pct"], 73.50)
    assert_rate(run["adoption_factor"], 0.7350)
    # The doubled reported acreage is capped at the enrolled acreage.
    assert_acres(run["verified_acres"], 1000.00)
    assert_tonnes(run["gross_removals_t"], 257.250)
    assert_tonnes(run["uncertainty_deduction_t"], 30.870)
    assert_tonnes(run["net_removals_t"], 226.380)
    assert run["sampling_uncertainty_pct"] is None
    # Averaging all three packets would give 82.33 and a different tonnage.
    assert run["mean_coverage_pct"] != 82.33
    assert run["packet_count"] != 3


def test_the_discrepancy_tolerance_gates_a_positive_opinion_only(scenario):
    """A 5.87 per cent restatement blocks a positive opinion, a far larger 41.16 per cent
    restatement is accepted as qualified, and after a resample a restatement landing
    exactly on the 5.00 threshold is accepted because equality passes.

    PRD §3.6: "The tolerance gate applies to `POSITIVE` opinions only."

    PRD §3.6: "A `POSITIVE` opinion requires `material_discrepancy_pct` to be no greater
    than 5.00 — equality passes — and a larger gap is refused with
    `ERR_MATERIAL_DISCREPANCY_EXCEEDED`."

    PRD §3.6: "The new window is re-checked against the body's concurrency ceiling,
    `resample_count` increases by one, `restated_removals_t` and `findings_note` are
    cleared to null, `material_discrepancy_pct` is reset to 0.00, and the `opinion`
    returns `QUALIFIED → PENDING`."

    Design: Corner/calculations/material_discrepancy_threshold_gates_only_positive_opinions
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    scenario.create_run(METHOD_MODEL)
    submitted = scenario.submit_run()
    assert_tonnes(submitted["net_removals_t"], 283.360)
    scenario.accredit_body(max_concurrent_visits=2)
    scenario.commission_verification()

    blocked = scenario.api.opine_verification(
        scenario.verification_id,
        opinion_payload(
            OPINION_POSITIVE, restated_removals_t=300.000, findings_note="restated upward"
        ),
        scenario.verifier_auth,
    )

    # 100 * |300.000 - 283.360| / 283.360 = 5.87, above the 5.00 tolerance.
    validate_error(blocked, ERR_MATERIAL_DISCREPANCY_EXCEEDED, 422)
    still_pending = get_success_data(
        scenario.api.get_verification(scenario.verification_id, ADMIN_HEADERS)
    )
    assert still_pending["opinion"] == OPINION_PENDING
    assert_pct(still_pending["material_discrepancy_pct"], 0.00)

    qualified = scenario.opine(
        OPINION_QUALIFIED, restated_removals_t=400.000, findings_note="material rework needed"
    )

    # Seven times the tolerance, and yet accepted, because the gate is opinion-conditional.
    assert qualified["opinion"] == OPINION_QUALIFIED
    assert_pct(qualified["material_discrepancy_pct"], 41.16)
    assert scenario.reload_run()["status"] == RUN_SUBMITTED

    resampled = get_success_data(
        scenario.api.resample_verification(
            scenario.verification_id,
            resample_payload(
                sample_pct=15.00,
                site_visit_start="2026-10-01",
                site_visit_end="2026-10-03",
            ),
            scenario.verifier_auth,
        )
    )

    assert resampled["opinion"] == OPINION_PENDING
    assert_pct(resampled["sample_pct"], 15.00)
    assert_pct(resampled["material_discrepancy_pct"], 0.00)
    assert resampled["restated_removals_t"] is None
    assert resampled["findings_note"] is None
    assert resampled["resample_count"] == 1

    final = scenario.opine(OPINION_POSITIVE, restated_removals_t=297.528)

    # 100 * |297.528 - 283.360| / 283.360 is exactly 5.00, and the ceiling is inclusive.
    assert_pct(final["material_discrepancy_pct"], 5.00)
    assert final["opinion"] == OPINION_POSITIVE
    assert scenario.reload_run()["status"] == RUN_VERIFIED

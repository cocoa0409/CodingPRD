"""Two-variant arithmetic: baseline method and quantification method.

The same evidence base is read twice by two declared variants, and each variant
must produce its own figures and leave the other variant's fields null.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_pct,
    assert_rate,
    assert_tonnes,
)
from test_helpers.constants import (
    BASELINE_HISTORICAL_DATA,
    BASELINE_MODELED,
    BASELINE_PROPOSED,
    BASELINE_SUPERSEDED,
    ENROLLMENT_ACCEPTED,
    METHOD_MEASUREMENT,
    METHOD_MODEL,
)
from test_helpers.test_users import ADMIN_HEADERS


def test_historical_baseline_derives_mean_from_admissible_records_only(scenario):
    """The HISTORICAL_DATA variant averages the observed per-acre rates of the four
    admissible records and deducts uncertainty at two points per qualifying year.

    PRD §3.4: "Add together the `observed_emissions_per_acre` values of all qualifying
    records, divide that sum by `qualifying_years` — note that the divisor is the count
    of distinct years, not the count of records — and round half up to four decimal
    places; that is `historical_mean_rate`."

    Design: Difficulty/dual_variant_calc/baseline_historical_vs_modeled_divergence
    """
    scenario.accepted_enrollment()

    baseline = scenario.propose_baseline(BASELINE_HISTORICAL_DATA)

    assert baseline["method"] == BASELINE_HISTORICAL_DATA
    assert baseline["qualifying_years"] == 4
    assert_rate(baseline["historical_mean_rate"], 0.1450)
    assert_tonnes(baseline["baseline_emissions_t"], 145.000)
    assert_pct(baseline["uncertainty_pct"], 7.00)
    assert baseline["status"] == BASELINE_PROPOSED


def test_modeled_baseline_ignores_observations_and_supersedes_the_incumbent(scenario):
    """The MODELED variant reads the same records only for their cardinality, scales the
    programme rate by the soil factor, and displaces the incumbent proposal.

    PRD §3.4: "Multiply the field's `mapped_acres` by the standard's
    `modeled_baseline_rate_per_acre`, then by the soil factor for the field's
    `soil_group`, which is 1.00 for `LOAM`, 0.90 for `CLAY` and 1.15 for `SAND`, and
    round half up to three decimal places to get `baseline_emissions_t`."

    Design: Difficulty/dual_variant_calc/baseline_historical_vs_modeled_divergence
    """
    scenario.accepted_enrollment()
    historical = scenario.propose_baseline(BASELINE_HISTORICAL_DATA)

    modeled = scenario.propose_baseline(BASELINE_MODELED)

    assert modeled["historical_mean_rate"] is None
    assert modeled["qualifying_years"] == 4
    assert_tonnes(modeled["baseline_emissions_t"], 200.000)
    assert_pct(modeled["uncertainty_pct"], 19.00)
    assert modeled["status"] == BASELINE_PROPOSED

    displaced = validate_success(scenario.api.get_baseline(historical["id"], ADMIN_HEADERS))
    assert displaced["status"] == BASELINE_SUPERSEDED
    assert scenario.reload_enrollment()["status"] == ENROLLMENT_ACCEPTED


def test_model_quantification_scales_the_programme_rate_by_adoption(scenario):
    """The MODEL variant multiplies the methodology's sequestration rate by verified
    acres and the adoption factor, and leaves the sampling figure null.

    PRD §3.6: "Multiply the pinned standard's `sequestration_rate_per_acre` by
    `verified_acres` and then by `adoption_factor`, rounding half up to three decimal
    places, to get `gross_removals_t`."

    Design: Difficulty/dual_variant_calc/quantification_model_vs_measurement_divergence
    """
    scenario.active_enrollment()
    scenario.passed_packet()

    run = scenario.create_run(METHOD_MODEL)

    assert run["verified_acres"] == 1000.00
    assert_pct(run["mean_coverage_pct"], 92.00)
    assert_rate(run["adoption_factor"], 0.9200)
    assert run["sampling_uncertainty_pct"] is None
    assert_tonnes(run["gross_removals_t"], 322.000)
    assert_tonnes(run["uncertainty_deduction_t"], 38.640)
    assert_tonnes(run["net_removals_t"], 283.360)
    assert run["packet_count"] == 1


def test_measurement_quantification_subtracts_the_baseline_tonnage(scenario):
    """The MEASUREMENT variant reads the same packet, subtracts the baseline tonnage,
    derives its own sampling uncertainty and leaves the adoption factor null, so the
    two variants disagree by 139.210 tonnes on identical evidence.

    PRD §3.6: "For each included packet multiply its `measured_value` by its
    `reported_acres`, add the products together, and round half up to three decimal
    places to get the measured stock change; subtract the baseline's
    `baseline_emissions_t` from it, round half up to three decimal places, and floor
    the result at 0.000 to get `gross_removals_t`."

    Design: Difficulty/dual_variant_calc/quantification_model_vs_measurement_divergence
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    model_run = scenario.create_run(METHOD_MODEL)

    second, second_baseline, _field = scenario.additional_active_enrollment()
    scenario.file_packet(2026, enrollment_id=second["id"])
    scenario.qc_packet(scenario.packets[-1]["id"], "PASS")

    measurement_run = scenario.create_run(
        METHOD_MEASUREMENT,
        enrollment_id=second["id"],
        baseline_id=second_baseline["id"],
        expected_enrollment_version=scenario.reload_enrollment(second["id"])["version"],
    )

    assert measurement_run["adoption_factor"] is None
    assert_pct(measurement_run["sampling_uncertainty_pct"], 7.00)
    assert_tonnes(measurement_run["gross_removals_t"], 155.000)
    assert_tonnes(measurement_run["uncertainty_deduction_t"], 10.850)
    assert_tonnes(measurement_run["net_removals_t"], 144.150)
    assert measurement_run["packet_count"] == 1
    assert_tonnes(model_run["net_removals_t"] - measurement_run["net_removals_t"], 139.210)

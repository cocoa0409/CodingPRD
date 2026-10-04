"""Production-run consistency rules, run yield precision, and the nominal
bin-energy financing read."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_module_series,
    create_production_line,
    create_production_run_payload,
    create_ramping_line,
    post_production_run,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]


def test_run_yield_rate_precision_four_decimals(api):
    """PRD §3.3: "Each accepted run records its `run_yield_rate`: `good_modules`
    divided by `input_modules`, at 4 decimal places round half up."

    Design: Corner/calculations/run_yield_rate_precision_four_decimals
    """
    series = create_module_series()
    line = create_production_line()
    run = post_production_run(
        line["id"], series["id"], quarter=0, input_modules=3, good_modules=2
    )
    assert run["run_yield_rate"] == pytest.approx(0.6667, abs=1e-9), (
        f"2/3 must round half-up to 0.6667, got {run['run_yield_rate']}"
    )


def test_run_bin_counts_sum_mismatch_rejected(api):
    """PRD §3.3: "and `bin_counts` — an array of `bin_code` and `count` pairs
    whose counts must sum exactly to `good_modules` and whose every `bin_code`
    must exist in the produced series' `bin_profile`. A run violating any of
    these consistency rules is rejected with `ERR_RUN_INCONSISTENT` (HTTP 422)."

    Design: Corner/validations/run_bin_counts_sum_mismatch_rejected
    """
    series = create_module_series()
    line = create_production_line()
    payload = create_production_run_payload(
        line_id=line["id"],
        series_id=series["id"],
        quarter=0,
        input_modules=10,
        good_modules=10,
        bin_counts=[
            {"bin_code": "B1", "count": 6},
            {"bin_code": "B2", "count": 3},
        ],
    )
    resp = api.create_production_run(payload, PM)
    validate_error(resp, ApiErrorId.ERR_RUN_INCONSISTENT)


def test_run_quarter_mismatch_rejected(api):
    """PRD §3.3: "the `quarter` index the run belongs to (which must equal the
    line's current `ramp_quarter_index`)"
    PRD §3.3: "A run violating any of these consistency rules is rejected with
    `ERR_RUN_INCONSISTENT` (HTTP 422)."

    Design: Corner/validations/run_quarter_mismatch_rejected
    """
    bundle = create_ramping_line()
    line = bundle["line"]
    series = bundle["series"]
    assert line["ramp_quarter_index"] == 0
    payload = create_production_run_payload(
        line_id=line["id"],
        series_id=series["id"],
        quarter=1,
        input_modules=100,
        good_modules=90,
        bin_counts=[
            {"bin_code": "B1", "count": 45},
            {"bin_code": "B2", "count": 45},
        ],
    )
    resp = api.create_production_run(payload, PM)
    validate_error(resp, ApiErrorId.ERR_RUN_INCONSISTENT)


class TestNominalEnergyModelInvariant:
    """The nominal-variant financing read is computed from the declared
    bin_profile only; realized production runs must not move it."""

    def test_nominal_energy_ignores_realized_run(self, api):
        """PRD §3.3: "The nominal variant — used by the financing-model read and
        by guarantee baselines — sums, over each bin of the series' `bin_profile`,
        the bin's `wattage` multiplied by its declared `fraction`, then
        multiplies that weighted wattage by a performance ratio of 0.85 and by
        8,760 hours per year."
        PRD §3.3: "Each accepted run records its `run_yield_rate`: `good_modules`
        divided by `input_modules`, at 4 decimal places round half up."

        Design: Difficulty/dual_variant_calc/bin_energy_nominal_ignores_realized_yield
        """
        series = create_module_series(
            bin_profile=[
                {"bin_code": "HP", "wattage": 480.0, "fraction": 0.4},
                {"bin_code": "ST", "wattage": 475.0, "fraction": 0.6},
            ]
        )
        line = create_production_line()

        em_before = validate_success(api.get_energy_model(series["id"], PM), 200)
        before_value = em_before["nominal_kwh_per_kw"]

        run = post_production_run(
            line["id"], series["id"], quarter=0, input_modules=125,
            good_modules=100,
            bin_counts=[
                {"bin_code": "HP", "count": 30},
                {"bin_code": "ST", "count": 70},
            ],
        )
        assert run["run_yield_rate"] == pytest.approx(0.8000, abs=1e-9), (
            f"100/125 must be 0.8000, got {run['run_yield_rate']}"
        )

        em_after = validate_success(api.get_energy_model(series["id"], PM), 200)
        assert em_after["nominal_kwh_per_kw"] == pytest.approx(before_value, abs=1e-9), (
            "nominal variant is computed from the declared bin_profile; a realized "
            "run with yield 0.8000 must not move the financing read"
        )

    def test_nominal_energy_stable_across_differing_runs(self, api):
        """PRD §3.1: "The series also supports a computed read for project
        financing: the nominal-variant energy model returns `nominal_kwh_per_kw`
        alongside a `variant` marker, computed from the declared `bin_profile` as
        described in §3.3."
        PRD §3.3: "Because declared bin fractions and realized bin counts differ,
        the two variants produce different results for the same shipment; that
        difference is the point."

        Design: Difficulty/dual_variant_calc/bin_energy_nominal_ignores_realized_yield
        """
        series = create_module_series()
        line = create_production_line()

        em_initial = validate_success(api.get_energy_model(series["id"], PM), 200)
        assert "variant" in em_initial, "energy-model read must carry a variant marker"
        assert isinstance(em_initial["nominal_kwh_per_kw"], (int, float))

        post_production_run(line["id"], series["id"], quarter=0,
                            input_modules=100, good_modules=100)
        em_after_perfect = validate_success(api.get_energy_model(series["id"], PM), 200)
        post_production_run(line["id"], series["id"], quarter=0,
                            input_modules=100, good_modules=50)
        em_after_poor = validate_success(api.get_energy_model(series["id"], PM), 200)

        assert em_after_perfect["nominal_kwh_per_kw"] == pytest.approx(
            em_initial["nominal_kwh_per_kw"], abs=1e-9
        )
        assert em_after_poor["nominal_kwh_per_kw"] == pytest.approx(
            em_initial["nominal_kwh_per_kw"], abs=1e-9
        )

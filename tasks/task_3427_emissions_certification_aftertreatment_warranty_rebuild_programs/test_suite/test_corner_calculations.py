"""Corner coverage — calculations, part 1 (PRD §2.6 rounding, §3.3 adjusted
emissions and dosing calibration, §3.4 conformity ratio, §3.5 fault risk).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    add_spec_version,
    assert_in_use_compliance_result,
    compute_adjusted_emission,
    compute_conformity_ratio,
    compute_dosing_deviation,
    compute_dosing_target,
    compute_fault_risk_score,
    create_family,
    create_in_use_result_payload,
    create_published_standard,
    expected_calibration_status,
    expected_in_use_outcome,
    expected_test_result,
    fault_code,
    get_unit,
    ingest_snapshot,
    record_run_results,
    schedule_test_run,
    set_logical_clock,
    setup_engine_unit,
    setup_family_in_production,
    setup_family_testing,
    setup_fleet,
    validate_success,
)


def test_adjusted_emissions_equality_passes_and_pm_leg_can_fail(api):
    """PRD §3.3: "The system computes `adjusted_nox_g_per_bhp_hr` as the measured NOx multiplied by the deterioration factor, rounded half-up to 4 decimal places, and `adjusted_pm_g_per_bhp_hr` the same way from the measured PM. The run's `result` is `PASS` exactly when the adjusted NOx is no greater than the family standard's `nox_limit_g_per_bhp_hr` and the adjusted PM is no greater than the standard's `pm_limit_g_per_bhp_hr` — equality at either limit passes — and `FAIL` otherwise."

    Run A: adjusted NOx of exactly 0.3500 against the 0.35 limit still PASSes
    (equality is inclusive). Run B: adjusted NOx passes but adjusted PM
    0.0101 (round_half_up(0.0092 x 1.1, 4)) exceeds the 0.01 limit, so the
    run FAILs — both legs must hold.

    Design: Corner/calculations/adjusted_emissions_equality_passes_and_pm_leg_can_fail
    """
    env = setup_family_testing()
    family_id = env["family"]["id"]
    run_a = schedule_test_run(
        family_id, test_type="NTE", lab_code="LAB-5",
        scheduled_start="2026-10-05T00:00:00Z", scheduled_end="2026-10-07T00:00:00Z",
    )
    run_b = schedule_test_run(
        family_id, test_type="NTE", lab_code="LAB-5",
        scheduled_start="2026-10-07T00:00:00Z", scheduled_end="2026-10-09T00:00:00Z",
    )

    rec_a = record_run_results(
        run_a["id"],
        measured_nox_g_per_bhp_hr=0.35,
        measured_pm_g_per_bhp_hr=0.009,
        deterioration_factor=1.0,
    )
    assert rec_a["adjusted_nox_g_per_bhp_hr"] == compute_adjusted_emission(0.35, 1.0) == 0.35
    assert rec_a["adjusted_pm_g_per_bhp_hr"] == compute_adjusted_emission(0.009, 1.0) == 0.009
    assert rec_a["result"] == expected_test_result(0.35, 0.009, 0.35, 0.01) == "PASS", (
        f"equality at the NOx limit passes, got {rec_a['result']}"
    )

    rec_b = record_run_results(
        run_b["id"],
        measured_nox_g_per_bhp_hr=0.30,
        measured_pm_g_per_bhp_hr=0.0092,
        deterioration_factor=1.1,
    )
    assert rec_b["adjusted_nox_g_per_bhp_hr"] == compute_adjusted_emission(0.30, 1.1) == 0.33
    assert rec_b["adjusted_pm_g_per_bhp_hr"] == compute_adjusted_emission(0.0092, 1.1) == 0.0101
    assert rec_b["result"] == expected_test_result(0.33, 0.0101, 0.35, 0.01) == "FAIL", (
        f"the PM leg fails the 0.01 limit, got {rec_b['result']}"
    )


def test_conformity_ratio_rounds_half_up_to_four_decimals(api, officer_headers):
    """PRD §3.4: "The record's `conformity_ratio` is the passing count divided by the sample size, rounded half-up to 4 decimal places; its `outcome` is `CONFORMING` when that rounded ratio is at least 0.9 — a ratio of exactly 0.9000 conforms, because the threshold is inclusive — and `NON_CONFORMING` otherwise."
    PRD §2.6: "Emissions measurements and compliance ratios are compared only after rounding. Adjusted emissions values, in-use conformity ratios, campaign completion rates, and dosing deviation percentages are each rounded half-up to 4 decimal places, and the rounded value — never the raw quotient or product — is what every threshold comparison consumes."

    5/7 = 0.714285... must serialize as exactly 0.7143 (round_half_up at 4dp),
    and the rounded value is what the 0.9 threshold consumes.

    Design: Corner/calculations/conformity_ratio_rounds_half_up_to_four_decimals
    """
    env = setup_family_in_production()
    set_logical_clock("2027-06-01T00:00:00Z")

    resp = api.create_in_use_result(
        env["family"]["id"],
        create_in_use_result_payload(
            test_period_label="2027-MY-Q2", sample_size=7, passing_units=5,
        ),
        officer_headers,
    )
    record = validate_success(resp, 201)
    assert_in_use_compliance_result(record)
    assert record["conformity_ratio"] == compute_conformity_ratio(5, 7) == 0.7143, (
        f"round_half_up(5/7, 4) = 0.7143 exactly, got {record['conformity_ratio']}"
    )
    assert record["outcome"] == expected_in_use_outcome(5, 7) == "NON_CONFORMING", (
        f"0.7143 < 0.9 must not conform, got {record['outcome']}"
    )


def test_dosing_calibration_tolerance_boundary(api, engineer_headers):
    """PRD §3.3: "The dosing target is computed from the family's displacement: 6.0 grams of DEF per kilowatt-hour, scaled by the family's `displacement_liters` against a 12.0-liter reference displacement, and the result is rounded half-up to 2 decimal places and persisted as `target_def_dosing_g_per_kwh`."
    PRD §3.3: "The spec's `calibration_status` becomes `CALIBRATED` exactly when the deviation is no greater than 0.05 — a deviation of precisely 0.0500 calibrates, because the boundary is inclusive — and the observed NOx average is no greater than 400 parts per million; otherwise it remains (or returns to) `UNCALIBRATED`."

    On a 12.0-liter family (target 6.00): deviation exactly 0.0500 calibrates
    (inclusive <=), 0.0517 does not, and a NOx reading of 450 ppm blocks
    calibration even at zero deviation.

    Design: Corner/calculations/dosing_calibration_tolerance_boundary
    """
    standard = create_published_standard()
    family = create_family(
        standard["id"], family_code="L9-2028", model_year=2028, displacement_liters=12.0,
    )
    spec = add_spec_version(family, calibrate=False, activate=False)

    cal1 = validate_success(
        api.calibrate_spec(
            spec["id"],
            {"observed_nox_ppm_avg": 250, "observed_def_consumption_g_per_kwh": 6.31},
            engineer_headers,
        )
    )
    assert cal1["target_def_dosing_g_per_kwh"] == compute_dosing_target(12.0) == 6.0
    assert cal1["last_deviation_pct"] == compute_dosing_deviation(6.31, 6.0) == 0.0517, (
        f"round_half_up(|6.31 - 6.00| / 6.00, 4) = 0.0517, got {cal1['last_deviation_pct']}"
    )
    assert cal1["calibration_status"] == expected_calibration_status(250, 6.31, 12.0) == "UNCALIBRATED"

    cal2 = validate_success(
        api.calibrate_spec(
            spec["id"],
            {"observed_nox_ppm_avg": 250, "observed_def_consumption_g_per_kwh": 6.3},
            engineer_headers,
        )
    )
    assert cal2["last_deviation_pct"] == compute_dosing_deviation(6.3, 6.0) == 0.05, (
        f"deviation at exactly 0.0500, got {cal2['last_deviation_pct']}"
    )
    assert cal2["calibration_status"] == expected_calibration_status(250, 6.3, 12.0) == "CALIBRATED", (
        f"the 0.05 boundary is inclusive, got {cal2['calibration_status']}"
    )

    cal3 = validate_success(
        api.calibrate_spec(
            spec["id"],
            {"observed_nox_ppm_avg": 450, "observed_def_consumption_g_per_kwh": 6.0},
            engineer_headers,
        )
    )
    assert cal3["last_deviation_pct"] == compute_dosing_deviation(6.0, 6.0) == 0.0
    assert cal3["calibration_status"] == expected_calibration_status(450, 6.0, 12.0) == "UNCALIBRATED", (
        f"the NOx leg fails at 450 > 400 ppm even at zero deviation, got {cal3['calibration_status']}"
    )


def test_fault_risk_score_threshold_70_boundary(api, admin_headers):
    """PRD §3.5: "First, fault points: every `fault_codes` entry contributes 40 points when its severity is `CRITICAL`, 20 when `MAJOR`, and 5 when `MINOR`. Second, drift points: the absolute value of `nox_sensor_drift_ppm` is divided by 10 and floored to a whole number, and the result is capped at 30 drift points."
    PRD §3.5: "When the resulting score is at least 70, the unit's `predictive_service_due` flag is set true; the flag is an advisory latch and is never cleared once set, flagging the unit for service scheduling driven by the data stream."

    Score exactly 70 (CRITICAL 40 + MAJOR 20 + drift 100 -> 10) latches
    predictive_service_due true; score 69 (same faults, drift 95 -> 9 points)
    does not — the >= threshold is boundary-inclusive.

    Design: Corner/calculations/fault_risk_score_threshold_70_boundary
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    unit_a = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-101")
    unit_b = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-102")
    set_logical_clock("2026-11-15T00:00:00Z")
    faults = [fault_code("P2201", "CRITICAL"), fault_code("P20EE", "MAJOR")]

    snap_a = ingest_snapshot(
        unit_a["id"],
        recorded_at="2026-11-15T01:00:00Z", odometer_miles=15000, engine_hours=400,
        fault_codes=faults, def_consumption_gal=40.0, nox_sensor_drift_ppm=100,
    )
    assert snap_a["fault_risk_score"] == compute_fault_risk_score(faults, 100, 40.0, 0, 15000) == 70
    assert get_unit(unit_a["id"])["predictive_service_due"] is True, (
        "70 >= 70 latches the advisory flag"
    )

    snap_b = ingest_snapshot(
        unit_b["id"],
        recorded_at="2026-11-15T01:00:00Z", odometer_miles=15000, engine_hours=400,
        fault_codes=faults, def_consumption_gal=40.0, nox_sensor_drift_ppm=95,
    )
    assert snap_b["fault_risk_score"] == compute_fault_risk_score(faults, 95, 40.0, 0, 15000) == 69
    assert get_unit(unit_b["id"])["predictive_service_due"] is False, (
        "69 < 70 must not latch the advisory flag"
    )


def test_fault_risk_def_zero_penalty_only_beyond_500_mile_delta(api, admin_headers):
    """PRD §3.5: "Third, a DEF penalty: when `def_consumption_gal` is exactly 0 and the odometer delta — the snapshot's `odometer_miles` minus the unit's accumulated miles as they stood immediately before this ingestion — exceeds 500 miles, a flat 25 penalty points are added; otherwise none."
    PRD §3.5: "On acceptance the unit's accumulated miles and hours advance to the snapshot's readings, `last_snapshot_at` becomes the snapshot's `recorded_at`, and the unit's `version` increments."

    A 6000-mile zero-DEF interval scores 45 (20 MAJOR + 25 penalty) while a
    400-mile zero-DEF interval scores 20 (no penalty): the penalty applies
    only when the odometer delta exceeds 500.

    Design: Corner/calculations/fault_risk_def_zero_penalty_only_beyond_500_mile_delta
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    unit_a = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-101")
    unit_b = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-102")
    set_logical_clock("2026-11-15T00:00:00Z")
    faults = [fault_code("P20EE", "MAJOR")]

    snap_a = ingest_snapshot(
        unit_a["id"],
        recorded_at="2026-11-15T01:00:00Z", odometer_miles=6000, engine_hours=150,
        fault_codes=faults, def_consumption_gal=0.0, nox_sensor_drift_ppm=0,
    )
    assert snap_a["fault_risk_score"] == compute_fault_risk_score(faults, 0, 0.0, 0, 6000) == 45, (
        f"20 MAJOR + 25 DEF-zero penalty (6000 > 500 delta), got {snap_a['fault_risk_score']}"
    )

    snap_b = ingest_snapshot(
        unit_b["id"],
        recorded_at="2026-11-15T01:00:00Z", odometer_miles=400, engine_hours=10,
        fault_codes=faults, def_consumption_gal=0.0, nox_sensor_drift_ppm=0,
    )
    assert snap_b["fault_risk_score"] == compute_fault_risk_score(faults, 0, 0.0, 0, 400) == 20, (
        f"400 <= 500 delta: no penalty even though DEF is 0, got {snap_b['fault_risk_score']}"
    )

    assert get_unit(unit_a["id"])["accumulated_miles"] == 6000
    assert get_unit(unit_b["id"])["accumulated_miles"] == 400

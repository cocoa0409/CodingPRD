"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS, FLAT_RATE_SCHEDULE


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "facility_name": "Test Facility",
        "contract_term_years": TEST_DEFAULTS["CONTRACT_TERM_YEARS"],
        "guarantee_start_date": TEST_DEFAULTS["GUARANTEE_START_DATE"],
        "mv_protocol": "IPMVP_C",
        "guaranteed_annual_savings_cents": TEST_DEFAULTS["GUARANTEED_ANNUAL_SAVINGS_CENTS"],
        "contract_value_cents": TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_baseline_payload(**overrides) -> dict:
    defaults = {
        "baseline_period_start": TEST_DEFAULTS["BASELINE_PERIOD_START"],
        "baseline_period_end": TEST_DEFAULTS["BASELINE_PERIOD_END"],
        "annual_energy_kwh": TEST_DEFAULTS["ANNUAL_ENERGY_KWH"],
        "rate_schedule": [dict(t) for t in FLAT_RATE_SCHEDULE],
        "heating_degree_days": TEST_DEFAULTS["HEATING_DEGREE_DAYS"],
        "cooling_degree_days": TEST_DEFAULTS["COOLING_DEGREE_DAYS"],
        "occupancy_factor": TEST_DEFAULTS["OCCUPANCY_FACTOR"],
    }
    defaults.update(overrides)
    return defaults


def create_bundle_payload(**overrides) -> dict:
    defaults = {"name": "Test Bundle"}
    defaults.update(overrides)
    return defaults


def create_measure_payload(**overrides) -> dict:
    defaults = {
        "measure_type": "LIGHTING",
        "installed_cost_cents": 600000,
        "annual_savings_cents": 300000,
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "facility_type": "LEASE",
        "principal_cents": 1000000,
        "annual_rate_pct": 5.0,
        "term_years": 10,
    }
    defaults.update(overrides)
    return defaults


def create_draw_payload(**overrides) -> dict:
    defaults = {"amount_cents": 100000, "purpose": "deposit"}
    defaults.update(overrides)
    return defaults


def create_phase_payload(**overrides) -> dict:
    defaults = {
        "phase_label": "Phase 1",
        "window_start": TEST_DEFAULTS["PHASE_WINDOW_START"],
        "window_end": TEST_DEFAULTS["PHASE_WINDOW_END"],
        "disruption_budget_hours": TEST_DEFAULTS["DISRUPTION_BUDGET_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_disruption_payload(**overrides) -> dict:
    defaults = {
        "occurred_at": "2026-09-02T10:00:00Z",
        "hours": 2,
        "cause": "equipment staging",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "period_year": 1,
        "actual_energy_kwh": 80000,
        "period_hdd": TEST_DEFAULTS["HEATING_DEGREE_DAYS"],
        "period_cdd": TEST_DEFAULTS["COOLING_DEGREE_DAYS"],
        "period_occupancy_factor": TEST_DEFAULTS["OCCUPANCY_FACTOR"],
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(**overrides) -> dict:
    defaults = {
        "baseline_id": None,
        "supersedes_adjustment_id": None,
        "reason": "FACILITY_REDUCTION",
        "kwh_delta": -10000,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "report_id": None,
        "claimed_savings_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_owner_rep_payload(**overrides) -> dict:
    defaults = {"full_name": "Owen Owner", "organization": "City Schools"}
    defaults.update(overrides)
    return defaults


def create_esco_engineer_payload(**overrides) -> dict:
    defaults = {"full_name": "Erin ESCO", "license_number": "PE-1042"}
    defaults.update(overrides)
    return defaults

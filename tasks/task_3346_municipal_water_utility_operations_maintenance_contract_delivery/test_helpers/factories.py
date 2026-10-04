"""Payload factories -- one per entity, input fields only."""
from .constants import TEST_DEFAULTS

D = TEST_DEFAULTS


def municipality_payload(**overrides) -> dict:
    payload = {
        "name": D["MUNICIPALITY_NAME"],
        "state_code": D["STATE_CODE"],
        "population_served": D["POPULATION_SERVED"],
        "owns_treatment_works": True,
    }
    payload.update(overrides)
    return payload


def contract_payload(**overrides) -> dict:
    payload = {
        "title": D["CONTRACT_TITLE"],
        "award_date": D["AWARD_DATE"],
        "contract_start_date": D["CONTRACT_START_DATE"],
        "contract_end_date": D["CONTRACT_END_DATE"],
        "annual_fee_cents": D["ANNUAL_FEE_CENTS"],
        "operator_penalty_share_pct": D["OPERATOR_PENALTY_SHARE_PCT"],
        "benchmark_index_baseline": D["BENCHMARK_INDEX_BASELINE"],
    }
    payload.update(overrides)
    return payload


def standard_payload(**overrides) -> dict:
    payload = {
        "code": D["STANDARD_CODE"],
        "title": D["STANDARD_TITLE"],
        "metric_type": D["STANDARD_METRIC_TYPE"],
        "criticality_weight": D["STANDARD_CRITICALITY_WEIGHT"],
        "threshold_value": D["STANDARD_THRESHOLD_VALUE"],
        "threshold_direction": D["STANDARD_THRESHOLD_DIRECTION"],
        "breach_penalty_cents": D["STANDARD_BREACH_PENALTY_CENTS"],
    }
    payload.update(overrides)
    return payload


def measurement_payload(**overrides) -> dict:
    payload = {
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "measured_value": 9.0,
    }
    payload.update(overrides)
    return payload


def staffing_commitment_payload(**overrides) -> dict:
    payload = {
        "role_code": D["ROLE_CODE"],
        "committed_fte": 2.0,
    }
    payload.update(overrides)
    return payload


def employee_payload(**overrides) -> dict:
    payload = {
        "role_code": D["ROLE_CODE"],
        "full_name": D["EMPLOYEE_NAME"],
        "municipal_hire_date": D["EMPLOYEE_HIRE_DATE"],
        "transfer_offer_fte": 1.0,
    }
    payload.update(overrides)
    return payload


def asset_payload(**overrides) -> dict:
    payload = {
        "asset_tag": "PMP-101",
        "asset_class": "PUMP",
        "install_year": 2020,
        "useful_life_years": 15,
        "criticality_rank": 1,
    }
    payload.update(overrides)
    return payload


def assessment_payload(**overrides) -> dict:
    payload = {
        "assessed_at": D["ASSESSED_AT"],
        "assessed_score": 88.0,
        "is_baseline": True,
        "assessor_party": "OPERATOR",
    }
    payload.update(overrides)
    return payload


def permit_payload(**overrides) -> dict:
    payload = {
        "permit_number": D["PERMIT_NUMBER"],
        "permit_type": D["PERMIT_TYPE"],
        "regulator": D["PERMIT_REGULATOR"],
        "effective_date": D["PERMIT_EFFECTIVE_DATE"],
        "expiration_date": D["PERMIT_EXPIRATION_DATE"],
    }
    payload.update(overrides)
    return payload


def penalty_allocation_payload(**overrides) -> dict:
    payload = {
        "violation_code": "40CFR122-BYPASS",
        "total_penalty_cents": 2000000,
    }
    payload.update(overrides)
    return payload


def work_order_payload(**overrides) -> dict:
    payload = {
        "work_type": "CORRECTIVE",
        "estimated_cost_cents": 400000,
    }
    payload.update(overrides)
    return payload


def pm_schedule_payload(**overrides) -> dict:
    payload = {
        "frequency_days": 30,
        "duration_hours": 4.0,
        "first_due_at": "2026-10-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def emergency_payload(**overrides) -> dict:
    payload = {
        "event_type": "MAIN_BREAK",
        "severity": "MEDIUM",
        "occurred_at": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def renewal_proposal_payload(**overrides) -> dict:
    payload = {
        "round_number": 1,
        "proposed_fee_cents": 41000000,
        "proposed_term_years": 3,
        "submitted_by": "OPERATOR",
    }
    payload.update(overrides)
    return payload


def obligation_payload(**overrides) -> dict:
    payload = {
        "obligation_type": "RECORDS_TRANSFER",
        "due_at": "2026-06-01T00:00:00Z",
        "is_critical": False,
        "penalty_per_day_cents": 25000,
    }
    payload.update(overrides)
    return payload


def closure_payload(**overrides) -> dict:
    payload = {
        "labour_hours": 4.0,
        "materials_cents": 300000,
        "closure_narrative": (
            "Replaced the pump mechanical seal and verified shaft alignment after reassembly."
        ),
    }
    payload.update(overrides)
    return payload
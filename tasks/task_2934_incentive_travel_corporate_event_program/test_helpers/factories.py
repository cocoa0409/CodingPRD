"""Payload factories — one per entity, input fields only.

Money is always an integer count of whole cents and rates are always integer
basis points (PRD §2.6); nothing here is ever sent as a string.
"""
from typing import Any, Dict

from .constants import TEST_DEFAULTS

_EMPLOYEE_CODE_SEQ = {"n": 0}


def next_employee_code(prefix: str = "EMP") -> str:
    """Unique-per-run employee code (`employee_code` is unique per program)."""
    _EMPLOYEE_CODE_SEQ["n"] += 1
    return f"{prefix}-{_EMPLOYEE_CODE_SEQ['n']:04d}"


def create_program_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "qualification_metric": TEST_DEFAULTS["QUALIFICATION_METRIC"],
        "sales_period_start": TEST_DEFAULTS["SALES_PERIOD_START"],
        "sales_period_end": TEST_DEFAULTS["SALES_PERIOD_END"],
        "budget_total_cents": TEST_DEFAULTS["BUDGET_TOTAL_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_award_tier_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "tier_code": "PLATINUM",
        "tier_rank": 1,
        "qualification_threshold": 0,
        "budget_per_qualifier_cents": TEST_DEFAULTS["TIER_BUDGET_PER_QUALIFIER_CENTS"],
        "guest_allowance": 1,
        "air_cabin_class": "BUSINESS",
        "upgrade_allowance_cents": 0,
        "service_load_bp": 0,
    }
    payload.update(overrides)
    return payload


def create_qualifier_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "employee_code": next_employee_code(),
        "full_name": "Ana Ferreira",
        "baseline_metric": TEST_DEFAULTS["BASELINE_METRIC"],
        "actual_metric": TEST_DEFAULTS["ACTUAL_METRIC"],
        "guest_count": 0,
    }
    payload.update(overrides)
    return payload


def create_destination_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "city": TEST_DEFAULTS["CITY"],
        "country_code": TEST_DEFAULTS["COUNTRY_CODE"],
        "per_person_cost_cents": TEST_DEFAULTS["PER_PERSON_COST_CENTS"],
        "risk_score": TEST_DEFAULTS["RISK_SCORE"],
        "air_gateway_code": TEST_DEFAULTS["AIR_GATEWAY_CODE"],
    }
    payload.update(overrides)
    return payload


def create_supplier_contract_payload(
    program_id: str, destination_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "destination_id": destination_id,
        "supplier_name": TEST_DEFAULTS["SUPPLIER_NAME"],
        "supplier_kind": "HOTEL",
        "room_block_count": TEST_DEFAULTS["ROOM_BLOCK_COUNT"],
        "contracted_nights": TEST_DEFAULTS["CONTRACTED_NIGHTS"],
        "stay_start_at": TEST_DEFAULTS["STAY_START_AT"],
        "nightly_rate_cents": TEST_DEFAULTS["NIGHTLY_RATE_CENTS"],
        "attrition_allowance_bp": TEST_DEFAULTS["ATTRITION_ALLOWANCE_BP"],
        "force_majeure_clause": "STANDARD",
        "exposure_basis": "ATTRITION_BASIS",
    }
    payload.update(overrides)
    return payload


def create_deposit_milestone_payload(contract_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "contract_id": contract_id,
        "sequence": 1,
        "due_at": "2026-08-15T00:00:00Z",
        "amount_cents": 577_500,
        "refundable_bp": 10000,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(
    qualifier_id: str, expected_program_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "qualifier_id": qualifier_id,
        "registration_kind": "WINNER",
        "arrival_date": TEST_DEFAULTS["ARRIVAL_DATE"],
        "departure_date": TEST_DEFAULTS["DEPARTURE_DATE"],
        "rooms": 1,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def create_onsite_activity_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "name": "Douro Valley Sail",
        "start_at": TEST_DEFAULTS["ACTIVITY_START_AT"],
        "end_at": TEST_DEFAULTS["ACTIVITY_END_AT"],
        "capacity": 2,
        "risk_level": "LOW",
    }
    payload.update(overrides)
    return payload


def create_activity_signup_payload(
    activity_id: str, registration_id: str, expected_activity_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "activity_id": activity_id,
        "registration_id": registration_id,
        "expected_activity_version": expected_activity_version,
    }
    payload.update(overrides)
    return payload


def create_tax_award_report_payload(qualifier_id: str, tax_year: int = 2026, **overrides: Any):
    payload = {"qualifier_id": qualifier_id, "tax_year": tax_year}
    payload.update(overrides)
    return payload


def advance_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


def gross_up_policy_payload(gross_up_policy: str) -> Dict[str, Any]:
    return {"gross_up_policy": gross_up_policy}


def negotiate_payload(action: str, **terms: Any) -> Dict[str, Any]:
    payload = {"action": action}
    payload.update(terms)
    return payload


def air_payload(action: str, **fields: Any) -> Dict[str, Any]:
    payload = {"action": action}
    payload.update(fields)
    return payload


def respond_payload(response: str, **fields: Any) -> Dict[str, Any]:
    payload = {"response": response}
    payload.update(fields)
    return payload


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}

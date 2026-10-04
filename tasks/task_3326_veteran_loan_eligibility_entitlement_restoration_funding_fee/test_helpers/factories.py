"""Payload factories — one per creatable entity, input fields only."""
from __future__ import annotations

import itertools
from typing import Any, Dict

from .constants import STANDARD_CLOSE_DATE, STANDARD_FIRST_PAYMENT, STANDARD_PERIOD_END, STANDARD_PERIOD_START

_counter = itertools.count(1)


def _next_ssn() -> str:
    return f"{4000 + next(_counter) % 5000:04d}"


def create_veteran_payload(**overrides: Any) -> Dict[str, Any]:
    n = next(_counter)
    defaults: Dict[str, Any] = {
        "full_name": f"Veteran {n}",
        "ssn_last4": f"{4000 + n % 5000:04d}",
        "service_category": "REGULAR_MILITARY",
        "character_of_discharge": "HONORABLE",
        "receives_disability_compensation": False,
    }
    defaults.update(overrides)
    return defaults


def create_service_period_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "branch": "ARMY",
        "start_date": STANDARD_PERIOD_START,
        "end_date": STANDARD_PERIOD_END,
        "discharge_character": "HONORABLE",
    }
    defaults.update(overrides)
    return defaults


def create_coe_request_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"entitlement_code": "ERA_GULF"}
    defaults.update(overrides)
    return defaults


def create_loan_payload(coe_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "coe_id": coe_id,
        "purpose": "PURCHASE",
        "property_region": "SOUTH",
        "purchase_price_cents": 30000000,
        "down_payment_cents": 0,
        "interest_rate_percent": 6.5,
        "rate_type": "FIXED",
    }
    defaults.update(overrides)
    return defaults


def create_underwriting_decision_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "gross_monthly_income_cents": 600000,
        "new_housing_payment_cents": 150000,
        "other_obligations_annual_cents": [],
        "family_size": 4,
        "region": "SOUTH",
    }
    defaults.update(overrides)
    return defaults


def create_close_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "closing_date": STANDARD_CLOSE_DATE,
        "first_payment_due_date": STANDARD_FIRST_PAYMENT,
    }
    defaults.update(overrides)
    return defaults


def create_appraiser_payload(**overrides: Any) -> Dict[str, Any]:
    n = next(_counter)
    defaults: Dict[str, Any] = {
        "name": f"Appraiser {n}",
        "region": "SOUTH",
    }
    defaults.update(overrides)
    return defaults


def create_refinance_payload(expected_loan_version: int, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "refinance_type": "IRRRL",
        "new_rate_percent": 5.5,
        "new_rate_type": "FIXED",
        "flat_costs_cents": 150000,
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_assumption_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "buyer_name": "Buyer One",
        "buyer_is_veteran": False,
        "substitute_entitlement": False,
        "release_of_liability": True,
    }
    defaults.update(overrides)
    return defaults


def create_restoration_payload(loan_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "loan_id": loan_id,
        "restoration_type": "SALE_PAYOFF",
    }
    defaults.update(overrides)
    return defaults


def create_deployment_exception_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "deployment_start": "2026-03-01",
        "deployment_end": "2026-09-01",
        "orders_reference": "ORD-1",
    }
    defaults.update(overrides)
    return defaults

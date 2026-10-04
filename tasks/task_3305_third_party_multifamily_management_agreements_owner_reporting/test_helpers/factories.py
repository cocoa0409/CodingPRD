"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    BASE_FEE_PCT,
    DEFAULT_EFFECTIVE_DATE,
    DEFAULT_LEASE_END_DATE,
    DEFAULT_TAKEOVER_DATE,
    DEFAULT_TERM_END_DATE,
    INCENTIVE_THRESHOLD_EGI_CENTS,
    INCENTIVE_TIER1_RATE,
    MINIMUM_MONTHLY_FEE_CENTS,
)


def create_owner_payload(**overrides) -> dict:
    defaults = {"legal_name": "Test Owner LP", "distribution_day_of_month": 10}
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = {"name": "Test Property", "unit_count": 100}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "base_fee_pct": BASE_FEE_PCT,
        "minimum_monthly_fee_cents": MINIMUM_MONTHLY_FEE_CENTS,
        "incentive_threshold_egi_cents": INCENTIVE_THRESHOLD_EGI_CENTS,
        "incentive_tier1_rate": INCENTIVE_TIER1_RATE,
        "effective_date": DEFAULT_EFFECTIVE_DATE,
        "term_end_date": DEFAULT_TERM_END_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_onboarding_payload(**overrides) -> dict:
    defaults = {
        "prior_manager_name": "PriorCo",
        "takeover_date": DEFAULT_TAKEOVER_DATE,
        "deposits_received_cents": 0,
        "prepaid_rent_cents": 0,
        "delinquency_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    defaults = {
        "unit_label": "101",
        "full_name": "Res Test",
        "lease_end_date": DEFAULT_LEASE_END_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_contract_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "VendorCo",
        "service_type": "LANDSCAPING",
        "monthly_cost_cents": 10000,
        "start_date": "2026-08-01T00:00:00Z",
        "end_date": "2027-07-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": 2027,
        "kind": "ANNUAL",
        "operating_revenue_cents": 3000000,
        "operating_expense_cents": 2000000,
        "capex_total_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_payload(**overrides) -> dict:
    defaults = {
        "unit_label": "U1",
        "recommended_rent_cents": 200000,
        "effective_start_date": "2026-10-01T00:00:00Z",
        "effective_end_date": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    defaults = {
        "role_title": "PROPERTY_MANAGER",
        "hourly_cost_cents": 3000,
        "scheduled_hours_per_week": 30,
        "shared_region_code": "R1",
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(**overrides) -> dict:
    defaults = {
        "kind": "RENT",
        "amount_cents": 100000,
        "accrual_month": "2026-09",
        "collected_month": "2026-09",
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(**overrides) -> dict:
    defaults = {"period_month": "2026-09", "basis": "CASH"}
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {"period_month": "2026-09", "package_type": "MONTHLY_OWNER"}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "RESIDENT_INCIDENT",
        "reserved_amount_cents": 0,
        "indemnified_by": "OWNER",
        "incident_date": "2026-09-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults

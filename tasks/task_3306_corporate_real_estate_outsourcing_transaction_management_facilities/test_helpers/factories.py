"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_name": "Test Account",
        "client_name": "Test Client",
        "portfolio_sqft": TEST_DEFAULTS["PORTFOLIO_SQFT"],
        "platform_tier": TEST_DEFAULTS["PLATFORM_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "property_address": TEST_DEFAULTS["PROPERTY_ADDRESS"],
        "market_code": TEST_DEFAULTS["MARKET_CODE"],
        "leased_sqft": TEST_DEFAULTS["LEASED_SQFT"],
        "base_rent_cents_per_year": TEST_DEFAULTS["PRIOR_RENT_CENTS"],
        "lease_start_date": TEST_DEFAULTS["LEASE_START"],
        "lease_end_date": TEST_DEFAULTS["LEASE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_transaction_request_payload(account_id: str, lease_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "lease_id": lease_id,
        "request_type": "RENEWAL",
        "prior_rent_cents_per_year": TEST_DEFAULTS["PRIOR_RENT_CENTS"],
        "proposed_rent_cents_per_year": TEST_DEFAULTS["PROPOSED_RENT_CENTS"],
        "requested_term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "third_party_commission_cents": TEST_DEFAULTS["THIRD_PARTY_COMMISSION_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_commission_record_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "commission_source": "THIRD_PARTY",
        "base_rent_cents": 40_000_000,
        "commission_pct": 0.15,
        "accrual_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_broker_engagement_payload(
    account_id: str, transaction_request_id: str, **overrides
) -> dict:
    defaults = {
        "account_id": account_id,
        "transaction_request_id": transaction_request_id,
        "market_code": TEST_DEFAULTS["MARKET_CODE"],
        "broker_name": "Pat Senior",
        "licensed_in_market": True,
        "broker_class": "SENIOR",
    }
    defaults.update(overrides)
    return defaults


def create_kpi_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "kpi_code": "SLA_SCORE",
        "kpi_family": "SERVICE_LEVEL",
        "measurement_unit": "BPS",
        "measurement_window": "QUARTERLY",
        "target_value": 9100,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "vendor_name": "Ace Janitorial",
        "service_line": "JANITORIAL",
        "delivery_model": "SELF_PERFORM",
        "sourcing_program": "DIVERSITY",
        "service_rate_cents_per_sqft": 1.25,
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(account_id: str, vendor_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "vendor_id": vendor_id,
        "site_name": "Tower 42000",
        "sqft": 40_001,
    }
    defaults.update(overrides)
    return defaults


def create_consolidation_project_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "project_name": "Consolidation One",
        "planned_sqft_reduction": 360_128,
        "cost_inflation_factor": 1.05,
        "per_site_rates": [3.335, 6.665, 4.005],
        "per_site_sqft_reductions": [40_001, 25_002, 15_003],
    }
    defaults.update(overrides)
    return defaults


def create_scorecard_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "service_line": "JANITORIAL",
        "quality_bps": 9800,
        "response_bps": 9300,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "discipline": "TRANSACTION",
        "finding": "Approval minutes incomplete",
    }
    defaults.update(overrides)
    return defaults


def create_data_license_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "licensee_name": "Meridian Analytics",
        "platform_tier_at_issue": "ENTERPRISE",
        "data_scope": "AGGREGATE",
    }
    defaults.update(overrides)
    return defaults


def create_transition_task_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "task_name": "Records handover",
        "task_type": "DATA_HANDOVER",
        "sequence_no": 1,
        "blocking": True,
        "due_at": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fee_accrual_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "period": "2026-Q3",
        "base_fee_cents": 3_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {
        "assignee_name": "Dana Director",
        "assignment_role": "APPROVAL_AUTHORITY",
        "approval_level": "ACCOUNT_EXECUTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_audit_review_payload(**overrides) -> dict:
    defaults = {
        "reviewer_name": "Rae Auditor",
        "round_notes": "Round one",
    }
    defaults.update(overrides)
    return defaults
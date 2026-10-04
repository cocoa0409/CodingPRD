"""Payload factories — one per creatable resource, input fields only."""
from .constants import TEST_DEFAULTS


def create_application_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Lending Co",
        "net_worth_cents": TEST_DEFAULTS["NET_WORTH_CENTS"],
        "liquid_assets_cents": TEST_DEFAULTS["LIQUID_ASSETS_CENTS"],
        "origination_experience_months": TEST_DEFAULTS["ORIGINATION_EXPERIENCE_MONTHS"],
        "branch_count": TEST_DEFAULTS["BRANCH_COUNT"],
        "annual_origination_volume_cents": TEST_DEFAULTS["ANNUAL_ORIGINATION_VOLUME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_custodian_payload(**overrides) -> dict:
    defaults = {"firm_name": "TrustVault Custody"}
    defaults.update(overrides)
    return defaults


def create_engagement_payload(custodian_id, issuer_id, **overrides) -> dict:
    defaults = {
        "custodian_id": custodian_id,
        "issuer_id": issuer_id,
        "window_start": TEST_DEFAULTS["ENGAGEMENT_WINDOW_START"],
        "window_end": TEST_DEFAULTS["ENGAGEMENT_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(issuer_id, custodian_id, expected_issuer_version, **overrides) -> dict:
    defaults = {
        "issuer_id": issuer_id,
        "custodian_id": custodian_id,
        "pool_type": "SINGLE_FAMILY",
        "term_months": 360,
        "note_rate_bps": TEST_DEFAULTS["POOL_NOTE_RATE_BPS"],
        "expected_issuer_version": expected_issuer_version,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(pool_id, principal_balance_cents, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "principal_balance_cents": principal_balance_cents,
        "note_rate_bps": TEST_DEFAULTS["LOAN_NOTE_RATE_BPS"],
        "government_insurance": "FHA",
        "escrow_monthly_cents": TEST_DEFAULTS["ESCROW_MONTHLY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_custodial_account_payload(issuer_id, account_type, **overrides) -> dict:
    defaults = {"issuer_id": issuer_id, "account_type": account_type}
    defaults.update(overrides)
    return defaults


def create_account_transaction_payload(component, amount_cents, **overrides) -> dict:
    defaults = {"component": component, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_certification_payload(decision="CERTIFIED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_investor_report_payload(pool_id, period_month, collection_rate_bps,
                                   expected_pool_version, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "period_month": period_month,
        "collection_rate_bps": collection_rate_bps,
        "expected_pool_version": expected_pool_version,
    }
    defaults.update(overrides)
    return defaults


def create_corrective_action_plan_payload(breach_id, **overrides) -> dict:
    defaults = {
        "breach_id": breach_id,
        "plan_summary": "Cure the delinquency via payoff and buyout",
        "target_cure_month": "2026-12",
    }
    defaults.update(overrides)
    return defaults


def create_portfolio_transfer_payload(defaulted_issuer_id, successor_issuer_id,
                                      expected_defaulted_issuer_version, **overrides) -> dict:
    defaults = {
        "defaulted_issuer_id": defaulted_issuer_id,
        "successor_issuer_id": successor_issuer_id,
        "expected_defaulted_issuer_version": expected_defaulted_issuer_version,
    }
    defaults.update(overrides)
    return defaults

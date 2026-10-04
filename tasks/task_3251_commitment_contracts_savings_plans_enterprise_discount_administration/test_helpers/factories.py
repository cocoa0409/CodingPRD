"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_billing_org_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Org",
        "max_hourly_commitment_cents": TEST_DEFAULTS["ORG_CEILING"],
        "capacity_quota_units": TEST_DEFAULTS["ORG_QUOTA"],
    }
    defaults.update(overrides)
    return defaults


def create_linked_account_payload(org_id, **overrides) -> dict:
    defaults = {
        "org_id": org_id,
        "name": "acct-1",
        "external_ref": "ext-1",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(org_id, **overrides) -> dict:
    defaults = {
        "org_id": org_id,
        "name": "A",
        "committed_spend_cents": TEST_DEFAULTS["COMMITTED_SPEND"],
        "term_start": TEST_DEFAULTS["DEFAULT_TERM_START"],
        "term_end": TEST_DEFAULTS["DEFAULT_TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_discount_tier_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "service_family": "COMPUTE",
        "threshold_cents": 0,
        "rate": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(agreement_id, expected_agreement_version, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "service_family": "COMPUTE",
        "discount_rate": 0.20,
        "effective_from": "2026-10-01T00:00:00Z",
        "effective_to": "2026-11-01T00:00:00Z",
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(org_id, agreement_id, **overrides) -> dict:
    defaults = {
        "org_id": org_id,
        "agreement_id": agreement_id,
        "type": "SAVINGS_PLAN",
        "instance_family": "COMPUTE",
        "units": 0,
        "hourly_commitment_cents": 100,
        "plan_discount_rate": 0.30,
        "term_start": TEST_DEFAULTS["DEFAULT_TERM_START"],
        "term_end": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_usage_payload(linked_account_id, **overrides) -> dict:
    defaults = {
        "linked_account_id": linked_account_id,
        "service_family": "COMPUTE",
        "usage_hour_start": TEST_DEFAULTS["USAGE_HOUR_00"],
        "list_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_credit_grant_payload(org_id, **overrides) -> dict:
    defaults = {
        "org_id": org_id,
        "amount_cents": 1000,
        "expires_at": TEST_DEFAULTS["GRANT_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def generate_invoice_payload(org_id, **overrides) -> dict:
    defaults = {
        "org_id": org_id,
        "period_index": 0,
    }
    defaults.update(overrides)
    return defaults


def settle_invoice_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def assess_trueup_payload(agreement_id, **overrides) -> dict:
    defaults = {"agreement_id": agreement_id}
    defaults.update(overrides)
    return defaults


def create_forecast_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "variant": "LINEAR",
    }
    defaults.update(overrides)
    return defaults

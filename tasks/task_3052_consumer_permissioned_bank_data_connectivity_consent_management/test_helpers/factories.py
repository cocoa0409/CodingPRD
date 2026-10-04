"""Payload factories — one per creatable entity, input fields only."""

from .constants import FAR_EXPIRY, TEST_DEFAULTS


def create_institution_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Institution",
        "supported_methods": ["CREDENTIALS", "BANK_API"],
        "target_method": "BANK_API",
        "migration_window_start": "2026-09-10T00:00:00Z",
        "migration_window_end": "2026-11-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "rate_limit_per_hour": TEST_DEFAULTS["RATE_LIMIT_PER_HOUR"],
        "permitted_fields_by_scope": {
            "BALANCE": ["current_cents", "available_cents"],
            "TRANSACTIONS": ["amount_cents", "posted_at"],
            "IDENTITY": ["legal_name"],
            "INCOME": ["annual_income_cents"],
            "ASSETS": ["asset_value_cents"],
        },
        "expected_institution_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_recipient_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Recipient",
        "declared_use_case": "testing",
        "minimization_policy": "BROAD",
    }
    defaults.update(overrides)
    return defaults


def create_tier_payload(**overrides) -> dict:
    defaults = {
        "tier_name": "Test Tier",
        "scopes_included": ["BALANCE"],
        "rate_class": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(**overrides) -> dict:
    defaults = {
        "consumer_ref": TEST_DEFAULTS["CONSUMER_REF"],
        "data_scopes": ["BALANCE"],
        "expires_at": FAR_EXPIRY,
        "expected_recipient_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_connection_payload(**overrides) -> dict:
    defaults = {
        "consumer_ref": TEST_DEFAULTS["CONSUMER_REF"],
        "consent_id": "",
        "method": "CREDENTIALS",
    }
    defaults.update(overrides)
    return defaults


def refresh_payload(**overrides) -> dict:
    defaults = {"kind": "FULL"}
    defaults.update(overrides)
    return defaults

"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_bank_sponsor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Cedar Trust Bank",
        "charter_state_code": "UT",
        "sponsorship_capacity_programs": TEST_DEFAULTS["SPONSORSHIP_CAPACITY"],
        "oversight_tier": "TIER_1",
        "regulator_exam_due_at": "2027-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(sponsor_bank_id: str, **overrides) -> dict:
    defaults = {
        "name": "Harbor Reload Program",
        "sponsor_bank_id": sponsor_bank_id,
        "program_type": "BAAS_PROGRAM_MANAGER",
        "settlement_cycle": "DAILY",
        "oversight_review_due_at": "2026-12-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_brand_partner_payload(program_id: str, expected_program_version: int, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "brand_name": "Sunrise Brand",
        "services_scope": ["CARD_ISSUANCE", "LEDGERING"],
        "card_issuance_enabled": True,
        "ledgering_enabled": True,
        "compliance_oversight_enabled": False,
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_retailer_agreement_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "retailer_name": "QuickMart",
        "fee_split_retailer_pct": TEST_DEFAULTS["FEE_SPLIT_RETAILER_PCT"],
        "per_transaction_limit_cents": TEST_DEFAULTS["PER_TRANSACTION_LIMIT_CENTS"],
        "daily_location_limit_cents": TEST_DEFAULTS["DAILY_LOCATION_LIMIT_CENTS"],
        "settlement_period_hours": TEST_DEFAULTS["SETTLEMENT_PERIOD_HOURS"],
        "reload_enabled": True,
    }
    defaults.update(overrides)
    return defaults


def create_reload_location_payload(retailer_agreement_id: str, **overrides) -> dict:
    defaults = {
        "retailer_agreement_id": retailer_agreement_id,
        "location_code": "QM-001",
        "state_code": "TX",
        "register_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_card_account_payload(program_id: str, brand_partner_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "brand_partner_id": brand_partner_id,
        "account_ref": "ACCT-0001",
        "cardholder_name": "Dana Holder",
        "cardholder_agreement_type": "REG_E",
    }
    defaults.update(overrides)
    return defaults


def create_load_payload(reload_location_id: str, card_account_id: str,
                        expected_card_account_version: int, **overrides) -> dict:
    defaults = {
        "reload_location_id": reload_location_id,
        "card_account_id": card_account_id,
        "principal_cents": 3000,
        "expected_card_account_version": expected_card_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_aml_alert_payload(program_id: str, card_account_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "card_account_id": card_account_id,
        "alert_type": "VELOCITY",
        "window_start_at": "2026-09-01T00:00:00Z",
        "window_end_at": "2026-09-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(program_id: str, load_transaction_id: str, card_account_id: str,
                           expected_load_transaction_version: int, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "load_transaction_id": load_transaction_id,
        "card_account_id": card_account_id,
        "dispute_reason": "UNAUTHORIZED_LOAD",
        "claimed_amount_cents": 1500,
        "expected_load_transaction_version": expected_load_transaction_version,
    }
    defaults.update(overrides)
    return defaults


def create_loss_allocation_payload(program_id: str, load_transaction_id: str,
                                   retailer_agreement_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "load_transaction_id": load_transaction_id,
        "retailer_agreement_id": retailer_agreement_id,
        "total_loss_cents": 18000,
        "allocation_basis": "FRAUD_LOSS",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_batch_payload(retailer_agreement_id: str, **overrides) -> dict:
    defaults = {
        "retailer_agreement_id": retailer_agreement_id,
        "period_start_at": "2026-09-01T00:00:00Z",
        "period_end_at": "2026-09-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_float_window_payload(reload_location_id: str, **overrides) -> dict:
    defaults = {
        "reload_location_id": reload_location_id,
        "window_start_at": "2026-09-01T14:00:00Z",
        "window_end_at": "2026-09-01T15:00:00Z",
        "armored_carrier": "Loomis",
        "float_amount_cents": TEST_DEFAULTS["FLOAT_AMOUNT_CENTS"],
        "buffer_minutes": 120,
    }
    defaults.update(overrides)
    return defaults
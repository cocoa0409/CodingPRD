"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Flat Co",
    "STATE_CODE": "TX",
    "OWNER_NAME": "Flat Line",
    "PROCESSING_STARTED_AT": "2023-01-01T00:00:00Z",
    "BATCH_GROSS_CENTS": 1_000_000,
    "GUARANTOR_FULL_NAME": "G Name",
    "GUARANTOR_EMAIL": "g@x.com",
    "GUARANTEE_CAP_CENTS": 2_000_000,
    "BANK_LEGAL_NAME": "Partner Bank",
    "BANK_DISCOUNT_PCT": 0.04,
}


def create_merchant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "owner_name": DEFAULTS["OWNER_NAME"],
        "processing_started_at": DEFAULTS["PROCESSING_STARTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "processing_date": "2026-09-01",
        "gross_cents": DEFAULTS["BATCH_GROSS_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def accept_offer_payload(expected_merchant_version, **overrides) -> dict:
    defaults = {
        "selected_principal_cents": 500_000,
        "accepted_holdback_pct": 0.10,
        "guarantor_full_name": DEFAULTS["GUARANTOR_FULL_NAME"],
        "guarantor_email": DEFAULTS["GUARANTOR_EMAIL"],
        "guarantee_cap_cents": DEFAULTS["GUARANTEE_CAP_CENTS"],
        "expected_merchant_version": expected_merchant_version,
    }
    defaults.update(overrides)
    return defaults


def create_sweep_payload(batch_id, expected_loan_version, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_catch_up_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_bank_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["BANK_LEGAL_NAME"],
        "purchase_discount_pct": DEFAULTS["BANK_DISCOUNT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def quote_sale_payload(bank_id, **overrides) -> dict:
    defaults = {"bank_id": bank_id}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}

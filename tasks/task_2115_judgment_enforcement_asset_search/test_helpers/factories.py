"""Payload factories — one per creatable resource, client-supplied fields only."""

import itertools

from .constants import TEST_DEFAULTS

_case_number_counter = itertools.count(1)


def unique_case_number(prefix: str = "CV-2026") -> str:
    """A court_case_number that will not collide inside one state."""
    return f"{prefix}-{next(_case_number_counter):05d}"


def create_creditor_payload(**overrides) -> dict:
    payload = {
        "name": "Harbor Recovery LLC",
        "contact_email": "ops@harbor.example",
    }
    payload.update(overrides)
    return payload


def create_debtor_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Reyes",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_judgment_payload(creditor_id: str, debtor_id: str, **overrides) -> dict:
    payload = {
        "creditor_id": creditor_id,
        "debtor_id": debtor_id,
        "court_case_number": unique_case_number(),
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "original_principal_cents": TEST_DEFAULTS["PRINCIPAL_CENTS"],
        "interest_rate_bps": TEST_DEFAULTS["INTEREST_RATE_BPS"],
        "entered_on": TEST_DEFAULTS["ENTERED_ON"],
        "filing_costs_cents": TEST_DEFAULTS["FILING_COSTS_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_county_filing_payload(judgment_id: str, **overrides) -> dict:
    payload = {
        "judgment_id": judgment_id,
        "county_code": TEST_DEFAULTS["COUNTY_CODE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "filing_type": "ABSTRACT_OF_JUDGMENT",
        "fee_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_asset_finding_payload(judgment_id: str, **overrides) -> dict:
    payload = {
        "judgment_id": judgment_id,
        "asset_type": "BANK_ACCOUNT",
        "institution_name": "First Pacific Bank",
        "identifier_last4": "8811",
        "estimated_value_cents": TEST_DEFAULTS["BANK_BALANCE_CENTS"],
        "source": "PUBLIC_RECORD",
    }
    payload.update(overrides)
    return payload


def create_employment_finding_payload(judgment_id: str, weekly_disposable_earnings_cents: int,
                                      **overrides) -> dict:
    """weekly_disposable_earnings_cents is required exactly when asset_type is EMPLOYMENT."""
    payload = {
        "judgment_id": judgment_id,
        "asset_type": "EMPLOYMENT",
        "institution_name": "Atlantic Freight Co",
        "identifier_last4": "7712",
        "estimated_value_cents": 0,
        "source": "PUBLIC_RECORD",
        "weekly_disposable_earnings_cents": weekly_disposable_earnings_cents,
    }
    payload.update(overrides)
    return payload


def skip_trace_payload(expected_debtor_version: int, **overrides) -> dict:
    payload = {
        "vendor": "TLOxp",
        "located": True,
        "hits_count": 3,
        "expected_debtor_version": expected_debtor_version,
    }
    payload.update(overrides)
    return payload


def create_enforcement_action_payload(judgment_id: str, asset_finding_id: str,
                                      expected_judgment_version: int, **overrides) -> dict:
    payload = {
        "judgment_id": judgment_id,
        "asset_finding_id": asset_finding_id,
        "action_type": "BANK_LEVY",
        "expected_judgment_version": expected_judgment_version,
    }
    payload.update(overrides)
    return payload


def create_exemption_claim_payload(enforcement_action_id: str, **overrides) -> dict:
    payload = {
        "enforcement_action_id": enforcement_action_id,
        "claim_type": "SOCIAL_SECURITY",
        "claimed_amount_cents": 100_000,
    }
    payload.update(overrides)
    return payload


def create_examination_payload(judgment_id: str, **overrides) -> dict:
    payload = {
        "judgment_id": judgment_id,
        "scheduled_at": "2026-09-01T15:00:00Z",
    }
    payload.update(overrides)
    return payload


def issue_subpoena_payload(**overrides) -> dict:
    payload = {
        "recipient_type": "EMPLOYER",
        "recipient_name": "Atlantic Freight Co",
    }
    payload.update(overrides)
    return payload


def create_settlement_offer_payload(judgment_id: str, expected_judgment_version: int,
                                    **overrides) -> dict:
    payload = {
        "judgment_id": judgment_id,
        "offered_by": "CREDITOR",
        "kind": "LUMP_SUM",
        "amount_cents": 4_000_000,
        "expires_at": "2026-12-01T00:00:00Z",
        "expected_judgment_version": expected_judgment_version,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(judgment_id: str, amount_cents: int, received_on: str,
                           **overrides) -> dict:
    payload = {
        "judgment_id": judgment_id,
        "amount_cents": amount_cents,
        "received_on": received_on,
        "source": "DEBTOR_DIRECT",
    }
    payload.update(overrides)
    return payload

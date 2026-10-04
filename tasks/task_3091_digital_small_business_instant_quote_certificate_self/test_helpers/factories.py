"""Payload factories — one per entity, input fields only."""

from .constants import (
    CLOCK_DEFAULT_EFFECTIVE_AT,
    RULE_WINDOW_FROM,
    RULE_WINDOW_TO,
)


def create_class_code_payload(**overrides) -> dict:
    defaults = {
        "code": "91341",
        "description": "Contractor",
        "eligible_lines": ["GL", "PL", "TOOLS"],
        "base_rates_cents": {"GL": 12000, "PL": 18000, "TOOLS": 6000},
        "risk_factor": 1.0,
        "appetite_active": True,
    }
    defaults.update(overrides)
    return defaults


def create_appetite_rule_payload(**overrides) -> dict:
    defaults = {
        "keyword": "contractor",
        "class_code": "91341",
        "disposition": "ADMIT",
        "effective_from": RULE_WINDOW_FROM,
        "effective_to": RULE_WINDOW_TO,
        "priority_rank": 1,
        "is_enabled": True,
    }
    defaults.update(overrides)
    return defaults


def create_business_account_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Corner Bakery LLC",
        "contact_email": "bakery@example.com",
        "channel": "DIRECT",
    }
    defaults.update(overrides)
    return defaults


def create_risk_signal_payload(**overrides) -> dict:
    defaults = {
        "business_account_id": "",
        "signal_type": "LOSS_HISTORY",
        "severity": 50,
        "detail": "Automated screen result",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    defaults = {
        "business_account_id": "",
        "raw_description": "contractor",
        "selected_lines": ["GL"],
        "exposure_units": 10,
        "requested_effective_at": CLOCK_DEFAULT_EFFECTIVE_AT,
        "uw_answers": {},
    }
    defaults.update(overrides)
    return defaults


def bind_quote_payload(**overrides) -> dict:
    defaults = {"expected_quote_version": 1}
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(**overrides) -> dict:
    defaults = {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": CLOCK_DEFAULT_EFFECTIVE_AT,
        "expected_policy_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {"policy_id": "", "endorsement_id": ""}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "policy_id": "",
        "loss_occurred_at": CLOCK_DEFAULT_EFFECTIVE_AT,
        "description": "Ladder fell on client property",
        "claim_amount_cents": 150000,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "photo_ref": "ph://evidence-1",
        "exif_taken_at": CLOCK_DEFAULT_EFFECTIVE_AT,
        "file_size_bytes": 2048,
    }
    defaults.update(overrides)
    return defaults


def create_non_renewal_notice_payload(**overrides) -> dict:
    defaults = {"reason_code": "RISK_ESCALATION"}
    defaults.update(overrides)
    return defaults

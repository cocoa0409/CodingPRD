"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_member_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["LEGAL_NAME"],
        "member_kind": "BOTH",
        "region": TEST_DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(sponsor_member_id, **overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["PARTICIPANT_NAME"],
        "sponsor_member_id": sponsor_member_id,
        "program_name": TEST_DEFAULTS["PROGRAM_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_merchant_payload(participant_id=None, acquirer_member_id=None,
                            **overrides) -> dict:
    defaults = {
        "mcc": TEST_DEFAULTS["MCC"],
        "region": TEST_DEFAULTS["REGION"],
        "declared_monthly_volume_cents": TEST_DEFAULTS["DECLARED_VOLUME_CENTS"],
    }
    if participant_id is not None:
        defaults["participant_id"] = participant_id
    if acquirer_member_id is not None:
        defaults["acquirer_member_id"] = acquirer_member_id
    defaults.update(overrides)
    return defaults


def create_bin_range_payload(issuer_member_id, **overrides) -> dict:
    defaults = {
        "bin_prefix": "411111",
        "issuer_member_id": issuer_member_id,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(owner_member_id, **overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "program_type": "CARD_PRODUCT",
        "product_code": "CC1",
        "owner_member_id": owner_member_id,
    }
    defaults.update(overrides)
    return defaults


def create_certification_test_payload(**overrides) -> dict:
    defaults = {"scope": "NEW_PRODUCT"}
    defaults.update(overrides)
    return defaults


def create_rule_payload(rule_code="R-TEST-1", **overrides) -> dict:
    defaults = {
        "rule_code": rule_code,
        "title": "Test rule",
        "body": "Rule body",
        "region_scope": "GLOBAL",
        "effective_from": "2026-09-01T00:00:00Z",
        "fine_schedule": [
            {"min_amount_minor": 1, "max_amount_minor": None,
             "fine_cents": 1000},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_rule_violation_payload(rule_id, subject_member_id, **overrides) -> dict:
    defaults = {
        "rule_id": rule_id,
        "subject_member_id": subject_member_id,
        "severity": "MINOR",
        "transaction_amount_minor": 100,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(issuer_member_id, acquirer_member_id, merchant_id,
                           **overrides) -> dict:
    defaults = {
        "reason_code": TEST_DEFAULTS["REASON_CODE"],
        "issuer_member_id": issuer_member_id,
        "acquirer_member_id": acquirer_member_id,
        "merchant_id": merchant_id,
        "transaction_amount_cents": 10000,
        "currency": TEST_DEFAULTS["CURRENCY"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "evidence_type": "TRANSACTION_RECORD",
        "document_ref": "doc-1",
    }
    defaults.update(overrides)
    return defaults


def create_interchange_rate_payload(**overrides) -> dict:
    defaults = {
        "merchant_category": TEST_DEFAULTS["MCC"],
        "transaction_type": "CARD_NOT_PRESENT",
        "data_quality_tier": "STANDARD",
        "rate_basis_points": 100,
        "fixed_fee_cents": 50,
        "region_scope": "GLOBAL",
        "effective_from": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fraud_case_payload(merchant_id, reported_by_member_id, **overrides) -> dict:
    defaults = {
        "merchant_id": merchant_id,
        "reported_by_member_id": reported_by_member_id,
        "fraud_amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_fraud_program_cycle_payload(**overrides) -> dict:
    defaults = {
        "cycle_label": "CYC-1",
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-16T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_window_payload(**overrides) -> dict:
    defaults = {
        "window_date": TEST_DEFAULTS["WINDOW_DATE"],
        "opens_at": TEST_DEFAULTS["WINDOW_OPENS_AT"],
        "closes_at": TEST_DEFAULTS["WINDOW_CLOSES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_settlement_line_payload(window_id, from_member_id, to_member_id,
                                   **overrides) -> dict:
    defaults = {
        "window_id": window_id,
        "from_member_id": from_member_id,
        "to_member_id": to_member_id,
        "amount_cents": 1000,
        "currency": TEST_DEFAULTS["CURRENCY"],
        "reference": "ref-1",
    }
    defaults.update(overrides)
    return defaults

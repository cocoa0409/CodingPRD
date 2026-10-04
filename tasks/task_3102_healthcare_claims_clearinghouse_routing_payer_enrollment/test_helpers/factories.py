"""Payload factories — one per creatable resource, input fields only."""

from typing import Any, Dict

from .constants import (
    CREDENTIAL_EFFECTIVE_AT,
    CREDENTIAL_EXPIRES_AT,
    SERVICE_TYPE_GENERAL_BENEFITS,
)


def create_provider_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "legal_name": "Acme Health Partners",
        "tax_identification_number": "123456789",
        "national_provider_identifier": "1234567893",
        "billing_model": "PROVIDER_FUNDED",
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "submitter_id": "SUB-001",
        "trading_partner_agreement_ref": "TPA-2026-001",
        "effective_at": CREDENTIAL_EFFECTIVE_AT,
        "expires_at": CREDENTIAL_EXPIRES_AT,
    }
    defaults.update(overrides)
    return defaults


def create_payer_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "payer_id_code": "PAYAA",
        "display_name": "Payer A",
        "claims_lead_time_days": 5,
        "remittance_lead_time_days": 5,
        "eligibility_lead_time_seconds": 60,
        "pricing_model": "PROVIDER_FUNDED",
        "monthly_minimum_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_tier_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "applies_to": "CLAIM",
        "volume_floor": 1,
        "rate_cents": 10,
    }
    defaults.update(overrides)
    return defaults


def create_edit_rule_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "rule_code": "DX_REQUIRED",
        "applies_to": "CLAIM_INTAKE",
        "severity": "ERROR",
        "expression": "diagnosis_codes.nonempty",
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "payer_id": "",
        "transaction_type": "CLAIMS_837",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "payer_id": "",
        "submitter_credential_id": "",
        "patient_control_number": "PCN-001",
        "idempotency_key": "IDEM-001",
        "service_date": "2026-09-01T00:00:00Z",
        "total_charge_cents": 100,
        "diagnosis_codes": ["Z00.0"],
        "rendering_npi": "1234567893",
        "subscriber_id": "MBR-001",
        "lines": [{"cpt_code": "99213", "units": 1, "unit_charge_cents": 100}],
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "check_number": "CHK-001",
        "paid_amount_cents": 0,
        "adjustment_amount_cents": 0,
        "patient_responsibility_cents": 0,
        "denial_reason_codes": [],
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "payer_id": "",
        "subscriber_id": "MBR-001",
        "service_type_code": SERVICE_TYPE_GENERAL_BENEFITS,
        "idempotency_key": "IDEM-E-001",
    }
    defaults.update(overrides)
    return defaults


def create_outage_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "severity": "FULL",
        "affects_transaction_types": ["CLAIMS_837"],
    }
    defaults.update(overrides)
    return defaults


def create_usage_invoice_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "period_yyyy_mm": "2026-09",
    }
    defaults.update(overrides)
    return defaults

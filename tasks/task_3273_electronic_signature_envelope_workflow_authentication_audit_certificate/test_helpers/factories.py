"""Payload factories — one per entity, declared input fields only."""
from .constants import (
    DEFAULT_ACCESS_CODE,
    DEFAULT_AUTH_LEVEL,
    DEFAULT_EXPIRES_AFTER_DAYS,
    DEFAULT_ROUTING_MODE,
    DEFAULT_SENDER_VISIBLE_WINDOW_DAYS,
    DEFAULT_TEMPLATE_AUTH_LEVEL,
    TEST_ACCOUNT_NAME,
    TEST_STATE_CODE,
)

DEFAULTS = {
    "ACCOUNT_NAME": TEST_ACCOUNT_NAME,
    "STATE_CODE": TEST_STATE_CODE,
    "SUBJECT": "Test Envelope",
    "RETENTION_YEARS": 3,
    "PAGE_COUNT": 3,
    "ROLE_SLOT_COUNT": 1,
}


def create_account_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["ACCOUNT_NAME"], "state_code": DEFAULTS["STATE_CODE"]}
    payload.update(overrides)
    return payload


def create_retention_policy_payload(**overrides) -> dict:
    payload = {
        "name": "Standard Retention",
        "scope": "GLOBAL",
        "retention_years": DEFAULTS["RETENTION_YEARS"],
        "purge_mode": "ANONYMIZE_METADATA",
        "purge_grace_days": 0,
    }
    payload.update(overrides)
    return payload


def update_retention_policy_payload(**overrides) -> dict:
    payload = {
        "retention_years": DEFAULTS["RETENTION_YEARS"],
        "purge_mode": "ANONYMIZE_METADATA",
        "purge_grace_days": 0,
    }
    payload.update(overrides)
    return payload


def create_template_payload(owning_account_id: str, **overrides) -> dict:
    payload = {
        "owning_account_id": owning_account_id,
        "name": "Template",
        "default_routing_mode": DEFAULT_ROUTING_MODE,
        "default_auth_level": DEFAULT_TEMPLATE_AUTH_LEVEL,
        "page_count": DEFAULTS["PAGE_COUNT"],
        "role_slot_count": DEFAULTS["ROLE_SLOT_COUNT"],
    }
    payload.update(overrides)
    return payload


def instantiate_template_payload(
    sender_account_id: str, retention_policy_id: str, recipients=None, **overrides
) -> dict:
    payload = {
        "sender_account_id": sender_account_id,
        "retention_policy_id": retention_policy_id,
        "subject": DEFAULTS["SUBJECT"],
        "recipients": recipients if recipients is not None else [],
    }
    payload.update(overrides)
    return payload


def create_envelope_payload(
    sender_account_id: str, retention_policy_id: str, **overrides
) -> dict:
    payload = {
        "sender_account_id": sender_account_id,
        "subject": DEFAULTS["SUBJECT"],
        "routing_mode": DEFAULT_ROUTING_MODE,
        "expires_after_days": DEFAULT_EXPIRES_AFTER_DAYS,
        "sender_visible_window_days": DEFAULT_SENDER_VISIBLE_WINDOW_DAYS,
        "retention_policy_id": retention_policy_id,
    }
    payload.update(overrides)
    return payload


def create_document_payload(**overrides) -> dict:
    payload = {"name": "Document.pdf", "page_count": DEFAULTS["PAGE_COUNT"]}
    payload.update(overrides)
    return payload


def create_recipient_payload(**overrides) -> dict:
    payload = {
        "role": "SIGNER",
        "email": "recipient@example.com",
        "routing_order": 1,
        "auth_level": DEFAULT_AUTH_LEVEL,
        "consent_accepted": True,
    }
    if payload["auth_level"] == "ACCESS_CODE":
        payload["access_code"] = DEFAULT_ACCESS_CODE
    payload.update(overrides)
    return payload


def create_field_payload(
    envelope_document_id: str, recipient_id: str, **overrides
) -> dict:
    payload = {
        "envelope_document_id": envelope_document_id,
        "recipient_id": recipient_id,
        "field_type": "SIGNATURE",
        "required": True,
        "page_number": 1,
        "tab_order": 1,
    }
    payload.update(overrides)
    return payload


def create_session_payload(consent: bool = True) -> dict:
    return {"consent_to_electronic_records": consent}


def authenticate_payload(method: str, **overrides) -> dict:
    payload = {"method": method}
    payload.update(overrides)
    return payload


def decline_payload(reason: str = "Terms unacceptable") -> dict:
    return {"decline_reason": reason}


def void_payload(expected_envelope_version: int, **overrides) -> dict:
    payload = {
        "expected_envelope_version": expected_envelope_version,
        "void_reason": "superseded",
        "refund_credit": False,
    }
    payload.update(overrides)
    return payload


def expire_payload(expected_envelope_version: int) -> dict:
    return {"expected_envelope_version": expected_envelope_version}


def complete_payload(expected_envelope_version: int) -> dict:
    return {"expected_envelope_version": expected_envelope_version}


def purge_payload(expected_envelope_version: int) -> dict:
    return {"expected_envelope_version": expected_envelope_version}


def legal_hold_payload(legal_hold: bool, hold_until=None) -> dict:
    payload = {"legal_hold": legal_hold}
    if hold_until is not None:
        payload["hold_until"] = hold_until
    return payload


def credit_adjustment_payload(delta_units: int, reason: str = "adjustment") -> dict:
    return {"delta_units": delta_units, "reason": reason}


def create_bulk_send_payload(
    account_id: str, template_id: str, total_rows: int = 2
) -> dict:
    return {"account_id": account_id, "template_id": template_id, "total_rows": total_rows}


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
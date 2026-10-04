"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_member_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "full_name": f"Test Member {n}",
        "email": f"member{n}@example.com",
        "membership_tier": "STANDARD",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_guardian_link_payload(guardian_member_id, **overrides) -> dict:
    defaults = {
        "guardian_member_id": guardian_member_id,
        "relation_label": "guardian",
    }
    defaults.update(overrides)
    return defaults


def create_record_item_payload(**overrides) -> dict:
    defaults = {
        "item_kind": "CONDITION",
        "label": _uniq("Label"),
        "detail": "clinical detail",
        "severity": "HIGH",
        "provider_document_ref": _uniq("doc"),
    }
    defaults.update(overrides)
    return defaults


def create_contact_payload(**overrides) -> dict:
    defaults = {
        "contact_name": _uniq("Contact"),
        "phone": "+15550000000",
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_directive_payload(**overrides) -> dict:
    defaults = {
        "directive_type": "DNR",
        "document_ref": _uniq("directive-doc"),
        "release_scope": "EMERGENCY_AND_CONTACTS",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_sku": _uniq("SKU"),
        "product_name": "Test Product",
        "base_price_cents": 2000,
        "max_engrave_chars": 40,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "engraving_text": "Test engraving",
        "engrave_mode": "MANUAL",
    }
    defaults.update(overrides)
    return defaults


def create_responder_payload(**overrides) -> dict:
    defaults = {
        "agency_name": "Test EMS",
        "credential_code": _uniq("CRED"),
        "access_tier": "BASIC",
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_access_event_payload(credential_code, identifier_code, **overrides) -> dict:
    defaults = {
        "credential_code": credential_code,
        "identifier_code": identifier_code,
        "lookup_method": "IDENTIFIER",
    }
    defaults.update(overrides)
    return defaults


def create_wandering_case_payload(**overrides) -> dict:
    defaults = {"opened_via": "HOTLINE_ESCALATION"}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(record_item_id, **overrides) -> dict:
    defaults = {
        "record_item_id": record_item_id,
        "claim_text": "the record item is inaccurate",
    }
    defaults.update(overrides)
    return defaults

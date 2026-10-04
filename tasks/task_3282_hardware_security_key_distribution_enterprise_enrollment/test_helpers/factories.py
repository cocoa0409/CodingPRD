"""Payload factories — one per entity, input fields only."""

import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Org {_n()}",
        "assurance_tier": "STANDARD",
        "authentication_policy": "STANDARD",
        "idp_protocols": ["FIDO2"],
        "backup_key_minimum": 2,
    }
    defaults.update(overrides)
    return defaults


def create_key_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": f"M-{_n()}",
        "connectors": ["USB_C"],
        "protocols": ["FIDO2"],
        "form_factor": "KEYCHAIN",
        "unit_price_cents": 150,
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": f"D-{_n()}",
        "platform": "WINDOWS",
        "connectors": ["USB_C"],
        "protocol_capability": ["FIDO2"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "employee_ref": f"E-{n}",
        "location": "HQ",
        "directory_user_id": f"u-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(model_code, quantity=1, **overrides) -> dict:
    defaults = {
        "lines": [{"model_code": model_code, "quantity": quantity}],
        "shipping_location": "HQ",
    }
    defaults.update(overrides)
    return defaults


def create_key_batch_payload(*serials, firmware_version="5.4.3", model_code=None) -> dict:
    """Build the bulk pre-registration body; per-key model_code only when given."""
    keys = []
    for s in serials:
        k = {"serial_number": s, "firmware_version": firmware_version}
        if model_code is not None:
            k["model_code"] = model_code
        keys.append(k)
    return {"keys": keys}


def create_subscription_payload(**overrides) -> dict:
    defaults = {
        "tier": "BASIC",
        "refresh_interval_days": 30,
        "replacement_credits_total": 10,
    }
    defaults.update(overrides)
    return defaults


def create_temporary_access_payload(**overrides) -> dict:
    defaults = {
        "method": "SMART_CARD",
        "duration_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def create_help_desk_case_payload(identity_account_id, **overrides) -> dict:
    defaults = {
        "identity_account_id": identity_account_id,
        "category": "LOST_KEY",
        "description": f"case {_n()}",
    }
    defaults.update(overrides)
    return defaults

"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Ada Byers",
    "EMAIL": "ada@example.com",
    "PHONE": "+15550001001",
    "ISSUER_NAME": "Meridian Bank",
    "COUNTRY_CODE": "US",
    "DEVICE_MODEL": "Phone X",
    "OS_VERSION": "26.0",
    "FPAN_LAST4": "4242",
    "PAN_LAST4": "4242",
    "EXPIRY": "0930",
    "EMBOSSING_NAME": "ADA BYERS",
    "CURRENCY": "USD",
}


def create_cardholder_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "email": DEFAULTS["EMAIL"],
        "phone": DEFAULTS["PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(cardholder_id, **overrides) -> dict:
    defaults = {
        "cardholder_id": cardholder_id,
        "device_serial": "SN-001",
        "device_model": DEFAULTS["DEVICE_MODEL"],
        "os_version": DEFAULTS["OS_VERSION"],
    }
    defaults.update(overrides)
    return defaults


def create_issuer_payload(**overrides) -> dict:
    defaults = {
        "issuer_name": DEFAULTS["ISSUER_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(issuer_id, **overrides) -> dict:
    defaults = {
        "issuer_id": issuer_id,
        "branding_color": "#112233",
        "branding_logo_ref": "logo://m",
        "terms_version": "v1",
        "fee_bps": 150,
        "fee_cap_cents": 500,
        "fee_floor_cents": 0,
        "express_transit_supported": True,
        "effective_at": "2026-09-01T00:00:00Z",
        "expires_at": "2027-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_card_account_payload(cardholder_id, issuer_id, **overrides) -> dict:
    defaults = {
        "cardholder_id": cardholder_id,
        "issuer_id": issuer_id,
        "fpan_last4": DEFAULTS["FPAN_LAST4"],
        "card_product": "TRANSIT",
    }
    defaults.update(overrides)
    return defaults


def create_card_artifact_payload(card_account_id, **overrides) -> dict:
    defaults = {
        "card_account_id": card_account_id,
        "pan_last4": DEFAULTS["PAN_LAST4"],
        "expiry": DEFAULTS["EXPIRY"],
        "embossing_name": DEFAULTS["EMBOSSING_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_provisioning_session_payload(card_artifact_id, **overrides) -> dict:
    defaults = {
        "card_artifact_id": card_artifact_id,
        "idempotency_key": "prov-1",
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(**overrides) -> dict:
    defaults = {
        "cryptogram": "cgm-1",
        "amount_cents": 1000,
        "currency": DEFAULTS["CURRENCY"],
        "merchant_id": "m-1",
        "merchant_category": "GENERAL",
        "biometric_verified": True,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": "UNRECOGNIZED"}
    defaults.update(overrides)
    return defaults


def create_merchant_program_payload(issuer_id, **overrides) -> dict:
    defaults = {
        "issuer_id": issuer_id,
        "program_code": "PROG-1",
        "merchant_name": "Corner Store",
        "required_pan_last4": "",
        "max_auth_amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_transit_operator_payload(**overrides) -> dict:
    defaults = {
        "operator_code": "BART",
        "name": "Bay Transit",
        "flat_fare_cents": 250,
        "express_cap_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_transit_allowlist_payload(transit_operator_id, card_account_id, **overrides) -> dict:
    defaults = {
        "transit_operator_id": transit_operator_id,
        "card_account_id": card_account_id,
    }
    defaults.update(overrides)
    return defaults

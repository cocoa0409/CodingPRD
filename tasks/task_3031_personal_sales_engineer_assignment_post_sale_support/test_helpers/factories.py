"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ENGINEER_NAME": "Dana Riggs",
    "ENGINEER_EMAIL": "dana.riggs@sweetwater.example",
    "CUSTOMER_NAME": "Riley Chance",
    "CUSTOMER_EMAIL": "riley.chance@example.com",
    "CUSTOMER_STATE": "IN",
    "CENTER_NAME": "Indianapolis Bench",
    "GUITAR_CODE": "SW-GTR-100",
    "GUITAR_NAME": "Studio Guitar 100",
    "GUITAR_PRICE": 120000,
    "AMP_CODE": "SW-AMP-050",
    "AMP_NAME": "Combo Amp 50",
    "AMP_PRICE": 90000,
    "SERIAL": "SN-GTR-5521",
    "FAULT": "Fret buzz on the low E",
    "TICKET_SUBJECT": "Amp hum at high gain",
}


def create_engineer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["ENGINEER_NAME"],
        "email": DEFAULTS["ENGINEER_EMAIL"],
        "region": "MIDWEST",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "home_state": DEFAULTS["CUSTOMER_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": DEFAULTS["GUITAR_CODE"],
        "display_name": DEFAULTS["GUITAR_NAME"],
        "product_family": "GUITAR",
        "unit_price_cents": DEFAULTS["GUITAR_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_service_center_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CENTER_NAME"],
        "region": "MIDWEST",
        "capacity_slots": 2,
        "accepted_families": ["GUITAR", "AMPLIFIER"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(customer_id, engineer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "engineer_id": engineer_id,
        "reason_code": "NEW_ACCOUNT",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(customer_id, engineer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "engineer_id": engineer_id,
        "package_type": "SYSTEM_PACKAGE",
    }
    defaults.update(overrides)
    return defaults


def create_quote_line_payload(**overrides) -> dict:
    defaults = {
        "product_code": DEFAULTS["GUITAR_CODE"],
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_instrument_unit_payload(quote_line_id, **overrides) -> dict:
    defaults = {
        "quote_line_id": quote_line_id,
        "serial_number": DEFAULTS["SERIAL"],
        "model_code": DEFAULTS["GUITAR_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_setup_measurements_payload(**overrides) -> dict:
    defaults = {
        "action_height_mm": 1.50,
        "relief_mm": 0.10,
        "intonation_offset_cents": 2,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_plan_payload(customer_id, instrument_unit_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "instrument_unit_id": instrument_unit_id,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(warranty_plan_id, service_center_id, **overrides) -> dict:
    defaults = {
        "warranty_plan_id": warranty_plan_id,
        "reported_fault": DEFAULTS["FAULT"],
        "service_center_id": service_center_id,
    }
    defaults.update(overrides)
    return defaults


def create_support_ticket_payload(customer_id, service_center_id=None, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "subject": DEFAULTS["TICKET_SUBJECT"],
        "channel": "PHONE",
    }
    if service_center_id is not None:
        defaults["service_center_id"] = service_center_id
    defaults.update(overrides)
    return defaults


def create_backorder_payload(quote_line_id, engineer_id, **overrides) -> dict:
    defaults = {
        "quote_line_id": quote_line_id,
        "engineer_id": engineer_id,
    }
    defaults.update(overrides)
    return defaults


def create_gear_exchange_payload(quote_line_id, customer_id, **overrides) -> dict:
    defaults = {
        "quote_line_id": quote_line_id,
        "customer_id": customer_id,
        "reason": "TONE_MISMATCH",
    }
    defaults.update(overrides)
    return defaults


def create_certification_attempt_payload(engineer_id, **overrides) -> dict:
    defaults = {
        "engineer_id": engineer_id,
        "product_family": "GUITAR",
        "score_pct": 85,
    }
    defaults.update(overrides)
    return defaults
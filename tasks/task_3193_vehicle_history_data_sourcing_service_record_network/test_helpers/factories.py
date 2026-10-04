"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "NETWORK_NAME": "TestNet",
    "GUARANTEE_PAYOUT_CAP_CENTS": 5_000_000,
    "SOURCE_TYPE": "MVA",
    "JURISDICTION": "CA",
    "VIN": "1HGCM82633A004352",
    "SHOP_LEGAL_NAME": "Shop One",
    "DEALER_LEGAL_NAME": "Dealer One",
    "CONSUMER_EMAIL": "owner@example.com",
    "ASKING_PRICE_CENTS": 700_000,
    "EVENT_DATE": "2026-09-01",
    "PAYLOAD_REF": "ref-1",
    "IDEMPOTENCY_KEY": "key-1",
    "REASON": "record is wrong",
    "CLAIMANT_NAME": "Buyer One",
    "CLAIM_REASON": "brand issue found after purchase",
    "CLOCK_START": "2026-09-01T00:00:00Z",
}


def create_network_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["NETWORK_NAME"],
        "guarantee_payout_cap_cents": DEFAULTS["GUARANTEE_PAYOUT_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_source_payload(**overrides) -> dict:
    defaults = {
        "source_type": DEFAULTS["SOURCE_TYPE"],
        "jurisdiction": DEFAULTS["JURISDICTION"],
    }
    defaults.update(overrides)
    return defaults


def create_record_payload(**overrides) -> dict:
    defaults = {
        "vin": DEFAULTS["VIN"],
        "record_type": "ACCIDENT",
        "event_date": DEFAULTS["EVENT_DATE"],
        "damage_severity": 3,
        "payload_ref": DEFAULTS["PAYLOAD_REF"],
        "idempotency_key": DEFAULTS["IDEMPOTENCY_KEY"],
    }
    defaults.update(overrides)
    return defaults


def create_service_record_payload(**overrides) -> dict:
    defaults = {
        "vin": DEFAULTS["VIN"],
        "event_date": DEFAULTS["EVENT_DATE"],
        "odometer_reading": 10_000,
        "payload_ref": DEFAULTS["PAYLOAD_REF"],
        "idempotency_key": DEFAULTS["IDEMPOTENCY_KEY"],
    }
    defaults.update(overrides)
    return defaults


def create_correction_payload(**overrides) -> dict:
    defaults = {
        "target_record_id": "",
        "reason": DEFAULTS["REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_shop_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["SHOP_LEGAL_NAME"]}
    defaults.update(overrides)
    return defaults


def create_consumer_payload(**overrides) -> dict:
    defaults = {"email": DEFAULTS["CONSUMER_EMAIL"]}
    defaults.update(overrides)
    return defaults


def create_dealer_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["DEALER_LEGAL_NAME"]}
    defaults.update(overrides)
    return defaults


def create_listing_payload(**overrides) -> dict:
    defaults = {
        "vehicle_id": "",
        "asking_price_cents": DEFAULTS["ASKING_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "listing_id": "",
        "claimant_name": DEFAULTS["CLAIMANT_NAME"],
        "claim_reason": DEFAULTS["CLAIM_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "vehicle_id": "",
        "product": "CONSUMER_SINGLE",
    }
    defaults.update(overrides)
    return defaults

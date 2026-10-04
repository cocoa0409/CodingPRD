"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Co",
    "BILLING_EMAIL": "test@example.com",
    "START_DATE": "2026-09-01T00:00:00Z",
    "TERM_MONTHS": 12,
    "CONTAINER_SIZE": "CY_4",
    "FREQUENCY_PER_WEEK": 2,
    "BASE_RATE_CENTS": 100000,
    "FUEL_FIXED_PCT": 0.10,
    "ENV_PCT": 0.10,
    "ADMIN_PCT": 0.05,
    "CONTAMINATION_FEE_CENTS": 15000,
    "OVERWEIGHT_FEE_CENTS": 20000,
    "EFFECTIVE_FROM": "2026-09-01T00:00:00Z",
    "OCCURRED_DATE": "2026-09-01",
    "PHOTO_URL": "https://img.example/photo.jpg",
    "EVIDENCE_URL": "https://docs.example/offer.pdf",
    "COMPETITOR_MONTHLY_CENTS": 90000,
    "ROLLOFF_CONTAINER": "YD_20",
    "RENTAL_DAYS": 5,
    "DELIVERY_FEE_CENTS": 10000,
    "DAILY_RENTAL_CENTS": 1000,
    "OVERAGE_TON_CENTS": 8000,
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "billing_email": DEFAULTS["BILLING_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "customer_id": overrides.pop("customer_id", ""),
        "start_date": DEFAULTS["START_DATE"],
        "term_months": DEFAULTS["TERM_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_service_line_payload(**overrides) -> dict:
    defaults = {
        "container_size": DEFAULTS["CONTAINER_SIZE"],
        "frequency_per_week": DEFAULTS["FREQUENCY_PER_WEEK"],
        "base_rate_cents": DEFAULTS["BASE_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_pickup_event_payload(**overrides) -> dict:
    defaults = {
        "service_line_id": overrides.pop("service_line_id", ""),
        "occurred_date": DEFAULTS["OCCURRED_DATE"],
        "outcome": "COMPLETED",
    }
    defaults.update(overrides)
    return defaults


def create_fixed_surcharge_config_payload(**overrides) -> dict:
    defaults = {
        "fuel_mode": "FIXED",
        "fuel_fixed_pct": DEFAULTS["FUEL_FIXED_PCT"],
        "environmental_pct": DEFAULTS["ENV_PCT"],
        "admin_pct": DEFAULTS["ADMIN_PCT"],
        "contamination_fee_cents": DEFAULTS["CONTAMINATION_FEE_CENTS"],
        "overweight_fee_cents": DEFAULTS["OVERWEIGHT_FEE_CENTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_notice_payload(**overrides) -> dict:
    defaults = {
        "contract_id": overrides.pop("contract_id", ""),
        "reason": "CPI",
        "pct_increase": 0.05,
        "effective_date": "2026-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_change_request_payload(**overrides) -> dict:
    defaults = {
        "service_line_id": overrides.pop("service_line_id", ""),
        "new_container_size": "CY_6",
        "new_frequency_per_week": 3,
        "effective_date": "2026-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_competing_offer_payload(**overrides) -> dict:
    defaults = {
        "contract_id": overrides.pop("contract_id", ""),
        "competitor_monthly_cents": DEFAULTS["COMPETITOR_MONTHLY_CENTS"],
        "evidence_doc_url": DEFAULTS["EVIDENCE_URL"],
    }
    defaults.update(overrides)
    return defaults


def create_cancellation_request_payload(**overrides) -> dict:
    defaults = {
        "contract_id": overrides.pop("contract_id", ""),
        "requested_end_date": "2027-07-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_credit_payload(**overrides) -> dict:
    defaults = {
        "service_line_id": overrides.pop("service_line_id", ""),
        "pickup_event_id": overrides.pop("pickup_event_id", ""),
    }
    defaults.update(overrides)
    return defaults


def create_rolloff_order_payload(**overrides) -> dict:
    defaults = {
        "customer_id": overrides.pop("customer_id", ""),
        "container_size": DEFAULTS["ROLLOFF_CONTAINER"],
        "delivery_date": "2026-09-05T00:00:00Z",
        "rental_days": DEFAULTS["RENTAL_DAYS"],
        "delivery_fee_cents": DEFAULTS["DELIVERY_FEE_CENTS"],
        "daily_rental_cents": DEFAULTS["DAILY_RENTAL_CENTS"],
        "overage_ton_cents": DEFAULTS["OVERAGE_TON_CENTS"],
    }
    defaults.update(overrides)
    return defaults

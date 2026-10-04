"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BROKER_LEGAL_NAME": "Test Brokerage",
    "CARRIER_LEGAL_NAME": "Test Carriers",
    "ORIGIN": "DAL",
    "DESTINATION": "HOU",
    "EQUIPMENT_TYPE": "DRY_VAN",
    "RATE_OFFER_CENTS": 100000,
    "AGREED_RATE_CENTS": 99000,
    "FUEL_PRICE_CENTS": 400,
    "WINDOW_START": "2026-08-02T00:00:00Z",
    "WINDOW_END": "2026-08-05T00:00:00Z",
}


def create_broker_org_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["BROKER_LEGAL_NAME"], "mc_number": "MC-1"}
    defaults.update(overrides)
    return defaults


def create_carrier_org_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["CARRIER_LEGAL_NAME"], "dot_number": "DOT-1"}
    defaults.update(overrides)
    return defaults


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "code": "PRO",
        "monthly_posting_allowance": 5,
        "overage_tier1_limit": 2,
        "overage_hard_cap": 2,
        "search_daily_limit": 20,
        "analytics_depth": "LANE_LEVEL",
        "requires_data_contribution": False,
    }
    defaults.update(overrides)
    return defaults


def create_load_post_payload(**overrides) -> dict:
    defaults = {
        "origin": DEFAULTS["ORIGIN"],
        "destination": DEFAULTS["DESTINATION"],
        "equipment_type": DEFAULTS["EQUIPMENT_TYPE"],
        "pickup_window_start": DEFAULTS["WINDOW_START"],
        "pickup_window_end": DEFAULTS["WINDOW_END"],
        "rate_offer_cents": DEFAULTS["RATE_OFFER_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_truck_post_payload(**overrides) -> dict:
    defaults = {
        "origin": DEFAULTS["ORIGIN"],
        "destination": DEFAULTS["DESTINATION"],
        "equipment_type": DEFAULTS["EQUIPMENT_TYPE"],
        "available_from": DEFAULTS["WINDOW_START"],
        "available_until": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(load_post_id, truck_post_id, **overrides) -> dict:
    defaults = {
        "load_post_id": load_post_id,
        "truck_post_id": truck_post_id,
        "agreed_rate_cents": DEFAULTS["AGREED_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_transaction_payload(**overrides) -> dict:
    defaults = {
        "origin": DEFAULTS["ORIGIN"],
        "destination": DEFAULTS["DESTINATION"],
        "equipment_type": DEFAULTS["EQUIPMENT_TYPE"],
        "rate_kind": "SPOT",
        "rate_cents": DEFAULTS["RATE_OFFER_CENTS"],
        "fuel_price_cents": DEFAULTS["FUEL_PRICE_CENTS"],
        "transaction_date": "2026-07-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_credit_report_event_payload(broker_org_id, **overrides) -> dict:
    defaults = {
        "broker_org_id": broker_org_id,
        "invoice_amount_cents": 50000,
        "days_to_pay": 45,
    }
    defaults.update(overrides)
    return defaults


def create_authority_verification_payload(org_kind, org_id, **overrides) -> dict:
    """org_kind is 'broker' or 'carrier'; exactly one org FK is set."""
    defaults = {
        "authority_reference": "AUTH-REF-1",
        "insurance_windows": [
            {"effective_from": "2026-01-01T00:00:00Z", "effective_to": "2027-01-01T00:00:00Z"}
        ],
    }
    if org_kind == "broker":
        defaults["broker_org_id"] = org_id
    else:
        defaults["carrier_org_id"] = org_id
    defaults.update(overrides)
    return defaults

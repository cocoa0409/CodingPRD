"""Payload factories — one per entity, input fields only.

Every factory returns the mandatory keys; callers override whatever the
scenario needs. Only fields the PRD declares as client-supplied appear here.
"""
from .constants import TEST_DEFAULTS


def route_payload(**overrides) -> dict:
    """Payload for POST /fare/routes.

    Only the mandatory keys are emitted; every optional risk parameter takes
    its server-side default unless explicitly overridden.
    """
    payload = {
        "origin_airport": "SFO",
        "destination_airport": "JFK",
        "flight_number": "HA101",
        "region": TEST_DEFAULTS["REGION"],
        "base_fare_cents": TEST_DEFAULTS["BASE_FARE_CENTS"],
        "fare_band_cents": [7000, 8000, 9000, 10000, 11000],
        "peak_price_day_index": 4,
        "seats_left": 9,
        "disclosure_headline": TEST_DEFAULTS["DISCLOSURE_HEADLINE"],
    }
    payload.update(overrides)
    return payload


def itinerary_payload(route_id: str, **overrides) -> dict:
    payload = {
        "route_id": route_id,
        "departure_date": TEST_DEFAULTS["DEPARTURE_DATE"],
        "traveler_user_id": "tv-mara",
    }
    payload.update(overrides)
    return payload


def observation_payload(route_id: str, itinerary_id: str, **overrides) -> dict:
    payload = {
        "route_id": route_id,
        "itinerary_id": itinerary_id,
        "fare_cents": 10000,
        "seats_left": 6,
    }
    payload.update(overrides)
    return payload


def demand_curve_payload(route_id: str, **overrides) -> dict:
    payload = {
        "route_id": route_id,
        "price_date": TEST_DEFAULTS["CLOCK_DEFAULT"],
        "each_day_prices_cents": list(TEST_DEFAULTS["CURVE_EACH_DAY_PRICES_CENTS"]),
        "seats_left_at_each_day": list(TEST_DEFAULTS["CURVE_SEATS_LEFT_AT_EACH_DAY"]),
    }
    payload.update(overrides)
    return payload


def freeze_payload(**overrides) -> dict:
    """Payload for opening a freeze against an itinerary.

    `expected_itinerary_version` must be supplied by the caller with the
    itinerary's current version.
    """
    payload = {
        "deposit_cents": TEST_DEFAULTS["DEPOSIT_CENTS"],
        "disclosure_version": 1,
        "disclosure_acknowledged": True,
    }
    payload.update(overrides)
    return payload


def protection_payload(itinerary_id: str, **overrides) -> dict:
    payload = {
        "itinerary_id": itinerary_id,
        "product_type": "CANCELLATION",
        "cancellation_disruption_probability": 0.25,
        "disclosure_version": 1,
        "disclosure_acknowledged": True,
    }
    payload.update(overrides)
    return payload


def claim_payload(freeze_id: str, **overrides) -> dict:
    payload = {"freeze_id": freeze_id, "market_price_cents": 16500}
    payload.update(overrides)
    return payload


def payment_payload(itinerary_id: str, **overrides) -> dict:
    payload = {
        "itinerary_id": itinerary_id,
        "payment_kind": "DEPOSIT",
        "amount_cents": 250,
        "capture": True,
    }
    payload.update(overrides)
    return payload


def hedging_position_payload(route_id: str, **overrides) -> dict:
    payload = {
        "route_id": route_id,
        "coverage_date": "2026-09-15T00:00:00Z",
        "hedge_price_cents": 9000,
        "contract_quantity_cents": 500000,
    }
    payload.update(overrides)
    return payload


def risk_pool_payload(**overrides) -> dict:
    payload = {"region": TEST_DEFAULTS["REGION"], "pool_code": "WEST-RP-1"}
    payload.update(overrides)
    return payload


def change_event_payload(protection_id: str, **overrides) -> dict:
    payload = {
        "protection_id": protection_id,
        "new_departure_date": "2026-12-05T00:00:00Z",
        "gap_direction": "ORIGIN_DIRECTION",
    }
    payload.update(overrides)
    return payload


def rebooking_option_payload(change_event_id: str, **overrides) -> dict:
    payload = {
        "change_event_id": change_event_id,
        "departure_date": "2026-12-05T00:00:00Z",
        "option_fare_cents": 12300,
    }
    payload.update(overrides)
    return payload


def destination_option_payload(itinerary_id: str, **overrides) -> dict:
    payload = {
        "itinerary_id": itinerary_id,
        "departure_date": "2026-12-05T00:00:00Z",
        "option_fare_cents": 12300,
        "direction": "ORIGIN_DIRECTION",
    }
    payload.update(overrides)
    return payload
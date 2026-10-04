"""Payload factories — one per entity, input fields only."""
from typing import Any, Dict, Optional

# Canonical pricing policy used across scenarios (P1): three distance bands,
# two value tiers, two peak windows, 25% peak uplift, 50% surge pass-through.
P1_DISTANCE_BANDS = [
    {"max_m": 3000, "base_cents": 500, "per_100m_cents": 0},
    {"max_m": 8000, "base_cents": 500, "per_100m_cents": 25},
    {"max_m": 15000, "base_cents": 1750, "per_100m_cents": 40},
]
P1_VALUE_TIERS = [
    {"min_order_value_cents": 10000, "surcharge_cents": 200},
    {"min_order_value_cents": 50000, "surcharge_cents": 500},
]
P1_PEAK_WINDOWS = [
    {"start_local_hhmm": "11:00", "end_local_hhmm": "14:00"},
    {"start_local_hhmm": "17:00", "end_local_hhmm": "21:00"},
]
P1_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
P1_EFFECTIVE_UNTIL = "2027-01-01T00:00:00Z"


def create_merchant_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "name": "Test Merchant",
        "billing_balance_cents": 100000,
        "default_refund_split_merchant_pct": 50,
        "late_credit_enabled": True,
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "name": "Test Store",
        "address_text": "1 Origin Way",
        "lat": 0.0,
        "lng": 0.0,
        "delivery_radius_m": 20000,
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return defaults


def create_pricing_policy_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "distance_bands": [dict(b) for b in P1_DISTANCE_BANDS],
        "value_tiers": [dict(t) for t in P1_VALUE_TIERS],
        "peak_windows": [dict(w) for w in P1_PEAK_WINDOWS],
        "peak_uplift_pct": 0.25,
        "surge_passthrough_pct": 0.5,
        "effective_from": P1_EFFECTIVE_FROM,
        "effective_until": P1_EFFECTIVE_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_serviceability_override_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "address_pattern": "Dest Rd",
        "effect": "DENY",
    }
    defaults.update(overrides)
    return defaults


def check_serviceability_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "dropoff_lat": 0.01,
        "dropoff_lng": 0.0,
        "address_text": "10 Dest Rd",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(store_id: str, **overrides) -> dict:
    defaults: Dict[str, Any] = {
        "store_id": store_id,
        "dropoff_lat": 0.02,
        "dropoff_lng": 0.0,
        "address_text": "10 Dest Rd",
        "order_value_cents": 5000,
        "pickup_ready_at": "2026-09-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(quote_id: str, idempotency_key: str, **overrides) -> dict:
    defaults: Dict[str, Any] = {
        "quote_id": quote_id,
        "customer_reference": f"REF-{idempotency_key}",
        "idempotency_key": idempotency_key,
    }
    defaults.update(overrides)
    return defaults


def accept_order_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {"promised_at": "2026-09-01T02:00:00Z"}
    defaults.update(overrides)
    return defaults


def report_undeliverable_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {"reason_code": "CUSTOMER_UNAVAILABLE"}
    defaults.update(overrides)
    return defaults


def create_disposition_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {"resolution": "RETURN_TO_STORE"}
    defaults.update(overrides)
    return defaults


def complete_disposition_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {"outcome": "RETURNED"}
    defaults.update(overrides)
    return defaults


def create_tracking_event_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "event_type": "NOTE",
        "note": "note",
        "visibility": "MERCHANT_VISIBLE",
    }
    defaults.update(overrides)
    return defaults


def create_courier_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {"name": "Test Courier", "max_active_deliveries": 4}
    defaults.update(overrides)
    return defaults


def create_batch_payload(
    store_id: str,
    courier_id: str,
    order_ids: list,
    expected_courier_version: int,
    **overrides,
) -> dict:
    defaults: Dict[str, Any] = {
        "store_id": store_id,
        "courier_id": courier_id,
        "order_ids": list(order_ids),
        "dispatch_window_start": "2026-09-01T00:30:00Z",
        "dispatch_window_end": "2026-09-01T01:30:00Z",
        "expected_courier_version": expected_courier_version,
    }
    defaults.update(overrides)
    return defaults


def create_refund_claim_payload(delivery_order_id: str, **overrides) -> dict:
    defaults: Dict[str, Any] = {
        "delivery_order_id": delivery_order_id,
        "fault_code": "COURIER_DELAY",
        "claimed_amount_cents": 200,
    }
    defaults.update(overrides)
    return defaults


def decide_claim_payload(decision: str = "APPROVE") -> dict:
    return {"decision": decision}


def create_sla_report_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults

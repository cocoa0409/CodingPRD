"""Payload factories — one per create endpoint, input fields only."""

from .constants import (
    DEFAULT_BASE_DEMAND_UNITS,
    DEFAULT_BUSINESS_DATE,
    DEFAULT_LABEL,
    DEFAULT_LIST_PRICE_CENTS,
    DEFAULT_PRODUCT_NAME,
    DEFAULT_RACK_CAPACITY,
    DEFAULT_SKU,
    DEFAULT_WINDOW_END_MINUTE,
    DEFAULT_WINDOW_START_MINUTE,
)
from .types import JsonObject


def store_day_payload(**overrides) -> JsonObject:
    defaults = {"business_date": DEFAULT_BUSINESS_DATE}
    defaults.update(overrides)
    return defaults


def daypart_payload(**overrides) -> JsonObject:
    defaults = {
        "label": DEFAULT_LABEL,
        "window_start_minute": DEFAULT_WINDOW_START_MINUTE,
        "window_end_minute": DEFAULT_WINDOW_END_MINUTE,
        "rack_capacity": DEFAULT_RACK_CAPACITY,
        "base_demand_units": DEFAULT_BASE_DEMAND_UNITS,
    }
    defaults.update(overrides)
    return defaults


def demand_event_payload(**overrides) -> JsonObject:
    defaults = {
        "name": "Game Night",
        "window_start_at": "2026-09-10T16:00:00Z",
        "window_end_at": "2026-09-10T19:00:00Z",
        "demand_multiplier": 2.0,
    }
    defaults.update(overrides)
    return defaults


def batch_payload(size_units: int = 10, **overrides) -> JsonObject:
    defaults = {"size_units": size_units}
    defaults.update(overrides)
    return defaults


def product_payload(**overrides) -> JsonObject:
    defaults = {
        "sku": DEFAULT_SKU,
        "name": DEFAULT_PRODUCT_NAME,
        "list_price_cents": DEFAULT_LIST_PRICE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def production_run_payload(product_id, dough_batch_id, cheese_batch_id, quantity, **overrides) -> JsonObject:
    defaults = {
        "product_id": product_id,
        "dough_batch_id": dough_batch_id,
        "cheese_batch_id": cheese_batch_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id, quantity=1, customized=False) -> JsonObject:
    return {"product_id": product_id, "quantity": quantity, "customized": customized}


def order_payload(store_day_id, daypart_id, customer_id, kind, lines) -> JsonObject:
    return {
        "store_day_id": store_day_id,
        "daypart_id": daypart_id,
        "customer_id": customer_id,
        "kind": kind,
        "lines": lines,
    }


def locker_slot_payload(slot_number: int = 1, **overrides) -> JsonObject:
    defaults = {"slot_number": slot_number}
    defaults.update(overrides)
    return defaults


def crew_shift_payload(**overrides) -> JsonObject:
    defaults = {
        "crew_member_id": "crew-1",
        "station": "OVEN",
        "start_minute": 600,
        "end_minute": 780,
    }
    defaults.update(overrides)
    return defaults


def discard_payload(reason="DAMAGED", **overrides) -> JsonObject:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


__all__ = [
    "store_day_payload",
    "daypart_payload",
    "demand_event_payload",
    "batch_payload",
    "product_payload",
    "production_run_payload",
    "order_line",
    "order_payload",
    "locker_slot_payload",
    "crew_shift_payload",
    "discard_payload",
]

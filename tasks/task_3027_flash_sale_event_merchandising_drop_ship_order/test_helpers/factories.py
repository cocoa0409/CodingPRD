"""Payload factories — one per entity, caller-supplied fields only.

Derived fields are never sent: the platform computes them.
"""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "LEGAL_NAME": TEST_DEFAULTS["LEGAL_NAME"],
    "SHOP_NAME": TEST_DEFAULTS["SHOP_NAME"],
    "EVENT_TITLE": TEST_DEFAULTS["EVENT_TITLE"],
    "UNIT_PRICE_CENTS": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    "UNIT_COST_CENTS": TEST_DEFAULTS["UNIT_COST_CENTS"],
    "ALLOCATION_UNITS": TEST_DEFAULTS["ALLOCATION_UNITS"],
    "SHIP_TIME_QUOTE_DAYS": TEST_DEFAULTS["SHIP_TIME_QUOTE_DAYS"],
    "WINDOW_START": "2026-09-01T00:00:00Z",
    "WINDOW_END": "2026-09-02T00:00:00Z",
}


def create_vendor_payload(**overrides) -> dict:
    payload = {"legal_name": DEFAULTS["LEGAL_NAME"]}
    payload.update(overrides)
    return payload


def create_shop_payload(vendor_id: str = None, **overrides) -> dict:
    payload = {"vendor_id": vendor_id, "shop_name": DEFAULTS["SHOP_NAME"]}
    payload.update(overrides)
    return payload


def create_event_payload(shop_id: str = None, **overrides) -> dict:
    payload = {
        "shop_id": shop_id,
        "event_title": DEFAULTS["EVENT_TITLE"],
        "starts_at": DEFAULTS["WINDOW_START"],
        "ends_at": DEFAULTS["WINDOW_END"],
        "ship_time_quote_days": DEFAULTS["SHIP_TIME_QUOTE_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_listing_payload(event_id: str = None, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "vendor_sku": "NW-SKU-1",
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "vendor_unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "allocation_units": DEFAULTS["ALLOCATION_UNITS"],
        "reveal_at": DEFAULTS["WINDOW_START"],
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {"email": "buyer@example.com", "full_name": "Casey Buyer"}
    payload.update(overrides)
    return payload


def create_order_payload(customer_id: str = None, **overrides) -> dict:
    payload = {"customer_id": customer_id}
    payload.update(overrides)
    return payload


def create_line_payload(listing_id: str = None, quantity: int = 1, **overrides) -> dict:
    payload = {"listing_id": listing_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_purchase_order_payload(vendor_id: str = None, event_id: str = None,
                                  expected_vendor_version=None, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "event_id": event_id,
        "expected_vendor_version": expected_vendor_version,
    }
    payload.update(overrides)
    return payload


def create_poline_payload(listing_id: str = None, quantity_ordered: int = 1,
                          **overrides) -> dict:
    payload = {"listing_id": listing_id, "quantity_ordered": quantity_ordered}
    payload.update(overrides)
    return payload


def create_shipment_payload(purchase_order_id: str = None, quantity_shipped: int = 1,
                            allocations=None, **overrides) -> dict:
    payload = {
        "purchase_order_id": purchase_order_id,
        "quantity_shipped": quantity_shipped,
        "carrier_tracking_code": "TRK-1",
        "shipped_at": "2026-09-01T06:00:00Z",
        "allocations": allocations if allocations is not None else [],
    }
    payload.update(overrides)
    return payload


def create_return_payload(confirmation_id: str = None, reason_code: str = "DAMAGED",
                          expected_confirmation_version=None, **overrides) -> dict:
    payload = {
        "confirmation_id": confirmation_id,
        "reason_code": reason_code,
        "expected_confirmation_version": expected_confirmation_version,
    }
    payload.update(overrides)
    return payload


def create_credit_payload(amount_cents: int = 1000, idempotency_key: str = "credit-1",
                          **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "idempotency_key": idempotency_key,
        "reason_code": "GOODWILL",
    }
    payload.update(overrides)
    return payload


def create_payout_payload(amount_cents: int = 1000, idempotency_key: str = "payout-1",
                          **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "idempotency_key": idempotency_key}
    payload.update(overrides)
    return payload


def create_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
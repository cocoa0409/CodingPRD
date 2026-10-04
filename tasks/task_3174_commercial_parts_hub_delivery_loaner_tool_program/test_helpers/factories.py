"""Payload factories -- one per entity, only the fields a client supplies."""

DEFAULTS = {
    "SHOP_NAME": "Test Repair Shop",
    "BILLING_ADDRESS": "1 Test St",
    "VIN": "1HGCM82633A004352",
    "STOREFRONT_RADIUS_MILES": 5.0,
    "PROMISE_TIME_MINUTES": 240,
    "DAILY_CAPACITY_UNITS": 500,
    "CREDIT_LIMIT_CENTS": 5_000_000,
    "CREDIT_TERMS_DAYS": 30,
    "LIST_PRICE_CENTS": 1673,
    "ON_HAND_UNITS": 20,
}


# ── Commercial account ────────────────────────────────────────────────────
def create_account_payload(home_store_id, **overrides) -> dict:
    payload = {
        "shop_name": DEFAULTS["SHOP_NAME"],
        "tax_id": "TX-TEST-0001",
        "billing_address": DEFAULTS["BILLING_ADDRESS"],
        "home_store_id": home_store_id,
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "credit_terms_days": DEFAULTS["CREDIT_TERMS_DAYS"],
        "delivery_service_level": "SHOP_DELIVERY",
    }
    payload.update(overrides)
    return payload


# ── Store ─────────────────────────────────────────────────────────────────
def create_store_payload(**overrides) -> dict:
    payload = {
        "store_code": "S-TEST",
        "name": "Test Store",
        "store_type": "SATELLITE",
        "delivery_radius_miles": DEFAULTS["STOREFRONT_RADIUS_MILES"],
        "cutoff_hour_local": 15,
        "cutoff_buffer_minutes": 30,
        "promise_time_minutes": DEFAULTS["PROMISE_TIME_MINUTES"],
        "daily_capacity_units": DEFAULTS["DAILY_CAPACITY_UNITS"],
    }
    payload.update(overrides)
    return payload


# ── Part ──────────────────────────────────────────────────────────────────
def create_part_payload(**overrides) -> dict:
    payload = {
        "sku": "TEST-1",
        "description": "Test Part",
        "line_code": "IGN",
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
        "core_charge_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_part_fitment_payload(**overrides) -> dict:
    payload = {
        "year_from": 2015,
        "year_to": 2024,
        "make": "Kestrel",
        "model": "Vireo",
        "engine_code": "2.4L-I4",
        "drive_type": "FWD",
    }
    payload.update(overrides)
    return payload


def create_part_interchange_payload(**overrides) -> dict:
    payload = {
        "interchange_sku": "ALT-1",
        "interchange_brand": "Alternate",
    }
    payload.update(overrides)
    return payload


# ── Vehicle ───────────────────────────────────────────────────────────────
def create_vehicle_payload(**overrides) -> dict:
    payload = {
        "vin": DEFAULTS["VIN"],
        "year": 2019,
        "make": "Kestrel",
        "model": "Vireo",
        "engine_code": "2.4L-I4",
        "drive_type": "FWD",
    }
    payload.update(overrides)
    return payload


# ── Inventory line ────────────────────────────────────────────────────────
def create_inventory_item_payload(store_id, part_id, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "part_id": part_id,
        "on_hand_units": DEFAULTS["ON_HAND_UNITS"],
    }
    payload.update(overrides)
    return payload


# ── Sales rep and coverage ────────────────────────────────────────────────
def create_sales_rep_payload(home_store_id, **overrides) -> dict:
    payload = {
        "email": "rep@parts.example",
        "full_name": "Test Rep",
        "district_code": "D-01",
        "home_store_id": home_store_id,
    }
    payload.update(overrides)
    return payload


def create_rep_coverage_payload(rep_id, account_id, **overrides) -> dict:
    payload = {
        "rep_id": rep_id,
        "account_id": account_id,
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2026-10-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ── Part order ────────────────────────────────────────────────────────────
def create_order_payload(account_id, line_items, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload


def line_item(part_id, quantity=1, **overrides) -> dict:
    item = {"part_id": part_id, "quantity": quantity}
    item.update(overrides)
    return item


# ── Tool catalogue, fitment and loan ──────────────────────────────────────
def create_tool_catalog_payload(**overrides) -> dict:
    payload = {
        "tool_sku": "TOOL-TEST",
        "tool_name": "Test Tool",
        "deposit_amount_cents": 3000,
        "replacement_part_id": None,
        "replacement_unit_cost_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_tool_fitment_payload(part_id, **overrides) -> dict:
    payload = {
        "part_id": part_id,
        "placement": "FRONT",
        "depth_index": 1,
    }
    payload.update(overrides)
    return payload


def create_loan_payload(account_id, tool_catalog_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "tool_catalog_id": tool_catalog_id,
        "deposit_amount_cents": 3000,
    }
    payload.update(overrides)
    return payload


# ── Core return and warranty ──────────────────────────────────────────────
def create_core_return_payload(order_id, line_items, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload


def create_warranty_payload(account_id, part_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "part_id": part_id,
        "purchase_order_id": None,
        "purchased_at": "2026-08-01T00:00:00Z",
        "warranty_expires_at": "2027-08-01T00:00:00Z",
        "claim_reference": None,
    }
    payload.update(overrides)
    return payload


# ── Service route and stop ────────────────────────────────────────────────
def create_route_payload(**overrides) -> dict:
    payload = {
        "route_code": "R-TEST",
        "service_date": "2026-09-02T00:00:00Z",
        "driver_id": "drv-test",
        "driver_type": "AFFILIATE",
        "departure_at": "2026-09-02T13:00:00Z",
        "shift_end_at": "2026-09-02T21:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_route_stop_payload(account_id, expected_route_version, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "stop_kind": "CUSTOMER",
        "delivery_window_start": "2026-09-02T14:00:00Z",
        "delivery_window_end": "2026-09-02T15:00:00Z",
        "travel_minutes_from_previous": 20,
        "drop_minutes": 10,
        "order_ids": [],
        "expected_route_version": expected_route_version,
    }
    payload.update(overrides)
    return payload
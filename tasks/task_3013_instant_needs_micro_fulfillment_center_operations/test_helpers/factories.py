"""Payload factories — one per entity, input fields only.

Every factory accepts ``**overrides`` so tests control exactly the values a
claim depends on while getting PRD-consistent defaults for everything else.
"""

from .constants import ADULT_BIRTHDATE, STANDARD_FEE_SCHEDULE

_counter = {"n": 0}


def _unique(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:04d}"


def create_site_payload(**overrides) -> dict:
    defaults = {
        "code": _unique("SITE"),
        "name": "Downtown MFC",
        "delivery_radius_miles": 5.0,
        "fee_schedule": dict(STANDARD_FEE_SCHEDULE),
        "fee_waiver_threshold_cents": 3000,
        "batch_max_lines": 2,
        "batch_max_items": 20,
        "expiry_horizon_days": 2,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _unique("SKU"),
        "name": "Chips",
        "price_cents": 500,
        "product_class": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_inventory_balance_payload(site_id: str, product_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id, "product_id": product_id, "min_par_level": 0}
    defaults.update(overrides)
    return defaults


def create_receipt_adjustment_payload(qty: int, **overrides) -> dict:
    defaults = {"kind": "RECEIPT", "qty": qty, "reason": "opening"}
    defaults.update(overrides)
    return defaults


def create_shrink_dispose_payload(qty: int, lot_id: str, **overrides) -> dict:
    defaults = {"kind": "SHRINK_DISPOSE", "qty": qty, "lot_id": lot_id, "reason": "write-off"}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": f"{_unique('cust')}@example.com",
        "full_name": "Ada Adult",
        "date_of_birth": ADULT_BIRTHDATE,
    }
    defaults.update(overrides)
    return defaults


def create_wallet_adjustment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": "operator adjustment"}
    defaults.update(overrides)
    return defaults


def create_membership_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "tier": "FAM", "monthly_fee_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_replenish_order_payload(site_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "reference": _unique("PO"),
        "lines": lines,
        "expected_at": "2026-09-11T08:00:00Z",
        "idempotency_key": _unique("po-key"),
    }
    defaults.update(overrides)
    return defaults


def replenish_line(product_id: str, qty: int, unit_cost_cents: int = 200) -> dict:
    return {"product_id": product_id, "qty": qty, "unit_cost_cents": unit_cost_cents}


def create_order_payload(customer_id: str, site_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "site_id": site_id,
        "lines": lines,
        "delivery_distance_miles": 1.0,
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id: str, qty: int) -> dict:
    return {"product_id": product_id, "qty": qty}


def create_picker_payload(site_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id, "name": _unique("Picker")}
    defaults.update(overrides)
    return defaults


def create_driver_payload(site_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id, "name": _unique("Driver"), "max_run_orders": 4}
    defaults.update(overrides)
    return defaults


def create_pick_batch_payload(site_id: str, picker_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id, "picker_id": picker_id}
    defaults.update(overrides)
    return defaults


def create_delivery_bag_payload(order_id: str, **overrides) -> dict:
    defaults = {"order_id": order_id}
    defaults.update(overrides)
    return defaults


def handoff_scan_payload(scanned_birthdate: str, scanned_id_last4: str, **overrides) -> dict:
    defaults = {
        "scanned_birthdate": scanned_birthdate,
        "scanned_id_last4": scanned_id_last4,
    }
    defaults.update(overrides)
    return defaults

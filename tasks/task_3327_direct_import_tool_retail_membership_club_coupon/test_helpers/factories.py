"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import WINDOW_END_DEFAULT, WINDOW_START_DEFAULT

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_item_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": "Test Item",
        "brand_tier": "VALUE",
        "origin_country": "CN",
        "unit_retail_cents": 1000,
        "member_price_cents": 900,
        "floor_margin_pct": 0.05,
        "lead_time_days": 30,
        "unit_weight_kg": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(item_id: str, quantity: int = 10,
                                  unit_cost_cents: int = 500, **overrides) -> dict:
    defaults = {
        "po_number": _uniq("PO"),
        "lines": [{"item_id": item_id, "quantity": quantity,
                   "unit_cost_cents": unit_cost_cents}],
        "estimated_duty_cents": 0,
        "estimated_freight_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(po_id: str, item_id: str, quantity: int = 10,
                             **overrides) -> dict:
    defaults = {
        "po_id": po_id,
        "container_number": _uniq("CNT"),
        "lines": [{"item_id": item_id, "quantity": quantity}],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(assortment_item_ids=None, **overrides) -> dict:
    defaults = {
        "store_code": _uniq("ST"),
        "name": "Test Store",
        "format": "STANDARD",
        "market_tier": "PRIMARY",
        "receiving_capacity_units": 500,
        "assortment_item_ids": list(assortment_item_ids or []),
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(container_id: str, item_id: str, quantity: int = 1,
                              **overrides) -> dict:
    defaults = {"container_id": container_id, "item_id": item_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"email": f"{_uniq('cust')}@example.com", "full_name": "Test Customer"}
    defaults.update(overrides)
    return defaults


def create_membership_payload(tier: str = "CLUB", **overrides) -> dict:
    defaults = {"tier": tier}
    defaults.update(overrides)
    return defaults


def create_coupon_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("CPN"),
        "channel": "APP",
        "audience": "ALL",
        "discount_type": "PERCENT_OFF_BASKET",
        "discount_value": 10,
        "per_customer_limit": 9,
        "budget_cents": 100000,
        "window_start": WINDOW_START_DEFAULT,
        "window_end": WINDOW_END_DEFAULT,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(store_id: str, customer_id: str, **overrides) -> dict:
    defaults = {"store_id": store_id, "customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_sale_line_payload(item_id: str, quantity: int = 1, **overrides) -> dict:
    defaults = {"item_id": item_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_warranty_line_payload(item_id: str, covered_item_id: str,
                                 warranty_price_cents: int = 500,
                                 quantity: int = 1, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "quantity": quantity,
        "is_warranty_line": True,
        "covered_item_id": covered_item_id,
        "warranty_price_cents": warranty_price_cents,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(sale_line_id: str, claim_amount_cents: int = 500,
                                  **overrides) -> dict:
    defaults = {
        "sale_line_id": sale_line_id,
        "reason": "defect",
        "claim_amount_cents": claim_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(item_id: str, severity: str = "NOTICE", **overrides) -> dict:
    defaults = {"item_id": item_id, "severity": severity, "reason": "safety concern"}
    defaults.update(overrides)
    return defaults

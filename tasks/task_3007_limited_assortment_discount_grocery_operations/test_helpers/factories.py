"""Payload factories — one per creatable resource, input fields only.

Each factory supplies a valid-by-default payload; tests override the fields
they are exercising. Unique codes are minted per call so repeated creations
inside one test never collide on uniqueness constraints.
"""

import itertools
from typing import Any, Dict, Optional

_counter = itertools.count(1)


def _suffix() -> int:
    return next(_counter)


def category_payload(code: Optional[str] = None, name: Optional[str] = None, sku_cap: Optional[int] = None, **overrides: Any) -> Dict[str, Any]:
    """Payload for POST /v1/categories. sku_cap omitted -> server default 2."""
    n = _suffix()
    payload: Dict[str, Any] = {
        "code": code or f"CAT-{n}",
        "name": name or f"Category {n}",
    }
    if sku_cap is not None:
        payload["sku_cap"] = sku_cap
    payload.update(overrides)
    return payload


def supplier_payload(name: Optional[str] = None, contact_email: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    n = _suffix()
    payload: Dict[str, Any] = {
        "name": name or f"Supplier {n}",
        "contact_email": contact_email or f"supplier{n}@example.com",
    }
    payload.update(overrides)
    return payload


def product_payload(
    category_id: str,
    sku_code: Optional[str] = None,
    name: Optional[str] = None,
    kind: str = "CORE",
    shelf_ready_packaging: bool = True,
    barcode_count: int = 2,
    unit_cost_cents: int = 100,
    price_cents: int = 349,
    **overrides: Any,
) -> Dict[str, Any]:
    n = _suffix()
    payload: Dict[str, Any] = {
        "category_id": category_id,
        "sku_code": sku_code or f"SKU-{n}",
        "name": name or f"Product {n}",
        "kind": kind,
        "shelf_ready_packaging": shelf_ready_packaging,
        "barcode_count": barcode_count,
        "unit_cost_cents": unit_cost_cents,
        "price_cents": price_cents,
    }
    payload.update(overrides)
    return payload


def tender_payload(product_id: str, bid_ceiling_cents: int = 1000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "bid_ceiling_cents": bid_ceiling_cents,
    }
    payload.update(overrides)
    return payload


def bid_payload(supplier_id: str, unit_cost_cents: int = 700, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supplier_id": supplier_id,
        "unit_cost_cents": unit_cost_cents,
    }
    payload.update(overrides)
    return payload


def panel_payload(sample_code: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    n = _suffix()
    payload: Dict[str, Any] = {"sample_code": sample_code or f"BLIND-{n}"}
    payload.update(overrides)
    return payload


def panel_score_payload(score: int = 80, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"score": score}
    payload.update(overrides)
    return payload


def store_payload(
    code: Optional[str] = None,
    name: Optional[str] = None,
    tier: str = "STANDARD",
    weekly_labor_budget_cents: int = 100000,
    **overrides: Any,
) -> Dict[str, Any]:
    n = _suffix()
    payload: Dict[str, Any] = {
        "code": code or f"S{n}",
        "name": name or f"Store {n}",
        "tier": tier,
        "weekly_labor_budget_cents": weekly_labor_budget_cents,
    }
    payload.update(overrides)
    return payload


def employee_payload(name: Optional[str] = None, role: str = "CASHIER", **overrides: Any) -> Dict[str, Any]:
    n = _suffix()
    payload: Dict[str, Any] = {"name": name or f"Employee {n}", "role": role}
    payload.update(overrides)
    return payload


def finds_buy_payload(
    product_id: str,
    week_start_date: str = "2026-09-07",
    week_end_date: str = "2026-09-13",
    total_quantity: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "week_start_date": week_start_date,
        "week_end_date": week_end_date,
        "total_quantity": total_quantity,
    }
    payload.update(overrides)
    return payload


def cart_coin_event_payload(event_type: str = "INSERT", coin_count: int = 1, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type, "coin_count": coin_count}
    payload.update(overrides)
    return payload


def register_shift_payload(cashier_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cashier_id": cashier_id}
    payload.update(overrides)
    return payload


def scan_payload(items_count: int = 100, voids_count: Optional[int] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"items_count": items_count}
    if voids_count is not None:
        payload["voids_count"] = voids_count
    payload.update(overrides)
    return payload


def labor_window_payload(
    aisle_zone: str = "Z1",
    role: str = "STOCKER",
    starts_at: str = "2026-09-07T06:00:00Z",
    ends_at: str = "2026-09-07T08:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "aisle_zone": aisle_zone,
        "role": role,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def claim_payload(
    product_id: str,
    store_id: str,
    quantity: int = 1,
    unit_price_cents: int = 349,
    purchase_date: str = "2026-08-20",
    reason: str = "OTHER",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "store_id": store_id,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "purchase_date": purchase_date,
        "reason": reason,
    }
    payload.update(overrides)
    return payload

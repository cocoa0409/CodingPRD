"""Request-payload factories.

Every monetary amount is emitted as a JSON integer of cents, never a string.
Weights, distances and markup fractions are emitted as JSON numbers. Each
factory supplies the minimum valid body and lets callers override or add any
field via keyword arguments, so a test can build an invalid body by passing an
out-of-range value explicitly.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_0800,
    PRICING_UNIT_EACH,
    PRICING_UNIT_PER_LB,
    TIER_PROBATION,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay overrides on base; a None override deletes the key."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None and key in merged:
            del merged[key]
        else:
            merged[key] = value
    return merged


def _prune(body: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is None.

    Applied to the base body of every factory that carries PRD-defaulted
    optional fields, so a caller passing ``field=None`` omits that field from
    the request entirely and exercises the server-side default rather than
    sending an explicit JSON null.
    """
    return {key: value for key, value in body.items() if value is not None}


def _int(value: Any) -> Any:
    """int() that passes None through, so _prune can still drop the key."""
    return None if value is None else int(value)


# --------------------------------------------------------------------------
# Retailer / catalog
# --------------------------------------------------------------------------
#: PRD 3.1 makes `store_code` unique across all retailer rows, so the default
#: cannot be a fixed literal: a test that builds its world twice inside one
#: server lifetime would have its second retailer refused with
#: ERR_INVALID_REQUEST. Each defaulted body therefore gets its own code.
_STORE_CODE_SEQ = itertools.count(1)


def retailer_payload(
    legal_name: str = "Bay Fresh Market LLC",
    store_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if store_code is None:
        store_code = "BFM-%04d" % next(_STORE_CODE_SEQ)
    return _merge(
        _prune({"legal_name": legal_name, "store_code": store_code}), overrides
    )


def catalog_item_each_payload(
    retailer_id: str,
    sku: str = "SKU-EACH-EBT",
    name: str = "Canned Beans",
    in_store_price_cents: int = 400,
    is_ebt_eligible: bool = True,
    unit_weight_lb: float = 1.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        _prune(
            {
                "retailer_id": retailer_id,
                "sku": sku,
                "name": name,
                "pricing_unit": PRICING_UNIT_EACH,
                "in_store_price_cents": _int(in_store_price_cents),
                "is_ebt_eligible": is_ebt_eligible,
                "unit_weight_lb": unit_weight_lb,
            }
        ),
        overrides,
    )


def catalog_item_per_lb_payload(
    retailer_id: str,
    sku: str = "SKU-LB-EBT",
    name: str = "Ground Coffee Bulk",
    in_store_price_cents: int = 599,
    is_ebt_eligible: bool = True,
    estimated_weight_lb: float = 2.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        _prune(
            {
                "retailer_id": retailer_id,
                "sku": sku,
                "name": name,
                "pricing_unit": PRICING_UNIT_PER_LB,
                "in_store_price_cents": _int(in_store_price_cents),
                "is_ebt_eligible": is_ebt_eligible,
                "estimated_weight_lb": estimated_weight_lb,
            }
        ),
        overrides,
    )


def parity_policy_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# --------------------------------------------------------------------------
# Customer / credits
# --------------------------------------------------------------------------
def customer_payload(
    display_name: str = "Dana Ortiz",
    card_last4: str = "4242",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        _prune({"display_name": display_name, "card_last4": card_last4}), overrides
    )


def credit_entry_payload(
    amount_cents: int,
    reason_code: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"amount_cents": int(amount_cents), "reason_code": reason_code}, overrides
    )


# --------------------------------------------------------------------------
# Shopper / ratings
# --------------------------------------------------------------------------
def shopper_payload(
    display_name: str = "Sam Reyes",
    service_area_code: str = "SF-01",
    vehicle_capacity_units: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        _prune(
            {
                "display_name": display_name,
                "service_area_code": service_area_code,
                "vehicle_capacity_units": _int(vehicle_capacity_units),
            }
        ),
        overrides,
    )


def rating_payload(stars: int, order_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"stars": int(stars)}
    if order_id is not None:
        body["order_id"] = order_id
    return _merge(body, overrides)


def ratings_backfill_payload(
    shopper_id: str, stars_sequence: List[int], **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"shopper_id": shopper_id, "stars_sequence": list(stars_sequence)}, overrides
    )


def shopper_history_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# --------------------------------------------------------------------------
# Orders / lines
# --------------------------------------------------------------------------
def order_payload(
    customer_id: str,
    retailer_id: str,
    delivery_distance_mi: float = 3.0,
    delivery_deadline: str = "2026-08-01T11:00:00Z",
    ebt_requested: bool = False,
    tip_amount_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        _prune(
            {
                "customer_id": customer_id,
                "retailer_id": retailer_id,
                "delivery_distance_mi": delivery_distance_mi,
                "delivery_deadline": delivery_deadline,
                "ebt_requested": ebt_requested,
                "tip_amount_cents": _int(tip_amount_cents),
            }
        ),
        overrides,
    )


def line_each_payload(
    catalog_item_id: str, requested_qty: int = 1, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        _prune(
            {"catalog_item_id": catalog_item_id, "requested_qty": _int(requested_qty)}
        ),
        overrides,
    )


def line_per_lb_payload(
    catalog_item_id: str, requested_weight_lb: float = 2.0, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        _prune(
            {
                "catalog_item_id": catalog_item_id,
                "requested_weight_lb": requested_weight_lb,
            }
        ),
        overrides,
    )


def tip_adjustment_payload(
    tip_amount_cents: int, expected_order_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "tip_amount_cents": int(tip_amount_cents),
            "expected_order_version": int(expected_order_version),
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Batches
# --------------------------------------------------------------------------
def batch_payload(
    service_area_code: str = "SF-01",
    shop_window_start: str = CLOCK_0800,
    shop_window_end: str = "2026-08-01T11:00:00Z",
    tier_access_floor: Optional[str] = TIER_PROBATION,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "service_area_code": service_area_code,
        "shop_window_start": shop_window_start,
        "shop_window_end": shop_window_end,
    }
    if tier_access_floor is not None:
        body["tier_access_floor"] = tier_access_floor
    return _merge(body, overrides)


def batch_order_payload(
    order_id: str, expected_batch_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "order_id": order_id,
            "expected_batch_version": int(expected_batch_version),
        },
        overrides,
    )


def abandon_payload(reason_note: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if reason_note is not None:
        body["reason_note"] = reason_note
    return _merge(body, overrides)


# --------------------------------------------------------------------------
# Picks / replacements
# --------------------------------------------------------------------------
def pick_each_payload(picked_qty: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"picked_qty": int(picked_qty)}, overrides)


def pick_weighted_payload(final_weight_lb: float, **overrides: Any) -> Dict[str, Any]:
    return _merge({"final_weight_lb": final_weight_lb}, overrides)


def replacement_request_payload(
    batch_id: str,
    order_line_id: str,
    proposed_catalog_item_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "batch_id": batch_id,
            "order_line_id": order_line_id,
            "proposed_catalog_item_id": proposed_catalog_item_id,
        },
        overrides,
    )

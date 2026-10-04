"""Payload factories for the Digital Makeline Capacity API.

One factory per writable resource, carrying only the fields the client may
supply. Every factory accepts ``**overrides`` so a test can adjust the one
field it cares about without re-stating the rest.
"""

from typing import Any, Dict, List


# ── Logical clock ──────────────────────────────────────────────────────────

def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ── Stores ─────────────────────────────────────────────────────────────────

def store_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_code": "S1",
        "name": "Test Store",
        "digital_line_capacity_per_interval": 10,
        "instore_line_capacity_per_interval": 10,
        "pacing_interval_minutes": 15,
        "overage_threshold_pct": 0.8,
        "marketplace_commission_pct": 0.22,
    }
    payload.update(overrides)
    return payload


# ── Ingredients and batches ────────────────────────────────────────────────

def ingredient_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ingredient_code": "CHICKEN",
        "display_name": "Chicken",
        "unit_cost_cents_per_gram": 2.1,
        "par_level_grams": 5000,
        "hold_time_minutes": 240,
        "batch_size_grams": 3000,
    }
    payload.update(overrides)
    return payload


def batch_payload(store_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_id": store_id,
        "cooked_at": "2026-09-01T09:00:00Z",
        "grams_cooked": 10000,
    }
    payload.update(overrides)
    return payload


# ── Menu items and recipe components ───────────────────────────────────────

def menu_item_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_code": "BOWL",
        "display_name": "Chicken Bowl",
        "base_price_cents": 1095,
    }
    payload.update(overrides)
    return payload


def recipe_component_payload(ingredient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ingredient_id": ingredient_id,
        "standard_grams": 120,
    }
    payload.update(overrides)
    return payload


# ── Marketplace channels ───────────────────────────────────────────────────

def marketplace_channel_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "channel_code": "DASH",
        "markup_pct": 0.18,
        "commission_pct": 0.22,
        "active": True,
    }
    payload.update(overrides)
    return payload


# ── Production windows ─────────────────────────────────────────────────────

def production_window_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "interval_start": "2026-09-01T10:15:00Z",
        "interval_end": "2026-09-01T10:30:00Z",
    }
    payload.update(overrides)
    return payload


# ── Orders ─────────────────────────────────────────────────────────────────

def order_line_payload(menu_item_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "menu_item_id": menu_item_id,
        "quantity": 1,
        "customizations": [],
    }
    payload.update(overrides)
    return payload


def order_payload(channel: str, lines: List[Dict[str, Any]], **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "channel": channel,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def verification_payload(line_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"line_results": line_results}


def line_result(menu_item_id: str, matched: bool) -> Dict[str, Any]:
    return {"menu_item_id": menu_item_id, "matched": matched}


# ── Staffing deployments ───────────────────────────────────────────────────

def deployment_payload(shift_date: str, expected_store_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shift_date": shift_date,
        "predicted_digital_mix_pct": 0.5,
        "predicted_instore_mix_pct": 0.5,
        "headcount": 4,
        "expected_store_version": expected_store_version,
    }
    payload.update(overrides)
    return payload


# ── Waste events ───────────────────────────────────────────────────────────

def waste_event_payload(ingredient_batch_id: str, grams: int, reason: str) -> Dict[str, Any]:
    return {
        "ingredient_batch_id": ingredient_batch_id,
        "grams": grams,
        "reason": reason,
    }


# ── Day close ──────────────────────────────────────────────────────────────

def day_close_payload(expected_store_version: int) -> Dict[str, Any]:
    return {"expected_store_version": expected_store_version}

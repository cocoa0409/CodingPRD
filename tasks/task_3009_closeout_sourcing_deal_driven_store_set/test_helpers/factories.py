"""Payload factories — one per entity, input fields only."""

from .constants import JURISDICTION_CA

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_jurisdiction_rule_payload(**overrides) -> dict:
    defaults = dict(JURISDICTION_CA)
    defaults["jurisdiction_code"] = f"J{_seq():04d}"
    defaults.update(overrides)
    # PRD §3.1: window_days / required_offer_days are "both ... required for
    # that rule and absent otherwise" — strip them from non-WAS_NOW_WINDOW
    # payloads unless the caller explicitly pins a value.
    if defaults.get("comparison_rule") != "WAS_NOW_WINDOW":
        if "window_days" not in overrides:
            defaults.pop("window_days", None)
        if "required_offer_days" not in overrides:
            defaults.pop("required_offer_days", None)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"name": f"Vendor {n}", "vendor_code": f"VND-{n}"}
    defaults.update(overrides)
    return defaults


def create_store_payload(jurisdiction_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Store {n}",
        "store_code": f"S{n}",
        "jurisdiction_id": jurisdiction_id,
        "performance_tier": "TIER_1",
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(vendor_id: str, home_jurisdiction_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "vendor_id": vendor_id,
        "home_jurisdiction_id": home_jurisdiction_id,
        "title": f"Lot {n}",
        "source_type": "MFR_OVERRUN",
        "condition_grade": "A",
        "quantity_total": 100,
        "total_cost_cents": 100000,
        "est_sellable_qty": 100,
        "comparison_price_cents": 10000,
        "vendor_msrp_cents": 10000,
        "pace_target_units_per_week": 10,
    }
    defaults.update(overrides)
    return defaults


def complete_screening_payload(**overrides) -> dict:
    defaults = {
        "recall_check": "PASS",
        "expiration_check": "PASS",
        "condition_verified": True,
        "qty_grade_a": 100,
        "qty_grade_b": 0,
        "qty_grade_c": 0,
    }
    defaults.update(overrides)
    return defaults


def price_lot_payload(**overrides) -> dict:
    defaults = {"retail_price_cents": 4000, "advertises_comparison": True}
    defaults.update(overrides)
    return defaults


def create_allocation_payload(store_id: str, qty_requested: int, **overrides) -> dict:
    payload = {"store_id": store_id, "qty_requested": qty_requested}
    payload.update(overrides)
    return payload


def create_aisle_assignment_payload(lot_id: str, expected_store_version: int, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "aisle_code": "A1",
        "daily_unit_limit": 10,
        "expected_store_version": expected_store_version,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(home_store_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "member_code": f"M-{n}",
        "tier": "GOLD",
        "home_store_id": home_store_id,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "starts_at": "2026-09-02T10:00:00Z",
        "ends_at": "2026-09-02T12:00:00Z",
        "min_tier": "BRONZE",
        "extra_discount_pct": 10,
    }
    defaults.update(overrides)
    return defaults


def purchase_payload(lot_id: str, qty: int, **overrides) -> dict:
    payload = {"lot_id": lot_id, "qty": qty}
    payload.update(overrides)
    return payload


def create_disposition_payload(expected_lot_version: int = None, **overrides) -> dict:
    defaults = {"action": "MARKDOWN", "markdown_pct": 25,
                "expected_lot_version": expected_lot_version}
    defaults.update(overrides)
    return defaults

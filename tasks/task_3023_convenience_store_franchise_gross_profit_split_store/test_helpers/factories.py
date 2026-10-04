"""Payload factories -- one per resource, input fields only."""

from .constants import DEFAULTS, WEEK_PERIOD_END, WEEK_PERIOD_START

_STORE_NUMBER_SEQ = {"n": 1000}


def next_store_number(prefix: str = "TX") -> str:
    """Return a distinct store number, since store numbers are unique network-wide."""
    _STORE_NUMBER_SEQ["n"] += 1
    return f"{prefix}-{_STORE_NUMBER_SEQ['n']}"


def create_franchisee_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Test Operator LLC",
        "owner_name": "Test Owner",
        "entity_type": "LLC",
        "stated_net_worth_cents": DEFAULTS["STATED_NET_WORTH_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_store_payload(franchisee_id: str, **overrides) -> dict:
    payload = {
        "franchisee_id": franchisee_id,
        "store_number": next_store_number(overrides.pop("store_prefix", "TX")),
        "state_code": DEFAULTS["STATE_CODE"],
        "format": DEFAULTS["STORE_FORMAT"],
        "opened_on": DEFAULTS["OPENED_ON"],
        "cold_chain_certified": True,
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(franchisee_id: str, store_id: str, **overrides) -> dict:
    payload = {
        "franchisee_id": franchisee_id,
        "store_id": store_id,
        "split_pct": DEFAULTS["SPLIT_PCT"],
        "waste_share_pct": DEFAULTS["WASTE_SHARE_PCT"],
        "shrink_responsibility_pct": DEFAULTS["SHRINK_RESPONSIBILITY_PCT"],
        "rebate_pass_pct": DEFAULTS["REBATE_PASS_PCT"],
        "minimum_net_worth_cents": DEFAULTS["MINIMUM_NET_WORTH_CENTS"],
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
        "renewal_window_days": DEFAULTS["RENEWAL_WINDOW_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_settlement_payload(store_id: str, franchisee_id: str,
                              expected_store_version: int, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "franchisee_id": franchisee_id,
        "period_start": WEEK_PERIOD_START,
        "period_end": WEEK_PERIOD_END,
        "trailing_avg_gross_profit_cents": DEFAULTS["TRAILING_AVG_GROSS_PROFIT_CENTS"],
        "expected_store_version": expected_store_version,
    }
    payload.update(overrides)
    return payload


def create_revenue_line_payload(expected_settlement_version: int, **overrides) -> dict:
    payload = {
        "category": "MERCHANDISE",
        "gross_sales_cents": 5_000_000,
        "cost_of_goods_cents": 3_500_000,
        "expected_settlement_version": expected_settlement_version,
    }
    payload.update(overrides)
    return payload


def create_draw_payload(franchisee_id: str, store_id: str, **overrides) -> dict:
    payload = {
        "franchisee_id": franchisee_id,
        "store_id": store_id,
        "amount_cents": 1_000_000,
        "drawn_on": "2026-09-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_rebate_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "vendor_name": "Blue Ridge Distributing",
        "vendor_code": "BRD-01",
        "recommended_vendor": True,
        "rebate_cents": 1_000_000,
        "period_start": WEEK_PERIOD_START,
        "period_end": WEEK_PERIOD_END,
    }
    payload.update(overrides)
    return payload


def create_shrink_audit_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "book_inventory_cents": 8_000_000,
    }
    payload.update(overrides)
    return payload


def create_delivery_window_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "commissary_code": DEFAULTS["COMMISSARY_CODE"],
        "day_of_week": DEFAULTS["DAY_OF_WEEK"],
        "window_start": "2026-09-08T06:00:00Z",
        "window_end": "2026-09-08T10:00:00Z",
        "capacity_units": 2_000,
    }
    payload.update(overrides)
    return payload


def create_fresh_order_payload(store_id: str, delivery_window_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "delivery_window_id": delivery_window_id,
        "sku_code": "SKU-A",
        "ordered_units": 100,
        "unit_cost_cents": 499,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "next_store_number",
    "create_franchisee_payload", "create_store_payload", "create_agreement_payload",
    "create_settlement_payload", "create_revenue_line_payload", "create_draw_payload",
    "create_rebate_payload", "create_shrink_audit_payload",
    "create_delivery_window_payload", "create_fresh_order_payload",
]
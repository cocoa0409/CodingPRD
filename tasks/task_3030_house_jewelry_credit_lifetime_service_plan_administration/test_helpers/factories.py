"""Payload factories: one per entity, request-supplied fields only."""

from itertools import count

from .constants import DEFAULT_BUNDLE, DEFAULT_TX_REGULATION

_seq = count(1)


def _next() -> int:
    return next(_seq)


def create_store_payload(**overrides) -> dict:
    payload = {
        "store_code": "0142",
        "name": "Highland Village",
        "state_code": "TX",
        "credit_capacity_cents": 5_000_000,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "full_name": "Nina Ortiz",
        "email": f"nina.ortiz{n}@example.com",
        "state_code": "TX",
    }
    payload.update(overrides)
    return payload


def create_registry_row_payload(**overrides) -> dict:
    payload = {
        "registry_key": "TX",
        "credit_tier": "TIER_3",
        "base_limit_cents": 2_000_000,
        "min_down_payment_pct": 0.10,
        "registry_type": "STATE",
        "min_ticket_cents": 200_000,
    }
    payload.update(overrides)
    return payload


def create_regulation_payload(**overrides) -> dict:
    payload = dict(DEFAULT_TX_REGULATION)
    payload.update(overrides)
    return payload


def create_vendor_shop_payload(**overrides) -> dict:
    payload = {
        "shop_code": "JEWELCRAFT",
        "shop_name": "Jewelcraft Bench",
        "base_turnaround_days": 7,
        "rush_surcharge_cents": 4_000,
    }
    payload.update(overrides)
    return payload


def create_bundle_payload(**overrides) -> dict:
    payload = dict(DEFAULT_BUNDLE)
    payload.update(overrides)
    return payload


def create_credit_application_payload(**overrides) -> dict:
    payload = {
        "requested_limit_cents": 300_000,
        "requested_purchase_amount_cents": 300_000,
    }
    payload.update(overrides)
    return payload


def create_promotional_plan_payload(**overrides) -> dict:
    payload = {
        "plan_code": "PROMO_12_6M",
    }
    payload.update(overrides)
    return payload


def create_ledger_entry_payload(**overrides) -> dict:
    payload = {
        "entry_kind": "INSTALLMENT",
        "direction": "DECREASE",
        "amount_cents": 40_000,
        "adjustment_cents": -40_000,
        "reference_bucket": "PROMOTIONAL",
    }
    payload.update(overrides)
    return payload


def create_diamond_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "stone_code": f"ST-{n:04d}",
        "stone_kind": "NATURAL",
        "carat": 0.90,
    }
    payload.update(overrides)
    return payload


def create_purchase_payload(**overrides) -> dict:
    payload = {
        "base_price_cents": 450_018,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(**overrides) -> dict:
    payload = {
        "plan_term_months": 24,
    }
    payload.update(overrides)
    return payload


def create_inspection_visit_payload(**overrides) -> dict:
    payload = {
        "visit_at": "2026-09-10T00:00:00Z",
        "result": "CLAIMED",
    }
    payload.update(overrides)
    return payload


def create_repair_payload(**overrides) -> dict:
    payload = {
        "failure_class": "SETTING",
        "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000,
        "declared_loss_liability_cents": 5_000,
    }
    payload.update(overrides)
    return payload


def create_repair_hold_payload(extended_promised_delivery_at, **overrides) -> dict:
    payload = {"extended_promised_delivery_at": extended_promised_delivery_at}
    payload.update(overrides)
    return payload


def create_appraisal_payload(**overrides) -> dict:
    payload = {
        "appraisal_kind": "REPLACEMENT",
    }
    payload.update(overrides)
    return payload


def create_custom_design_order_payload(**overrides) -> dict:
    payload = {
        "estimate_amount_cents": 250_000,
        "deposit_pct": 0.40,
    }
    payload.update(overrides)
    return payload


def create_billing_statement_payload(**overrides) -> dict:
    payload = {
        "statement_period": "2026-09",
        "lines": [
            {"amount_cents": 250_000, "billable_pct": 1.0, "line_status": "BILLABLE"},
            {"amount_cents": 260_000, "billable_pct": 1.0, "line_status": "BILLABLE"},
        ],
    }
    payload.update(overrides)
    return payload


__all__ = [
    "create_store_payload",
    "create_customer_payload",
    "create_registry_row_payload",
    "create_regulation_payload",
    "create_vendor_shop_payload",
    "create_bundle_payload",
    "create_credit_application_payload",
    "create_promotional_plan_payload",
    "create_ledger_entry_payload",
    "create_diamond_payload",
    "create_purchase_payload",
    "create_registration_payload",
    "create_inspection_visit_payload",
    "create_repair_payload",
    "create_repair_hold_payload",
    "create_appraisal_payload",
    "create_custom_design_order_payload",
    "create_billing_statement_payload",
]
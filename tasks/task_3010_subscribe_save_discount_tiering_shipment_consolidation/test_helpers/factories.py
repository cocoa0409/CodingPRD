"""Payload factories — one per creatable resource, input fields only."""
import uuid

from .constants import (
    DEFAULT_CADENCE_MONTHS,
    DEFAULT_PREFERRED_DAY,
    DEFAULT_START_DATE,
    REGION,
)


def _uniq(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": f"{_uniq('cust')}@example.com",
        "full_name": "Test Customer",
        "region": REGION,
        "preferred_delivery_day": DEFAULT_PREFERRED_DAY,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": "Test Product",
        "region": REGION,
    }
    defaults.update(overrides)
    return defaults


def create_price_event_payload(price_cents=1000, effective_from="2026-09-01T00:00:00Z", **overrides) -> dict:
    defaults = {"price_cents": price_cents, "effective_from": effective_from}
    defaults.update(overrides)
    return defaults


def create_inventory_placement_payload(**overrides) -> dict:
    defaults = {"region": REGION}
    defaults.update(overrides)
    return defaults


def create_receive_payload(units=50, **overrides) -> dict:
    defaults = {"units": units}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, product_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "cadence_months": DEFAULT_CADENCE_MONTHS,
        "quantity": 1,
        "start_date": DEFAULT_START_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_coupon_payload(code=None, **overrides) -> dict:
    defaults = {
        "code": code or _uniq("CPN").upper(),
        "discount_type": "FLAT",
        "flat_off_cents": 100,
        "valid_from": "2026-09-01",
        "valid_to": "2026-09-30",
    }
    defaults.update(overrides)
    # A None override means "omit this optional field" (e.g. a PERCENT coupon
    # must not carry flat_off_cents).
    return {k: v for k, v in defaults.items() if v is not None}


def create_promotion_payload(bonus_product_id, **overrides) -> dict:
    defaults = {
        "bonus_product_id": bonus_product_id,
        "min_line_count": 3,
        "starts_on": "2026-09-01",
        "ends_on": "2026-10-01",
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(damaged_line_ids, **overrides) -> dict:
    defaults = {"damaged_line_ids": list(damaged_line_ids)}
    defaults.update(overrides)
    return defaults


def create_generate_plans_payload(delivery_month="2026-09", **overrides) -> dict:
    defaults = {"delivery_month": delivery_month}
    defaults.update(overrides)
    return defaults


def create_recompute_forecasts_payload(region=REGION, forecast_month="2026-09", **overrides) -> dict:
    defaults = {"region": region, "forecast_month": forecast_month}
    defaults.update(overrides)
    return defaults

"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import (
    DESIGN_WIN_START_DATE,
    EOL_LAST_ORDER_DATE,
    EOL_LAST_SHIP_DATE,
    EOL_NOTICE_DATE,
    POOL_PERIOD_END,
    POOL_PERIOD_START,
)

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_part_payload(
    part_number=None,
    description="Precision analog part",
    package_family="PDIP",
    process_technology="ANALOG_BIPOLAR",
    automotive_grade=None,
    demand_rate_units_per_week=None,
    buffer_multiple=None,
) -> dict:
    payload = {
        "part_number": part_number or _uniq("OPA"),
        "description": description,
        "package_family": package_family,
        "process_technology": process_technology,
    }
    if automotive_grade is not None:
        payload["automotive_grade"] = automotive_grade
    if demand_rate_units_per_week is not None:
        payload["demand_rate_units_per_week"] = demand_rate_units_per_week
    if buffer_multiple is not None:
        payload["buffer_multiple"] = buffer_multiple
    return payload


def create_customer_payload(
    name=None,
    tier="STANDARD",
    channel="DIRECT_FIELD",
    credit_limit_cents=10_000_000,
    discount_pct=None,
) -> dict:
    payload = {
        "name": name or _uniq("Customer"),
        "tier": tier,
        "channel": channel,
        "credit_limit_cents": credit_limit_cents,
    }
    if discount_pct is not None:
        payload["discount_pct"] = discount_pct
    return payload


def create_pricing_schedule_payload(
    part_id,
    expected_part_version,
    effective_from,
    tiers=None,
    unit_price_cents=100,
) -> dict:
    return {
        "part_id": part_id,
        "effective_from": effective_from,
        "tiers": tiers if tiers is not None else [
            {"min_qty": 1, "unit_price_cents": unit_price_cents}
        ],
        "expected_part_version": expected_part_version,
    }


def create_order_payload(customer_id, lines) -> dict:
    return {"customer_id": customer_id, "lines": lines}


def create_capacity_pool_payload(
    site_name="DFAB",
    process_technology="ANALOG_BIPOLAR",
    period_start=POOL_PERIOD_START,
    period_end=POOL_PERIOD_END,
    total_units=10000,
) -> dict:
    return {
        "site_name": site_name,
        "process_technology": process_technology,
        "period_start": period_start,
        "period_end": period_end,
        "total_units": total_units,
    }


def create_allocation_run_payload(period_label="2026-W40") -> dict:
    return {"period_label": period_label}


def create_eol_notice_payload(
    notice_date=EOL_NOTICE_DATE,
    last_order_date=EOL_LAST_ORDER_DATE,
    last_ship_date=EOL_LAST_SHIP_DATE,
    reason="End of life program",
) -> dict:
    return {
        "notice_date": notice_date,
        "last_order_date": last_order_date,
        "last_ship_date": last_ship_date,
        "reason": reason,
    }


def create_lifetime_buy_payload(eol_notice_id, part_id, customer_id, quantity) -> dict:
    return {
        "eol_notice_id": eol_notice_id,
        "part_id": part_id,
        "customer_id": customer_id,
        "quantity": quantity,
    }


def create_site_qualification_payload(
    site_name, segment="AUTOMOTIVE", validity_months=None
) -> dict:
    payload = {"site_name": site_name, "segment": segment}
    if validity_months is not None:
        payload["validity_months"] = validity_months
    return payload


def create_reference_design_payload(title=None, featured_part_number="") -> dict:
    return {
        "title": title or _uniq("Reference design"),
        "featured_part_number": featured_part_number,
    }


def create_design_win_payload(
    reference_design_id,
    customer_id,
    part_id,
    expected_lifetime_revenue_cents=1_000_000,
    annual_volume_units=5200,
    start_date=DESIGN_WIN_START_DATE,
) -> dict:
    return {
        "reference_design_id": reference_design_id,
        "customer_id": customer_id,
        "part_id": part_id,
        "expected_lifetime_revenue_cents": expected_lifetime_revenue_cents,
        "annual_volume_units": annual_volume_units,
        "start_date": start_date,
    }

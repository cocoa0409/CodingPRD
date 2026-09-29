"""Request payload builders for every creation endpoint.

Only client-supplied input fields appear here: derived, computed and
system-owned fields are never sent. Money, tonnage and gas figures are emitted
as JSON numbers, and every instant is a full ISO 8601 UTC instant rather than a
date-only string.

Business codes obey the length and charset rules of PRD section 2.10:
``site_code`` is 3 to 12 characters of uppercase A-Z and digits, ``train_code``
is 2 to 12 characters, and every other code is 2 to 16.
"""

import itertools
import random
import string

from .constants import DEFAULT_CLOCK_STAMP  # noqa: F401  (documents the epoch)

_counter = itertools.count(1)
_ALNUM = string.ascii_uppercase + string.digits


def _suffix(width: int = 5) -> str:
    """A short uppercase alphanumeric token, unique within a test process."""
    n = next(_counter)
    rand = "".join(random.choice(_ALNUM) for _ in range(max(0, width - len(str(n)))))
    return f"{rand}{n}"


def unique_site_code(prefix: str = "ST") -> str:
    """3 to 12 characters of uppercase A-Z and digits only."""
    return f"{prefix}{_suffix(6)}"[:12]


def unique_code(prefix: str = "CD") -> str:
    """A business code of 2 to 16 characters."""
    return f"{prefix}{_suffix(6)}"[:16]


def unique_train_code(prefix: str = "RT") -> str:
    """A train code of 2 to 12 characters."""
    return f"{prefix}{_suffix(5)}"[:12]


# ---------------------------------------------------------------------------
# Plant
# ---------------------------------------------------------------------------
def plant_payload(
    name: str = "Riverbend Nitrogen Complex",
    site_code: str = None,
    permit_limit_tons_30d: float = 12.00,
    spot_gas_index_usd_per_mmbtu: float = 4.2000,
    **extra,
):
    """POST /nitrogen-ops/plants."""
    payload = {
        "name": name,
        "site_code": site_code or unique_site_code(),
        "permit_limit_tons_30d": permit_limit_tons_30d,
        "spot_gas_index_usd_per_mmbtu": spot_gas_index_usd_per_mmbtu,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ReformerTrain
# ---------------------------------------------------------------------------
def reformer_train_payload(
    plant_id: str,
    train_code: str = None,
    rated_ammonia_tpd: float = 1800.0,
    **extra,
):
    """POST /nitrogen-ops/reformer-trains."""
    payload = {
        "plant_id": plant_id,
        "train_code": train_code or unique_train_code(),
        "rated_ammonia_tpd": rated_ammonia_tpd,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# CatalystCharge
# ---------------------------------------------------------------------------
def catalyst_charge_payload(
    train_id: str,
    charge_code: str = None,
    design_life_hours: float = 40000.0,
    baseline_operating_hours=None,
    poisoning_index=None,
    **extra,
):
    """POST /nitrogen-ops/catalyst-charges.

    ``baseline_operating_hours`` and ``poisoning_index`` are the two optional
    seeding fields; omitting them leaves the server defaults in force.
    """
    payload = {
        "train_id": train_id,
        "charge_code": charge_code or unique_code("CC"),
        "design_life_hours": design_life_hours,
    }
    if baseline_operating_hours is not None:
        payload["baseline_operating_hours"] = baseline_operating_hours
    if poisoning_index is not None:
        payload["poisoning_index"] = poisoning_index
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# GasHedgeLot
# ---------------------------------------------------------------------------
def gas_hedge_lot_payload(
    plant_id: str,
    mmbtu_volume: float = 100000.0,
    strike_price_usd_per_mmbtu: float = 3.0000,
    delivery_month: str = "2026-09",
    lot_code: str = None,
    **extra,
):
    """POST /nitrogen-ops/gas-hedge-lots."""
    payload = {
        "plant_id": plant_id,
        "lot_code": lot_code or unique_code("HL"),
        "mmbtu_volume": mmbtu_volume,
        "strike_price_usd_per_mmbtu": strike_price_usd_per_mmbtu,
        "delivery_month": delivery_month,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ProductLine
# ---------------------------------------------------------------------------
def product_line_payload(
    plant_id: str,
    product_code: str = "UREA",
    ammonia_tons_per_product_ton: float = 0.580,
    conversion_cost_usd_per_ton: float = 38.000,
    regulated: bool = False,
    priority_rank: int = 10,
    **extra,
):
    """POST /nitrogen-ops/product-lines."""
    payload = {
        "plant_id": plant_id,
        "product_code": product_code,
        "ammonia_tons_per_product_ton": ammonia_tons_per_product_ton,
        "conversion_cost_usd_per_ton": conversion_cost_usd_per_ton,
        "regulated": regulated,
        "priority_rank": priority_rank,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ProductionRun
# ---------------------------------------------------------------------------
def production_run_payload(
    train_id: str,
    window_start: str = "2026-09-01T00:00:00.000Z",
    window_end: str = "2026-09-11T00:00:00.000Z",
    target_ammonia_tons: float = 5000.000,
    run_code: str = None,
    **extra,
):
    """POST /nitrogen-ops/production-runs."""
    payload = {
        "train_id": train_id,
        "run_code": run_code or unique_code("PR"),
        "window_start": window_start,
        "window_end": window_end,
        "target_ammonia_tons": target_ammonia_tons,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ProductionOrder
# ---------------------------------------------------------------------------
def production_order_payload(
    run_id: str,
    product_line_id: str,
    destination_asset_id: str,
    requested_tons: float = 1000.000,
    order_code: str = None,
    **extra,
):
    """POST /nitrogen-ops/production-orders."""
    payload = {
        "run_id": run_id,
        "product_line_id": product_line_id,
        "destination_asset_id": destination_asset_id,
        "order_code": order_code or unique_code("PO"),
        "requested_tons": requested_tons,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# StorageAsset
# ---------------------------------------------------------------------------
def storage_asset_payload(
    plant_id: str,
    asset_kind: str = "TANK",
    product_code: str = "UREA",
    capacity_tons: float = 20000.000,
    security_class: str = "BASIC",
    seasonal_reserve_pct=None,
    asset_code: str = None,
    **extra,
):
    """POST /nitrogen-ops/storage-assets."""
    payload = {
        "plant_id": plant_id,
        "asset_code": asset_code or unique_code("SA"),
        "asset_kind": asset_kind,
        "product_code": product_code,
        "capacity_tons": capacity_tons,
        "security_class": security_class,
    }
    if seasonal_reserve_pct is not None:
        payload["seasonal_reserve_pct"] = seasonal_reserve_pct
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Shipment
# ---------------------------------------------------------------------------
def shipment_payload(
    origin_asset_id: str,
    dest_asset_id: str,
    mode: str = "RAIL",
    tons: float = 1000.000,
    distance_miles: float = 100.0,
    window_start: str = "2026-08-05T00:00:00.000Z",
    window_end: str = "2026-08-10T00:00:00.000Z",
    production_order_id=None,
    shipment_code: str = None,
    **extra,
):
    """POST /nitrogen-ops/shipments."""
    payload = {
        "origin_asset_id": origin_asset_id,
        "dest_asset_id": dest_asset_id,
        "shipment_code": shipment_code or unique_code("SH"),
        "mode": mode,
        "tons": tons,
        "distance_miles": distance_miles,
        "window_start": window_start,
        "window_end": window_end,
    }
    if production_order_id is not None:
        payload["production_order_id"] = production_order_id
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# PriceQuote
# ---------------------------------------------------------------------------
def price_quote_payload(
    plant_id: str,
    product_line_id: str,
    tons: float = 6000.000,
    pass_through_basis: str = "HEDGED_BLEND",
    expires_at: str = "2027-04-15T00:00:00.000Z",
    quote_code: str = None,
    **extra,
):
    """POST /nitrogen-ops/price-quotes."""
    payload = {
        "plant_id": plant_id,
        "product_line_id": product_line_id,
        "quote_code": quote_code or unique_code("QT"),
        "tons": tons,
        "pass_through_basis": pass_through_basis,
        "expires_at": expires_at,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Turnaround
# ---------------------------------------------------------------------------
def turnaround_payload(
    plant_id: str,
    train_id: str,
    scope: str = "CATALYST_CHANGE",
    window_start: str = "2026-11-01T00:00:00.000Z",
    window_end: str = "2026-11-27T00:00:00.000Z",
    turnaround_code: str = None,
    **extra,
):
    """POST /nitrogen-ops/turnarounds."""
    payload = {
        "plant_id": plant_id,
        "train_id": train_id,
        "turnaround_code": turnaround_code or unique_code("TA"),
        "scope": scope,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# TurnaroundTask
# ---------------------------------------------------------------------------
def turnaround_task_payload(
    turnaround_id: str,
    duration_days: int = 7,
    predecessor_task_id=None,
    task_code: str = None,
    **extra,
):
    """POST /nitrogen-ops/turnaround-tasks."""
    payload = {
        "turnaround_id": turnaround_id,
        "task_code": task_code or unique_code("TK"),
        "duration_days": duration_days,
    }
    if predecessor_task_id is not None:
        payload["predecessor_task_id"] = predecessor_task_id
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# EmissionsReading
# ---------------------------------------------------------------------------
def emissions_reading_payload(
    plant_id: str,
    pollutant: str = "NOX",
    rate_lb_per_hour: float = 50.000,
    interval_hours: float = 480.0,
    reading_at: str = "2026-08-01T00:00:00.000Z",
    **extra,
):
    """POST /nitrogen-ops/emissions-readings."""
    payload = {
        "plant_id": plant_id,
        "pollutant": pollutant,
        "rate_lb_per_hour": rate_lb_per_hour,
        "interval_hours": interval_hours,
        "reading_at": reading_at,
    }
    payload.update(extra)
    return payload

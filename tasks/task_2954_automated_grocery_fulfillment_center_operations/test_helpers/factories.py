"""Request-payload builders.

Every builder returns a plain dict of valid defaults that callers override with
keyword arguments.  Monetary amounts are whole-cent JSON numbers, never
strings.  Every instant is a full ISO 8601 UTC timestamp with exactly three
fractional digits, never a bare date.
"""

import itertools

from .constants import DEFAULT_CLOCK_UTC
from .types import LoyaltyTier, TemperatureZone

_counter = itertools.count(1)


def unique_suffix():
    """A short monotonically increasing suffix for unique code fields."""
    return f"{next(_counter):05d}"


def _merge(base, overrides):
    payload = dict(base)
    for key, value in overrides.items():
        payload[key] = value
    return payload


# ─── Logical clock ───────────────────────────────────────────────────────────


def clock_payload(current_utc=DEFAULT_CLOCK_UTC):
    return {"current_utc": current_utc}


# ─── Standing plant ──────────────────────────────────────────────────────────


def delivery_route_payload(**overrides):
    suffix = unique_suffix()
    return _merge(
        {
            "route_code": f"RT-{suffix}",
            "service_area_name": f"Service Area {suffix}",
            "van_capacity_totes": 40,
            "base_delivery_fee_cents": 500,
            "per_km_cost_cents": 120,
        },
        overrides,
    )


def dock_bay_payload(**overrides):
    suffix = unique_suffix()
    return _merge(
        {
            "bay_code": f"BAY-{suffix}",
            "parallel_van_capacity": 2,
        },
        overrides,
    )


def grid_zone_payload(**overrides):
    suffix = unique_suffix()
    return _merge(
        {
            "zone_code": f"GZ-{suffix}",
            "temperature_zone": TemperatureZone.AMBIENT.value,
            "bot_count": 12,
        },
        overrides,
    )


def pick_station_payload(**overrides):
    suffix = unique_suffix()
    return _merge(
        {
            "station_code": f"PS-{suffix}",
            "temperature_zone_capability": [
                TemperatureZone.AMBIENT.value,
                TemperatureZone.CHILLED.value,
                TemperatureZone.FROZEN.value,
            ],
            "max_concurrent_totes": 6,
        },
        overrides,
    )


def inventory_sku_payload(grid_zone_id, **overrides):
    """A non-catchweight SKU.  The three weight fields must stay absent."""
    suffix = unique_suffix()
    return _merge(
        {
            "sku_code": f"SKU-{suffix}",
            "name": f"Grocery Item {suffix}",
            "grid_zone_id": grid_zone_id,
            "temperature_zone": TemperatureZone.AMBIENT.value,
            "substitution_group_code": f"GRP-{suffix}",
            "is_catchweight": False,
            "unit_price_cents": 250,
            "physical_units": 500,
        },
        overrides,
    )


def catchweight_sku_payload(grid_zone_id, **overrides):
    """A weighed SKU, carrying the three fields catchweight items require."""
    suffix = unique_suffix()
    return _merge(
        {
            "sku_code": f"CWS-{suffix}",
            "name": f"Weighed Item {suffix}",
            "grid_zone_id": grid_zone_id,
            "temperature_zone": TemperatureZone.AMBIENT.value,
            "substitution_group_code": f"GRP-{suffix}",
            "is_catchweight": True,
            "unit_price_cents": 1300,
            "physical_units": 500,
            "price_per_kg_cents": 1300,
            "nominal_weight_grams": 1000,
            "weight_tolerance_pct": 0.05,
        },
        overrides,
    )


def customer_account_payload(home_route_id, **overrides):
    suffix = unique_suffix()
    return _merge(
        {
            "email": f"shopper{suffix}@example.com",
            "full_name": f"Shopper {suffix}",
            "loyalty_tier": LoyaltyTier.BASIC.value,
            "home_route_id": home_route_id,
        },
        overrides,
    )


# ─── Slots, baskets and bookings ─────────────────────────────────────────────


def delivery_slot_payload(route_id, **overrides):
    return _merge(
        {
            "route_id": route_id,
            "window_start": "2026-08-05T10:00:00.000Z",
            "window_end": "2026-08-05T12:00:00.000Z",
            "total_capacity_units": 100,
            "withheld_units": 0,
        },
        overrides,
    )


def customer_order_payload(**overrides):
    return _merge({"stop_distance_km": 5.00}, overrides)


def order_line_payload(sku_id, **overrides):
    return _merge({"sku_id": sku_id, "ordered_qty": 1}, overrides)


def slot_booking_payload(
    delivery_slot_id, customer_order_id, expected_order_version, **overrides
):
    return _merge(
        {
            "delivery_slot_id": delivery_slot_id,
            "customer_order_id": customer_order_id,
            "units": 1,
            "expected_order_version": expected_order_version,
        },
        overrides,
    )


def capacity_units_payload(units, **overrides):
    """Body for the capacity release and capacity withholding levers."""
    return _merge({"units": units}, overrides)


# ─── Waves, docks, totes and retrievals ──────────────────────────────────────


def delivery_wave_payload(route_id, delivery_slot_id, **overrides):
    suffix = unique_suffix()
    return _merge(
        {
            "route_id": route_id,
            "delivery_slot_id": delivery_slot_id,
            "wave_code": f"WV-{suffix}",
            "cutoff_at": "2026-08-05T08:00:00.000Z",
        },
        overrides,
    )


def slot_orders_payload(customer_order_id, **overrides):
    return _merge({"customer_order_id": customer_order_id}, overrides)


def assign_dock_payload(dock_bay_id, load_start, load_end, **overrides):
    return _merge(
        {
            "dock_bay_id": dock_bay_id,
            "load_start": load_start,
            "load_end": load_end,
        },
        overrides,
    )


def tote_payload(wave_id, pick_station_id, **overrides):
    suffix = unique_suffix()
    return _merge(
        {
            "wave_id": wave_id,
            "pick_station_id": pick_station_id,
            "tote_code": f"TT-{suffix}",
            "temperature_zone": TemperatureZone.AMBIENT.value,
        },
        overrides,
    )


def assign_tote_payload(tote_id, **overrides):
    return _merge({"tote_id": tote_id}, overrides)


def complete_pick_task_payload(picked_units, **overrides):
    """Completion body.  ``actual_weight_grams`` belongs only to weighed SKUs."""
    return _merge({"picked_units": picked_units}, overrides)


# ─── Substitutions ───────────────────────────────────────────────────────────


def substitution_proposal_payload(
    order_line_id, substitute_sku_id, expected_order_line_version, **overrides
):
    return _merge(
        {
            "order_line_id": order_line_id,
            "substitute_sku_id": substitute_sku_id,
            "expected_order_line_version": expected_order_line_version,
        },
        overrides,
    )


# ─── Maintenance and audits ──────────────────────────────────────────────────


def maintenance_window_payload(grid_zone_id, **overrides):
    return _merge(
        {
            "grid_zone_id": grid_zone_id,
            "window_start": "2026-08-02T09:00:00.000Z",
            "window_end": "2026-08-02T11:00:00.000Z",
        },
        overrides,
    )


def audit_counts_payload(counts, **overrides):
    """``counts`` is a list of ``{"sku_id": ..., "counted_units": ...}`` dicts."""
    return _merge({"counts": list(counts)}, overrides)


def audit_count_entry(sku_id, counted_units):
    return {"sku_id": sku_id, "counted_units": counted_units}

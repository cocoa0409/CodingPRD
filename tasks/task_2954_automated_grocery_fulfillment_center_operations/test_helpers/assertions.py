"""Domain assertions and small response readers.

Two things here deserve a note.  First, instants are compared through
:func:`assert_instant_equals`, which normalises the fractional-second width so
that ``2026-08-05T10:00:00Z`` and ``2026-08-05T10:00:00.000Z`` compare equal.
Second, list responses are read through :func:`list_items`, which unwraps the
envelope exactly once — there is no nested ``data.data``.
"""

import re

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import SURGE_CEILING, SURGE_FLOOR

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$"
)


# ─── Instants ────────────────────────────────────────────────────────────────


def canonical_instant(value):
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits."""
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"not an ISO 8601 UTC instant: {value!r}"
    date_part, time_part, fraction, offset = match.groups()
    assert offset in ("Z", "+00:00", "-00:00"), f"instant must be UTC: {value!r}"
    fraction = (fraction or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{fraction}Z"


def assert_instant_equals(actual, expected, label="instant"):
    """Compare two instants regardless of how many fractional digits each has."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_field(entity, field):
    value = entity.get(field)
    assert value is not None, f"{field} must not be null"
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 instant: {value!r}"


# ─── Envelope readers ────────────────────────────────────────────────────────


def read_object(response, expected_status=200):
    """Read a single-resource response body."""
    data = validate_success(response, expected_status)
    assert isinstance(data, dict), f"expected an object payload, got {type(data)}"
    assert "data" not in data or not isinstance(data.get("data"), dict), (
        "payload looks double-wrapped; read the envelope only once"
    )
    return data


def list_items(response):
    """Read a list response and return just the item list."""
    items, _meta = validate_paginated(response)
    assert isinstance(items, list), f"expected an array payload, got {type(items)}"
    return items


def list_items_and_meta(response):
    """Read a list response and return the item list together with its meta."""
    items, meta = validate_paginated(response)
    assert isinstance(items, list), f"expected an array payload, got {type(items)}"
    return items, meta


def list_ids(response):
    return [item["id"] for item in list_items(response)]


def find_by_id(items, target_id):
    for item in items:
        if item["id"] == target_id:
            return item
    raise AssertionError(f"no item with id {target_id} in {[i['id'] for i in items]}")


def only_item(items):
    assert len(items) == 1, f"expected exactly one item, got {len(items)}"
    return items[0]


# ─── Common resource properties ──────────────────────────────────────────────


def assert_common_fields(entity):
    """Every resource carries an id, two timestamps and a version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert_instant_field(entity, "created_at")
    assert_instant_field(entity, "updated_at")
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, f"version must start at 1, got {entity['version']}"


def assert_version_is(entity, expected, label="version"):
    assert entity["version"] == expected, (
        f"{label}: expected version {expected}, got {entity['version']}"
    )


def assert_field_absent_or_null(entity, field):
    assert entity.get(field) is None, (
        f"{field} should be null, got {entity.get(field)!r}"
    )


def assert_money(entity, field, expected):
    """Money is a whole-cent integer, never a string and never a float."""
    actual = entity.get(field)
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} cents, got {actual}"


def assert_int_field(entity, field, expected):
    actual = entity.get(field)
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_ratio(entity, field, expected, places=4):
    """Compare a rounded ratio such as an accuracy score or a multiplier."""
    actual = entity.get(field)
    assert actual is not None, f"{field} must not be null"
    assert round(float(actual), places) == round(float(expected), places), (
        f"{field}: expected {expected}, got {actual}"
    )


# ─── Entity-shaped assertions ────────────────────────────────────────────────


def assert_delivery_route_shape(route):
    assert_common_fields(route)
    for field in (
        "route_code",
        "service_area_name",
        "van_capacity_totes",
        "base_delivery_fee_cents",
        "per_km_cost_cents",
    ):
        assert field in route, f"delivery route is missing {field}"


def assert_dock_bay_shape(bay):
    assert_common_fields(bay)
    for field in ("bay_code", "parallel_van_capacity"):
        assert field in bay, f"dock bay is missing {field}"


def assert_grid_zone_shape(zone):
    assert_common_fields(zone)
    for field in (
        "zone_code",
        "temperature_zone",
        "bot_count",
        "status",
        "accuracy_score_unit_weighted",
        "accuracy_score_sku_weighted",
        "last_audited_at",
    ):
        assert field in zone, f"grid zone is missing {field}"


def assert_pick_station_shape(station):
    assert_common_fields(station)
    for field in (
        "station_code",
        "temperature_zone_capability",
        "max_concurrent_totes",
        "current_tote_count",
        "status",
    ):
        assert field in station, f"pick station is missing {field}"
    assert isinstance(station["temperature_zone_capability"], list)


def assert_station_status_matches_count(station):
    """A station is IDLE exactly when it holds no open tote."""
    expected = "IDLE" if station["current_tote_count"] == 0 else "ACTIVE"
    assert station["status"] == expected, (
        f"station holding {station['current_tote_count']} open totes "
        f"should be {expected}, got {station['status']}"
    )


def assert_inventory_sku_shape(sku):
    assert_common_fields(sku)
    for field in (
        "sku_code",
        "name",
        "grid_zone_id",
        "temperature_zone",
        "substitution_group_code",
        "is_catchweight",
        "unit_price_cents",
        "price_per_kg_cents",
        "nominal_weight_grams",
        "weight_tolerance_pct",
        "physical_units",
        "allocated_units",
        "on_hand_units",
        "last_count_system_units",
        "last_count_counted_units",
        "last_count_variance_units",
    ):
        assert field in sku, f"SKU is missing {field}"


def assert_maintenance_window_shape(window):
    assert_common_fields(window)
    for field in ("grid_zone_id", "window_start", "window_end", "status"):
        assert field in window, f"maintenance window is missing {field}"


def assert_delivery_slot_shape(slot):
    assert_common_fields(slot)
    for field in (
        "route_id",
        "window_start",
        "window_end",
        "total_capacity_units",
        "withheld_units",
        "held_units",
        "confirmed_units",
        "available_units",
        "surge_multiplier",
    ):
        assert field in slot, f"delivery slot is missing {field}"


def assert_customer_account_shape(account):
    assert_common_fields(account)
    for field in ("email", "full_name", "loyalty_tier", "home_route_id"):
        assert field in account, f"customer account is missing {field}"


def assert_customer_order_shape(order):
    assert_common_fields(order)
    for field in (
        "customer_id",
        "wave_id",
        "stop_distance_km",
        "fulfillment_status",
        "billing_status",
        "merchandise_subtotal_cents",
        "delivery_fee_cents",
        "loyalty_discount_cents",
        "order_total_cents",
        "authorized_amount_cents",
        "captured_amount_cents",
        "dispatch_blocked",
        "open_substitution_count",
    ):
        assert field in order, f"customer order is missing {field}"


def assert_order_line_shape(line):
    assert_common_fields(line)
    for field in (
        "order_id",
        "sku_id",
        "ordered_qty",
        "nominal_weight_grams",
        "line_status",
        "substitution_resolution",
        "provisional_line_price_cents",
        "final_line_price_cents",
        "picked_units",
        "picked_weight_grams",
    ):
        assert field in line, f"order line is missing {field}"


def assert_slot_booking_shape(booking):
    assert_common_fields(booking)
    for field in (
        "delivery_slot_id",
        "customer_order_id",
        "units",
        "status",
        "quoted_fee_cents",
        "surge_multiplier_at_booking",
    ):
        assert field in booking, f"slot booking is missing {field}"


def assert_delivery_wave_shape(wave):
    assert_common_fields(wave)
    for field in (
        "route_id",
        "delivery_slot_id",
        "dock_bay_id",
        "wave_code",
        "cutoff_at",
        "load_start",
        "load_end",
        "status",
        "posture",
        "order_count",
        "tote_count",
        "load_sequence",
        "transport_cost_cents",
        "consolidated_by_user_id",
    ):
        assert field in wave, f"delivery wave is missing {field}"
    assert isinstance(wave["load_sequence"], list)


def assert_tote_shape(tote):
    assert_common_fields(tote)
    for field in (
        "wave_id",
        "pick_station_id",
        "tote_code",
        "temperature_zone",
        "status",
        "assigned_line_count",
    ):
        assert field in tote, f"tote is missing {field}"


def assert_pick_task_shape(task):
    assert_common_fields(task)
    for field in (
        "order_line_id",
        "sku_id",
        "grid_zone_id",
        "pick_station_id",
        "tote_id",
        "sequence_index",
        "allocated_units",
        "picked_units",
        "actual_weight_grams",
        "status",
    ):
        assert field in task, f"retrieval task is missing {field}"


def assert_substitution_proposal_shape(proposal):
    assert_common_fields(proposal)
    for field in (
        "order_line_id",
        "substitute_sku_id",
        "supersedes_proposal_id",
        "round_no",
        "proposed_price_delta_cents",
        "status",
        "expires_at",
    ):
        assert field in proposal, f"substitution proposal is missing {field}"


# ─── Status assertions ───────────────────────────────────────────────────────


def assert_status(entity, expected, field="status"):
    actual = entity.get(field)
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_order_statuses(order, fulfillment_status=None, billing_status=None):
    """The two order dimensions advance independently; check them by name."""
    if fulfillment_status is not None:
        assert order["fulfillment_status"] == fulfillment_status, (
            f"fulfillment_status: expected {fulfillment_status}, "
            f"got {order['fulfillment_status']}"
        )
    if billing_status is not None:
        assert order["billing_status"] == billing_status, (
            f"billing_status: expected {billing_status}, "
            f"got {order['billing_status']}"
        )


def assert_wave_posture(wave, expected):
    assert wave["posture"] == expected, (
        f"posture: expected {expected}, got {wave['posture']}"
    )


def assert_order_money(
    order,
    merchandise_subtotal_cents=None,
    delivery_fee_cents=None,
    loyalty_discount_cents=None,
    order_total_cents=None,
    authorized_amount_cents=None,
    captured_amount_cents=None,
):
    """Assert whichever of the order's six money figures the caller names."""
    expectations = {
        "merchandise_subtotal_cents": merchandise_subtotal_cents,
        "delivery_fee_cents": delivery_fee_cents,
        "loyalty_discount_cents": loyalty_discount_cents,
        "order_total_cents": order_total_cents,
        "authorized_amount_cents": authorized_amount_cents,
        "captured_amount_cents": captured_amount_cents,
    }
    for field, expected in expectations.items():
        if expected is None:
            continue
        assert_money(order, field, expected)


# ─── Conserved ledgers ───────────────────────────────────────────────────────


def assert_slot_ledger_balances(slot):
    """total_capacity_units == withheld + held + confirmed + available."""
    total = slot["total_capacity_units"]
    parts = (
        slot["withheld_units"]
        + slot["held_units"]
        + slot["confirmed_units"]
        + slot["available_units"]
    )
    assert total == parts, (
        "slot capacity ledger does not balance: "
        f"total_capacity_units={total} but withheld={slot['withheld_units']} "
        f"+ held={slot['held_units']} + confirmed={slot['confirmed_units']} "
        f"+ available={slot['available_units']} = {parts}"
    )


def assert_slot_ledger(
    slot,
    total_capacity_units=None,
    withheld_units=None,
    held_units=None,
    confirmed_units=None,
    available_units=None,
):
    expectations = {
        "total_capacity_units": total_capacity_units,
        "withheld_units": withheld_units,
        "held_units": held_units,
        "confirmed_units": confirmed_units,
        "available_units": available_units,
    }
    for field, expected in expectations.items():
        if expected is None:
            continue
        assert_int_field(slot, field, expected)
    assert_slot_ledger_balances(slot)


def assert_sku_ledger_balances(sku):
    """physical_units == on_hand_units + allocated_units."""
    assert sku["physical_units"] == sku["on_hand_units"] + sku["allocated_units"], (
        "SKU unit ledger does not balance: "
        f"physical_units={sku['physical_units']} but on_hand={sku['on_hand_units']} "
        f"+ allocated={sku['allocated_units']}"
    )


def assert_sku_ledger(
    sku, physical_units=None, allocated_units=None, on_hand_units=None
):
    expectations = {
        "physical_units": physical_units,
        "allocated_units": allocated_units,
        "on_hand_units": on_hand_units,
    }
    for field, expected in expectations.items():
        if expected is None:
            continue
        assert_int_field(sku, field, expected)
    assert_sku_ledger_balances(sku)


def assert_surge_multiplier(slot, expected):
    """A surge multiplier sits in the closed interval 1.00 to 1.80."""
    actual = slot["surge_multiplier"]
    assert SURGE_FLOOR - 1e-9 <= float(actual) <= SURGE_CEILING + 1e-9, (
        f"surge_multiplier {actual} escaped the clamp"
    )
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"surge_multiplier: expected {expected}, got {actual}"
    )


# ─── Ordering assertions ─────────────────────────────────────────────────────


def assert_sequence_indexes(tasks_in_expected_order):
    """Retrieval indexes are one-based positions in the retrieval sequence."""
    for position, task in enumerate(tasks_in_expected_order, start=1):
        assert task["sequence_index"] == position, (
            f"task {task['id']} should carry sequence_index {position}, "
            f"got {task['sequence_index']}"
        )


def assert_load_sequence(wave, expected_tote_ids):
    actual = wave["load_sequence"]
    assert actual == list(expected_tote_ids), (
        f"load_sequence: expected {list(expected_tote_ids)}, got {actual}"
    )
    assert len(set(actual)) == len(actual), "load_sequence repeats a tote"

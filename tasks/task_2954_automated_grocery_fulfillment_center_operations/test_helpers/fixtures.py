"""Setup builders.

Every function here performs setup only, through the public API, and reads its
responses with the lenient :func:`get_success_data` so that a broken setup step
reports itself clearly instead of failing an unrelated assertion later.

The builders come in two layers.  The lower layer creates one resource each.
The upper layer stitches those into the recurring situations the suite needs:
a plant, a booked basket, a wave in the middle of picking, a short line with a
substitution proposal waiting on it.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    assign_dock_payload,
    assign_tote_payload,
    audit_count_entry,
    audit_counts_payload,
    capacity_units_payload,
    catchweight_sku_payload,
    clock_payload,
    complete_pick_task_payload,
    customer_account_payload,
    customer_order_payload,
    delivery_route_payload,
    delivery_slot_payload,
    delivery_wave_payload,
    dock_bay_payload,
    grid_zone_payload,
    inventory_sku_payload,
    maintenance_window_payload,
    order_line_payload,
    pick_station_payload,
    slot_booking_payload,
    slot_orders_payload,
    substitution_proposal_payload,
    tote_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    GRID_ENGINEER_HEADERS,
    PICK_OPERATOR_HEADERS,
    WAVE_PLANNER_HEADERS,
    make_customer_headers,
)
from .types import TemperatureZone


# ─── Logical clock ───────────────────────────────────────────────────────────


def set_clock(client, current_utc):
    """Move the logical clock to a specific instant."""
    return get_success_data(client.set_clock(clock_payload(current_utc), ADMIN_HEADERS))


def reset_clock(client):
    return set_clock(client, DEFAULT_CLOCK_UTC)


# ─── Standing plant ──────────────────────────────────────────────────────────


def create_delivery_route(client, **overrides):
    return get_success_data(
        client.create_delivery_route(delivery_route_payload(**overrides), ADMIN_HEADERS)
    )


def create_dock_bay(client, **overrides):
    return get_success_data(
        client.create_dock_bay(dock_bay_payload(**overrides), ADMIN_HEADERS)
    )


def create_grid_zone(client, **overrides):
    return get_success_data(
        client.create_grid_zone(grid_zone_payload(**overrides), ADMIN_HEADERS)
    )


def create_pick_station(client, **overrides):
    return get_success_data(
        client.create_pick_station(pick_station_payload(**overrides), ADMIN_HEADERS)
    )


def create_inventory_sku(client, grid_zone_id, **overrides):
    return get_success_data(
        client.create_inventory_sku(
            inventory_sku_payload(grid_zone_id, **overrides), ADMIN_HEADERS
        )
    )


def create_catchweight_sku(client, grid_zone_id, **overrides):
    return get_success_data(
        client.create_inventory_sku(
            catchweight_sku_payload(grid_zone_id, **overrides), ADMIN_HEADERS
        )
    )


def create_customer_account(client, home_route_id, **overrides):
    return get_success_data(
        client.create_customer_account(
            customer_account_payload(home_route_id, **overrides), ADMIN_HEADERS
        )
    )


def create_delivery_slot(client, route_id, **overrides):
    return get_success_data(
        client.create_delivery_slot(
            delivery_slot_payload(route_id, **overrides), ADMIN_HEADERS
        )
    )


def create_maintenance_window(client, grid_zone_id, **overrides):
    return get_success_data(
        client.create_maintenance_window(
            maintenance_window_payload(grid_zone_id, **overrides),
            GRID_ENGINEER_HEADERS,
        )
    )


def activate_maintenance_window(client, window_id):
    return get_success_data(
        client.activate_maintenance_window(window_id, GRID_ENGINEER_HEADERS)
    )


def complete_maintenance_window(client, window_id):
    return get_success_data(
        client.complete_maintenance_window(window_id, GRID_ENGINEER_HEADERS)
    )


def record_audit_counts(client, grid_zone_id, counts):
    """``counts`` is a list of ``(sku_id, counted_units)`` pairs."""
    entries = [audit_count_entry(sku_id, units) for sku_id, units in counts]
    return get_success_data(
        client.record_audit_counts(
            grid_zone_id, audit_counts_payload(entries), GRID_ENGINEER_HEADERS
        )
    )


def build_plant(client, temperature_zone=TemperatureZone.AMBIENT.value, **overrides):
    """A route, a dock bay, a grid zone and a pick station that can serve it."""
    route = create_delivery_route(client, **overrides.pop("route", {}))
    bay = create_dock_bay(client, **overrides.pop("bay", {}))
    zone = create_grid_zone(
        client, temperature_zone=temperature_zone, **overrides.pop("zone", {})
    )
    station = create_pick_station(client, **overrides.pop("station", {}))
    return {"route": route, "bay": bay, "zone": zone, "station": station}


# ─── Baskets, lines and bookings ─────────────────────────────────────────────


def create_customer_order(client, customer_account_id, **overrides):
    """Open a basket as the shopper who owns it."""
    return get_success_data(
        client.create_customer_order(
            customer_order_payload(**overrides),
            make_customer_headers(customer_account_id),
        )
    )


def add_order_line(client, customer_account_id, order_id, sku_id, **overrides):
    return get_success_data(
        client.add_order_line(
            order_id,
            order_line_payload(sku_id, **overrides),
            make_customer_headers(customer_account_id),
        )
    )


def read_order(client, customer_account_id, order_id):
    return get_success_data(
        client.get_customer_order(order_id, make_customer_headers(customer_account_id))
    )


def read_order_as_admin(client, order_id):
    return get_success_data(client.get_customer_order(order_id, ADMIN_HEADERS))


def read_order_line(client, customer_account_id, line_id):
    return get_success_data(
        client.get_order_line(line_id, make_customer_headers(customer_account_id))
    )


def create_slot_booking(client, customer_account_id, slot_id, order_id, **overrides):
    """Book a slot, reading the order's current version for the guard."""
    headers = make_customer_headers(customer_account_id)
    order = get_success_data(client.get_customer_order(order_id, headers))
    payload = slot_booking_payload(slot_id, order_id, order["version"], **overrides)
    return get_success_data(client.create_slot_booking(payload, headers))


def confirm_slot_booking(client, customer_account_id, booking_id):
    return get_success_data(
        client.confirm_slot_booking(
            booking_id, make_customer_headers(customer_account_id)
        )
    )


def release_capacity(client, slot_id, units):
    return get_success_data(
        client.release_capacity(slot_id, capacity_units_payload(units), ADMIN_HEADERS)
    )


def withhold_capacity(client, slot_id, units):
    return get_success_data(
        client.withhold_capacity(slot_id, capacity_units_payload(units), ADMIN_HEADERS)
    )


def cancel_customer_order(client, customer_account_id, order_id):
    return get_success_data(
        client.cancel_customer_order(
            order_id, make_customer_headers(customer_account_id)
        )
    )


def build_shopper_with_basket(
    client,
    route_id,
    sku_ids,
    ordered_qty=1,
    loyalty_tier=None,
    stop_distance_km=5.00,
    **account_overrides,
):
    """An account plus a DRAFT basket carrying one line per SKU given."""
    if loyalty_tier is not None:
        account_overrides["loyalty_tier"] = loyalty_tier
    account = create_customer_account(client, route_id, **account_overrides)
    order = create_customer_order(
        client, account["id"], stop_distance_km=stop_distance_km
    )
    lines = []
    for sku_id in sku_ids:
        lines.append(
            add_order_line(
                client, account["id"], order["id"], sku_id, ordered_qty=ordered_qty
            )
        )
    return {"account": account, "order": order, "lines": lines}


# ─── Waves, docks and totes ──────────────────────────────────────────────────


def create_delivery_wave(client, route_id, delivery_slot_id, **overrides):
    return get_success_data(
        client.create_delivery_wave(
            delivery_wave_payload(route_id, delivery_slot_id, **overrides),
            WAVE_PLANNER_HEADERS,
        )
    )


def slot_order_into_wave(client, wave_id, order_id, headers=WAVE_PLANNER_HEADERS):
    return get_success_data(
        client.slot_orders(wave_id, slot_orders_payload(order_id), headers)
    )


def assign_dock(
    client, wave_id, dock_bay_id, load_start, load_end, headers=WAVE_PLANNER_HEADERS
):
    return get_success_data(
        client.assign_dock(
            wave_id, assign_dock_payload(dock_bay_id, load_start, load_end), headers
        )
    )


def start_picking(client, wave_id, headers=WAVE_PLANNER_HEADERS):
    return get_success_data(client.start_picking(wave_id, headers))


def consolidate_wave(client, wave_id, headers=WAVE_PLANNER_HEADERS):
    return get_success_data(client.consolidate_wave(wave_id, headers))


def compute_loading_sequence(client, wave_id, headers=WAVE_PLANNER_HEADERS):
    return get_success_data(client.compute_loading_sequence(wave_id, headers))


def dispatch_wave(client, wave_id, headers):
    """Dispatch must be driven by a planner other than the one who consolidated."""
    return get_success_data(client.dispatch_wave(wave_id, headers))


def read_wave(client, wave_id, headers=WAVE_PLANNER_HEADERS):
    return get_success_data(client.get_delivery_wave(wave_id, headers))


def create_tote(client, wave_id, pick_station_id, **overrides):
    return get_success_data(
        client.create_tote(
            tote_payload(wave_id, pick_station_id, **overrides), PICK_OPERATOR_HEADERS
        )
    )


def seal_tote(client, tote_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(client.seal_tote(tote_id, headers))


def unseal_tote(client, tote_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(client.unseal_tote(tote_id, headers))


def read_tote(client, tote_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(client.get_tote(tote_id, headers))


def read_pick_station(client, station_id):
    return get_success_data(client.get_pick_station(station_id, ADMIN_HEADERS))


def read_grid_zone(client, zone_id):
    return get_success_data(client.get_grid_zone(zone_id, ADMIN_HEADERS))


def read_inventory_sku(client, sku_id):
    return get_success_data(client.get_inventory_sku(sku_id, ADMIN_HEADERS))


def read_delivery_slot(client, slot_id):
    return get_success_data(client.get_delivery_slot(slot_id, ADMIN_HEADERS))


def read_slot_booking(client, booking_id, headers=ADMIN_HEADERS):
    return get_success_data(client.get_slot_booking(booking_id, headers))


# ─── Retrieval tasks ─────────────────────────────────────────────────────────


def list_pick_tasks(client, headers=PICK_OPERATOR_HEADERS, **params):
    body = get_success_data(client.list_pick_tasks(headers, params=params or None))
    return body


def pick_task_for_line(client, order_line_id, headers=PICK_OPERATOR_HEADERS):
    """Retrieval tasks appear in no creation response, so they are looked up."""
    tasks = list_pick_tasks(client, headers, order_line_id=order_line_id)
    active = [t for t in tasks if t["status"] in ("QUEUED", "RETRIEVING")]
    pool = active or tasks
    assert pool, f"no retrieval task exists for order line {order_line_id}"
    return sorted(pool, key=lambda t: t["created_at"])[-1]


def pick_tasks_for_wave(client, wave_id, headers=PICK_OPERATOR_HEADERS):
    """Every retrieval task of the wave, in retrieval-sequence order."""
    orders = get_success_data(
        client.list_customer_orders(headers, params={"wave_id": wave_id})
    )
    tasks = []
    for order in orders:
        lines = get_success_data(
            client.list_order_lines(headers, params={"order_id": order["id"]})
        )
        for line in lines:
            tasks.extend(
                list_pick_tasks(client, headers, order_line_id=line["id"])
            )
    return sorted(tasks, key=lambda t: t["sequence_index"])


def assign_tote(client, task_id, tote_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(
        client.assign_tote(task_id, assign_tote_payload(tote_id), headers)
    )


def start_retrieval(client, task_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(client.start_retrieval(task_id, headers))


def complete_pick_task(
    client, task_id, picked_units, headers=PICK_OPERATOR_HEADERS, **overrides
):
    return get_success_data(
        client.complete_pick_task(
            task_id, complete_pick_task_payload(picked_units, **overrides), headers
        )
    )


def cancel_pick_task(client, task_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(client.cancel_pick_task(task_id, headers))


def read_pick_task(client, task_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(client.get_pick_task(task_id, headers))


# ─── Substitution proposals ──────────────────────────────────────────────────


def list_substitution_proposals(client, headers=PICK_OPERATOR_HEADERS, **params):
    return get_success_data(
        client.list_substitution_proposals(headers, params=params or None)
    )


def proposal_for_line(client, order_line_id, headers=PICK_OPERATOR_HEADERS):
    """The automatically created DRAFT proposal is discoverable only by filter."""
    proposals = list_substitution_proposals(
        client, headers, order_line_id=order_line_id
    )
    assert proposals, f"no substitution proposal exists for line {order_line_id}"
    return sorted(proposals, key=lambda p: p["round_no"])[-1]


def create_substitution_proposal(
    client, order_line_id, substitute_sku_id, expected_order_line_version, **overrides
):
    return get_success_data(
        client.create_substitution_proposal(
            substitution_proposal_payload(
                order_line_id,
                substitute_sku_id,
                expected_order_line_version,
                **overrides,
            ),
            PICK_OPERATOR_HEADERS,
        )
    )


def propose_substitution(client, proposal_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(client.propose_substitution(proposal_id, headers))


def approve_substitution(client, customer_account_id, proposal_id):
    return get_success_data(
        client.approve_substitution(
            proposal_id, make_customer_headers(customer_account_id)
        )
    )


def decline_substitution(client, customer_account_id, proposal_id):
    return get_success_data(
        client.decline_substitution(
            proposal_id, make_customer_headers(customer_account_id)
        )
    )


def expire_substitution(client, proposal_id, headers=WAVE_PLANNER_HEADERS):
    return get_success_data(client.expire_substitution(proposal_id, headers))


def accept_shortage(client, customer_account_id, line_id):
    return get_success_data(
        client.accept_shortage(line_id, make_customer_headers(customer_account_id))
    )


def read_substitution_proposal(client, proposal_id, headers=PICK_OPERATOR_HEADERS):
    return get_success_data(client.get_substitution_proposal(proposal_id, headers))


# ─── Composite situations ────────────────────────────────────────────────────


def build_confirmed_order(
    client,
    route_id,
    slot_id,
    sku_ids,
    ordered_qty=1,
    units=1,
    loyalty_tier=None,
    stop_distance_km=5.00,
    **account_overrides,
):
    """An account whose basket holds a CONFIRMED booking on the given slot.

    The order comes back at fulfillment_status SLOTTED and billing_status
    AUTHORIZED, which is the state order slotting into a wave requires.
    """
    basket = build_shopper_with_basket(
        client,
        route_id,
        sku_ids,
        ordered_qty=ordered_qty,
        loyalty_tier=loyalty_tier,
        stop_distance_km=stop_distance_km,
        **account_overrides,
    )
    account = basket["account"]
    booking = create_slot_booking(
        client, account["id"], slot_id, basket["order"]["id"], units=units
    )
    booking = confirm_slot_booking(client, account["id"], booking["id"])
    order = read_order(client, account["id"], basket["order"]["id"])
    return {
        "account": account,
        "order": order,
        "lines": basket["lines"],
        "booking": booking,
    }


def build_waved_order(
    client,
    route_id,
    slot_id,
    sku_ids,
    ordered_qty=1,
    units=1,
    wave=None,
    loyalty_tier=None,
    stop_distance_km=5.00,
    **account_overrides,
):
    """A confirmed order attached to a FORMING wave on the same slot."""
    confirmed = build_confirmed_order(
        client,
        route_id,
        slot_id,
        sku_ids,
        ordered_qty=ordered_qty,
        units=units,
        loyalty_tier=loyalty_tier,
        stop_distance_km=stop_distance_km,
        **account_overrides,
    )
    if wave is None:
        wave = create_delivery_wave(client, route_id, slot_id)
    wave = slot_order_into_wave(client, wave["id"], confirmed["order"]["id"])
    confirmed["wave"] = wave
    confirmed["order"] = read_order(
        client, confirmed["account"]["id"], confirmed["order"]["id"]
    )
    return confirmed


def build_picking_wave(
    client,
    route_id,
    slot_id,
    sku_ids,
    ordered_qty=1,
    units=1,
    loyalty_tier=None,
    stop_distance_km=5.00,
    **account_overrides,
):
    """A wave in PICKING with one member order and its retrieval tasks created."""
    waved = build_waved_order(
        client,
        route_id,
        slot_id,
        sku_ids,
        ordered_qty=ordered_qty,
        units=units,
        loyalty_tier=loyalty_tier,
        stop_distance_km=stop_distance_km,
        **account_overrides,
    )
    waved["wave"] = start_picking(client, waved["wave"]["id"])
    waved["order"] = read_order(
        client, waved["account"]["id"], waved["order"]["id"]
    )
    waved["tasks"] = pick_tasks_for_wave(client, waved["wave"]["id"])
    return waved


def drive_task_to_retrieving(
    client, task_id, wave_id, pick_station_id, temperature_zone, tote=None
):
    """Open a tote of the right class, bind the task to it and send the bots."""
    if tote is None:
        tote = create_tote(
            client, wave_id, pick_station_id, temperature_zone=temperature_zone
        )
    assign_tote(client, task_id, tote["id"])
    task = start_retrieval(client, task_id)
    return {"tote": tote, "task": task}


def build_short_line(
    client,
    route_id,
    slot_id,
    sku_ids,
    ordered_qty=2,
    picked_units=1,
    temperature_zone=TemperatureZone.AMBIENT.value,
    **kwargs,
):
    """Drive one line all the way to a short pick.

    The returned dict carries the wave, the order, the line, the tote and the
    retrieval task that came back short.  A substitution proposal exists on the
    line only when the catalogue offered a comparable substitute.
    """
    picking = build_picking_wave(
        client, route_id, slot_id, sku_ids, ordered_qty=ordered_qty, **kwargs
    )
    task = picking["tasks"][0]
    driven = drive_task_to_retrieving(
        client,
        task["id"],
        picking["wave"]["id"],
        task["pick_station_id"],
        temperature_zone,
    )
    picking["tote"] = driven["tote"]
    picking["task"] = complete_pick_task(client, task["id"], picked_units)
    picking["line"] = read_order_line(
        client, picking["account"]["id"], picking["lines"][0]["id"]
    )
    picking["order"] = read_order(
        client, picking["account"]["id"], picking["order"]["id"]
    )
    picking["wave"] = read_wave(client, picking["wave"]["id"])
    return picking


def build_substitution_group(
    client, grid_zone_id, group_code, prices, temperature_zone=None, **overrides
):
    """A family of interchangeable SKUs sharing one substitution group code."""
    skus = []
    for price in prices:
        payload_overrides = dict(overrides)
        payload_overrides["substitution_group_code"] = group_code
        payload_overrides["unit_price_cents"] = price
        if temperature_zone is not None:
            payload_overrides["temperature_zone"] = temperature_zone
        skus.append(create_inventory_sku(client, grid_zone_id, **payload_overrides))
    return skus

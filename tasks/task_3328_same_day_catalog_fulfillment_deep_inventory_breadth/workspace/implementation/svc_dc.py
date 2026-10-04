"""Distribution center, logical clock, posture and the daily cutoff roll."""

from common import invalid_request, require_int, require_str
from calculations import (compute_cutoff_passed, derive_posture,
                          inventory_positioning_decision)
from db import iso_millis, local_datetime
from errors import not_found

REGIONS = ("NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST")

RAISE_ACTIONS = ("RAISE", "OPEN", "SET", "ADD", "HOLD")
CLEAR_ACTIONS = ("CLEAR", "RELEASE", "CLOSE", "REMOVE", "RESOLVE", "UNHOLD")


def recompute_local_fields(dc, store):
    offset = dc.get("utc_offset_minutes", 0) or 0
    local_dt = local_datetime(store.current_utc, offset)
    dc["local_current_time"] = local_dt.strftime("%H:%M:%S")
    dc["cutoff_passed"] = compute_cutoff_passed(local_dt, dc.get("local_cutoff_time", "00:00:00"))


def recompute_all_local_fields(store):
    for dc in store.distribution_centers.values():
        recompute_local_fields(dc, store)


def local_dt_of(dc, store):
    return local_datetime(store.current_utc, dc.get("utc_offset_minutes", 0) or 0)


def has_open_hold(store, dc_id):
    return len(store.dc_holds.get(dc_id, [])) > 0


def refresh_posture(dc, store):
    """Re-derive OPEN | RESTRICTED | LOCKDOWN from holds and inbound reserve."""
    dc["operations_posture"] = derive_posture(dc, has_open_hold(store, dc["id"]))
    return dc["operations_posture"]


def inbound_headroom(dc):
    return (dc.get("inbound_capacity_units", 0) or 0) - (dc.get("inbound_reserved_units", 0) or 0)


# ------------------------------------------------------------------- clock

def set_current_utc(store, current_utc):
    """Move the logical clock and recompute every DC's local time and flag."""
    store.current_utc = current_utc
    recompute_all_local_fields(store)
    store.dc_local_times = {
        dc["code"]: dc["local_current_time"]
        for dc in sorted(store.distribution_centers.values(),
                         key=lambda d: (d.get("code", ""), d.get("created_at", "")))
    }
    return clock_tick_payload(store)


def clock_tick_payload(store):
    return {
        "current_utc": iso_millis(store.current_utc),
        "dc_local_times": dict(store.dc_local_times),
    }


# ------------------------------------------------------- create / read DCs

def validate_code(code):
    if not (2 <= len(code) <= 8) or not code.isupper():
        raise invalid_request("Field 'code' must be 2-8 uppercase characters.")
    return code


def create_dc(store, body):
    code = validate_code(require_str(body, "code"))
    if any(d.get("code") == code for d in store.distribution_centers.values()):
        raise invalid_request("Field 'code' must be unique.")

    region = require_str(body, "region")
    if region not in REGIONS:
        raise invalid_request("Field 'region' must be one of %s." % " | ".join(REGIONS))

    local_zone = require_str(body, "local_zone")
    if any(d.get("local_zone") == local_zone for d in store.distribution_centers.values()):
        raise invalid_request("Field 'local_zone' must be unique across distribution centers.")

    local_cutoff_time = require_str(body, "local_cutoff_time")
    _validate_hhmmss(local_cutoff_time, "local_cutoff_time")
    utc_offset_minutes = require_int(body, "utc_offset_minutes", -480, 840)
    inbound_capacity_units = require_int(body, "inbound_capacity_units", 0)
    transit_seconds = require_int(body, "transit_seconds", 0)

    record = {
        "code": code,
        "region": region,
        "local_zone": local_zone,
        "local_cutoff_time": local_cutoff_time,
        "local_current_time": "00:00:00",
        "utc_offset_minutes": utc_offset_minutes,
        "inbound_capacity_units": inbound_capacity_units,
        "transit_seconds": transit_seconds,
        "cutoff_passed": False,
        "cutoff_sequence_index": 0,
        "inbound_reserved_units": 0,
        "operations_posture": "OPEN",
    }
    store.stamp(record)
    store.distribution_centers[record["id"]] = record
    recompute_local_fields(record, store)
    refresh_posture(record, store)
    return record


def _validate_hhmmss(value, field):
    parts = value.split(":")
    if len(parts) != 3:
        raise invalid_request("Field '%s' must be HH:MM:SS." % field)
    try:
        hh, mm, ss = (int(p) for p in parts)
    except ValueError:
        raise invalid_request("Field '%s' must be HH:MM:SS." % field)
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        raise invalid_request("Field '%s' must be a valid 24h wall-clock time." % field)


def get_dc(store, dc_id):
    record = store.distribution_centers.get(dc_id)
    if record is None:
        raise not_found("ERR_DC_NOT_FOUND", "No distribution center exists for id '%s'." % dc_id)
    return record


# ------------------------------------------------------------ cutoff roll

def roll_cutoff(store, dc):
    flags = _positioning_flags(dc, store)
    for row in store.stock_rows.values():
        if row.get("dc_id") == dc["id"]:
            row["positioning_flag"] = flags.get(row.get("item_id"), "UNDERSTOCKED")
    dc["cutoff_sequence_index"] = (dc.get("cutoff_sequence_index", 0) or 0) + 1
    # The posture is derived here too, so the hold-driven cascade fires on the
    # same automatic basis as it does on reeducate (PRD section 3.8).
    before = dc.get("operations_posture")
    refresh_posture(dc, store)
    if dc["operations_posture"] == "LOCKDOWN" and before != "LOCKDOWN":
        _cascade_lockdown(dc, store)
    elif dc["operations_posture"] != "LOCKDOWN" and before == "LOCKDOWN":
        _cascade_release(dc, store)
    store.touch(dc)
    return dc


def _positioning_flags(dc, store):
    """One classification for the whole DC, applied to every stock row."""
    if not any(r.get("dc_id") == dc["id"] for r in store.stock_rows.values()):
        return {}
    result = inventory_positioning_decision(dc["id"], store)
    return {row.get("item_id"): result
            for row in store.stock_rows.values() if row.get("dc_id") == dc["id"]}


# ---------------------------------------------------- quality / damage hold

def reeducate(store, dc, body):
    action = require_str(body, "hold_action").strip().upper()
    raise_hold = action in RAISE_ACTIONS
    if not raise_hold and action not in CLEAR_ACTIONS:
        raise invalid_request("Field 'hold_action' must raise or clear the hold.")

    holds = store.dc_holds.setdefault(dc["id"], [])
    if raise_hold:
        holds.append({"reason": body.get("reason"), "raised_at": store.now_iso()})
        refresh_posture(dc, store)
        if dc["operations_posture"] == "LOCKDOWN":
            _cascade_lockdown(dc, store)
    else:
        if holds:
            holds.pop()
        refresh_posture(dc, store)
        if dc["operations_posture"] != "LOCKDOWN":
            _cascade_release(dc, store)
    store.touch(dc)
    return dc


def _cascade_lockdown(dc, store):
    """Four hops: hold the shipments, unwind picks back to ALLOCATED."""
    for shipment in sorted(store.shipments.values(), key=lambda s: s.get("created_at", "")):
        if shipment.get("dc_id") != dc["id"] or shipment.get("shipment_status") != "CUTOFF_CONFIRMED":
            continue
        shipment["shipment_status"] = "HELD"
        store.touch(shipment)
        order = store.orders.get(shipment.get("order_id"))
        if order is None:
            continue
        # A shipment in CUTOFF_CONFIRMED implies the order had already moved past
        # picking, so the reversion must also cover the SHIPPED value — guarding on
        # PICKED alone would leave the hop dead for every certified shipment.
        if order.get("fulfillment_status") in ("PICKED", "SHIPPED"):
            order["fulfillment_status"] = "ALLOCATED"
            store.touch(order)
        for line in _order_lines(order["id"], store):
            if line.get("line_status") == "PICKED":
                line["line_status"] = "ALLOCATED"
                store.touch(line)
            task = _task_for_line(line["id"], store)
            if task is not None:
                task["shortage_disposition"] = "NONE"
                task["pick_status"] = "PICKING"
                store.touch(task)


def _cascade_release(dc, store):
    """Two hops: release the held shipments and restore PICKED orders."""
    for shipment in sorted(store.shipments.values(), key=lambda s: s.get("created_at", "")):
        if shipment.get("dc_id") != dc["id"] or shipment.get("shipment_status") != "HELD":
            continue
        shipment["shipment_status"] = "CUTOFF_CONFIRMED"
        store.touch(shipment)
        order = store.orders.get(shipment.get("order_id"))
        if order is None:
            continue
        if order.get("fulfillment_status") == "ALLOCATED":
            order["fulfillment_status"] = "PICKED"
            store.touch(order)


def _order_lines(order_id, store):
    return [l for l in store.order_lines.values() if l.get("order_id") == order_id]


def _task_for_line(line_id, store):
    for task in store.pick_tasks.values():
        if task.get("line_id") == line_id:
            return task
    return None
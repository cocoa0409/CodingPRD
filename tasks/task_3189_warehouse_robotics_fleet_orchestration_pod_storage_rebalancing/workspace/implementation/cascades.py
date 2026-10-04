"""Cascades: posture changes, clock-driven sweeps, maintenance activation, pod recomputes."""

from datetime import timedelta

from db import store
from models import base_entity, bump, fmt_iso, new_id, now_iso


def recompute_pod_slots_used(pod):
    count = sum(
        1
        for s in store.inventory_slots.values()
        if s["pod_id"] == pod["id"] and s["quantity"] > 0
    )
    pod["slots_used"] = count


def recompute_sku_counters(sku):
    on_hand = 0
    reserved = 0
    for s in store.inventory_slots.values():
        if s["sku_id"] != sku["id"]:
            continue
        on_hand += s["quantity"]
        reserved += s["quantity_reserved"]
    sku["total_units_on_hand"] = on_hand
    sku["total_units_reserved"] = reserved


def find_slot(pod_id, sku_id):
    for s in store.inventory_slots.values():
        if s["pod_id"] == pod_id and s["sku_id"] == sku_id:
            return s
    return None


def park_zone_units(zone_id, skip_statuses=frozenset()):
    """ACTIVE units homed in zone -> PARKED (posture cascade)."""
    for unit in store.drive_units.values():
        if unit["home_zone_id"] != zone_id:
            continue
        if unit["status"] in skip_statuses:
            continue
        if unit["status"] == "ACTIVE":
            unit["status"] = "PARKED"
            bump(unit)


def freeze_zone_units(zone_id):
    """FROZEN cascade: every unit not CHARGING/MAINTENANCE/STRANDED -> PARKED."""
    for unit in store.drive_units.values():
        if unit["home_zone_id"] != zone_id:
            continue
        if unit["status"] in {"CHARGING", "MAINTENANCE", "STRANDED", "RETIRED", "PARKED"}:
            continue
        unit["status"] = "PARKED"
        bump(unit)


def unpark_zone_units(zone_id):
    for unit in store.drive_units.values():
        if unit["home_zone_id"] == zone_id and unit["status"] == "PARKED":
            unit["status"] = "ACTIVE"
            bump(unit)


def maybe_auto_preventive_window(unit):
    """On charge_cycle_count reaching threshold, auto-create a PREVENTIVE window."""
    if unit["charge_cycle_count"] < 5:
        return None
    if unit["charge_cycle_count"] % 5 != 0:
        return None
    starts = store.clock + timedelta(minutes=60)
    ends = starts + timedelta(minutes=30)
    window = base_entity()
    window.update(
        {
            "drive_unit_id": unit["id"],
            "starts_at": fmt_iso(starts),
            "ends_at": fmt_iso(ends),
            "status": "SCHEDULED",
            "kind": "PREVENTIVE",
            "_starts_dt": starts,
            "_ends_dt": ends,
        }
    )
    store.maintenance_windows[window["id"]] = window
    return window


def _activate_window(window):
    """SCHEDULED -> ACTIVE; pull the covered unit into MAINTENANCE."""
    window["status"] = "ACTIVE"
    bump(window)
    unit = store.drive_units.get(window["drive_unit_id"])
    if unit is None:
        return
    if unit["status"] == "CHARGING":
        # Abort any OPEN session on this unit.
        for session in store.charging_sessions.values():
            if session["drive_unit_id"] == unit["id"] and session["status"] == "OPEN":
                session["status"] = "ABORTED"
                session["ended_at"] = now_iso()
                bump(session)
                charger = store.chargers.get(session["charger_id"])
                if charger is not None:
                    charger["slots_in_use"] = max(0, charger["slots_in_use"] - 1)
                    bump(charger)
        unit["status"] = "MAINTENANCE"
        bump(unit)
    elif unit["status"] == "ACTIVE":
        unit["status"] = "MAINTENANCE"
        bump(unit)


def clock_sweep():
    """Re-evaluate all time-driven cascades after a clock advance (PRD 2.4)."""
    now = store.clock
    # MaintenanceWindow activation: SCHEDULED and now in [starts_at, ends_at).
    for window in list(store.maintenance_windows.values()):
        if window["status"] != "SCHEDULED":
            continue
        if window["_starts_dt"] <= now < window["_ends_dt"]:
            _activate_window(window)
    # CustomerOrder CUTOFF_MISSED: strictly greater than cutoff while RECEIVED.
    for order in store.orders.values():
        if order["status"] != "RECEIVED":
            continue
        cutoff = order.get("_cutoff_dt")
        if cutoff is not None and now > cutoff:
            order["status"] = "CUTOFF_MISSED"
            bump(order)


def entity_out(entity):
    """Strip private _ keys for serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def list_out(entities):
    return [entity_out(e) for e in entities]


def cancel_pick_task_with_release(task):
    """Cancel a CREATED or QUEUED pick task with full reservation release."""
    was_queued = task["status"] == "QUEUED"
    task["status"] = "CANCELLED"
    bump(task)
    if not was_queued:
        return
    station = store.pick_stations.get(task["station_id"])
    if station is not None:
        station["queue_length"] = max(0, station["queue_length"] - 1)
        bump(station)
    pod = store.pods.get(task["pod_id"])
    if pod is not None and pod["status"] == "RESERVED":
        pod["status"] = "IN_STORAGE"
        bump(pod)
    order = store.orders.get(task["order_id"])
    line = store.order_lines.get(task["line_id"])
    sku_id = line["sku_id"] if line is not None else None
    slot = find_slot(task["pod_id"], sku_id) if sku_id else None
    if slot is not None:
        slot["quantity_reserved"] = max(0, slot["quantity_reserved"] - task["quantity"])
        bump(slot)
    if sku_id:
        sku = store.skus.get(sku_id)
        if sku is not None:
            recompute_sku_counters(sku)
            bump(sku)


def fail_pick_task_for_stranded(task):
    """In-flight task FAILED when its DriveUnit becomes STRANDED (PRD 3.6)."""
    task["status"] = "FAILED"
    bump(task)
    station = store.pick_stations.get(task["station_id"])
    if station is not None:
        station["queue_length"] = max(0, station["queue_length"] - 1)
        bump(station)
    pod = store.pods.get(task["pod_id"])
    if pod is not None:
        pod["status"] = "QUARANTINED"
        bump(pod)
    line = store.order_lines.get(task["line_id"])
    sku_id = line["sku_id"] if line is not None else None
    slot = find_slot(task["pod_id"], sku_id) if sku_id else None
    if slot is not None:
        slot["quantity_reserved"] = max(0, slot["quantity_reserved"] - task["quantity"])
        bump(slot)
    if sku_id:
        sku = store.skus.get(sku_id)
        if sku is not None:
            recompute_sku_counters(sku)
            bump(sku)

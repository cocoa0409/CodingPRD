"""Appointment transitions and the periodic operations sweep (PRD 3.5, 3.10)."""

from constants import MISSED_GRACE_MINUTES, parse_instant, utc
from db import clock_now, db, mint_id, touch
from errors import ApiError
from services.common import append_status_event, load_accessorial_total
from services.carriers import sync_carrier
from services.common import live_quotes_for
from services.docks import (
    close_detention, committed_today_count, open_detention, position_is_free,
    hold_dock, release_dock,
)
from services.common import live_quotes_for as _live_quotes_for
from services.carriers import sync_carrier


def get_slot(appointment_id):
    row = db.appointments.get(appointment_id)
    if row is None:
        raise ApiError("ERR_APPOINTMENT_NOT_FOUND")
    return row


def reschedule(appointment_id, body):
    """PRD 3.5 — a reschedule can only bring an appointment forward."""
    slot = get_slot(appointment_id)
    if slot["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    window_start = parse_instant(body.get("window_start"), "window_start")
    window_end = parse_instant(body.get("window_end"), "window_end")
    facility = db.facilities[slot["facility_id"]]

    if not utc(window_start) < utc(slot["window_start"]):
        raise ApiError("ERR_RESCHEDULE_ONLY_EARLIER")

    requested_position = body.get("dock_position")
    if requested_position is None:
        requested_position = slot["dock_position"]
    try:
        position = int(requested_position)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "dock_position must be an integer.")
    capacity = int(facility["dock_capacity"])
    if position < 1 or position > capacity:
        raise ApiError("ERR_INVALID_REQUEST",
                       "dock_position must be between 1 and the facility capacity.")
    if not position_is_free(facility, position, window_start, window_end,
                            exclude_appointment_id=slot["id"]):
        raise ApiError("ERR_APPOINTMENT_OVERLAP")
    if committed_today_count(facility) >= capacity:
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED")

    slot["window_start"] = window_start
    slot["window_end"] = window_end
    slot["dock_position"] = position
    slot["status"] = "IN_PROGRESS"
    touch(slot)
    open_detention(slot)
    return slot


def complete(appointment_id):
    slot = get_slot(appointment_id)
    if slot["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    slot["status"] = "COMPLETED"
    touch(slot)
    event = None
    for row in db.detention_events.values():
        if row["appointment_id"] == slot["id"] and row["status"] == "OPEN":
            event = row
            break
    if event is not None:
        close_detention(event)
    load = db.loads.get(slot["load_id"]) if slot["load_id"] else None
    if load is not None:
        load["accessorial_total_cents"] = load_accessorial_total(load["id"])
        touch(load)
    return slot


def cancel(appointment_id):
    slot = get_slot(appointment_id)
    if slot["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    slot["status"] = "CANCELLED"
    touch(slot)
    facility = db.facilities[slot["facility_id"]]
    release_dock(facility)
    return slot


def restore(appointment_id):
    slot = get_slot(appointment_id)
    if slot["status"] != "CANCELLED":
        raise ApiError("ERR_INVALID_STATE")
    facility = db.facilities[slot["facility_id"]]
    if committed_today_count(facility) >= int(facility["dock_capacity"]):
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED")
    slot["status"] = "SCHEDULED"
    touch(slot)
    hold_dock(facility)
    return slot


def appointment_list(rows, filters):
    result = list(rows)
    for field in ("facility_id", "load_id", "carrier_id", "status", "slot_kind"):
        value = filters.get(field)
        if value is None or value == "":
            continue
        result = [row for row in result if row.get(field) == value]
    scheduled_date = filters.get("scheduled_date")
    if scheduled_date:
        day = parse_instant(scheduled_date, "scheduled_date")
        result = [row for row in result
                  if utc(row["scheduled_date"]).date() == utc(day).date()]
    result.sort(key=lambda row: row["created_at"])
    return result


def operations_sweep():
    """The batch form of the clock re-evaluation (PRD 3.10)."""
    now = clock_now()
    swept_appointments = []
    # Clock-relative quote expiry is the first thing the sweep re-evaluates, so a
    # quote whose deadline the clock has passed no longer counts as live.
    from services.common import expire_all_quotes
    expire_all_quotes()

    def overdue(slot):
        return utc(now) > utc(slot["window_end"]) + _minutes(MISSED_GRACE_MINUTES)

    in_progress = [slot for slot in db.appointments.values() if slot["status"] == "IN_PROGRESS"]
    in_progress.sort(key=lambda row: (row["window_end"], row["created_at"]))
    for slot in in_progress:
        if not overdue(slot):
            continue
        slot["status"] = "MISSED"
        touch(slot)
        swept_appointments.append(slot["id"])
        if slot["slot_kind"] == "PICKUP" and slot["load_id"]:
            from services.tracking import evaluate_breach
            load = db.loads.get(slot["load_id"])
            if load is not None:
                evaluate_breach(load)
                touch(load)
        facility = db.facilities.get(slot["facility_id"])
        if facility is not None:
            release_dock(facility)

    scheduled = [slot for slot in db.appointments.values() if slot["status"] == "SCHEDULED"]
    scheduled.sort(key=lambda row: (row["window_end"], row["created_at"]))
    for slot in scheduled:
        if not overdue(slot):
            continue
        slot["status"] = "MISSED"
        touch(slot)
        swept_appointments.append(slot["id"])
        facility = db.facilities.get(slot["facility_id"])
        if facility is not None:
            release_dock(facility)

    uncovered = []
    posted = [load for load in db.loads.values() if load["status"] == "POSTED"]
    posted.sort(key=lambda row: (row["pickup_window_start"], row["created_at"]))
    for load in posted:
        if _live_quotes_for(load["id"]):
            continue
        horizon = utc(load["pickup_window_start"]) - _hours(24)
        if utc(now) >= horizon:
            load["status"] = "UNCOVERED"
            touch(load)
            append_status_event(load["id"], "UNCOVERED", "PLATFORM")
            uncovered.append(load["id"])

    # The sweep suspends carriers whose insurance has lapsed, measured against
    # the instant the sweep is processing (PRD 3.10).
    suspended = []
    for carrier in list(db.carriers.values()):
        if sync_carrier(carrier):
            suspended.append(carrier["id"])

    return {
        "swept_appointment_ids": swept_appointments,
        "uncovered_load_ids": uncovered,
        "suspended_carrier_ids": suspended,
        "processed_at": now,
    }


def _minutes(count):
    from datetime import timedelta
    return timedelta(minutes=count)


def _hours(count):
    from datetime import timedelta
    return timedelta(hours=count)
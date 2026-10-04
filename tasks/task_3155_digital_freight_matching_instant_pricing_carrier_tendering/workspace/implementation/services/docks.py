"""Docks, appointments, interval bookkeeping and detention (PRD 2.11, 3.5, 2.9)."""

import math
from datetime import datetime, timedelta

from constants import (
    DOCK_BUFFER_MINUTES, MISSED_GRACE_MINUTES, utc,
)
from db import clock_now, db, mint_id, touch
from errors import ApiError
from services.common import (
    append_status_event, load_accessorial_total, refresh_live_settlement_for_load,
)


def day_midnight(instant):
    instant = utc(instant)
    return instant.replace(hour=0, minute=0, second=0, microsecond=0)


def same_day(left, right):
    if left is None or right is None:
        return False
    return day_midnight(left) == day_midnight(right)


def overlaps(start_a, end_a, start_b, end_b):
    """Half-open comparison: touching ends are adjacent, not overlapping."""
    return utc(start_a) < utc(end_b) and utc(start_b) < utc(end_a)


def buffered(start, end):
    return (utc(start) - timedelta(minutes=DOCK_BUFFER_MINUTES),
            utc(end) + timedelta(minutes=DOCK_BUFFER_MINUTES))


def blocking_slots(facility_id):
    return [slot for slot in db.appointments.values()
            if slot["facility_id"] == facility_id
            and slot["status"] in ("SCHEDULED", "IN_PROGRESS")]


def position_is_free(facility, position, window_start, window_end,
                     exclude_appointment_id=None, use_buffer=True):
    if use_buffer:
        wide_start, wide_end = buffered(window_start, window_end)
    else:
        wide_start, wide_end = utc(window_start), utc(window_end)
    for slot in blocking_slots(facility["id"]):
        if slot["dock_position"] != position:
            continue
        if exclude_appointment_id is not None and slot["id"] == exclude_appointment_id:
            continue
        if overlaps(slot["window_start"], slot["window_end"], wide_start, wide_end):
            return False
    return True


def select_dock_position(facility, window_start, window_end,
                         requested_position=None, exclude_appointment_id=None):
    """The dock selector waterfall (PRD 2.11 / scaffold Table 3).

    Considers the window widened by 120 minutes on each side and returns the
    lowest-numbered free position, or refuses with ERR_APPOINTMENT_OVERLAP.
    """
    capacity = int(facility["dock_capacity"])
    if requested_position is not None:
        try:
            position = int(requested_position)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "dock_position must be an integer.")
        if position < 1 or position > capacity:
            raise ApiError("ERR_INVALID_REQUEST",
                           "dock_position must be between 1 and the facility capacity.")
        if not position_is_free(facility, position, window_start, window_end,
                                exclude_appointment_id=exclude_appointment_id):
            raise ApiError("ERR_APPOINTMENT_OVERLAP")
        return position
    for position in range(1, capacity + 1):
        if position_is_free(facility, position, window_start, window_end,
                            exclude_appointment_id=exclude_appointment_id):
            return position
    raise ApiError("ERR_APPOINTMENT_OVERLAP")


def committed_today_count(facility):
    """SCHEDULED + IN_PROGRESS slots on the facility's current logical date.

    PRD 2.11 — the facility publishes `dock_capacity`, the number of dock
    positions bookable on a calendar day, and the count rises when a slot is
    created in SCHEDULED or IN_PROGRESS status and falls when a slot leaves
    that pair of states. Slots dated on other days do not count against the
    current date's figure.
    """
    current = day_midnight(clock_now())
    return sum(1 for slot in db.appointments.values()
               if slot["facility_id"] == facility["id"]
               and slot["status"] in ("SCHEDULED", "IN_PROGRESS")
               and same_day(slot["scheduled_date"], current))


def recompute_docks(facility):
    facility["docks_committed_today"] = committed_today_count(facility)
    return facility["docks_committed_today"]


def hold_dock(facility):
    recompute_docks(facility)
    return facility["docks_committed_today"]


def release_dock(facility):
    recompute_docks(facility)
    return facility["docks_committed_today"]


def dock_capacity_guard(facility):
    """The guard trips at equality (PRD 2.11)."""
    if committed_today_count(facility) >= int(facility["dock_capacity"]):
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED")


def equipment_window_conflict(equipment_id, window_start, window_end):
    """Zero-buffer, half-open comparison over non-terminal bookings (PRD 3.7)."""
    for booking in db.bookings.values():
        if booking["equipment_id"] != equipment_id:
            continue
        if booking["status"] not in ("PENDING_APPOINTMENT", "IN_TRANSIT"):
            continue
        if (utc(booking["booking_window_start"]) < utc(window_end)
                and utc(window_start) < utc(booking["booking_window_end"])):
            return booking
    return None


# --------------------------------------------------------------------------
# Appointment construction
# --------------------------------------------------------------------------
def create_appointment(facility, load_id, carrier_id, slot_kind, window_start,
                       window_end, scheduled_date, dock_position=None,
                       status="SCHEDULED"):
    now = clock_now()
    if not utc(window_end) > utc(window_start):
        raise ApiError("ERR_WINDOW_ORDER")
    day = day_midnight(scheduled_date if scheduled_date else window_start)
    # A slot on the facility's current logical date counts against its daily
    # capacity; the guard trips at equality (PRD 2.11).  A full day is reported
    # as the capacity refusal whatever the selector would have found.
    if same_day(day, clock_now()) and int(facility["dock_capacity"]) <= committed_today_count(facility):
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED")
    position = select_dock_position(facility, window_start, window_end,
                                    requested_position=dock_position)
    slot = {
        "id": mint_id(),
        "facility_id": facility["id"],
        "load_id": load_id,
        "carrier_id": carrier_id,
        "slot_kind": slot_kind,
        "dock_position": position,
        "window_start": utc(window_start),
        "window_end": utc(window_end),
        "scheduled_date": day_midnight(scheduled_date if scheduled_date else window_start),
        "status": status,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.appointments[slot["id"]] = slot
    hold_dock(facility)
    return slot


# --------------------------------------------------------------------------
# Detention
# --------------------------------------------------------------------------
def detention_figures(dwell_minutes, facility):
    """PRD 2.9 — floor, subtract, clamp, ceil to hours, then apply the rate."""
    billable = max(0, int(dwell_minutes) - int(facility["free_dwell_minutes"]))
    hours = int(math.ceil(billable / 60.0)) if billable > 0 else 0
    return billable, hours * int(facility["detention_rate_per_hour_cents"])


def close_detention(event, departed_at=None):
    facility = db.facilities.get(event["facility_id"])
    at = utc(departed_at) if departed_at is not None else clock_now()
    event["departed_at"] = at
    dwell = int((at - utc(event["arrived_at"])).total_seconds() // 60)
    event["dwell_minutes"] = dwell
    billable, charge = detention_figures(dwell, facility)
    event["billable_detention_minutes"] = billable
    event["detention_charge_cents"] = charge
    event["status"] = "CLOSED"
    touch(event)
    cascade_detention_close(event)
    return event


def cascade_detention_close(event):
    load = db.loads.get(event["load_id"])
    if load is not None:
        load["accessorial_total_cents"] = load_accessorial_total(load["id"])
        touch(load)
        refresh_live_settlement_for_load(load["id"])


def open_detention(appointment):
    now = clock_now()
    event = {
        "id": mint_id(),
        "appointment_id": appointment["id"],
        "facility_id": appointment["facility_id"],
        "load_id": appointment["load_id"],
        "carrier_id": appointment["carrier_id"],
        "arrived_at": now,
        "departed_at": None,
        "dwell_minutes": 0,
        "billable_detention_minutes": 0,
        "detention_charge_cents": 0,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.detention_events[event["id"]] = event
    return event


def oldest_open_detention(load_id):
    rows = [event for event in db.detention_events.values()
            if event["load_id"] == load_id and event["status"] == "OPEN"]
    if not rows:
        return None
    rows.sort(key=lambda row: row["created_at"])
    return rows[0]
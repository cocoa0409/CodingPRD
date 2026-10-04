"""Driver tracking, status advancement and the load-lifecycle cascades (PRD 3.6)."""

from constants import (
    STATUS_EVENT_TYPES, STATUS_RANKS, TOLERANCE_MINUTES, parse_instant, plus_minutes, utc,
)
from db import clock_now, db, mint_id, touch
from errors import ApiError
from services.common import (
    append_status_event, compute_projected_delay, get_carrier, get_load,
    load_accessorial_total, refresh_carrier_score, refresh_load_derived,
)
from services.docks import (
    close_detention, day_midnight, oldest_open_detention, open_detention,
    position_is_free, select_dock_position,
)
from services.settlements import create_settlement_for_delivery


def load_pings(load_id):
    rows = [ping for ping in db.tracking_pings.values() if ping["load_id"] == load_id]
    rows.sort(key=lambda row: row["sequence"])
    return rows


def greatest_rank(load_id):
    ranks = [ping["status_rank"] for ping in db.tracking_pings.values()
             if ping["load_id"] == load_id]
    return max(ranks) if ranks else 0


def record_ping(load_id, body):
    load = get_load(load_id)
    carrier = get_carrier(body.get("carrier_id"))

    reported_status = body.get("reported_status")
    if reported_status not in STATUS_RANKS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown reported_status.")
    sequence = body.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ApiError("ERR_INVALID_REQUEST", "sequence must be an integer.")

    existing = load_pings(load_id)
    if sequence != len(existing) + 1:
        raise ApiError("ERR_TRACKING_SEQUENCE_OUT_OF_ORDER")

    rank = STATUS_RANKS[reported_status]
    if rank > greatest_rank(load_id) + 1:
        raise ApiError("ERR_TRACKING_SEQUENCE_GAP")

    eta = None
    if body.get("eta_utc") is not None:
        eta = parse_instant(body["eta_utc"], "eta_utc")

    # The rank may only climb one rung at a time; the two cross-load rules of
    # PRD 3.6 are the same comparison expressed per target state.
    if reported_status == "IN_TRANSIT" and greatest_rank(load_id) < 2:
        raise ApiError("ERR_TRACKING_SEQUENCE_GAP")
    if reported_status == "DELIVERED" and greatest_rank(load_id) < 4:
        raise ApiError("ERR_TRACKING_SEQUENCE_GAP")

    # Plan the delivery-window placement before any state is committed so the
    # whole cascade stays atomic.
    planned_position = None
    if reported_status == "IN_TRANSIT":
        planned_position = _plan_delivery_slot(load, eta)

    now = clock_now()
    ping = {
        "id": mint_id(),
        "load_id": load["id"],
        "carrier_id": carrier["id"],
        "sequence": sequence,
        "reported_status": reported_status,
        "status_rank": rank,
        "location_code": body.get("location_code"),
        "eta_utc": eta,
        "recorded_at": now,
        "created_at": now,
    }
    db.tracking_pings[ping["id"]] = ping

    load["tracking_status_rank"] = max(load["tracking_status_rank"], rank)

    if reported_status == "AT_PICKUP":
        _arrival_at_pickup(load, carrier, now)
    elif reported_status == "AT_DELIVERY":
        _arrival_at_delivery(load, carrier, now)
    elif reported_status == "IN_TRANSIT":
        _departure(load, carrier, now, eta, planned_position)
    elif reported_status == "DELIVERED":
        _delivery(load, carrier, now)

    load["projected_delay_minutes"] = compute_projected_delay(load)
    touch(load)
    return ping


def _plan_delivery_slot(load, eta):
    if eta is None:
        return None
    destination = db.facilities.get(load["destination_facility_id"])
    if destination is None:
        return None
    window_start = plus_minutes(eta, -int(destination["default_appointment_minutes"]))
    window_end = eta
    for position in range(1, int(destination["dock_capacity"]) + 1):
        if position_is_free(destination, position, window_start, window_end,
                            exclude_appointment_id=None):
            return (position, window_start, window_end)
    raise ApiError("ERR_APPOINTMENT_OVERLAP")


def _pickup_appointment(load):
    rows = [slot for slot in db.appointments.values()
            if slot["load_id"] == load["id"] and slot["slot_kind"] == "PICKUP"
            and slot["status"] in ("SCHEDULED", "IN_PROGRESS")]
    if not rows:
        return None
    rows.sort(key=lambda row: row["created_at"])
    return rows[0]


def _delivery_appointment(load):
    rows = [slot for slot in db.appointments.values()
            if slot["load_id"] == load["id"] and slot["slot_kind"] == "DELIVERY"
            and slot["status"] in ("SCHEDULED", "IN_PROGRESS")]
    if not rows:
        return None
    rows.sort(key=lambda row: row["created_at"])
    return rows[-1]


def _arrival_at_pickup(load, carrier, now):
    if load["actual_pickup_at"] is None:
        load["actual_pickup_at"] = now
    appointment = _pickup_appointment(load)
    if appointment is not None and appointment["status"] == "SCHEDULED":
        appointment["status"] = "IN_PROGRESS"
        touch(appointment)
        open_detention(appointment)
    append_status_event(load["id"], "ARRIVED_PICKUP", "DRIVER_APP")
    evaluate_breach(load)


def _arrival_at_delivery(load, carrier, now):
    appointment = _delivery_appointment(load)
    if appointment is not None and appointment["status"] == "SCHEDULED":
        appointment["status"] = "IN_PROGRESS"
        touch(appointment)
        open_detention(appointment)
    append_status_event(load["id"], "ARRIVED_DELIVERY", "DRIVER_APP")


def _departure(load, carrier, now, eta, planned):
    if load["status"] != "BOOKED":
        return
    appointment = _pickup_appointment(load)
    if appointment is not None and appointment["status"] == "IN_PROGRESS":
        appointment["status"] = "COMPLETED"
        touch(appointment)
        event = None
        for row in db.detention_events.values():
            if row["appointment_id"] == appointment["id"] and row["status"] == "OPEN":
                event = row
                break
        if event is not None:
            close_detention(event, now)
    load["accessorial_total_cents"] = load_accessorial_total(load["id"])
    append_status_event(load["id"], "DEPARTED_PICKUP", "DRIVER_APP")
    load["status"] = "IN_TRANSIT"
    booking = None
    rows = [row for row in db.bookings.values()
            if row["load_id"] == load["id"] and row["status"] == "PENDING_APPOINTMENT"]
    if rows:
        rows.sort(key=lambda row: row["created_at"])
        booking = rows[-1]
        booking["status"] = "IN_TRANSIT"
        touch(booking)
    if planned is not None:
        position, window_start, window_end = planned
        destination = db.facilities[load["destination_facility_id"]]
        slot = {
            "id": mint_id(),
            "facility_id": destination["id"],
            "load_id": load["id"],
            "carrier_id": carrier["id"],
            "slot_kind": "DELIVERY",
            "dock_position": position,
            "window_start": window_start,
            "window_end": window_end,
            "scheduled_date": day_midnight(window_start),
            "status": "SCHEDULED",
            "created_at": clock_now(),
            "updated_at": clock_now(),
            "version": 1,
        }
        db.appointments[slot["id"]] = slot
        from services.docks import hold_dock
        hold_dock(destination)


def _delivery(load, carrier, now):
    if load["status"] != "IN_TRANSIT":
        return
    event = oldest_open_detention(load["id"])
    if event is not None:
        close_detention(event, now)
    booking = None
    rows = [row for row in db.bookings.values()
            if row["load_id"] == load["id"] and row["status"] in ("PENDING_APPOINTMENT", "IN_TRANSIT")]
    if rows:
        rows.sort(key=lambda row: row["created_at"])
        booking = rows[-1]
    load["accessorial_total_cents"] = load_accessorial_total(load["id"])
    load["status"] = "DELIVERED"
    load["delivered_at"] = now
    load["actual_delivery_at"] = now
    if booking is not None:
        booking["status"] = "DELIVERED"
        touch(booking)
        create_settlement_for_delivery(load, booking)
    append_status_event(load["id"], "DELIVERED", "DRIVER_APP")
    refresh_carrier_score(carrier)


def evaluate_breach(load):
    """PRD 3.6 — a breach is strictly more than 30 minutes past the window."""
    if load["actual_pickup_at"] is None:
        return False
    elapsed = (utc(load["actual_pickup_at"]) - utc(load["pickup_window_end"])).total_seconds()
    if elapsed > TOLERANCE_MINUTES * 60:
        if not load["pickup_breach_flag"]:
            load["pickup_breach_flag"] = True
            shipper = db.shippers.get(load["shipper_id"])
            if shipper is not None:
                shipper["breached_pickup_count"] += 1
                touch(shipper)
            if load["carrier_id"]:
                carrier = db.carriers.get(load["carrier_id"])
                if carrier is not None:
                    refresh_carrier_score(carrier, bump=True)
        return True
    return False


def add_status_event(body):
    load = get_load(body.get("load_id"))
    event_type = body.get("event_type")
    if event_type not in STATUS_EVENT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown event_type.")
    return event_type


def ping_list(pings, filters):
    rows = list(pings)
    for field in ("load_id", "carrier_id"):
        value = filters.get(field)
        if value is None or value == "":
            continue
        rows = [row for row in rows if row.get(field) == value]
    rows.sort(key=lambda row: (row["load_id"], row["sequence"]))
    return rows


def status_event_list(events, filters):
    rows = list(events)
    for field in ("load_id", "event_type"):
        value = filters.get(field)
        if value is None or value == "":
            continue
        rows = [row for row in rows if row.get(field) == value]
    rows.sort(key=lambda row: row["created_at"])
    return rows
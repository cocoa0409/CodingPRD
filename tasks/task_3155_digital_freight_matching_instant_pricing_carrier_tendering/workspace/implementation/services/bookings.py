"""Booking / tender, and additional appointments (PRD 3.7)."""

from constants import utc
from db import clock_now, db, mint_id, touch
from errors import ApiError
from services.common import (
    append_status_event, get_carrier, get_equipment, get_load, get_quote, get_shipper,
    refresh_carrier_score, refresh_contract, refresh_load_derived, refresh_shipper,
)
from services import pricing
from services.carriers import carrier_eligibility_gate, sync_carrier
from services.docks import (
    create_appointment, dock_capacity_guard, equipment_window_conflict,
    select_dock_position,
)


def create_booking(body):
    load = get_load(body.get("load_id"))
    carrier = get_carrier(body.get("carrier_id"))
    quote = get_quote(body.get("rate_quote_id"))
    equipment = get_equipment(body.get("equipment_id"))
    shipper = get_shipper(load["shipper_id"])

    expected = body.get("expected_load_version")
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST", "expected_load_version is required.")

    if load["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE")
    if quote["status"] not in ("ACTIVE", "VIEWED"):
        raise ApiError("ERR_INVALID_STATE")

    # The carrier passes the eligibility gate before any price work happens.
    carrier_eligibility_gate(carrier, load, shipper)

    refresh_shipper(shipper)
    if shipper["credit_available_cents"] < quote["min_rate_cents"]:
        raise ApiError("ERR_SHIPPER_CREDIT_EXHAUSTED")
    if not utc(quote["acceptance_deadline"]) > clock_now():
        raise ApiError("ERR_QUOTE_EXPIRED")
    if equipment["status"] == "IN_SHOP" or equipment["equipment_type"] != load["equipment_type"]:
        raise ApiError("ERR_EQUIPMENT_UNAVAILABLE")

    window_start = load["pickup_window_start"]
    window_end = load["pickup_window_end"]

    # Interval conflicts, equipment first — an equipment conflict must never be
    # masked by an appointment failure.
    if equipment_window_conflict(equipment["id"], window_start, window_end) is not None:
        raise ApiError("ERR_EQUIPMENT_WINDOW_CONFLICT")

    facility = db.facilities.get(load["origin_facility_id"])
    if facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    # A full day is reported as the capacity refusal before the selector is
    # consulted; the selector itself only ever declines with the overlap error.
    dock_capacity_guard(facility)
    select_dock_position(facility, window_start, window_end)

    # Referential integrity closes the set.
    if quote["load_id"] != load["id"]:
        raise ApiError("ERR_QUOTE_LOAD_MISMATCH")
    if equipment["carrier_id"] != carrier["id"]:
        raise ApiError("ERR_EQUIPMENT_CARRIER_MISMATCH")

    if int(expected) != int(load["version"]):
        raise ApiError("ERR_STALE_VERSION")

    amount = pricing.booked_price(quote, load)
    now = clock_now()

    appointment = create_appointment(
        facility, load["id"], carrier["id"], "PICKUP", window_start, window_end,
        scheduled_date=window_start, status="SCHEDULED")

    booking = {
        "id": mint_id(),
        "load_id": load["id"],
        "carrier_id": carrier["id"],
        "rate_quote_id": quote["id"],
        "equipment_id": equipment["id"],
        "agreed_rate_cents": amount,
        "booked_at": now,
        "booking_window_start": utc(window_start),
        "booking_window_end": utc(window_end),
        "appointment_id": appointment["id"],
        "contract_lane_draw": load["lane_contract_id"] is not None,
        "quick_pay_elected": False,
        "quick_pay_discount_cents": 0,
        "settled_at": None,
        "status": "PENDING_APPOINTMENT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.bookings[booking["id"]] = booking

    load["carrier_id"] = carrier["id"]
    load["equipment_id"] = equipment["id"]
    load["status"] = "BOOKED"
    touch(load)
    refresh_load_derived(load)

    equipment["status"] = "ASSIGNED"
    touch(equipment)

    quote["status"] = "ACCEPTED"
    touch(quote)
    for sibling in db.quotes.values():
        if sibling["load_id"] == load["id"] and sibling["id"] != quote["id"]:
            if sibling["status"] in ("ACTIVE", "VIEWED"):
                sibling["status"] = "SUPERSEDED"
                touch(sibling)

    shipper["credit_used_cents"] += amount
    touch(shipper)
    refresh_shipper(shipper)

    if load["lane_contract_id"] is not None:
        contract = db.contracts.get(load["lane_contract_id"])
        if contract is not None:
            refresh_contract(contract)

    append_status_event(load["id"], "BOOKED", "PLATFORM")
    return booking


def additional_appointment(booking_id, body):
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    load = db.loads.get(booking["load_id"])
    slot_kind = body.get("slot_kind")
    if slot_kind not in ("PICKUP", "DELIVERY"):
        raise ApiError("ERR_INVALID_REQUEST", "slot_kind must be PICKUP or DELIVERY.")
    window_start = body.get("window_start")
    window_end = body.get("window_end")
    if window_start is None or window_end is None:
        raise ApiError("ERR_INVALID_REQUEST", "window_start and window_end are required.")
    from constants import parse_instant
    start = parse_instant(window_start, "window_start")
    end = parse_instant(window_end, "window_end")
    if not end > start:
        raise ApiError("ERR_WINDOW_ORDER")
    facility_id = (load["destination_facility_id"] if slot_kind == "DELIVERY"
                   else load["origin_facility_id"])
    facility = db.facilities.get(facility_id)
    if facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    dock_capacity_guard(facility)
    return create_appointment(facility, load["id"], booking["carrier_id"], slot_kind,
                              start, end, scheduled_date=start,
                              dock_position=body.get("dock_position"))


def booking_list(bookings, filters):
    rows = list(bookings)
    for field in ("load_id", "carrier_id", "rate_quote_id", "equipment_id",
                  "appointment_id", "status"):
        value = filters.get(field)
        if value is None or value == "":
            continue
        rows = [row for row in rows if row.get(field) == value]
    rows.sort(key=lambda row: row["created_at"])
    return rows
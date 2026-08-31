"""Service days, interruptions and the logical harbor clock — PRD 2.5, 3.2, 3.9."""

from flask import Blueprint

import calc
import cascades
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list, read_pagination, paginate
from errors import ApiError
from store import store, iso_instant

bp = Blueprint("days", __name__)


def find_service_day(day_id):
    row = store.service_days.get(day_id)
    if row is None:
        raise ApiError("ERR_SERVICE_DAY_NOT_FOUND", "No service day with id %s." % day_id)
    return row


@bp.post("/harbor/service-days")
def create_service_day():
    require("HarborAdmin")
    body = v.body()
    service_date_raw, _service_date = v.get_calendar_date(body, "service_date")
    wind = v.get_number(body, "wind_knots", minimum=0)
    wave = v.get_number(body, "wave_height_m", minimum=0)
    low_water = v.get_number(body, "low_water_m", minimum=0)
    manual = v.get_boolean(body, "manual_suspension", required=False, default=False)
    event_name = v.get_string(body, "event_name", required=False, default=None,
                              nullable=True)
    attendance = v.get_integer(body, "expected_attendance", required=False,
                               default=0, minimum=0)

    # rung 9 — calendar uniqueness
    if calc.day_by_date(service_date_raw) is not None:
        raise ApiError("ERR_SERVICE_DAY_DUPLICATE",
                       "An operating day already exists for %s." % service_date_raw)

    row = store.new_row()
    row.update({
        "service_date": service_date_raw,
        "wind_knots": wind,
        "wave_height_m": wave,
        "low_water_m": low_water,
        "manual_suspension": manual,
        "event_name": event_name,
        "expected_attendance": attendance,
    })
    calc.recompute_day_derived(row)
    store.service_days[row["id"]] = row
    return created(serialize.service_day(row))


@bp.get("/harbor/service-days/<day_id>")
def read_service_day(day_id):
    require("HarborAdmin", "Dispatcher", "VesselMaster", "Rider", "FareAuditor")
    return ok(serialize.service_day(find_service_day(day_id)))


@bp.patch("/harbor/service-days/<day_id>")
def update_service_day(day_id):
    require("HarborAdmin")
    day = find_service_day(day_id)
    body = v.body()

    if "wind_knots" in body:
        day["wind_knots"] = v.get_number(body, "wind_knots", minimum=0)
    if "wave_height_m" in body:
        day["wave_height_m"] = v.get_number(body, "wave_height_m", minimum=0)
    if "low_water_m" in body:
        day["low_water_m"] = v.get_number(body, "low_water_m", minimum=0)
    if "manual_suspension" in body:
        day["manual_suspension"] = v.get_boolean(body, "manual_suspension", required=True)
    if "event_name" in body:
        day["event_name"] = v.get_string(body, "event_name", required=False,
                                         default=None, nullable=True)
    if "expected_attendance" in body:
        day["expected_attendance"] = v.get_integer(body, "expected_attendance", minimum=0)

    calc.recompute_day_derived(day)
    store.touch(day)

    if day["posture"] == "SUSPENDED":
        cascades.cascade_a(day)

    return ok(serialize.service_day(day))


# --------------------------------------------------------- interruptions

@bp.post("/harbor/service-days/<day_id>/interruptions")
def declare_interruption(day_id):
    actor = require("Dispatcher")
    day = find_service_day(day_id)
    body = v.body()
    cause = v.get_enum(body, "cause", ("WEATHER", "TIDE", "MECHANICAL", "DOCK_CLOSURE"))

    # rung 10 — state precondition
    if day["posture"] != "SUSPENDED":
        raise ApiError("ERR_INTERRUPTION_NOT_DECLARABLE",
                       "The operating day is not SUSPENDED.")

    row = store.new_row()
    row.update({
        "service_day_id": day["id"],
        "cause": cause,
        "declared_by_user_id": actor.user_id,
        "status": "DECLARED",
        "affected_booking_count": 0,
        "total_provisional_refund_cents": 0,
    })

    claimed_bookings = set(c["booking_id"] for c in store.claims.values())
    eligible = []
    for booking in store.bookings.values():
        if booking["status"] != "INTERRUPTED":
            continue
        trip = store.trips.get(booking.get("trip_id"))
        if trip is None or trip["service_day_id"] != day["id"]:
            continue
        if booking["id"] in claimed_bookings:
            continue
        eligible.append(booking)
    eligible = store.ordered(eligible)

    total = 0
    for booking in eligible:
        if booking["interrupted_from_status"] == "BOARDED":
            entitlement = calc.apply_bp(booking["fare_charged_cents"],
                                        calc.PARTIAL_LEG_SHARE_BP)
        else:
            entitlement = booking["fare_charged_cents"]

        if booking["redemption_status"] == "RESTORED":
            ride_restored = True
            cash = 0
            credit = 0
        else:
            ride_restored = False
            cash = min(entitlement, calc.CASH_REFUND_CAP_CENTS)
            credit = entitlement - cash

        claim = store.new_row()
        claim.update({
            "booking_id": booking["id"],
            "service_interruption_id": row["id"],
            "declarer_user_id": actor.user_id,
            "approver_user_id": None,
            "entitlement_cents": entitlement,
            "cash_refund_cents": cash,
            "credit_refund_cents": credit,
            "ride_restored": ride_restored,
            "status": "OPEN",
        })
        store.claims[claim["id"]] = claim
        total += entitlement

    row["affected_booking_count"] = len(eligible)
    row["total_provisional_refund_cents"] = total
    store.interruptions[row["id"]] = row
    return created(serialize.interruption(row))


@bp.get("/harbor/service-days/<day_id>/interruptions")
def list_interruptions(day_id):
    require("HarborAdmin", "Dispatcher", "FareAuditor")
    day = find_service_day(day_id)
    limit, offset = read_pagination()
    rows = store.ordered([r for r in store.interruptions.values()
                          if r["service_day_id"] == day["id"]])
    window = paginate(rows, limit, offset)
    return ok_list([serialize.interruption(r) for r in window], limit, offset, len(rows))


# ----------------------------------------------------------------- clock

@bp.post("/_clock/set_current_utc")
def set_clock():
    require("HarborAdmin")
    body = v.body()
    _raw, instant = v.get_utc_instant(body, "to_iso8601")
    store.set_clock(instant)
    return ok({"current_utc": iso_instant(instant)})

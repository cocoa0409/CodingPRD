"""Clock, franchisors, hearing rooms and dealership records (PRD 2.5 / 3.1)."""

from flask import Blueprint, request

import db
import derive
import enums
import response
import serializers
import sweep
import validation as v
from errors import ApiError
from middleware import guard

bp = Blueprint("reference", __name__)

ALL = enums.ROLE_ALL


def _listing(kind, serializer, matcher=None):
    limit, offset = response.read_pagination(request.args)
    rows = [row for row in db.ordered(kind) if matcher is None or matcher(row)]
    window, total = response.page(rows, limit, offset)
    return response.array_response([serializer(row) for row in window], limit, offset, total)


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    guard(["BoardAdmin"])
    body = v.read_body()
    target = v.req_instant(body, "to_iso8601")
    if not target > db.now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC", "to_iso8601 must be strictly later than the current clock")
    db.set_clock(target)
    counters = sweep.run(target.date())
    payload = {"current_utc": db.iso_instant(target)}
    payload.update(counters)
    return response.object_response(payload, 200)


# ---------------------------------------------------------------------------
# franchisors
# ---------------------------------------------------------------------------
@bp.post("/manufacturers")
def create_manufacturer():
    guard(["BoardAdmin"])
    body = v.read_body()
    legal_name = v.req_string(body, "legal_name", 1, 200)
    line_make = v.req_string(body, "line_make", 2, 20, r"^[A-Z]{2,20}$")
    home_office_state = v.req_string(body, "home_office_state", 2, 2, r"^[A-Z]{2}$")
    posted_rate = v.req_int(body, "posted_warranty_labor_rate_cents", 1000, 100000)
    registration = v.opt_enum(body, "state_registration_status", enums.REGISTRATION_STATUSES, "REGISTERED")

    for existing in db.ordered("manufacturer"):
        if existing["line_make"] == line_make:
            raise ApiError("ERR_DUPLICATE_LINE_MAKE", "line_make %s is already registered" % line_make)

    record = db.insert("manufacturer", {
        "legal_name": legal_name,
        "line_make": line_make,
        "home_office_state": home_office_state,
        "posted_warranty_labor_rate_cents": posted_rate,
        "state_registration_status": registration,
        "open_dispute_count": 0,
        "active_filing_count": 0,
    })
    return response.object_response(serializers.manufacturer(record), 201)


@bp.get("/manufacturers/<record_id>")
def read_manufacturer(record_id):
    guard(ALL)
    record = db.get("manufacturer", record_id)
    if record is None:
        raise ApiError("ERR_MANUFACTURER_NOT_FOUND", "No such franchisor")
    return response.object_response(serializers.manufacturer(record), 200)


@bp.get("/manufacturers")
def list_manufacturers():
    guard(ALL)
    registration = v.query_enum("state_registration_status", enums.REGISTRATION_STATUSES)
    line_make = v.query_string("line_make")

    def matcher(row):
        if registration is not None and row["state_registration_status"] != registration:
            return False
        if line_make is not None and row["line_make"] != line_make:
            return False
        return True

    return _listing("manufacturer", serializers.manufacturer, matcher)


# ---------------------------------------------------------------------------
# hearing rooms
# ---------------------------------------------------------------------------
@bp.post("/hearing-rooms")
def create_hearing_room():
    guard(["BoardAdmin"])
    body = v.read_body()
    room_code = v.req_string(body, "room_code", 2, 12)
    seating_capacity = v.req_int(body, "seating_capacity", 10, 400)
    max_per_day = v.opt_int(body, "max_hearings_per_day", 1, 4, 2)
    buffer_minutes = v.opt_int(body, "buffer_minutes", 0, 240, 60)

    for existing in db.ordered("hearing_room"):
        if existing["room_code"] == room_code:
            raise ApiError("ERR_DUPLICATE_ROOM_CODE", "room_code %s already exists" % room_code)

    record = db.insert("hearing_room", {
        "room_code": room_code,
        "seating_capacity": seating_capacity,
        "max_hearings_per_day": max_per_day,
        "buffer_minutes": buffer_minutes,
        "booked_hearing_count": 0,
    })
    return response.object_response(serializers.hearing_room(record), 201)


@bp.get("/hearing-rooms/<record_id>")
def read_hearing_room(record_id):
    guard(["BoardAdmin", "HearingClerk", "Dealer", "Manufacturer"])
    record = db.get("hearing_room", record_id)
    if record is None:
        raise ApiError("ERR_HEARING_ROOM_NOT_FOUND", "No such hearing room")
    return response.object_response(serializers.hearing_room(record), 200)


@bp.get("/hearing-rooms")
def list_hearing_rooms():
    guard(["BoardAdmin", "HearingClerk"])
    return _listing("hearing_room", serializers.hearing_room)


# ---------------------------------------------------------------------------
# dealerships
# ---------------------------------------------------------------------------
@bp.post("/dealers")
def create_dealer():
    guard(["BoardAdmin"])
    body = v.read_body()
    legal_name = v.req_string(body, "legal_name", 1, 200)
    dealer_type = v.req_enum(body, "dealer_type", enums.DEALER_TYPES)
    county_tier = v.req_enum(body, "county_tier", enums.COUNTY_TIERS)
    site_x = v.req_decimal(body, "site_x_km", -500, 500, 2)
    site_y = v.req_decimal(body, "site_y_km", -500, 500, 2)
    line_make = v.opt_string(body, "line_make", 0, 20, r"^[A-Z]{0,20}$", "")

    record = db.insert("dealer", {
        "legal_name": legal_name,
        "dealer_type": dealer_type,
        "county_tier": county_tier,
        "line_make": line_make,
        "site_x_km": site_x,
        "site_y_km": site_y,
        "license_status": "PROSPECTIVE",
        "franchise_status": "NONE",
        "suspension_reason": "NONE",
        "license_effective_on": None,
        "license_expires_on": None,
        "disciplinary_points": 0,
        "restitution_outstanding_cents": 0,
        "licensed_salesperson_count": 0,
        "approved_warranty_labor_rate_cents": None,
    })
    return response.object_response(serializers.dealer(record), 201)


@bp.get("/dealers/<record_id>")
def read_dealer(record_id):
    guard(ALL)
    record = db.get("dealer", record_id)
    if record is None:
        raise ApiError("ERR_DEALER_NOT_FOUND", "No such dealership")
    return response.object_response(serializers.dealer(record), 200)


@bp.get("/dealers")
def list_dealers():
    guard(ALL)
    license_status = v.query_enum("license_status", enums.DEALER_LICENSE_STATUSES)
    franchise_status = v.query_enum("franchise_status", enums.FRANCHISE_STATUSES)
    county_tier = v.query_enum("county_tier", enums.COUNTY_TIERS)
    line_make = v.query_string("line_make")

    def matcher(row):
        if license_status is not None and row["license_status"] != license_status:
            return False
        if franchise_status is not None and row["franchise_status"] != franchise_status:
            return False
        if county_tier is not None and row["county_tier"] != county_tier:
            return False
        if line_make is not None and row["line_make"] != line_make:
            return False
        return True

    return _listing("dealer", serializers.dealer, matcher)

"""Passenger itineraries and boarding-pass verification (PRD section 3.4)."""
from flask import Blueprint

import clock
import db
import response
from errors import ApiError
from middleware import body, endpoint
from services import mix, pricing
from services.lookup import fetch, fetch_body, listing
from services.scope import ALL_ROLES, STAFF_ROLES, ensure_owner
from services.validate import (UPPER2, opt_bool, opt_string, opt_ts, present, req_string, req_ts)

bp = Blueprint("itineraries", __name__)


@bp.post("/itineraries")
@endpoint("SalesAssociate")
def create_itinerary():
    payload = body()
    terminal = fetch_body("terminals", "departure_terminal_id", payload)
    passenger_ref = req_string(payload, "passenger_ref")
    nationality_code = req_string(payload, "nationality_code", pattern=UPPER2)
    boarding_pass_barcode = req_string(payload, "boarding_pass_barcode")
    departure_utc = req_ts(payload, "departure_utc")
    destination_country = req_string(payload, "destination_country", pattern=UPPER2)
    final_destination_country = req_string(payload, "final_destination_country", pattern=UPPER2)
    has_connection = opt_bool(payload, "has_connection", default=False)
    connection_country = opt_string(payload, "connection_country", pattern=UPPER2)
    connection_departure_utc = opt_ts(payload, "connection_departure_utc")
    if not has_connection:
        if final_destination_country != destination_country:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "final_destination_country must equal destination_country for a direct journey.",
            )
        connection_country = None
        connection_departure_utc = None
    for existing in db.itineraries.values():
        if existing["boarding_pass_barcode"] == boarding_pass_barcode:
            raise ApiError("ERR_DUPLICATE_BOARDING_PASS")
        if existing["passenger_ref"] == passenger_ref:
            raise ApiError("ERR_DUPLICATE_BOARDING_PASS")
    itinerary = db.base()
    itinerary.update({
        "passenger_ref": passenger_ref,
        "nationality_code": nationality_code,
        "boarding_pass_barcode": boarding_pass_barcode,
        "departure_terminal_id": terminal["id"],
        "departure_utc": clock.fmt(departure_utc),
        "destination_country": destination_country,
        "has_connection": has_connection,
        "connection_country": connection_country,
        "connection_departure_utc": clock.fmt(connection_departure_utc),
        "final_destination_country": final_destination_country,
        "is_international": destination_country != terminal["country_code"],
        "scan_status": "UNSCANNED",
        "scanned_at": None,
        "amend_count": 0,
    })
    db.itineraries[itinerary["id"]] = itinerary
    return response.created(db.public(itinerary))


@bp.get("/itineraries/<itinerary_id>")
@endpoint(*ALL_ROLES)
def get_itinerary(itinerary_id):
    itinerary = fetch("itineraries", itinerary_id)
    ensure_owner(itinerary["id"])
    return response.single(db.public(itinerary))


@bp.get("/itineraries")
@endpoint(*STAFF_ROLES)
def list_itineraries():
    rows, limit, offset, total = listing(
        db.itineraries, ("departure_terminal_id", "nationality_code", "scan_status"))
    return response.collection(rows, limit, offset, total)


@bp.post("/itineraries/<itinerary_id>/scan-boarding-pass")
@endpoint("SalesAssociate")
def scan_boarding_pass(itinerary_id):
    itinerary = fetch("itineraries", itinerary_id)
    payload = body()
    scanned = req_string(payload, "boarding_pass_barcode")
    if itinerary["scan_status"] not in ("UNSCANNED", "AMENDED"):
        raise ApiError("ERR_ITINERARY_SCAN_STATE_INVALID")
    if clock.now() >= clock.parse(itinerary["departure_utc"]):
        raise ApiError("ERR_DEPARTURE_PASSED")
    if not itinerary["is_international"]:
        raise ApiError("ERR_ITINERARY_NOT_INTERNATIONAL")
    if scanned != itinerary["boarding_pass_barcode"]:
        raise ApiError("ERR_BOARDING_PASS_MISMATCH")
    itinerary["scan_status"] = "SCANNED"
    itinerary["scanned_at"] = clock.now_iso()
    db.touch(itinerary)
    terminal = db.terminals[itinerary["departure_terminal_id"]]
    mix.refresh(terminal)
    db.touch(terminal)
    return response.single(db.public(itinerary))


@bp.post("/itineraries/<itinerary_id>/amend")
@endpoint("SalesAssociate")
def amend_itinerary(itinerary_id):
    itinerary = fetch("itineraries", itinerary_id)
    payload = body()
    destination_country = req_string(payload, "destination_country", pattern=UPPER2)
    final_destination_country = req_string(payload, "final_destination_country", pattern=UPPER2)
    has_connection = opt_bool(payload, "has_connection", default=itinerary["has_connection"])
    connection_country = opt_string(
        payload, "connection_country", pattern=UPPER2, default=itinerary["connection_country"])
    connection_departure_utc = payload.get("connection_departure_utc")
    if present(payload, "connection_departure_utc"):
        connection_departure_utc = clock.fmt(req_ts(payload, "connection_departure_utc"))
    else:
        connection_departure_utc = itinerary["connection_departure_utc"]
    departure_utc = itinerary["departure_utc"]
    if present(payload, "departure_utc"):
        departure_utc = clock.fmt(req_ts(payload, "departure_utc"))
    if itinerary["scan_status"] != "SCANNED":
        raise ApiError("ERR_ITINERARY_SCAN_STATE_INVALID")
    if clock.now() >= clock.parse(itinerary["departure_utc"]):
        raise ApiError("ERR_DEPARTURE_PASSED")
    terminal = db.terminals[itinerary["departure_terminal_id"]]
    itinerary["destination_country"] = destination_country
    itinerary["final_destination_country"] = final_destination_country
    itinerary["has_connection"] = has_connection
    itinerary["connection_country"] = connection_country
    itinerary["connection_departure_utc"] = connection_departure_utc
    itinerary["departure_utc"] = departure_utc
    itinerary["is_international"] = destination_country != terminal["country_code"]
    itinerary["amend_count"] = itinerary["amend_count"] + 1
    itinerary["scanned_at"] = None
    itinerary["scan_status"] = "AMENDED"
    db.touch(itinerary)
    for sale in db.ordered(db.sales,
                           lambda s: s["itinerary_id"] == itinerary["id"]
                           and s["fulfillment_status"] == "ELIGIBILITY_CLEARED"):
        pricing.revert_to_cart(sale)
        db.touch(sale)
    mix.refresh(terminal)
    db.touch(terminal)
    return response.single(db.public(itinerary))

"""Shipment endpoints (PRD §3.6)."""

from flask import Blueprint

import calc
import db
import system
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import shipment_out
from validate import (json_body, req_str, req_dt, get_tour, get_shipment,
                      paginate, apply_filters, sorted_created)

bp = Blueprint("shipments", __name__)


@bp.route("/tours/<tour_id>/shipments", methods=["POST"])
def create_shipment(tour_id):
    require_roles("Shipper", "TourManager")
    tour = get_tour(tour_id)
    data = json_body()

    origin_id = data.get("origin_stop_id")
    if origin_id is not None and not isinstance(origin_id, str):
        fail("ERR_INVALID_REQUEST", "origin_stop_id must be a string or null")
    dest_id = data.get("destination_stop_id")
    if not isinstance(dest_id, str) or not dest_id:
        fail("ERR_INVALID_REQUEST",
             "Missing or invalid required field: destination_stop_id")
    depart_at = req_dt(data, "depart_at")
    arrive_at = req_dt(data, "arrive_at")
    carrier = req_str(data, "carrier_name")
    crate_ids = data.get("crate_ids")
    if not isinstance(crate_ids, list) \
            or any(not isinstance(c, str) for c in crate_ids):
        fail("ERR_INVALID_REQUEST", "crate_ids must be an array of strings")
    for cid in crate_ids:
        crate = db.crates.get(cid)
        if crate is None or crate["tour_id"] != tour["id"]:
            fail("ERR_INVALID_REQUEST",
                 "crate_ids must reference crates of this tour")

    # Route consecutiveness (business priority 13): destination must be a stop
    # of this tour; an explicit origin must be the destination's immediate
    # route predecessor; a null origin is the first leg only.
    dest = db.stops.get(dest_id)
    origin = db.stops.get(origin_id) if origin_id is not None else None
    consecutive = False
    if dest is not None and dest["tour_id"] == tour["id"]:
        if origin_id is None:
            consecutive = (dest["seq"] == 1)
        elif origin is not None and origin["tour_id"] == tour["id"]:
            consecutive = (origin["seq"] + 1 == dest["seq"])
    if not consecutive:
        fail("ERR_ROUTE_NOT_CONSECUTIVE",
             "Shipment origin/destination are not consecutive stops on this "
             "tour")

    shipment = db.stamp_new({
        "id": db.new_id(),
        "tour_id": tour["id"],
        "origin_stop_id": origin_id,
        "destination_stop_id": dest_id,
        "depart_at": depart_at,
        "arrive_at": arrive_at,
        "carrier_name": carrier,
        "status": "PLANNED",
        "crate_ids": list(crate_ids),
    })
    db.shipments[shipment["id"]] = shipment
    return ok_object(shipment_out(shipment), status=201)


@bp.route("/tours/<tour_id>/shipments", methods=["GET"])
def list_shipments(tour_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    items = [s for s in db.shipments.values() if s["tour_id"] == tour["id"]]
    items = apply_filters(items, [("destination_stop_id", "destination_stop_id"),
                                  ("status", "status")])
    return paginate([shipment_out(s) for s in sorted_created(items)])


@bp.route("/tours/<tour_id>/shipments/<shipment_id>", methods=["GET"])
def get_one_shipment(tour_id, shipment_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    return ok_object(shipment_out(get_shipment(tour, shipment_id)))


@bp.route("/tours/<tour_id>/shipments/<shipment_id>/transition",
          methods=["POST"])
def shipment_transition(tour_id, shipment_id):
    require_roles("Shipper", "Registrar")
    tour = get_tour(tour_id)
    shipment = get_shipment(tour, shipment_id)
    data = json_body()
    action = data.get("action")
    if action not in ("DISPATCH", "DEPART", "RECEIVE", "CLEAR"):
        fail("ERR_INVALID_REQUEST", "Unrecognized action: %r" % action)
    # Action-level authorization: DISPATCH/DEPART are the Shipper's;
    # RECEIVE/CLEAR are the Registrar's.
    if action in ("DISPATCH", "DEPART"):
        require_roles("Shipper")
    else:
        require_roles("Registrar")

    if action == "DISPATCH":
        if shipment["status"] != "PLANNED":
            fail("ERR_INVALID_STATE",
                 "DISPATCH is only permitted from PLANNED")
        if shipment["origin_stop_id"] is not None:
            origin = db.stops.get(shipment["origin_stop_id"])
            if origin is None or origin["status"] not in ("TEARDOWN", "CLOSED"):
                fail("ERR_INVALID_STATE",
                     "The origin stop must be TEARDOWN or CLOSED to dispatch")
        dest = db.stops.get(shipment["destination_stop_id"])
        certs = [c for c in system.certs_of_tour(tour["id"])
                 if dest is not None and c["tour_stop_id"] == dest["id"]]
        if not any(calc.cert_covers_leg(c, tour, shipment) for c in certs):
            fail("ERR_NO_INSURANCE_COVERAGE",
                 "No certificate covers this leg's destination stop")
        for cid in shipment["crate_ids"]:
            crate = db.crates.get(cid)
            if crate is not None:
                crate["location_status"] = "IN_TRANSIT"
                crate["current_stop_id"] = shipment["destination_stop_id"]
                db.touch(crate)
        shipment["status"] = "DISPATCHED"
        db.touch(shipment)
        return ok_object(shipment_out(shipment))

    if action == "DEPART":
        if shipment["status"] != "DISPATCHED":
            fail("ERR_INVALID_STATE", "DEPART is only permitted from DISPATCHED")
        shipment["status"] = "IN_TRANSIT"
        db.touch(shipment)
        return ok_object(shipment_out(shipment))

    if action == "RECEIVE":
        if shipment["status"] != "IN_TRANSIT":
            fail("ERR_INVALID_STATE", "RECEIVE is only permitted from IN_TRANSIT")
        shipment["status"] = "RECEIVED"
        db.touch(shipment)
        return ok_object(shipment_out(shipment))

    # CLEAR
    if shipment["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "CLEAR is only permitted from RECEIVED")
    if any(c["status"] in system.OPEN_CLAIM_STATES
           for c in system.claims_of_shipment(shipment["id"])):
        fail("ERR_INVALID_STATE",
             "Open damage claims block clearance")
    accepted = {r["crate_id"] for r in system.reports_of_shipment(shipment["id"])
                if r["phase"] == "UNPACK" and r["status"] == "ACCEPTED"}
    if any(cid not in accepted for cid in shipment["crate_ids"]):
        fail("ERR_INVALID_STATE",
             "Every crate on the manifest needs an ACCEPTED UNPACK report")
    shipment["status"] = "CLEARED"
    db.touch(shipment)
    return ok_object(shipment_out(shipment))

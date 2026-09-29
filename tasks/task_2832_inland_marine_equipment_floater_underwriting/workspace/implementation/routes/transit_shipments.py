from flask import Blueprint, request

import rating
import store
import views
from common import (API_PREFIX, clock_date, clock_now, envelope_list,
                    envelope_object, fail, paginate, parse_pagination, require)

bp = Blueprint("transit_shipments", __name__)

SHIPMENT = "/transit-shipments/<shipment_id>"


def _shipment(shipment_id):
    return store.find(store.transit_shipments, shipment_id,
                      "ERR_TRANSIT_SHIPMENT_NOT_FOUND")


@bp.get(API_PREFIX + "/transit-shipments")
def list_shipments():
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster")
    limit, offset = parse_pagination()
    rows = store.order(list(store.transit_shipments.values()))
    for field in ("coverage_part_id", "vehicle_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.shipment_view(r) for r in page], limit, offset, total)


@bp.get(API_PREFIX + SHIPMENT)
def get_shipment(shipment_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    shipment = _shipment(shipment_id)
    return envelope_object(views.shipment_view(shipment), 200)


@bp.post(API_PREFIX + SHIPMENT + "/depart")
def depart_shipment(shipment_id):
    require("Underwriter")
    shipment = _shipment(shipment_id)
    if shipment["status"] != "PLANNED":
        fail("ERR_SHIPMENT_NOT_IN_REQUIRED_STATE",
             "Shipment is %s" % shipment["status"])
    part = store.coverage_parts[shipment["coverage_part_id"]]
    policy = store.policies[part["policy_id"]]
    if policy["status"] != "IN_FORCE":
        fail("ERR_POLICY_NOT_IN_FORCE", "Policy is %s" % policy["status"])
    vehicle = store.vehicles[shipment["vehicle_id"]]
    if vehicle["status"] != "APPROVED":
        fail("ERR_VEHICLE_NOT_APPROVED", "Vehicle is %s" % vehicle["status"])
    if vehicle["ownership"] == "HIRED":
        expires = vehicle.get("approval_expires_on")
        if expires is None or clock_date() >= expires:
            # The lapse has two effects in the same call: the conveyance is
            # suspended and the departure is refused.
            vehicle["status"] = "SUSPENDED"
            store.touch(vehicle)
            fail("ERR_VEHICLE_APPROVAL_EXPIRED",
                 "Carrier approval for vehicle %s has lapsed" % vehicle["id"])
    catastrophe_zone, applicable_limit = rating.transit_applicable_limit(
        part, vehicle, shipment["origin_territory_code"],
        shipment["destination_territory_code"])
    shipment["catastrophe_zone"] = catastrophe_zone
    shipment["applicable_limit_cents"] = (applicable_limit if applicable_limit
                                          is not None else 0)
    shipment["status"] = "IN_TRANSIT"
    shipment["departed_at"] = clock_now()
    store.touch(shipment)
    store.touch(vehicle)
    return envelope_object(views.shipment_view(shipment), 200)


@bp.post(API_PREFIX + SHIPMENT + "/deliver")
def deliver_shipment(shipment_id):
    require("Underwriter")
    shipment = _shipment(shipment_id)
    if shipment["status"] != "IN_TRANSIT":
        fail("ERR_SHIPMENT_NOT_IN_REQUIRED_STATE",
             "Shipment is %s" % shipment["status"])
    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = clock_now()
    store.touch(shipment)
    vehicle = store.vehicles.get(shipment["vehicle_id"])
    if vehicle is not None:
        store.touch(vehicle)
    return envelope_object(views.shipment_view(shipment), 200)

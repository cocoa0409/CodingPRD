from flask import Blueprint

import rating
import store
import views
from common import (API_PREFIX, body, clock_date, clock_now, envelope_object, fail,
                    get_date, get_enum, get_int, get_str, require)

bp = Blueprint("vehicles", __name__)


@bp.post(API_PREFIX + "/vehicles")
def create_vehicle():
    require("Underwriter")
    b = body()
    unit_label = get_str(b, "unit_label", max_len=200)
    ownership = get_enum(b, "ownership", ("OWNED", "HIRED"))
    per_conveyance_limit_cents = get_int(b, "per_conveyance_limit_cents", minimum=1)
    carrier_name = get_str(b, "carrier_name", required=False, max_len=200)
    approval_expires_on = get_date(b, "approval_expires_on", required=False)
    row = store.make({
        "unit_label": unit_label,
        "ownership": ownership,
        "carrier_name": carrier_name,
        "per_conveyance_limit_cents": per_conveyance_limit_cents,
        "approval_expires_on": approval_expires_on,
        "status": "PENDING_APPROVAL",
        "in_transit_value_cents": 0,
        "approved_at": None,
    })
    store.vehicles[row["id"]] = row
    return envelope_object(views.vehicle_view(row), 201)


@bp.get(API_PREFIX + "/vehicles/<vehicle_id>")
def get_vehicle(vehicle_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster")
    vehicle = store.find(store.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    return envelope_object(views.vehicle_view(vehicle), 200)


@bp.post(API_PREFIX + "/vehicles/<vehicle_id>/approve")
def approve_vehicle(vehicle_id):
    require("Underwriter")
    vehicle = store.find(store.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    b = body()
    supplied = get_date(b, "approval_expires_on", required=False)
    if vehicle["status"] not in ("PENDING_APPROVAL", "SUSPENDED"):
        fail("ERR_VEHICLE_ALREADY_APPROVED", "Vehicle is already APPROVED")
    if vehicle["ownership"] == "HIRED":
        if not vehicle.get("carrier_name"):
            fail("ERR_CARRIER_APPROVAL_MISSING",
                 "A HIRED conveyance requires a carrier_name")
        if vehicle["status"] == "SUSPENDED" and supplied is None:
            fail("ERR_CARRIER_APPROVAL_MISSING",
                 "Re-approving a suspended conveyance requires a fresh "
                 "approval_expires_on")
        effective = supplied if supplied is not None else vehicle.get("approval_expires_on")
        if effective is None or effective <= clock_date():
            fail("ERR_CARRIER_APPROVAL_MISSING",
                 "approval_expires_on must be strictly after the current date")
    if supplied is not None:
        vehicle["approval_expires_on"] = supplied
    vehicle["status"] = "APPROVED"
    vehicle["approved_at"] = clock_now()
    store.touch(vehicle)
    return envelope_object(views.vehicle_view(vehicle), 200)

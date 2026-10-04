"""Program vehicle endpoints."""

from flask import Blueprint, request

import db
import services as svc
from errors import E_INVALID_REQUEST, raise_error
from db import stamp_created as DB_STAMP
from middleware import VIN_RE, check_schema, is_int, is_str
from middleware import body as get_body
from response import ok, ok_list
from services import by_created, get_vehicle, paginate

bp = Blueprint("vehicles", __name__)

VEHICLE_CLASSES = ("STANDARD", "XL", "LUXURY", "DELIVERY_VAN")
VEHICLE_STATUSES = ("AVAILABLE", "ASSIGNED", "MAINTENANCE", "RECOVERY", "RETIRED")


@bp.post("/program/vehicles")
def create_vehicle():
    payload = get_body()
    check_schema(payload, "POST", "/program/vehicles")
    vin = payload["vin"]
    if not is_str(vin) or not VIN_RE.match(vin):
        raise_error(E_INVALID_REQUEST, "vin must be exactly 17 alphanumeric characters.")
    model_name = payload["model_name"]
    if not is_str(model_name) or not model_name.strip():
        raise_error(E_INVALID_REQUEST, "model_name must be a non-empty string.")
    year = payload["model_year"]
    if not is_int(year) or year < 2018 or year > 2027:
        raise_error(E_INVALID_REQUEST, "model_year must be between 2018 and 2027.")
    vehicle_class = payload["vehicle_class"]
    if vehicle_class not in VEHICLE_CLASSES:
        raise_error(E_INVALID_REQUEST, "vehicle_class is not recognised.")
    odometer = payload["odometer_miles"]
    if not is_int(odometer) or odometer < 0:
        raise_error(E_INVALID_REQUEST, "odometer_miles must be a non-negative integer.")
    region = payload["region_code"]
    if not is_str(region) or len(region) != 2 or region != region.upper() \
            or not region.isalpha():
        raise_error(E_INVALID_REQUEST, "region_code must be a two-letter uppercase code.")
    for existing in db.VEHICLES.values():
        if existing["vin"] == vin:
            raise_error(E_INVALID_REQUEST, "vin is already registered.")

    row = {
        "id": db.new_id(),
        "vin": vin,
        "model_name": model_name,
        "model_year": year,
        "vehicle_class": vehicle_class,
        "odometer_miles": odometer,
        "baseline_odometer_miles": odometer,
        "vehicle_status": "AVAILABLE",
        "assigned_driver_id": None,
        "region_code": region,
        "recovery_entered_at": None,
        "returned_to_available_at": None,
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.VEHICLES[row["id"]] = row
    return ok(svc.vehicle_out(row), 201)


@bp.get("/program/vehicles")
def list_vehicles():
    rows = by_created(db.VEHICLES.values())
    filters = ("assigned_driver_id", "region_code", "vehicle_class", "vehicle_status",
               "model_name")
    for key in filters:
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if str(r[key]) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.vehicle_out(r) for r in page], limit, offset, total)


@bp.get("/program/vehicles/<vehicle_id>")
def get_one_vehicle(vehicle_id):
    return ok(svc.vehicle_out(get_vehicle(vehicle_id)))
"""Passenger manifest endpoints (PRD 3.4): add entries while PENDING/CONFIRMED,
list the manifest."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_RESERVATION_NOT_OWNED
from middleware import authorized, ALL_READ_ROLES
from response import success_object, success_list
from services.core import new_record, public_passenger, sort_created
from validate import (
    get_body, req_str, req_int, opt_bool, require_path_resource, get_pagination,
)

bp = Blueprint("passengers", __name__, url_prefix="/v1")


@bp.post("/reservations/<reservation_id>/passengers")
def add_passenger(reservation_id):
    caller = authorized(["Customer"])
    reservation = require_path_resource("reservations", reservation_id, "reservation")
    body = get_body()
    name = req_str(body, "name")
    weight = req_int(body, "weight_lbs", minimum=0)
    is_minor = opt_bool(body, "is_minor", default=False)
    if reservation["customer_id"] != caller.user_id:
        raise_error(ERR_RESERVATION_NOT_OWNED,
                    "acting customer does not match reservation.customer_id")
    if reservation["booking_status"] not in ("PENDING", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE,
                    f"cannot add passengers while reservation is "
                    f"{reservation['booking_status']}")
    rec = new_record("passengers", {
        "reservation_id": reservation["id"],
        "name": name,
        "weight_lbs": weight,
        "is_minor": is_minor,
    }, with_version=False)
    return success_object(public_passenger(rec), status=201)


@bp.get("/reservations/<reservation_id>/passengers")
def list_passengers(reservation_id):
    authorized(ALL_READ_ROLES)
    require_path_resource("reservations", reservation_id, "reservation")
    items = [p for p in db["passengers"].values()
             if p["reservation_id"] == reservation_id]
    items = sort_created(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public_passenger(p) for p in page], total, limit, offset)

"""Pilot endpoints (PRD 3.1, 2.10): register with external experience, read with
computed currency fields."""
from flask import Blueprint

from middleware import authorized, ALL_READ_ROLES
from response import success_object
from services.core import new_record, public_pilot
from validate import (
    get_body, req_str, req_date, opt_int, opt_number, require_path_resource,
)

bp = Blueprint("pilots", __name__, url_prefix="/v1")


@bp.post("/pilots")
def create_pilot():
    authorized(["OperationsManager"])
    body = get_body()
    rec = new_record("pilots", {
        "name": req_str(body, "name"),
        "certificate_number": req_str(body, "certificate_number"),
        "medical_expires_on": req_date(body, "medical_expires_on"),
        "external_pic_hours_180d": opt_number(body, "external_pic_hours_180d", default=0, minimum=0),
        "external_takeoffs_landings_90d": opt_int(body, "external_takeoffs_landings_90d", default=0, minimum=0),
    })
    return success_object(public_pilot(rec), status=201)


@bp.get("/pilots/<pilot_id>")
def get_pilot(pilot_id):
    authorized(ALL_READ_ROLES)
    rec = require_path_resource("pilots", pilot_id, "pilot")
    return success_object(public_pilot(rec))

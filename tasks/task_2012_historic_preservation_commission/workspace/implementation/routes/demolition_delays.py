"""Demolition delays: listing, lazy expiry, postponement (PRD 3.7)."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_STATE, ERR_POSTPONEMENT_LIMIT_REACHED
from middleware import get_caller, check_role_allowed, authorized, ALL_ROLES
from response import success_object
from routes.helpers import public, list_response
from services.calculations import (
    MAX_POSTPONEMENTS, provisional_delay_end_iso, lazy_expire_delay,
    lazy_expire_all_delays,
)
from services.core import touch
from validate import get_body, require_path_resource
from db import db

bp = Blueprint("demolition_delays", __name__, url_prefix="/preservation")


@bp.get("/demolition-delays")
def list_delays():
    authorized(ALL_ROLES)
    lazy_expire_all_delays()  # lazy EXPIRED evaluation against the logical clock
    filters = {
        "property_id": request.args.get("property_id"),
        "application_id": request.args.get("application_id"),
        "status": request.args.get("status"),
    }
    return list_response("demolition_delays", filters)


@bp.get("/demolition-delays/<rid>")
def get_delay(rid):
    authorized(ALL_ROLES)
    delay = require_path_resource("demolition_delays", rid)
    lazy_expire_delay(delay)
    return success_object(public(delay))


@bp.post("/demolition-delays/<rid>/postpone")
def postpone_delay(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, ["PreservationStaff"])
    delay = require_path_resource("demolition_delays", rid)
    lazy_expire_delay(delay)  # an action on the delay consults the clock first
    # Layer 5: state gate — a postpone after the effective end finds the delay EXPIRED.
    if delay["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE,
                    f"postpone requires ACTIVE, got {delay['status']}")
    # Layer 9: at most two postponements.
    if delay["postponement_count"] >= MAX_POSTPONEMENTS:
        raise_error(ERR_POSTPONEMENT_LIMIT_REACHED,
                    "postponement_count has reached the maximum of 2")
    delay["postponement_count"] += 1
    delay["provisional_delay_end"] = provisional_delay_end_iso(delay)
    touch(delay)
    return success_object(public(delay))

"""LaunchSite endpoints (PRD 3.1): create, read, permission lifecycle events."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized, ALL_READ_ROLES
from response import success_object
from services.core import new_record, touch, public_launch_site
from util import CLOCK
from validate import (
    get_body, req_str, req_int, req_date, require_path_resource,
)

bp = Blueprint("launch_sites", __name__, url_prefix="/v1")


@bp.post("/launch-sites")
def create_launch_site():
    authorized(["OperationsManager"])
    body = get_body()
    rec = new_record("launch_sites", {
        "name": req_str(body, "name"),
        "surface_wind_limit_kts": req_int(body, "surface_wind_limit_kts", minimum=0),
        "aloft_wind_limit_kts": req_int(body, "aloft_wind_limit_kts", minimum=0),
        "per_use_fee_cents": req_int(body, "per_use_fee_cents", minimum=0),
        "permission_status": "PENDING",
        "permission_granted_at": None,
        "permission_expires_on": req_date(body, "permission_expires_on"),
    })
    return success_object(public_launch_site(rec), status=201)


@bp.get("/launch-sites/<site_id>")
def get_launch_site(site_id):
    authorized(ALL_READ_ROLES)
    rec = require_path_resource("launch_sites", site_id, "launch site")
    return success_object(public_launch_site(rec))


@bp.post("/launch-sites/<site_id>/events")
def launch_site_events(site_id):
    authorized(["OperationsManager"])
    rec = require_path_resource("launch_sites", site_id, "launch site")
    body = get_body()
    event_type = req_str(body, "event_type")
    if event_type == "GRANT_PERMISSION":
        # PENDING → GRANTED, or REVOKED → GRANTED (re-grant refreshes the stamp)
        if rec["permission_status"] not in ("PENDING", "REVOKED"):
            raise_error(ERR_INVALID_STATE,
                        f"cannot GRANT_PERMISSION from {rec['permission_status']}")
        rec["permission_status"] = "GRANTED"
        rec["permission_granted_at"] = CLOCK.now_iso()
    elif event_type == "REVOKE_PERMISSION":
        if rec["permission_status"] != "GRANTED":
            raise_error(ERR_INVALID_STATE,
                        f"cannot REVOKE_PERMISSION from {rec['permission_status']}")
        rec["permission_status"] = "REVOKED"
    else:
        from errors import raise_error as _raise, ERR_INVALID_REQUEST
        _raise(ERR_INVALID_REQUEST, f"unknown event_type: {event_type}")
    touch(rec)
    return success_object(public_launch_site(rec))

"""Balloon endpoints (PRD 3.1): register, read, inspection (OCC), ground, return."""
from datetime import timedelta

from flask import Blueprint

from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_BALLOON_GROUNDED,
)
from middleware import authorized, ALL_READ_ROLES
from response import success_object
from services.cascades import ground_balloon_cascade
from services.core import new_record, touch, public_balloon
from util import parse_date, CLOCK
from validate import (
    get_body, req_str, req_int, require_path_resource,
)

bp = Blueprint("balloons", __name__, url_prefix="/v1")


@bp.post("/balloons")
def create_balloon():
    authorized(["OperationsManager"])
    body = get_body()
    rec = new_record("balloons", {
        "registration": req_str(body, "registration"),
        "basket_capacity_passengers": req_int(body, "basket_capacity_passengers", minimum=1),
        "max_gross_weight_lbs": req_int(body, "max_gross_weight_lbs", minimum=1),
        "empty_weight_lbs": req_int(body, "empty_weight_lbs", minimum=0),
        "status": "ACTIVE",
        "last_inspection_on": None,
        "inspection_due_on": None,
    })
    return success_object(public_balloon(rec), status=201)


@bp.get("/balloons/<balloon_id>")
def get_balloon(balloon_id):
    authorized(ALL_READ_ROLES)
    rec = require_path_resource("balloons", balloon_id, "balloon")
    return success_object(public_balloon(rec))


@bp.post("/balloons/<balloon_id>/events")
def balloon_events(balloon_id):
    authorized(["OperationsManager"])
    rec = require_path_resource("balloons", balloon_id, "balloon")
    body = get_body()
    event_type = req_str(body, "event_type")

    if event_type == "RECORD_INSPECTION":
        # Shape: inspected_on date + mandatory OCC field (PRD 2.7)
        inspected = req_str(body, "inspected_on")
        try:
            inspected_date = parse_date(inspected)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "inspected_on must be an ISO date (YYYY-MM-DD)")
        expected = body.get("expected_balloon_version")
        if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
            raise_error(ERR_INVALID_REQUEST,
                        "expected_balloon_version is required and must be an integer")
        # Priority 5: optimistic concurrency
        if expected != rec["version"]:
            raise_error(ERR_STALE_VERSION,
                        f"expected_balloon_version {expected} does not match current "
                        f"version {rec['version']}")
        rec["last_inspection_on"] = inspected_date.isoformat()
        rec["inspection_due_on"] = (inspected_date + timedelta(days=365)).isoformat()
        touch(rec)
        return success_object(public_balloon(rec))

    if event_type == "GROUND":
        if rec["status"] != "ACTIVE":
            raise_error(ERR_INVALID_STATE, f"cannot GROUND from {rec['status']}")
        rec["status"] = "GROUNDED"
        touch(rec)
        ground_balloon_cascade(rec)
        return success_object(public_balloon(rec))

    if event_type == "RETURN_TO_SERVICE":
        if rec["status"] != "GROUNDED":
            raise_error(ERR_INVALID_STATE,
                        f"cannot RETURN_TO_SERVICE from {rec['status']}")
        today = CLOCK.today()
        if (rec["last_inspection_on"] is None
                or parse_date(rec["inspection_due_on"]) < today):
            raise_error(ERR_BALLOON_GROUNDED,
                        "balloon inspection is missing or not current")
        rec["status"] = "ACTIVE"
        touch(rec)
        return success_object(public_balloon(rec))

    raise_error(ERR_INVALID_REQUEST, f"unknown event_type: {event_type}")

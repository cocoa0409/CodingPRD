"""Studio and equipment assets (PRD 3.6)."""

from flask import Blueprint

import constants as C
import db
import middleware
import serialize
import support
import validation
from errors import ApiError, bad_request, invalid_transition

bp = Blueprint("resources", __name__)

READ_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_FACILITIES_MANAGER,
    C.ROLE_SCHEDULING_COORDINATOR,
    C.ROLE_PRODUCER,
)

LEGAL_STATUS_MOVES = {
    ("AVAILABLE", "MAINTENANCE"),
    ("MAINTENANCE", "AVAILABLE"),
    ("AVAILABLE", "RETIRED"),
    ("MAINTENANCE", "RETIRED"),
}


@bp.post("/studio-resources")
def create_resource():
    middleware.authorize(C.ROLE_FACILITIES_MANAGER)
    body = validation.body()
    resource_code = validation.req_string(body, "resource_code")
    resource_class = validation.req_enum(body, "resource_class", C.RESOURCE_CLASSES)
    required_competency_code = validation.req_enum(
        body, "required_competency_code", C.COMPETENCY_CODES
    )
    capacity_slots = validation.req_int(body, "capacity_slots", minimum=1)
    turnaround_minutes = validation.req_int(body, "turnaround_minutes", minimum=0)
    base_deposit_cents = validation.req_int(body, "base_deposit_cents", minimum=0)
    replacement_value_cents = validation.req_int(body, "replacement_value_cents", minimum=0)
    if replacement_value_cents < base_deposit_cents:
        raise bad_request("replacement_value_cents must be at least base_deposit_cents")
    for row in db.all_rows("studio_resources"):
        if row["resource_code"] == resource_code:
            raise ApiError("ERR_DUPLICATE_NATURAL_KEY", "This resource_code is already registered")
    row = db.new_row(
        "studio_resources",
        {
            "resource_code": resource_code,
            "resource_class": resource_class,
            "required_competency_code": required_competency_code,
            "capacity_slots": capacity_slots,
            "turnaround_minutes": turnaround_minutes,
            "base_deposit_cents": base_deposit_cents,
            "replacement_value_cents": replacement_value_cents,
            "status": "AVAILABLE",
            "status_reason": None,
        },
    )
    return support.created("studio_resources", row)


@bp.get("/studio-resources/<resource_id>")
def read_resource(resource_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("studio_resources", resource_id)
    return support.single("studio_resources", row)


@bp.get("/studio-resources")
def list_resources():
    middleware.authorize(*READ_ROLES)
    resource_class = validation.query_enum("resource_class", C.RESOURCE_CLASSES)
    status = validation.query_enum("status", C.RESOURCE_STATUSES)
    validation.pagination()
    rows = support.filter_rows(
        "studio_resources", [("resource_class", resource_class), ("status", status)]
    )
    return support.collection_response("studio_resources", rows)


@bp.post("/studio-resources/<resource_id>/status")
def change_status(resource_id):
    middleware.authorize(C.ROLE_FACILITIES_MANAGER)
    body = validation.body()
    target = validation.req_enum(body, "status", C.RESOURCE_STATUSES)
    status_reason = validation.req_string(body, "status_reason")
    row = support.must_exist("studio_resources", resource_id)
    if (row["status"], target) not in LEGAL_STATUS_MOVES:
        raise invalid_transition("That asset status change is not available")
    # priority 20
    if target == "RETIRED" and serialize.open_reservation_count(resource_id) != 0:
        raise ApiError(
            "ERR_RESOURCE_HAS_OPEN_RESERVATIONS", "The asset still carries open reservations"
        )
    row["status"] = target
    row["status_reason"] = status_reason
    db.bump(row)
    return support.single("studio_resources", row)

"""Employer routes and the test-driving logical-clock facility."""

from flask import Blueprint

from db import clock, format_instant, store
from errors import ERR_INVALID_REQUEST, ApiError
from middleware import PURCHASER_ADMIN, RATING_ADMIN, body_json, require_read, authorize
from routes.common import filter_value, ok_list, ok_object, ok_payload
from services import employers as employer_service

bp = Blueprint("employers", __name__, url_prefix="/hospital-safety-rating")


@bp.post("/employers")
def create_employer():
    authorize([PURCHASER_ADMIN])
    employer = employer_service.create_employer(body_json())
    return ok_object(employer), 201


@bp.get("/employers")
def list_employers():
    require_read()
    rows = list(store.employers.values())
    purchaser_type = filter_value("purchaser_type")
    if purchaser_type is not None:
        rows = [row for row in rows if row.get("purchaser_type") == purchaser_type]
    return ok_list(rows)


@bp.get("/employers/<employer_id>")
def read_employer(employer_id):
    require_read()
    employer = employer_service.get_employer(employer_id)
    employer_service.recompute_employer_counters(employer)
    return ok_object(employer)


@bp.post("/employers/<employer_id>/network-listings")
def set_network_listing(employer_id):
    authorize([PURCHASER_ADMIN])
    employer = employer_service.get_employer(employer_id)
    updated = employer_service.set_network_listing(employer, body_json())
    return ok_object(updated)


# --- Test-driving facility --------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # This is the single operation exempt from the mandatory user-context
    # header check. When the caller does supply a role it must still hold the
    # operation, so a non-administrative role is refused.
    from flask import request
    from errors import ERR_INSUFFICIENT_PERMISSIONS
    supplied_role = request.headers.get("X-User-Role")
    if supplied_role is not None and str(supplied_role).strip() != "":
        if str(supplied_role).strip() != RATING_ADMIN:
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS)

    payload = body_json()
    to_iso8601 = payload.get("to_iso8601")
    if not isinstance(to_iso8601, str) or to_iso8601.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    try:
        instant = clock.set(to_iso8601)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST)
    return ok_payload({"current_utc": format_instant(instant)})
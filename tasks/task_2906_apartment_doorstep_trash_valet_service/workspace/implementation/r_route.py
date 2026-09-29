"""RouteAssignment endpoints (PRD s3.5 dispatch)."""

from flask import Blueprint

import shape
from authz import (
    admit,
    get_contractor,
    get_night,
    get_route,
    night_of_route,
    own,
    property_of_night,
    property_of_route,
)
from calc import (
    has_escalated_jam,
    recompute_assigned_unit_coverage,
    routes_of_contractor,
    routes_of_night,
)
from envelope import array_response, object_response
from errors import ApiError
from serializers import route_out
from shape import pagination, paginate, q
from store import (
    LIVE_ROUTE_STATUSES,
    OPEN_ROUTE_STATUSES,
    UNIT_BASE,
    clock,
    db,
    now_iso,
    parse_instant,
    sort_rows,
    stamp_new,
    touch,
)

bp = Blueprint("route", __name__)

TERMINAL_ROUTE = ("COMPLETED", "ABANDONED", "CANCELLED")


def _require_property_active(prop):
    """Rung 9: the four service-delivery writes are gated on property posture."""
    if prop is None:
        return
    if prop["status"] in ("SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_PROPERTY_SUSPENDED")


@bp.route("/valet/service-nights/<night_id>/route-assignments", methods=["POST"])
def create_route(night_id):
    admit(("PlatformAdmin", "ValetOpsManager"))
    night = get_night(night_id)
    body = shape.body()
    contractor_id = shape.req_str(body, "contractor_id", min_len=1, non_blank=True)
    unit_from = shape.req_int(body, "unit_from")
    unit_to = shape.req_int(body, "unit_to")
    expected_version = shape.req_int(body, "expected_service_night_version")
    if unit_from > unit_to:
        shape.bad("Field 'unit_from' must not exceed 'unit_to'.")

    # rung 6
    contractor = get_contractor(contractor_id)

    prop = property_of_night(night)

    # rung 9
    _require_property_active(prop)

    # rung 10
    if expected_version != night["version"]:
        raise ApiError("ERR_STALE_SERVICE_NIGHT_VERSION")

    # rung 11
    if contractor["onboarding_status"] != "CLEARED" or contractor["classification"] == "UNCLASSIFIED":
        raise ApiError("ERR_CONTRACTOR_NOT_ELIGIBLE")

    # rung 12
    if prop is not None and has_escalated_jam(prop["id"]):
        raise ApiError("ERR_COMPACTOR_BLOCKED")

    # rung 15 -- half-open window intersection against the contractor's live routes
    this_start = parse_instant(night["service_window_start"])
    this_end = parse_instant(night["service_window_end"])
    for other in routes_of_contractor(contractor["id"]):
        if other["status"] not in OPEN_ROUTE_STATUSES:
            continue
        other_night = db.nights.get(other["service_night_id"])
        if other_night is None:
            continue
        other_start = parse_instant(other_night["service_window_start"])
        other_end = parse_instant(other_night["service_window_end"])
        if other_start is None or other_end is None:
            continue
        if this_start < other_end and other_start < this_end:
            raise ApiError("ERR_CONTRACTOR_WINDOW_CONFLICT")

    # rung 19
    if prop is not None:
        lo = UNIT_BASE + 1
        hi = UNIT_BASE + prop["unit_count"]
        if unit_from < lo or unit_from > hi or unit_to < lo or unit_to > hi:
            raise ApiError("ERR_UNIT_RANGE_OUT_OF_BOUNDS")

    # rung 20
    for other in routes_of_night(night["id"]):
        if other["status"] not in LIVE_ROUTE_STATUSES:
            continue
        if unit_from <= other["unit_to"] and other["unit_from"] <= unit_to:
            raise ApiError("ERR_UNIT_RANGE_OVERLAP")

    row = {
        "service_night_id": night["id"],
        "contractor_id": contractor["id"],
        "unit_from": unit_from,
        "unit_to": unit_to,
        "unit_coverage_count": unit_to - unit_from + 1,
        "status": "ASSIGNED",
        "accepted_at": None,
        "completed_at": None,
        "scan_count": 0,
        "abandon_reason": None,
    }
    stamp_new(row)
    db.routes[row["id"]] = row

    recompute_assigned_unit_coverage(night)
    touch(night)
    return object_response(route_out(row), 201)


@bp.route("/valet/route-assignments/<route_id>", methods=["GET"])
def read_route(route_id):
    admit((
        "PlatformAdmin",
        "ValetOpsManager",
        "PropertyManager",
        "ComplianceOfficer",
        "Valet",
    ))
    row = get_route(route_id)
    return object_response(route_out(row))


@bp.route("/valet/route-assignments", methods=["GET"])
def list_routes():
    admit((
        "PlatformAdmin",
        "ValetOpsManager",
        "PropertyManager",
        "ComplianceOfficer",
        "Valet",
    ))
    limit, offset = pagination()
    f_night = q("service_night_id")
    f_contractor = q("contractor_id")
    f_status = q("status")
    rows = sort_rows(list(db.routes.values()))
    if f_night is not None:
        rows = [r for r in rows if r["service_night_id"] == f_night]
    if f_contractor is not None:
        rows = [r for r in rows if r["contractor_id"] == f_contractor]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([route_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/route-assignments/<route_id>/accept", methods=["POST"])
def accept_route(route_id):
    actor = admit(("Valet",))
    route = get_route(route_id)
    own(actor.user_id == route["contractor_id"])
    shape.body()

    # rung 8
    if route["status"] in TERMINAL_ROUTE:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if route["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE")
    contractor = db.contractors.get(route["contractor_id"])
    if contractor is None or contractor["onboarding_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE")

    # rung 9
    _require_property_active(property_of_route(route))

    route["status"] = "ACCEPTED"
    route["accepted_at"] = now_iso()
    touch(route)
    return object_response(route_out(route))


@bp.route("/valet/route-assignments/<route_id>/complete", methods=["POST"])
def complete_route(route_id):
    actor = admit(("Valet",))
    route = get_route(route_id)
    own(actor.user_id == route["contractor_id"])
    shape.body()

    # rung 8
    if route["status"] in TERMINAL_ROUTE:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if route["status"] not in ("ACCEPTED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE")

    # rung 9
    _require_property_active(property_of_route(route))

    route["status"] = "COMPLETED"
    route["completed_at"] = now_iso()
    touch(route)

    night = night_of_route(route)
    if night is not None:
        recompute_assigned_unit_coverage(night)
        touch(night)
    return object_response(route_out(route))


@bp.route("/valet/route-assignments/<route_id>/abandon", methods=["POST"])
def abandon_route(route_id):
    actor = admit(("PlatformAdmin", "ValetOpsManager", "Valet"))
    route = get_route(route_id)
    if actor.role == "Valet":
        own(actor.user_id == route["contractor_id"])
    body = shape.body()
    reason = shape.req_str(body, "reason", min_len=1, max_len=500, non_blank=True)

    # rung 8
    if route["status"] in TERMINAL_ROUTE:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if route["status"] not in OPEN_ROUTE_STATUSES:
        raise ApiError("ERR_INVALID_STATE")

    route["status"] = "ABANDONED"
    route["abandon_reason"] = reason
    touch(route)

    night = night_of_route(route)
    if night is not None:
        recompute_assigned_unit_coverage(night)
        touch(night)
    return object_response(route_out(route))

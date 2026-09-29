"""PermitApplication, MoratoriumWindow and logical-clock endpoints."""

from datetime import datetime

from flask import Blueprint

import calc
import domain
import serialize
import validate as v
from auth import (ALL_ROLES, ROLE_AUTHORITY_REVIEWER, ROLE_NETWORK_RECORDS_ADMIN,
                  ROLE_PERMIT_COORDINATOR, acting_user_id, endpoint)
from envelope import filter_value, object_response, paginate
from errors import ApiError
from store import (INSTANT_FMT, db, new_record, now_dt, now_iso, plus_days, set_clock,
                   sort_by_created, to_iso, touch)

bp = Blueprint("permit", __name__)

PERMIT_CREATE_FIELDS = ("segment_id", "authority_type", "authority_name",
                        "work_window_start_on", "work_window_end_on")
MORATORIUM_CREATE_FIELDS = ("municipality_code", "street_name", "resurfaced_on", "starts_on",
                            "ends_on", "moratorium_class", "ordinance_reference")

ROUTE_PERMITTING_STATUSES = ("SCOPE_LOCKED", "PERMITTING", "CONSTRUCTION_READY")


def _require_permitting_route_status(route):
    if route["status"] not in ROUTE_PERMITTING_STATUSES:
        raise ApiError(
            "ERR_INVALID_ROUTE_STATE",
            "The route must have reached SCOPE_LOCKED before a permit may be filed.",
        )


def _apply_approval(permit, segment, route):
    """The effects shared by an authority approval and a municipal lapsed grant."""
    permit["status"] = "APPROVED"
    domain.try_clear_segment_permit(segment)
    domain.try_advance_route_to_construction_ready(route)


# ---------------------------------------------------------------------------
# PermitApplication
# ---------------------------------------------------------------------------


@bp.route("/permit-applications", methods=["POST"])
@endpoint([ROLE_PERMIT_COORDINATOR])
def create_permit():
    payload = v.body()
    v.check_body(payload, PERMIT_CREATE_FIELDS)
    segment_id = v.req_id(payload, "segment_id")
    authority_type = v.req_enum(payload, "authority_type", calc.AUTHORITY_TYPES)
    authority_name = v.req_str(payload, "authority_name")
    window_start = v.req_date(payload, "work_window_start_on")
    window_end = v.req_date(payload, "work_window_end_on")
    v.order_dates(window_start, window_end, "work_window_start_on", "work_window_end_on")

    segment = domain.get_segment(segment_id)
    route = domain.route_of_segment(segment)
    _require_permitting_route_status(route)

    rec = new_record()
    rec.update({
        "segment_id": segment["id"],
        "authority_type": authority_type,
        "authority_name": authority_name,
        "work_window_start_on": window_start,
        "work_window_end_on": window_end,
        "status": "DRAFT",
        "submitted_at": None,
        "revision_round": 0,
        "review_days": None,
        "decision_due_at": None,
        "decided_at": None,
        "decided_by_user_id": None,
        "deemed": False,
        "decision_note": None,
    })
    db.permits[rec["id"]] = rec
    return object_response(serialize.permit(rec), 201)


@bp.route("/permit-applications/<permit_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_permit(permit_id):
    return object_response(serialize.permit(domain.get_permit(permit_id)))


@bp.route("/permit-applications/<permit_id>/submit", methods=["POST"])
@endpoint([ROLE_PERMIT_COORDINATOR])
def submit_permit(permit_id):
    v.check_body(v.body(), ())
    permit = domain.get_permit(permit_id)
    segment = db.segments[permit["segment_id"]]
    route = domain.route_of_segment(segment)

    _require_permitting_route_status(route)

    if permit["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_PERMIT_STATE")

    conflict = domain.moratorium_intersects_window(
        segment["municipality_code"], segment["street_name"],
        permit["work_window_start_on"], permit["work_window_end_on"],
    )
    if conflict is not None:
        raise ApiError("ERR_MORATORIUM_WINDOW_CONFLICT")

    submitted_dt = now_dt()
    review_days = calc.review_days(
        permit["authority_type"], permit["revision_round"], route["topology_objective"]
    )
    permit["status"] = "UNDER_REVIEW"
    permit["submitted_at"] = to_iso(submitted_dt)
    permit["review_days"] = review_days
    permit["decision_due_at"] = to_iso(plus_days(submitted_dt, review_days))
    touch(permit)

    if segment["permit_status"] in ("NOT_REQUIRED", "CLEARED", "BLOCKED"):
        segment["permit_status"] = "PENDING"
        touch(segment)

    if route["status"] == "SCOPE_LOCKED":
        route["status"] = "PERMITTING"
    domain.recompute_live_complexity_index(route)
    touch(route)
    return object_response(serialize.permit(permit))


@bp.route("/permit-applications/<permit_id>/review", methods=["POST"])
@endpoint([ROLE_AUTHORITY_REVIEWER])
def review_permit(permit_id):
    payload = v.body()
    v.check_body(payload, ("decision", "decision_note"))
    decision = v.req_enum(payload, "decision", calc.PERMIT_DECISIONS)
    decision_note = v.opt_str(payload, "decision_note", default=None)

    permit = domain.get_permit(permit_id)
    if permit["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PERMIT_STATE")

    segment = db.segments[permit["segment_id"]]
    route = domain.route_of_segment(segment)

    permit["decided_at"] = now_iso()
    permit["decided_by_user_id"] = acting_user_id()
    if decision_note is not None:
        permit["decision_note"] = decision_note
    touch(permit)

    if decision == "APPROVED":
        permit["deemed"] = False
        _apply_approval(permit, segment, route)
    elif decision == "REVISION_REQUESTED":
        permit["status"] = "REVISION_REQUESTED"
        permit["revision_round"] = permit["revision_round"] + 1
    else:
        permit["status"] = "DENIED"
        domain.permit_denial_cascade(permit)

    domain.recompute_live_complexity_index(route)
    touch(route)
    return object_response(serialize.permit(permit))


@bp.route("/permit-applications/<permit_id>/deemed-decision", methods=["POST"])
@endpoint([ROLE_PERMIT_COORDINATOR])
def deemed_decision(permit_id):
    v.check_body(v.body(), ())
    permit = domain.get_permit(permit_id)
    if permit["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PERMIT_STATE")

    due_at = permit["decision_due_at"]
    if due_at is None:
        raise ApiError("ERR_REVIEW_WINDOW_OPEN")
    due_dt = datetime.strptime(due_at, INSTANT_FMT)
    if not now_dt() > due_dt:
        raise ApiError("ERR_REVIEW_WINDOW_OPEN")

    segment = db.segments[permit["segment_id"]]
    route = domain.route_of_segment(segment)

    permit["deemed"] = True
    permit["decided_at"] = now_iso()
    permit["decided_by_user_id"] = None
    touch(permit)

    if permit["authority_type"] == "MUNICIPAL_ROW":
        _apply_approval(permit, segment, route)
    else:
        permit["status"] = "DENIED"
        domain.permit_denial_cascade(permit)

    domain.recompute_live_complexity_index(route)
    touch(route)
    return object_response(serialize.permit(permit))


# ---------------------------------------------------------------------------
# MoratoriumWindow
# ---------------------------------------------------------------------------


@bp.route("/moratorium-windows", methods=["POST"])
@endpoint([ROLE_NETWORK_RECORDS_ADMIN])
def create_moratorium_window():
    payload = v.body()
    v.check_body(payload, MORATORIUM_CREATE_FIELDS)
    municipality_code = v.req_str(payload, "municipality_code")
    street_name = v.req_str(payload, "street_name")
    resurfaced_on = v.req_date(payload, "resurfaced_on")
    starts_on = v.req_date(payload, "starts_on")
    ends_on = v.req_date(payload, "ends_on")
    v.order_dates(starts_on, ends_on, "starts_on", "ends_on")
    moratorium_class = v.req_enum(payload, "moratorium_class", calc.MORATORIUM_CLASSES_INPUT)
    ordinance_reference = v.req_str(payload, "ordinance_reference")

    clash = domain.moratorium_intersects_window(
        municipality_code, street_name, starts_on, ends_on
    )
    if clash is not None:
        raise ApiError("ERR_MORATORIUM_WINDOW_OVERLAP")

    rec = new_record()
    rec.update({
        "municipality_code": municipality_code,
        "street_name": street_name,
        "resurfaced_on": resurfaced_on,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "moratorium_class": moratorium_class,
        "ordinance_reference": ordinance_reference,
    })
    db.moratoria[rec["id"]] = rec
    return object_response(serialize.moratorium(rec), 201)


@bp.route("/moratorium-windows", methods=["GET"])
@endpoint(ALL_ROLES)
def list_moratorium_windows():
    rows = sort_by_created(list(db.moratoria.values()))
    municipality_code = filter_value("municipality_code")
    street_name = filter_value("street_name")
    if municipality_code is not None:
        rows = [r for r in rows if r["municipality_code"] == municipality_code]
    if street_name is not None:
        rows = [r for r in rows if r["street_name"] == street_name]
    return paginate(rows, serialize.moratorium)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint([ROLE_NETWORK_RECORDS_ADMIN])
def set_current_utc():
    payload = v.body()
    v.check_body(payload, ("to_iso8601",))
    moment = v.req_instant(payload, "to_iso8601")
    current = set_clock(moment)
    return object_response({"current_utc": current})

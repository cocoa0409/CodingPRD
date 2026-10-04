"""Routes: logical clock, agencies, calendar windows, staff, unavailability windows."""
from flask import Blueprint, request

import db
from errors import raise_error, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services_common import strip_internal, lapse_all_agreements
from util import new_id, now_ts, parse_date, require_fields, require_int, optional_str

bp = Blueprint("agency", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["to_iso8601"])
    import util
    current = util.set_clock(payload["to_iso8601"])
    lapse_all_agreements()
    return success_object({"current_utc": current}, 200)


@bp.route("/programs/agencies", methods=["POST"])
def create_agency():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["agency_code", "display_name"])
    tz = payload.get("primary_time_zone", "America/Chicago")
    if not isinstance(tz, str):
        raise_error("ERR_INVALID_REQUEST", "primary_time_zone must be a string")
    now = now_ts()
    agency = {
        "id": new_id(),
        "agency_code": payload["agency_code"],
        "display_name": payload["display_name"],
        "primary_time_zone": tz,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("agencies", agency)
    return success_object(strip_internal(agency), 201)


def _get_agency(agency_id):
    agency = db.get("agencies", agency_id)
    if agency is None:
        raise_error(ERR_NOT_FOUND, "agency not found")
    return agency


@bp.route("/programs/agencies/<agency_id>", methods=["GET"])
def get_agency(agency_id):
    require_roles("PlatformAdmin", "ProcurementOfficer", "ImplementationManager",
                  "AgencyProjectManager", "BusinessAnalyst", "DataMigrationLead")
    agency = _get_agency(agency_id)
    return success_object(strip_internal(agency), 200)


@bp.route("/programs/agencies/<agency_id>/calendar-windows", methods=["POST"])
def create_calendar_window(agency_id):
    require_roles("PlatformAdmin", "AgencyProjectManager")
    agency = _get_agency(agency_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["kind", "starts_on", "ends_on", "blackout", "description"])
    if payload["kind"] not in ("STATUTORY_DEADLINE", "ELECTION_FREEZE", "FISCAL_YEAR_END"):
        raise_error("ERR_INVALID_REQUEST", "invalid kind")
    starts = parse_date(payload["starts_on"], "starts_on")
    ends = parse_date(payload["ends_on"], "ends_on")
    if not isinstance(payload["blackout"], bool):
        raise_error("ERR_INVALID_REQUEST", "blackout must be boolean")
    if ends < starts:
        raise_error("ERR_INVALID_DATE_RANGE", "ends_on before starts_on")
    now = now_ts()
    win = {
        "id": new_id(),
        "agency_id": agency["id"],
        "kind": payload["kind"],
        "starts_on": payload["starts_on"],
        "ends_on": payload["ends_on"],
        "blackout": payload["blackout"],
        "description": payload["description"],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("calendar_windows", win)
    return success_object(strip_internal(win), 201)


@bp.route("/programs/agencies/<agency_id>/calendar-windows", methods=["GET"])
def list_calendar_windows(agency_id):
    require_roles("PlatformAdmin", "AgencyProjectManager", "ImplementationManager")
    agency = _get_agency(agency_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("calendar_windows", agency_id=agency["id"])
    kind = request.args.get("kind")
    if kind is not None:
        items = [w for w in items if w["kind"] == kind]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(w) for w in page], limit, offset, total)


@bp.route("/programs/agencies/<agency_id>/staff", methods=["POST"])
def create_staff(agency_id):
    require_roles("AgencyProjectManager", "PlatformAdmin")
    agency = _get_agency(agency_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["full_name", "email", "tenure_years", "staff_function"])
    tenure = require_int(payload, "tenure_years")
    if payload["staff_function"] not in ("SUBJECT_MATTER_EXPERT", "UAT_TESTER", "TRAINEE", "PROJECT_SPONSOR"):
        raise_error("ERR_INVALID_REQUEST", "invalid staff_function")
    # email unique per agency
    for s in db.filter_items("staff", agency_id=agency["id"]):
        if s["email"] == payload["email"]:
            raise_error("ERR_DUPLICATE_KEY", "email already registered for agency")
    now = now_ts()
    staff = {
        "id": new_id(),
        "agency_id": agency["id"],
        "full_name": payload["full_name"],
        "email": payload["email"],
        "tenure_years": tenure,
        "staff_function": payload["staff_function"],
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("staff", staff)
    return success_object(strip_internal(staff), 201)


@bp.route("/programs/agencies/<agency_id>/staff", methods=["GET"])
def list_staff(agency_id):
    require_roles("AgencyProjectManager", "PlatformAdmin", "ImplementationManager")
    agency = _get_agency(agency_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("staff", agency_id=agency["id"])
    sf = request.args.get("staff_function")
    if sf is not None:
        items = [s for s in items if s["staff_function"] == sf]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(s) for s in page], limit, offset, total)


def _get_staff(staff_id):
    s = db.get("staff", staff_id)
    if s is None:
        raise_error(ERR_NOT_FOUND, "staff not found")
    return s


@bp.route("/programs/staff/<staff_id>", methods=["GET"])
def get_staff(staff_id):
    require_roles("AgencyProjectManager", "PlatformAdmin", "ImplementationManager")
    return success_object(strip_internal(_get_staff(staff_id)), 200)


@bp.route("/programs/staff/<staff_id>/unavailability-windows", methods=["POST"])
def create_unavailability(staff_id):
    require_roles("AgencyProjectManager")
    staff = _get_staff(staff_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["starts_on", "ends_on", "reason"])
    starts = parse_date(payload["starts_on"], "starts_on")
    ends = parse_date(payload["ends_on"], "ends_on")
    if ends < starts:
        raise_error("ERR_INVALID_DATE_RANGE", "ends_on before starts_on")
    win = {
        "id": new_id(),
        "staff_member_id": staff["id"],
        "starts_on": payload["starts_on"],
        "ends_on": payload["ends_on"],
        "reason": payload["reason"],
        "created_at": now_ts(),
    }
    db.put("unavailability_windows", win)
    return success_object(strip_internal(win), 201)


@bp.route("/programs/staff/<staff_id>/unavailability-windows", methods=["GET"])
def list_unavailability(staff_id):
    require_roles("AgencyProjectManager", "ImplementationManager")
    staff = _get_staff(staff_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("unavailability_windows", staff_member_id=staff["id"])
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(w) for w in page], limit, offset, total)


@bp.route("/programs/staff/<staff_id>/uat-sessions", methods=["GET"])
def list_staff_uat_sessions(staff_id):
    require_roles("AgencyProjectManager", "ImplementationManager", "PlatformAdmin")
    staff = _get_staff(staff_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("uat_sessions", assigned_tester_id=staff["id"])
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(s) for s in page], limit, offset, total)


@bp.route("/programs/staff/<staff_id>/training-enrollments", methods=["GET"])
def list_staff_enrollments(staff_id):
    require_roles("AgencyProjectManager", "ImplementationManager", "PlatformAdmin")
    staff = _get_staff(staff_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("training_enrollments", staff_member_id=staff["id"])
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(e) for e in page], limit, offset, total)

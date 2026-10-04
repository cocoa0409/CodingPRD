"""Routes: interface endpoints and certifications."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_CERTIFICATION_WINDOW_OVERLAP, ERR_CERTIFICATION_OUTSIDE_WINDOW,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from routes_contracts import get_contract_or_404
from services_common import strip_internal, append_audit, recompute_readiness
from util import new_id, now_ts, touch, require_fields, parse_date, get_clock_date

bp = Blueprint("interfaces", __name__)


def get_interface_or_404(iid):
    i = db.get("interfaces", iid)
    if i is None:
        raise_error(ERR_NOT_FOUND, "interface not found")
    return i


def get_cert_or_404(cid):
    c = db.get("certifications", cid)
    if c is None:
        raise_error(ERR_NOT_FOUND, "certification not found")
    return c


def _windows_conflict(a_start, a_end, b_start, b_end):
    """Strict interior overlap; adjacency (end+1 == start) allowed."""
    if not (a_start <= b_end and b_start <= a_end):
        return False
    adjacent = (a_end + timedelta(days=1) == b_start) or (b_end + timedelta(days=1) == a_start)
    return not adjacent


def _check_window_overlap(interface_id, start, end, exclude_id=None):
    for cert in db.filter_items("certifications", interface_endpoint_id=interface_id):
        if cert["status"] == "CANCELLED" or cert["id"] == exclude_id:
            continue
        if _windows_conflict(start, end,
                             parse_date(cert["window_starts_on"]),
                             parse_date(cert["window_ends_on"])):
            raise_error(ERR_CERTIFICATION_WINDOW_OVERLAP,
                        "certification window overlaps existing window")


@bp.route("/programs/contracts/<contract_id>/interfaces", methods=["POST"])
def create_interface(contract_id):
    require_roles("InterfaceEngineer")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["name", "direction", "endpoint_kind"])
    if payload["direction"] not in ("OUTBOUND", "INBOUND"):
        raise_error(ERR_INVALID_REQUEST, "invalid direction")
    if payload["endpoint_kind"] not in ("STATE_SYSTEM", "COURT_SYSTEM",
                                        "PAYMENT_PROCESSOR", "REPORTING_REPOSITORY"):
        raise_error(ERR_INVALID_REQUEST, "invalid endpoint_kind")
    now = now_ts()
    iface = {
        "id": new_id(),
        "contract_id": c["id"],
        "name": payload["name"],
        "direction": payload["direction"],
        "endpoint_kind": payload["endpoint_kind"],
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("interfaces", iface)
    return success_object(strip_internal(iface), 201)


@bp.route("/programs/contracts/<contract_id>/interfaces", methods=["GET"])
def list_interfaces(contract_id):
    require_roles("InterfaceEngineer", "ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("interfaces", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    kind = request.args.get("endpoint_kind")
    if kind is not None:
        items = [i for i in items if i["endpoint_kind"] == kind]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(i) for i in page], limit, offset, total)


@bp.route("/programs/interfaces/<iid>", methods=["GET"])
def get_interface(iid):
    require_roles("InterfaceEngineer", "ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    return success_object(strip_internal(get_interface_or_404(iid)), 200)


@bp.route("/programs/interfaces/<iid>/start-development", methods=["POST"])
def start_development(iid):
    require_roles("InterfaceEngineer")
    i = get_interface_or_404(iid)
    if i["status"] != "PLANNED":
        raise_error(ERR_INVALID_STATE, "interface not PLANNED")
    i["status"] = "IN_DEVELOPMENT"
    touch(i)
    return success_object(strip_internal(i), 200)


@bp.route("/programs/interfaces/<iid>/start-testing", methods=["POST"])
def start_testing(iid):
    require_roles("InterfaceEngineer")
    i = get_interface_or_404(iid)
    if i["status"] != "IN_DEVELOPMENT":
        raise_error(ERR_INVALID_STATE, "interface not IN_DEVELOPMENT")
    i["status"] = "IN_TESTING"
    touch(i)
    return success_object(strip_internal(i), 200)


@bp.route("/programs/interfaces/<iid>/certifications", methods=["POST"])
def create_certification(iid):
    require_roles("InterfaceEngineer")
    iface = get_interface_or_404(iid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["window_starts_on", "window_ends_on"])
    start = parse_date(payload["window_starts_on"], "window_starts_on")
    end = parse_date(payload["window_ends_on"], "window_ends_on")
    if end < start:
        raise_error("ERR_INVALID_DATE_RANGE", "window_ends_on before window_starts_on")
    _check_window_overlap(iface["id"], start, end)
    now = now_ts()
    cert = {
        "id": new_id(),
        "interface_endpoint_id": iface["id"],
        "contract_id": iface["contract_id"],
        "window_starts_on": payload["window_starts_on"],
        "window_ends_on": payload["window_ends_on"],
        "status": "SCHEDULED",
        "attempt_no": 1,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("certifications", cert)
    return success_object(strip_internal(cert), 201)


@bp.route("/programs/interfaces/<iid>/certifications", methods=["GET"])
def list_certifications(iid):
    require_roles("InterfaceEngineer", "AgencyProjectManager", "PlatformAdmin")
    iface = get_interface_or_404(iid)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("certifications", interface_endpoint_id=iface["id"])
    contract_id = request.args.get("contract_id")
    if contract_id is not None:
        items = [c for c in items if c["contract_id"] == contract_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(c) for c in page], limit, offset, total)


@bp.route("/programs/contracts/<contract_id>/interface-certifications", methods=["GET"])
def list_contract_certifications(contract_id):
    require_roles("InterfaceEngineer", "AgencyProjectManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("certifications", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(x) for x in page], limit, offset, total)


@bp.route("/programs/interface-certifications/<cid>", methods=["GET"])
def get_certification(cid):
    require_roles("InterfaceEngineer", "AgencyProjectManager", "PlatformAdmin")
    return success_object(strip_internal(get_cert_or_404(cid)), 200)


@bp.route("/programs/interface-certifications/<cid>/begin", methods=["POST"])
def begin_certification(cid):
    require_roles("InterfaceEngineer")
    cert = get_cert_or_404(cid)
    if cert["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "certification not SCHEDULED")
    iface = get_interface_or_404(cert["interface_endpoint_id"])
    if iface["status"] != "IN_TESTING":
        raise_error(ERR_INVALID_STATE, "interface not IN_TESTING")
    today = get_clock_date()
    if not (parse_date(cert["window_starts_on"]) <= today <= parse_date(cert["window_ends_on"])):
        raise_error(ERR_CERTIFICATION_OUTSIDE_WINDOW, "clock date outside certification window")
    for other in db.filter_items("certifications", interface_endpoint_id=iface["id"]):
        if other["id"] != cert["id"] and other["status"] == "IN_PROGRESS":
            raise_error(ERR_INVALID_STATE, "another certification is IN_PROGRESS")
    cert["status"] = "IN_PROGRESS"
    touch(cert)
    return success_object(strip_internal(cert), 200)


@bp.route("/programs/interface-certifications/<cid>/pass", methods=["POST"])
def pass_certification(cid):
    user_id, role = require_roles("AgencyProjectManager")
    cert = get_cert_or_404(cid)
    if cert["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "certification not IN_PROGRESS")
    cert["status"] = "PASSED"
    touch(cert)
    iface = get_interface_or_404(cert["interface_endpoint_id"])
    first_pass = not any(
        c["status"] == "PASSED" and c["id"] != cert["id"]
        for c in db.filter_items("certifications", interface_endpoint_id=iface["id"]))
    if first_pass:
        iface["status"] = "CERTIFIED"
        touch(iface)
    recompute_readiness(cert["contract_id"])
    append_audit(cert["contract_id"], role, user_id,
                 "POST /programs/interface-certifications/{id}/pass",
                 "InterfaceCertification", cert["id"], "IN_PROGRESS -> PASSED")
    return success_object(strip_internal(cert), 200)


@bp.route("/programs/interface-certifications/<cid>/fail", methods=["POST"])
def fail_certification(cid):
    require_roles("AgencyProjectManager")
    cert = get_cert_or_404(cid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["failure_note"])
    if cert["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "certification not IN_PROGRESS")
    cert["status"] = "FAILED"
    touch(cert)
    return success_object(strip_internal(cert), 200)


@bp.route("/programs/interface-certifications/<cid>/retry", methods=["POST"])
def retry_certification(cid):
    require_roles("InterfaceEngineer")
    cert = get_cert_or_404(cid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["window_starts_on", "window_ends_on"])
    if cert["status"] != "FAILED":
        raise_error(ERR_INVALID_STATE, "certification not FAILED")
    start = parse_date(payload["window_starts_on"], "window_starts_on")
    end = parse_date(payload["window_ends_on"], "window_ends_on")
    if end < start:
        raise_error("ERR_INVALID_DATE_RANGE", "window_ends_on before window_starts_on")
    _check_window_overlap(cert["interface_endpoint_id"], start, end, exclude_id=cert["id"])
    cert["window_starts_on"] = payload["window_starts_on"]
    cert["window_ends_on"] = payload["window_ends_on"]
    cert["status"] = "SCHEDULED"
    cert["attempt_no"] += 1
    touch(cert)
    return success_object(strip_internal(cert), 200)


@bp.route("/programs/interface-certifications/<cid>/cancel", methods=["POST"])
def cancel_certification(cid):
    require_roles("InterfaceEngineer")
    cert = get_cert_or_404(cid)
    if cert["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "certification not SCHEDULED")
    cert["status"] = "CANCELLED"
    touch(cert)
    return success_object(strip_internal(cert), 200)

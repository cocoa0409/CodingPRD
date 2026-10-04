"""ManufacturerClient endpoints."""

from datetime import date

from flask import Blueprint, request

from db import db
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_forbidden_ownership,
    err_client_suspended,
    err_reidentification_prohibited,
    err_audit_cooldown_active,
)
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.cascades import reinstate_client_cascade
from services.common import body_json, require_fields, check_str, check_int, check_enum, check_date, mint

bp = Blueprint("clients", __name__)

ALL_ROLES_NO_SO = ["PlatformAdmin", "DataAcquisitionManager", "PrivacyOfficer", "ManufacturerClient"]

PURPOSES = {"AUDIT_COMPLIANCE", "REIDENTIFICATION"}


def _sorted(store_values):
    return sorted(store_values, key=lambda e: e["created_at"])


@bp.route("/clients", methods=["POST"])
def create_client():
    require_role(["PlatformAdmin"])
    data = body_json()
    require_fields(data, ["name", "entitlement_cells_total"])
    name = check_str(data, "name")
    total = check_int(data, "entitlement_cells_total", min_v=0)
    client = mint(db.clients, {
        "name": name,
        "status": "ACTIVE",
        "entitlement_cells_total": total,
        "entitlement_cells_balance": total,
    })
    return success_object(client, status=201)


@bp.route("/clients", methods=["GET"])
def list_clients():
    require_role(ALL_ROLES)
    limit, offset = get_pagination()
    status = None
    if "status" in request.args:
        status = request.args.get("status")
        if status not in ("ACTIVE", "SUSPENDED"):
            raise err_invalid_request("status must be ACTIVE or SUSPENDED")
    items = _sorted(db.clients.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)


@bp.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    user_id, role = require_role(ALL_ROLES_NO_SO)
    client = db.clients.get(cid)
    if client is None:
        raise err_not_found("Client not found")
    if role == "ManufacturerClient" and user_id != cid:
        raise err_forbidden_ownership()
    return success_object(client)


@bp.route("/clients/<cid>/reinstate", methods=["POST"])
def reinstate_client(cid):
    require_role(["PlatformAdmin"])
    client = db.clients.get(cid)
    if client is None:
        raise err_not_found("Client not found")
    if client["status"] != "SUSPENDED":
        raise err_invalid_state("Client must be SUSPENDED to reinstate")
    reinstate_client_cascade(client)
    return success_object(client)


@bp.route("/clients/<cid>/report-products", methods=["GET"])
def list_client_products(cid):
    user_id, role = require_role(ALL_ROLES_NO_SO)
    client = db.clients.get(cid)
    if client is None:
        raise err_not_found("Client not found")
    if role == "ManufacturerClient" and user_id != cid:
        raise err_forbidden_ownership()
    limit, offset = get_pagination()
    items = _sorted([p for p in db.products.values() if p["client_id"] == cid])
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)


@bp.route("/clients/<cid>/audit-events", methods=["GET"])
def list_client_audit_events(cid):
    user_id, role = require_role(["PlatformAdmin", "PrivacyOfficer", "ManufacturerClient"])
    client = db.clients.get(cid)
    if client is None:
        raise err_not_found("Client not found")
    if role == "ManufacturerClient" and user_id != cid:
        raise err_forbidden_ownership()
    limit, offset = get_pagination()
    items = _sorted([a for a in db.audit_events.values() if a["client_id"] == cid])
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)


@bp.route("/clients/<cid>/audit-requests", methods=["POST"])
def request_audit(cid):
    user_id, role = require_role(["ManufacturerClient"])
    if user_id != cid:
        raise err_forbidden_ownership()
    client = db.clients.get(cid)
    if client is None:
        raise err_not_found("Client not found")
    data = body_json()
    require_fields(data, ["window_start_date", "window_end_date", "purpose"])
    start = check_date(data, "window_start_date")
    end = check_date(data, "window_end_date")
    purpose = check_enum(data, "purpose", PURPOSES)
    if not end > start:
        raise err_invalid_request("window_end_date must be > window_start_date")
    if client["status"] != "ACTIVE":
        raise err_client_suspended()
    if purpose == "REIDENTIFICATION":
        raise err_reidentification_prohibited()
    # Cooldown: >= 30 whole days after the latest COMPLETED audit's window_end_date.
    completed = [a for a in db.audit_events.values()
                 if a["client_id"] == cid and a["status"] == "COMPLETED"]
    if completed:
        prev = sorted(completed, key=lambda a: (a["window_end_date"], a["created_at"]))[-1]
        gap = (date.fromisoformat(start) - date.fromisoformat(prev["window_end_date"])).days
        if gap < 30:
            raise err_audit_cooldown_active()
    # Overlap with any REQUESTED / SCHEDULED audit of the client (half-open).
    for a in db.audit_events.values():
        if a["client_id"] == cid and a["status"] in ("REQUESTED", "SCHEDULED"):
            if start < a["window_end_date"] and a["window_start_date"] < end:
                raise err_audit_cooldown_active()
    event = mint(db.audit_events, {
        "client_id": cid,
        "window_start_date": start,
        "window_end_date": end,
        "purpose": purpose,
        "outcome": None,
        "status": "REQUESTED",
    })
    return success_object(event, status=201)

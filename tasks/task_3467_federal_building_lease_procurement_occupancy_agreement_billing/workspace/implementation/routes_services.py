"""ServiceTicket endpoints (PRD section 3.7)."""
from flask import Blueprint, request

from calc import sla_adjudicate
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, agency_scope, body, paginate, require_auth)
from store import DB, bump, make_entity, now_str, pub, sorted_items

bp = Blueprint("services", __name__)


@bp.route("/leasing/buildings/<bid>/service-tickets", methods=["POST"])
def create_ticket(bid):
    uid, role = require_auth(["AgencyManager", "GSAPropertyManager"])
    b = body()
    roa = b.get("reported_oa_id")
    oa = DB["oas"].get(roa) if roa is not None else None
    # priority 3: agency scope (evaluable only when the OA resolves)
    if role == "AgencyManager" and oa is not None and oa["agency_id"] != uid:
        raise ApiError("ERR_AGENCY_SCOPE_VIOLATION", 403,
                       "AgencyManager may only report tickets for their own agency's OAs")
    # priority 4: path id (building) first, then body id (reported_oa_id)
    if bid not in DB["buildings"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Building not found")
    if roa is not None and oa is None:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    # priority 5: shape
    if not isinstance(roa, str) or roa == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "reported_oa_id is required")
    if b.get("category") not in ("MAINTENANCE", "SECURITY", "CLEANING"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "category must be MAINTENANCE, SECURITY, or CLEANING")
    if b.get("severity") not in ("CRITICAL", "ROUTINE"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "severity must be CRITICAL or ROUTINE")
    if not isinstance(b.get("description"), str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "description is required")
    # priority 7/10: the reported OA must be ACTIVE and on this building
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "reported_oa_id must resolve to an ACTIVE occupancy agreement")
    oa_building = oa["building_id"] if oa.get("building_id") else DB["leases"][oa["lease_id"]]["building_id"]
    if oa_building != bid:
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "reported_oa_id must be an ACTIVE OA on this building")
    e = make_entity()
    e.update({
        "building_id": bid,
        "reported_oa_id": roa,
        "category": b["category"],
        "severity": b["severity"],
        "description": b["description"],
        "status": "OPEN",
        "sla_hours": 24 if b["severity"] == "CRITICAL" else 72,
        "resolved_at": None,
        "verified_at": None,
        "sla_breached": None,
        "credit_cents": None,
    })
    DB["tickets"][e["id"]] = e
    return success(pub(e), 201)


@bp.route("/leasing/buildings/<bid>/service-tickets", methods=["GET"])
def list_tickets(bid):
    require_auth(ALL_ROLES)
    if bid not in DB["buildings"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Building not found")
    items = [t for t in DB["tickets"].values() if t["building_id"] == bid]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, pagination = paginate(sorted_items(items))
    return success([pub(t) for t in page], 200, pagination)


@bp.route("/leasing/service-tickets/<tid>/resolve", methods=["POST"])
def resolve_ticket(tid):
    require_auth(["GSAPropertyManager"])
    t = DB["tickets"].get(tid)
    if not t:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceTicket not found")
    if t["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an OPEN ticket can be resolved")
    t["resolved_at"] = now_str()
    t["status"] = "RESOLVED"
    bump(t)
    return success(pub(t))


@bp.route("/leasing/service-tickets/<tid>/verify", methods=["POST"])
def verify_ticket(tid):
    uid, role = require_auth(["AgencyManager"])
    t = DB["tickets"].get(tid)
    if not t:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceTicket not found")
    oa = DB["oas"][t["reported_oa_id"]]
    agency_scope(uid, role, oa["agency_id"])
    if t["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a RESOLVED ticket can be verified")
    t["verified_at"] = now_str()
    breached, credit = sla_adjudicate(t)
    t["sla_breached"] = breached
    t["credit_cents"] = credit
    if credit > 0:
        oa["pending_service_credit_cents"] += credit
        bump(oa)
    t["status"] = "VERIFIED"
    bump(t)
    return success(pub(t))

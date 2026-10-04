"""Product shelf and solicitation request routes (§3.8)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, require_string, require_enum, get_or_404,
    stamp_new, touch, paginate, sort_by_created_at,
)
from response import success_object, success_list

bp = Blueprint("compliance", __name__)
SHELF = "/branch-office/product-shelf"
SOLICIT = "/branch-office/solicitation-requests"

ASSET_CLASSES = {"MUTUAL_FUND", "ETF", "ANNUITY", "BOND", "ALTERNATIVE"}
COMPLEXITY_LEVELS = {"PLAIN", "COMPLEX", "RESTRICTED"}


def _approved_entry(product_code):
    for e in db.product_shelf.values():
        if e.get("product_code") == product_code and e.get("status") == "APPROVED":
            return e
    return None


@bp.route(SHELF, methods=["POST"])
def create_shelf_entry():
    user_id, role = auth_context()
    require_role(role, {"CompliancePrincipal"})
    body = body_json()
    require_fields(body, ["product_code", "asset_class", "complexity_level"])
    code = require_string(body, "product_code")
    asset_class = require_enum(body, "asset_class", ASSET_CLASSES)
    complexity = require_enum(body, "complexity_level", COMPLEXITY_LEVELS)
    if _approved_entry(code) is not None:
        raise err("ERR_DUPLICATE", "An APPROVED entry with this product_code already exists.")
    entry = stamp_new({
        "product_code": code,
        "asset_class": asset_class,
        "complexity_level": complexity,
        "status": "PROPOSED",
    }, with_version=False)
    db.product_shelf[entry["id"]] = entry
    return success_object(entry, 201)


@bp.route(SHELF, methods=["GET"])
def list_shelf():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor", "CompliancePrincipal"})
    items = list(db.product_shelf.values())
    status = request.args.get("status")
    if status:
        items = [e for e in items if e.get("status") == status]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{SHELF}/<eid>/approve", methods=["POST"])
def approve_shelf_entry(eid):
    user_id, role = auth_context()
    require_role(role, {"CompliancePrincipal"})
    entry = get_or_404(db.product_shelf, eid, "ProductShelfEntry")
    if entry.get("status") != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Shelf entry is not PROPOSED.")
    if _approved_entry(entry.get("product_code")) is not None:
        raise err("ERR_DUPLICATE", "An APPROVED entry with this product_code already exists.")
    entry["status"] = "APPROVED"
    return success_object(entry)


@bp.route(f"{SHELF}/<eid>/retire", methods=["POST"])
def retire_shelf_entry(eid):
    user_id, role = auth_context()
    require_role(role, {"CompliancePrincipal"})
    entry = get_or_404(db.product_shelf, eid, "ProductShelfEntry")
    if entry.get("status") != "APPROVED":
        raise err("ERR_INVALID_STATE", "Shelf entry is not APPROVED.")
    entry["status"] = "RETIRED"
    return success_object(entry)


@bp.route(SOLICIT, methods=["POST"])
def create_solicitation():
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    body = body_json()
    require_fields(body, ["advisor_id", "product_code", "client_household_id"])
    advisor = get_or_404(db.advisors, body["advisor_id"], "Advisor")
    if advisor["id"] != user_id:
        raise err("ERR_UNAUTHORIZED", "Advisors may only submit their own solicitation requests.")
    code = require_string(body, "product_code")
    household = require_string(body, "client_household_id")
    if _approved_entry(code) is None:
        raise err("ERR_PRODUCT_NOT_ON_SHELF", "No APPROVED shelf entry for this product_code.")
    req_obj = stamp_new({
        "advisor_id": advisor["id"],
        "product_code": code,
        "client_household_id": household,
        "status": "SUBMITTED",
        "decided_by_role": None,
    })
    db.solicitation_requests[req_obj["id"]] = req_obj
    return success_object(req_obj, 201)


@bp.route(SOLICIT, methods=["GET"])
def list_solicitations():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor", "CompliancePrincipal"})
    items = list(db.solicitation_requests.values())
    advisor_id = request.args.get("advisor_id")
    if advisor_id:
        items = [s for s in items if s.get("advisor_id") == advisor_id]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s.get("status") == status]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{SOLICIT}/<sid>/approve", methods=["POST"])
def approve_solicitation(sid):
    user_id, role = auth_context()
    require_role(role, {"CompliancePrincipal"})
    req_obj = get_or_404(db.solicitation_requests, sid, "SolicitationRequest")
    if req_obj.get("status") != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Solicitation request is not SUBMITTED.")
    advisor = db.advisors.get(req_obj.get("advisor_id"))
    if advisor is None:
        raise err("ERR_NOT_FOUND", "Requesting advisor not found.")
    # priority 5: segregation of duties fires before cross-entity gates
    entry = _approved_entry(req_obj.get("product_code"))
    complexity = entry.get("complexity_level") if entry is not None else None
    if complexity in ("COMPLEX", "RESTRICTED") and user_id == advisor["id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "COMPLEX/RESTRICTED solicitations may not be approved by the requester's own session.")
    # cross-entity gates
    if advisor.get("status") not in ("VALIDATED", "PRACTICING"):
        raise err("ERR_INVALID_STATE", "Requesting advisor is not VALIDATED or PRACTICING.")
    branch = db.branches.get(advisor.get("branch_id"))
    if branch is None or branch.get("operating_status") != "OPEN":
        raise err("ERR_INVALID_STATE", "The advisor's branch is not OPEN.")
    if entry is None:
        raise err("ERR_PRODUCT_NOT_ON_SHELF", "No APPROVED shelf entry for this product_code.")
    req_obj["status"] = "APPROVED"
    req_obj["decided_by_role"] = role
    touch(req_obj)
    return success_object(req_obj)


@bp.route(f"{SOLICIT}/<sid>/deny", methods=["POST"])
def deny_solicitation(sid):
    user_id, role = auth_context()
    require_role(role, {"CompliancePrincipal"})
    req_obj = get_or_404(db.solicitation_requests, sid, "SolicitationRequest")
    if req_obj.get("status") != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Solicitation request is not SUBMITTED.")
    req_obj["status"] = "DENIED"
    req_obj["decided_by_role"] = role
    touch(req_obj)
    return success_object(req_obj)


@bp.route(f"{SOLICIT}/<sid>/withdraw", methods=["POST"])
def withdraw_solicitation(sid):
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    req_obj = get_or_404(db.solicitation_requests, sid, "SolicitationRequest")
    if req_obj.get("status") != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Solicitation request is not SUBMITTED.")
    if req_obj.get("advisor_id") != user_id:
        raise err("ERR_UNAUTHORIZED", "Advisors may only withdraw their own requests.")
    req_obj["status"] = "WITHDRAWN"
    touch(req_obj)
    return success_object(req_obj)

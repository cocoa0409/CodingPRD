"""Routes: components and supplier documentation."""
from flask import Blueprint, request
from db import DB, stamp_new, touch
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_sod,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate
from services.core import recompute_kits_for_component

bp = Blueprint("components", __name__)

CATEGORIES = {"PROPULSION", "BODY", "AXLE", "ELECTRICAL", "FARE", "ACCESSIBILITY"}


def get_component_or_404(cid):
    c = DB.components.get(cid)
    if c is None:
        raise err_not_found("Component not found")
    return c


@bp.post("/api/components")
def create_component():
    require_roles("ComplianceOfficer", "PlatformAdmin")
    body = get_body()
    name = body.get("name")
    category = body.get("category")
    unit_cost_cents = body.get("unit_cost_cents")
    is_domestic = body.get("is_domestic")
    if name is None:
        raise err_invalid_request("Missing required field: name")
    if category is None:
        raise err_invalid_request("Missing required field: category")
    if category not in CATEGORIES:
        raise err_invalid_request("Unknown category")
    if unit_cost_cents is None:
        raise err_invalid_request("Missing required field: unit_cost_cents")
    if not isinstance(unit_cost_cents, int) or isinstance(unit_cost_cents, bool):
        raise err_invalid_request("unit_cost_cents must be an integer")
    if is_domestic is None:
        raise err_invalid_request("Missing required field: is_domestic")
    rec = {
        "name": name,
        "category": category,
        "unit_cost_cents": unit_cost_cents,
        "is_domestic": bool(is_domestic),
        "supplier_doc_status": "MISSING",
        "_submitted_by": None,
    }
    stamp_new(rec)
    DB.components[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/components")
def list_components():
    require_roles("PlatformAdmin", "ComplianceOfficer", "SupplierRep", "Auditor", "WarrantyAdmin")
    limit, offset = parse_pagination(request.args)
    category = request.args.get("category")
    doc_status = request.args.get("supplier_doc_status")
    items = list(DB.components.values())
    if category is not None:
        items = [c for c in items if c["category"] == category]
    if doc_status is not None:
        items = [c for c in items if c["supplier_doc_status"] == doc_status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(c) for c in window], limit, offset, total)


@bp.get("/api/components/<componentId>")
def get_component(componentId):
    require_roles("PlatformAdmin", "ComplianceOfficer", "SupplierRep", "Auditor", "WarrantyAdmin")
    c = get_component_or_404(componentId)
    return success_obj(public(c))


@bp.post("/api/components/<componentId>/supplier-docs")
def supplier_docs(componentId):
    uid, role = require_roles("SupplierRep")
    c = get_component_or_404(componentId)
    if c["supplier_doc_status"] not in ("MISSING", "REJECTED"):
        raise err_invalid_state("Component docs cannot be submitted from current state")
    c["supplier_doc_status"] = "SUBMITTED"
    c["_submitted_by"] = uid
    touch(c)
    recompute_kits_for_component(c["id"])
    return success_obj(public(c))


@bp.post("/api/components/<componentId>/verify-docs")
def verify_docs(componentId):
    uid, role = require_roles("ComplianceOfficer")
    c = get_component_or_404(componentId)
    if c["supplier_doc_status"] != "SUBMITTED":
        raise err_invalid_state("Component docs are not SUBMITTED")
    if c.get("_submitted_by") is not None and uid == c["_submitted_by"]:
        raise err_sod("Verifier must differ from submitter")
    c["supplier_doc_status"] = "VERIFIED"
    touch(c)
    recompute_kits_for_component(c["id"])
    return success_obj(public(c))


@bp.post("/api/components/<componentId>/reject-docs")
def reject_docs(componentId):
    uid, role = require_roles("ComplianceOfficer")
    c = get_component_or_404(componentId)
    if c["supplier_doc_status"] != "SUBMITTED":
        raise err_invalid_state("Component docs are not SUBMITTED")
    if c.get("_submitted_by") is not None and uid == c["_submitted_by"]:
        raise err_sod("Rejector must differ from submitter")
    c["supplier_doc_status"] = "REJECTED"
    touch(c)
    recompute_kits_for_component(c["id"])
    return success_obj(public(c))

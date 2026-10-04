"""Workscope versioning: create (OCC-guarded, server-assembled items, life
floor, supersede cascade), approve (cost cap), reject, and reads."""
from flask import Blueprint

from authz import check_operator_ownership, current_caller, require_roles
from calc import append_due_directive_items, workscope_totals
from cascade import supersede_workscope
from envelope import paginate, pagination_params, success
from errors import api_err
from routes_visits import get_visit_or_404, visit_engine
from serialize import requisition_json, workscope_json
from storage import DB, new_id, next_seq, now, touch
from validate import (
    as_enum,
    as_int,
    as_list,
    as_number,
    as_str,
    body,
    opt_field,
    req_field,
)

bp = Blueprint("workscopes", __name__)

ITEM_TYPES = {"MANDATORY_DIRECTIVE", "LLP_REPLACEMENT", "MODULE_OVERHAUL", "INSPECTION"}


def get_workscope_or_404(workscope_id):
    workscope = DB["workscopes"].get(workscope_id)
    if workscope is None:
        raise api_err("ERR_WORKSCOPE_NOT_FOUND", "workscope does not exist")
    return workscope


def workscope_owner_operator(workscope):
    visit = DB["visits"][workscope["shop_visit_id"]]
    return visit_engine(visit)["operator_id"]


def _validate_items(raw_items):
    items = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise api_err("ERR_INVALID_REQUEST", "items[{}] must be an object".format(index))
        item_code = as_str(req_field(raw, "item_code"), "items[].item_code")
        item_type = as_enum(req_field(raw, "item_type"), "items[].item_type", ITEM_TYPES)
        cost = as_number(req_field(raw, "estimated_cost_usd"), "items[].estimated_cost_usd")
        restores = as_int(req_field(raw, "restores_cycles"), "items[].restores_cycles")
        if restores < 0:
            raise api_err("ERR_INVALID_REQUEST", "items[].restores_cycles must be >= 0")
        directive_ref = raw.get("directive_ref")
        if item_type == "MANDATORY_DIRECTIVE":
            if directive_ref is None:
                raise api_err("ERR_INVALID_REQUEST",
                              "items[].directive_ref is required for MANDATORY_DIRECTIVE")
            directive_ref = as_str(directive_ref, "items[].directive_ref")
        else:
            if directive_ref is not None:
                raise api_err("ERR_INVALID_REQUEST",
                              "items[].directive_ref must be null unless MANDATORY_DIRECTIVE")
        items.append({
            "item_code": item_code, "item_type": item_type,
            "estimated_cost_usd": cost, "restores_cycles": restores,
            "directive_ref": directive_ref,
        })
    return items


@bp.route("/api/shop-visits/<visit_id>/workscopes", methods=["POST"])
def create_workscope(visit_id):
    require_roles("ShopPlanner")
    visit = get_visit_or_404(visit_id)
    data = body()
    expected = as_int(req_field(data, "expected_shop_visit_version"),
                      "expected_shop_visit_version")
    raw_items = opt_field(data, "items")
    if raw_items is None:
        raw_items = []
    proposed = _validate_items(as_list(raw_items, "items"))
    if visit["status"] != "INDUCTED":
        raise api_err("ERR_VISIT_NOT_INDUCTED", "visit is not INDUCTED")
    if expected != visit["version"]:
        raise api_err("ERR_STALE_VERSION", "shop visit version has advanced")
    previous = [
        w for w in DB["workscopes"].values()
        if w["shop_visit_id"] == visit_id and w["status"] != "SUPERSEDED"
    ]
    if any(w["status"] == "SUBMITTED" for w in previous):
        raise api_err("ERR_ACTIVE_WORKSCOPE_EXISTS",
                      "the latest workscope version is still SUBMITTED")
    engine = visit_engine(visit)
    items = append_due_directive_items(engine, proposed)
    total, restored = workscope_totals(engine, items)
    for old in previous:
        supersede_workscope(old)
    scope_version = (max((w["scope_version"] for w in previous), default=0)) + 1
    ts = now()
    workscope = {
        "id": new_id(), "shop_visit_id": visit_id, "scope_version": scope_version,
        "status": "SUBMITTED", "items": items, "total_cost_usd": total,
        "restores_llp_cycles": restored, "decided_at": None,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["workscopes"][workscope["id"]] = workscope
    touch(visit)
    return success(workscope_json(workscope), 201)


@bp.route("/api/workscopes/<workscope_id>/approve", methods=["POST"])
def approve_workscope(workscope_id):
    uid, role = require_roles("Operator")
    workscope = get_workscope_or_404(workscope_id)
    check_operator_ownership(uid, role, workscope_owner_operator(workscope))
    if workscope["status"] != "SUBMITTED":
        raise api_err("ERR_WORKSCOPE_NOT_SUBMITTED", "workscope is not SUBMITTED")
    visit = DB["visits"][workscope["shop_visit_id"]]
    if visit["status"] != "INDUCTED":
        raise api_err("ERR_VISIT_NOT_INDUCTED", "visit is not INDUCTED")
    engine = visit_engine(visit)
    agreement = DB["agreements"].get(engine["agreement_id"])
    if agreement is not None and workscope["total_cost_usd"] > agreement["max_workscope_cost_usd"]:
        raise api_err("ERR_WORKSCOPE_COST_CAP_EXCEEDED",
                      "workscope total exceeds the agreement's per-visit cost cap")
    workscope["status"] = "APPROVED"
    workscope["decided_at"] = now()
    touch(workscope)
    return success(workscope_json(workscope), 200)


@bp.route("/api/workscopes/<workscope_id>/reject", methods=["POST"])
def reject_workscope(workscope_id):
    uid, role = require_roles("Operator")
    workscope = get_workscope_or_404(workscope_id)
    check_operator_ownership(uid, role, workscope_owner_operator(workscope))
    if workscope["status"] != "SUBMITTED":
        raise api_err("ERR_WORKSCOPE_NOT_SUBMITTED", "workscope is not SUBMITTED")
    workscope["status"] = "REJECTED"
    workscope["decided_at"] = now()
    touch(workscope)
    return success(workscope_json(workscope), 200)


@bp.route("/api/workscopes/<workscope_id>", methods=["GET"])
def get_workscope(workscope_id):
    current_caller()
    return success(workscope_json(get_workscope_or_404(workscope_id)), 200)


@bp.route("/api/workscopes/<workscope_id>/part-requisitions", methods=["GET"])
def list_workscope_requisitions(workscope_id):
    current_caller()
    get_workscope_or_404(workscope_id)
    limit, offset = pagination_params()
    reqs = sorted(
        (r for r in DB["requisitions"].values() if r["workscope_id"] == workscope_id),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    page, meta = paginate(reqs, limit, offset)
    return success([requisition_json(r) for r in page], 200, meta)

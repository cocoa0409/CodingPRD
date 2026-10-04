"""Requirement catalogue endpoints (versioned rows)."""
from flask import Blueprint, request

import calc
from db import db, serialize
from util import (ApiError, bump, get_json, now_logical, ok, paginate, parse_dt,
                  sort_by_created, new_common)
from routes.shops import require_roles

bp = Blueprint("requirements", __name__)

ROLES_READ = {"NetworkAdmin", "NetworkAuditor", "ShopManager"}
CATEGORIES = {"EQUIPMENT", "TRAINING", "TOOLING", "STRUCTURAL"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}


def _validate_enum(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be one of {sorted(allowed)}")


def _lapse_pinned_attestations(req, reason):
    affected_shops = set()
    for a in db.attestations.values():
        if a["requirement_id"] == req["id"] and a["status"] == "ACTIVE":
            a["status"] = "LAPSED"
            a["lapse_reason"] = reason
            bump(a)
            affected_shops.add(a["shop_id"])
    for shop_id in affected_shops:
        shop = db.shops.get(shop_id)
        if shop:
            calc.recompute_shop_score(shop)
    calc.recompute_all_technicians()


@bp.post("/network/requirements")
def create_requirement():
    require_roles("NetworkAdmin")
    body = get_json()
    code = body.get("requirement_code")
    category = body.get("category")
    description = body.get("description")
    severity = body.get("severity_if_failed")
    effective_from = body.get("effective_from")
    if not isinstance(code, str) or not code:
        raise ApiError("ERR_INVALID_REQUEST", 400, "requirement_code is required")
    _validate_enum(category, CATEGORIES, "category")
    if not isinstance(description, str) or not description:
        raise ApiError("ERR_INVALID_REQUEST", 400, "description is required")
    _validate_enum(severity, SEVERITIES, "severity_if_failed")
    eff = parse_dt(effective_from, "effective_from")
    req = new_common()
    req.update({
        "requirement_code": code,
        "category": category,
        "requirement_version": 1,
        "supersedes_requirement_id": None,
        "description": description,
        "severity_if_failed": severity,
        "status": "DRAFT",
        "effective_from": effective_from,
    })
    db.requirements[req["id"]] = req
    return ok(serialize(req), 201)


@bp.get("/network/requirements")
def list_requirements():
    require_roles(*ROLES_READ)
    category = request.args.get("category")
    status = request.args.get("status")
    supersedes = request.args.get("supersedes_requirement_id")
    items = list(db.requirements.values())
    if category is not None:
        items = [r for r in items if r["category"] == category]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if supersedes is not None:
        items = [r for r in items if r["supersedes_requirement_id"] == supersedes]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@bp.get("/network/requirements/<req_id>")
def get_requirement(req_id):
    require_roles(*ROLES_READ)
    req = db.requirements.get(req_id)
    if not req:
        raise ApiError("ERR_NOT_FOUND", 404, "Requirement not found")
    return ok(serialize(req))


@bp.post("/network/requirements/<req_id>/publish")
def publish_requirement(req_id):
    require_roles("NetworkAdmin")
    req = db.requirements.get(req_id)
    if not req:
        raise ApiError("ERR_NOT_FOUND", 404, "Requirement not found")
    if req["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT requirement can be published")
    eff = parse_dt(req["effective_from"], "effective_from")
    if eff < now_logical():
        raise ApiError("ERR_EFFECTIVE_IN_PAST", 422,
                       "effective_from must be >= the logical clock")
    req["status"] = "PUBLISHED"
    bump(req)
    return ok(serialize(req))


@bp.post("/network/requirements/<req_id>/publish-revision")
def publish_revision(req_id):
    require_roles("NetworkAdmin")
    req = db.requirements.get(req_id)
    if not req:
        raise ApiError("ERR_NOT_FOUND", 404, "Requirement not found")
    if req["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PUBLISHED requirement can be revised")
    body = get_json()
    description = body.get("description")
    severity = body.get("severity_if_failed")
    effective_from = body.get("effective_from")
    if not isinstance(description, str) or not description:
        raise ApiError("ERR_INVALID_REQUEST", 400, "description is required")
    _validate_enum(severity, SEVERITIES, "severity_if_failed")
    eff = parse_dt(effective_from, "effective_from")
    if eff < now_logical():
        raise ApiError("ERR_EFFECTIVE_IN_PAST", 422,
                       "effective_from must be >= the logical clock")
    req["status"] = "SUPERSEDED"
    bump(req)
    new_req = new_common()
    new_req.update({
        "requirement_code": req["requirement_code"],
        "category": req["category"],
        "requirement_version": req["requirement_version"] + 1,
        "supersedes_requirement_id": req["id"],
        "description": description,
        "severity_if_failed": severity,
        "status": "PUBLISHED",
        "effective_from": effective_from,
    })
    db.requirements[new_req["id"]] = new_req
    _lapse_pinned_attestations(req, "REQUIREMENT_REVISED")
    return ok(serialize(new_req), 201)


@bp.post("/network/requirements/<req_id>/retire")
def retire_requirement(req_id):
    require_roles("NetworkAdmin")
    req = db.requirements.get(req_id)
    if not req:
        raise ApiError("ERR_NOT_FOUND", 404, "Requirement not found")
    if req["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT or PUBLISHED requirement can be retired")
    if req["status"] == "PUBLISHED":
        for audit in db.audits.values():
            if audit["status"] != "IN_PROGRESS":
                continue
            if any(a["audit_id"] == audit["id"]
                   and db.attestations.get(a["attestation_id"], {}).get(
                       "requirement_id") == req["id"]
                   for a in db.corrective_actions.values()):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "An IN_PROGRESS audit references this requirement")
    was_published = req["status"] == "PUBLISHED"
    req["status"] = "RETIRED"
    bump(req)
    if was_published:
        _lapse_pinned_attestations(req, "REQUIREMENT_RETIRED")
    return ok(serialize(req))

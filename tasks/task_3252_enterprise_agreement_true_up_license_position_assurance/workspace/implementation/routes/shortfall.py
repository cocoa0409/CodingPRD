"""Shortfall assessment endpoints."""
import flask

import db
from helpers import (err, success, parse_pagination, list_response, stamp_new)
from middleware import authenticate, require_role, check_ownership
from services import core_count_normalization

bp = flask.Blueprint("shortfall", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


def _assessment_org_id(a):
    ag = db.agreements.get(a["agreement_id"])
    return ag["organization_id"] if ag else None


def _compute_shortfall(ag):
    today = db.today()
    deps = [d for d in db.deployments.values()
            if d["agreement_id"] == ag["id"] and not d.get("retired", False)
            and db.parse_date(d["deployment_date"]) <= today]
    product_ids = []
    for d in deps:
        if d["product_id"] not in product_ids:
            product_ids.append(d["product_id"])
    for e in db.entitlements.values():
        if e["agreement_id"] == ag["id"] and e["product_id"] not in product_ids:
            product_ids.append(e["product_id"])
    lines = []
    for pid in product_ids:
        product = db.products[pid]
        pdeps = [d for d in deps if d["product_id"] == pid]
        if product["license_model"] == "PER_USER":
            required = sum(d["user_count"] for d in pdeps)
        elif product["license_model"] == "PER_DEVICE":
            required = sum(d["device_count"] for d in pdeps)
        else:
            required = sum(core_count_normalization(d) for d in pdeps)
        ents = [e for e in db.entitlements.values()
                if e["agreement_id"] == ag["id"] and e["product_id"] == pid]
        perp = sum(e["quantity"] for e in ents) if product["license_kind"] == "PERPETUAL" else 0
        subs = sum(e["quantity"] for e in ents) if product["license_kind"] == "SUBSCRIPTION" else 0
        effective = perp
        shortfall = max(0, required - effective)
        lines.append({
            "product_id": pid,
            "license_kind": product["license_kind"],
            "required_licenses": required,
            "perpetual_quantity": perp,
            "subscription_quantity": subs,
            "effective_coverage": effective,
            "shortfall": shortfall,
        })
    return lines


@bp.get("/licensing/agreements/<ag_id>/shortfall-assessment")
def shortfall_assessment(ag_id):
    user_id, role = authenticate()
    require_role(role, ("LicensingSpecialist", "Auditor"))
    ag = db.agreements.get(ag_id)
    if ag is None:
        err("ERR_NOT_FOUND", "Agreement not found.", 404)
    if ag["status"] not in ("EXPIRED", "NON_RENEWED"):
        err("ERR_INVALID_STATE", "Agreement must be EXPIRED or NON_RENEWED.", 409)
    assessment = {
        "agreement_id": ag["id"],
        "agreement_status": ag["status"],
        "assessed_at": db.now_iso(),
        "lines": _compute_shortfall(ag),
    }
    stamp_new(assessment, with_version=False)
    db.assessments[assessment["id"]] = assessment
    return success(assessment, status=200, response_type="object")


@bp.get("/licensing/shortfall-assessments/<sid>")
def get_assessment(sid):
    user_id, role = authenticate()
    require_role(role, ALL)
    a = db.assessments.get(sid)
    if a is None:
        err("ERR_NOT_FOUND", "Shortfall assessment not found.", 404)
    check_ownership(user_id, role, _assessment_org_id(a))
    return success(a, status=200, response_type="object")


@bp.get("/licensing/shortfall-assessments")
def flat_list_assessments():
    user_id, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    items = list(db.assessments.values())
    aid = flask.request.args.get("agreement_id")
    if aid is not None:
        items = [a for a in items if a["agreement_id"] == aid]
    if role == "CustomerAdmin":
        items = [a for a in items if _assessment_org_id(a) == user_id]
    return list_response(items, limit, offset)

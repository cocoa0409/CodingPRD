"""License entitlement endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     parse_pagination, list_response, stamp_new, touch)
from middleware import (authenticate, require_role, check_ownership,
                        authorize_agreement_path, scope_filter_for)
from services import adjusted_unit_price, org_of_agreement

bp = flask.Blueprint("entitlements", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


def _entitlement_org_id(e):
    ag = db.agreements.get(e["agreement_id"])
    return ag["organization_id"] if ag else None


def _locked_by_review(agreement_id):
    for r in db.trueup_reports.values():
        if r["agreement_id"] == agreement_id and r["status"] in ("SUBMITTED", "ACCEPTED"):
            return True
    return False


@bp.post("/licensing/agreements/<ag_id>/entitlements")
def create_entitlement(ag_id):
    _, role, ag = authorize_agreement_path(("LicensingSpecialist",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["product_id", "quantity"])
    product = db.products.get(body["product_id"])
    if product is None:
        err("ERR_NOT_FOUND", "Product not found.", 404)
    quantity = require_int(body, "quantity", minimum=1)
    for e in db.entitlements.values():
        if e["agreement_id"] == ag["id"] and e["product_id"] == product["id"]:
            err("ERR_DUPLICATE_ENTITLEMENT",
                "An entitlement for this (agreement_id, product_id) pair already exists.", 409)
    org = org_of_agreement(ag)
    ent = {
        "agreement_id": ag["id"],
        "product_id": product["id"],
        "quantity": quantity,
        "locked_baseline_quantity": quantity,
        "unit_price_cents": adjusted_unit_price(product, org["price_level"]),
        "acquired_at": db.today().isoformat(),
    }
    stamp_new(ent, with_version=True)
    db.entitlements[ent["id"]] = ent
    return success(ent, status=201, response_type="object")


@bp.get("/licensing/entitlements/<eid>")
def get_entitlement(eid):
    user_id, role = authenticate()
    require_role(role, ALL)
    ent = db.entitlements.get(eid)
    if ent is None:
        err("ERR_NOT_FOUND", "Entitlement not found.", 404)
    check_ownership(user_id, role, _entitlement_org_id(ent))
    return success(ent, status=200, response_type="object")


@bp.get("/licensing/agreements/<ag_id>/entitlements")
def list_agreement_entitlements(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    limit, offset = parse_pagination()
    items = [e for e in db.entitlements.values() if e["agreement_id"] == ag["id"]]
    pid = flask.request.args.get("product_id")
    if pid is not None:
        items = [e for e in items if e["product_id"] == pid]
    return list_response(items, limit, offset)


@bp.patch("/licensing/entitlements/<eid>")
def patch_entitlement(eid):
    _, role = authenticate()
    require_role(role, ("LicensingSpecialist",))
    ent = db.entitlements.get(eid)
    if ent is None:
        err("ERR_NOT_FOUND", "Entitlement not found.", 404)
    ag = db.agreements.get(ent["agreement_id"])
    if ag is None:
        err("ERR_NOT_FOUND", "Agreement not found.", 404)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    if _locked_by_review(ag["id"]):
        err("ERR_ENTITLEMENT_LOCKED_BY_REVIEW",
            "A true-up report for this agreement is under review.", 409)
    body = get_json_body()
    require_fields(body, ["quantity", "expected_entitlement_version"])
    quantity = require_int(body, "quantity", minimum=0)
    if not isinstance(body["expected_entitlement_version"], int) or isinstance(body["expected_entitlement_version"], bool):
        err("ERR_INVALID_REQUEST", "expected_entitlement_version must be an integer.", 400)
    if quantity < ent["locked_baseline_quantity"]:
        err("ERR_QUANTITY_BELOW_BASELINE",
            "quantity may not be reduced below locked_baseline_quantity.", 422)
    if body["expected_entitlement_version"] != ent["version"]:
        err("ERR_STALE_VERSION", "expected_entitlement_version does not match the current version.", 412)
    ent["quantity"] = quantity
    touch(ent)
    return success(ent, status=200, response_type="object")


@bp.get("/licensing/entitlements")
def flat_list_entitlements():
    user_id, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    items = list(db.entitlements.values())
    aid = flask.request.args.get("agreement_id")
    if aid is not None:
        items = [e for e in items if e["agreement_id"] == aid]
    pid = flask.request.args.get("product_id")
    if pid is not None:
        items = [e for e in items if e["product_id"] == pid]
    items = scope_filter_for(role, user_id, items, _entitlement_org_id)
    return list_response(items, limit, offset)

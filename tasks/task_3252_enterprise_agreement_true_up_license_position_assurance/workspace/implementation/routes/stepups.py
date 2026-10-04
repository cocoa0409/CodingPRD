"""Step-up conversion endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     parse_pagination, list_response, stamp_new, touch)
from middleware import (authenticate, require_role, check_ownership, scope_filter_for)
from services import adjusted_unit_price, org_of_agreement

bp = flask.Blueprint("stepups", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")
EDITION_ORDER = {"STANDARD": 0, "PROFESSIONAL": 1, "ENTERPRISE": 2}


def _conversion_org_id(c):
    ent = db.entitlements.get(c["entitlement_id"])
    if ent is None:
        return None
    ag = db.agreements.get(ent["agreement_id"])
    return ag["organization_id"] if ag else None


def _locked_by_review(agreement_id):
    return any(r["agreement_id"] == agreement_id and r["status"] in ("SUBMITTED", "ACCEPTED")
               for r in db.trueup_reports.values())


@bp.post("/licensing/entitlements/<eid>/step-up")
def create_step_up(eid):
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
    require_fields(body, ["target_product_id", "quantity"])
    target = db.products.get(body["target_product_id"])
    if target is None:
        err("ERR_NOT_FOUND", "Target product not found.", 404)
    source_product = db.products.get(ent["product_id"])
    quantity = require_int(body, "quantity")
    if quantity < 1:
        err("ERR_STEP_UP_INVALID", "quantity must be >= 1.", 422)
    if target["family"] != source_product["family"]:
        err("ERR_STEP_UP_INVALID", "Target product must be in the same family.", 422)
    if EDITION_ORDER[target["edition"]] <= EDITION_ORDER[source_product["edition"]]:
        err("ERR_STEP_UP_INVALID", "Target edition must be strictly above the source edition.", 422)
    if target["license_kind"] != source_product["license_kind"]:
        err("ERR_STEP_UP_INVALID", "Both products must share the same license_kind.", 422)
    conv = {
        "entitlement_id": ent["id"],
        "target_product_id": target["id"],
        "quantity": quantity,
        "charge_cents": 0,
        "status": "REQUESTED",
    }
    stamp_new(conv, with_version=True)
    db.step_ups[conv["id"]] = conv
    return success(conv, status=201, response_type="object")


@bp.get("/licensing/step-up-conversions/<cid>")
def get_step_up(cid):
    user_id, role = authenticate()
    require_role(role, ALL)
    conv = db.step_ups.get(cid)
    if conv is None:
        err("ERR_NOT_FOUND", "Step-up conversion not found.", 404)
    check_ownership(user_id, role, _conversion_org_id(conv))
    return success(conv, status=200, response_type="object")


@bp.get("/licensing/entitlements/<eid>/step-up-conversions")
def list_entitlement_step_ups(eid):
    user_id, role = authenticate()
    require_role(role, ALL)
    ent = db.entitlements.get(eid)
    if ent is None:
        err("ERR_NOT_FOUND", "Entitlement not found.", 404)
    ag = db.agreements.get(ent["agreement_id"])
    check_ownership(user_id, role, ag["organization_id"] if ag else None)
    limit, offset = parse_pagination()
    items = [c for c in db.step_ups.values() if c["entitlement_id"] == eid]
    return list_response(items, limit, offset)


@bp.post("/licensing/step-up-conversions/<cid>/execute")
def execute_step_up(cid):
    _, role = authenticate()
    require_role(role, ("LicensingSpecialist",))
    conv = db.step_ups.get(cid)
    if conv is None:
        err("ERR_NOT_FOUND", "Step-up conversion not found.", 404)
    if conv["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", "Conversion is not in REQUESTED.", 409)
    src = db.entitlements.get(conv["entitlement_id"])
    if src is None:
        err("ERR_NOT_FOUND", "Source entitlement not found.", 404)
    ag = db.agreements.get(src["agreement_id"])
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    if src["quantity"] < conv["quantity"]:
        err("ERR_INVALID_STATE", "Source entitlement quantity is below the conversion quantity.", 409)
    target = db.products.get(conv["target_product_id"])
    org = org_of_agreement(ag)
    tgt_unit = adjusted_unit_price(target, org["price_level"])
    delta = max(0, tgt_unit - src["unit_price_cents"])
    conv["charge_cents"] = conv["quantity"] * delta
    # move quantities
    src["quantity"] -= conv["quantity"]
    touch(src)
    tgt_ent = None
    for e in db.entitlements.values():
        if e["agreement_id"] == ag["id"] and e["product_id"] == target["id"]:
            tgt_ent = e
            break
    if tgt_ent is None:
        tgt_ent = {
            "agreement_id": ag["id"],
            "product_id": target["id"],
            "quantity": conv["quantity"],
            "locked_baseline_quantity": conv["quantity"],
            "unit_price_cents": tgt_unit,
            "acquired_at": db.today().isoformat(),
        }
        stamp_new(tgt_ent, with_version=True)
        db.entitlements[tgt_ent["id"]] = tgt_ent
    else:
        tgt_ent["quantity"] += conv["quantity"]
        tgt_ent["locked_baseline_quantity"] = tgt_ent["quantity"]
        touch(tgt_ent)
    conv["status"] = "COMPLETED"
    touch(conv)
    return success(conv, status=200, response_type="object")


@bp.post("/licensing/step-up-conversions/<cid>/reject")
def reject_step_up(cid):
    _, role = authenticate()
    require_role(role, ("LicensingSpecialist",))
    conv = db.step_ups.get(cid)
    if conv is None:
        err("ERR_NOT_FOUND", "Step-up conversion not found.", 404)
    if conv["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", "Conversion is not in REQUESTED.", 409)
    conv["status"] = "REJECTED"
    touch(conv)
    return success(conv, status=200, response_type="object")


@bp.get("/licensing/step-up-conversions")
def flat_list_step_ups():
    user_id, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    items = list(db.step_ups.values())
    eid = flask.request.args.get("entitlement_id")
    if eid is not None:
        items = [c for c in items if c["entitlement_id"] == eid]
    tpid = flask.request.args.get("target_product_id")
    if tpid is not None:
        items = [c for c in items if c["target_product_id"] == tpid]
    items = scope_filter_for(role, user_id, items, _conversion_org_id)
    return list_response(items, limit, offset)

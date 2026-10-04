"""Assurance benefit grant and redemption endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     require_enum, parse_pagination, list_response, stamp_new, touch)
from middleware import (authenticate, require_role, check_ownership,
                        authorize_agreement_path, scope_filter_for)

bp = flask.Blueprint("benefits", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


def _grant_org_id(g):
    ag = db.agreements.get(g["agreement_id"])
    return ag["organization_id"] if ag else None


def _redemption_org_id(r):
    g = db.benefit_grants.get(r["grant_id"])
    return _grant_org_id(g) if g else None


@bp.post("/licensing/agreements/<ag_id>/benefit-grants")
def create_grant(ag_id):
    _, role, ag = authorize_agreement_path(("LicensingSpecialist",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["benefit_type", "quantity_granted", "expires_on"])
    benefit_type = require_enum(body, "benefit_type",
                                ("TRAINING_VOUCHER", "SUPPORT_INCIDENT", "UPGRADE_RIGHT"))
    qty = require_int(body, "quantity_granted", minimum=1)
    try:
        expires = db.parse_date(body["expires_on"])
    except Exception:
        err("ERR_INVALID_REQUEST", "expires_on must be an ISO date.", 400)
    grant = {
        "agreement_id": ag["id"],
        "benefit_type": benefit_type,
        "quantity_granted": qty,
        "quantity_remaining": qty,
        "expires_on": expires.isoformat(),
        "status": "ACTIVE",
    }
    stamp_new(grant, with_version=True)
    db.benefit_grants[grant["id"]] = grant
    return success(grant, status=201, response_type="object")


@bp.get("/licensing/benefit-grants/<gid>")
def get_grant(gid):
    user_id, role = authenticate()
    require_role(role, ALL)
    grant = db.benefit_grants.get(gid)
    if grant is None:
        err("ERR_NOT_FOUND", "Benefit grant not found.", 404)
    check_ownership(user_id, role, _grant_org_id(grant))
    return success(grant, status=200, response_type="object")


@bp.get("/licensing/agreements/<ag_id>/benefit-grants")
def list_agreement_grants(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    limit, offset = parse_pagination()
    items = [g for g in db.benefit_grants.values() if g["agreement_id"] == ag["id"]]
    bt = flask.request.args.get("benefit_type")
    if bt is not None:
        items = [g for g in items if g["benefit_type"] == bt]
    status = flask.request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return list_response(items, limit, offset)


@bp.post("/licensing/benefit-grants/<gid>/redemptions")
def redeem(gid):
    user_id, role = authenticate()
    require_role(role, ("CustomerAdmin",))
    grant = db.benefit_grants.get(gid)
    if grant is None:
        err("ERR_NOT_FOUND", "Benefit grant not found.", 404)
    check_ownership(user_id, role, _grant_org_id(grant))
    if grant["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Grant is not ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["quantity"])
    quantity = require_int(body, "quantity")
    if db.parse_date(grant["expires_on"]) < db.today():
        err("ERR_BENEFIT_EXPIRED", "The grant has expired.", 422)
    if quantity < 1 or quantity > grant["quantity_remaining"]:
        err("ERR_REDEMPTION_EXCEEDS_REMAINING",
            "quantity must be >= 1 and <= grant.quantity_remaining.", 422)
    redemption = {
        "grant_id": grant["id"],
        "quantity": quantity,
        "redeemed_on": db.today().isoformat(),
    }
    stamp_new(redemption, with_version=False)
    db.redemptions[redemption["id"]] = redemption
    grant["quantity_remaining"] -= quantity
    if grant["quantity_remaining"] == 0:
        grant["status"] = "DEPLETED"
    touch(grant)
    return success(redemption, status=201, response_type="object")


@bp.get("/licensing/benefit-grants/<gid>/redemptions")
def list_redemptions(gid):
    user_id, role = authenticate()
    require_role(role, ALL)
    grant = db.benefit_grants.get(gid)
    if grant is None:
        err("ERR_NOT_FOUND", "Benefit grant not found.", 404)
    check_ownership(user_id, role, _grant_org_id(grant))
    limit, offset = parse_pagination()
    items = [r for r in db.redemptions.values() if r["grant_id"] == gid]
    return list_response(items, limit, offset)

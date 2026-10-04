"""Hosting authorization endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields,
                     parse_pagination, list_response, stamp_new, touch)
from middleware import (authenticate, require_role, check_ownership,
                        authorize_agreement_path, scope_filter_for)

bp = flask.Blueprint("hosting", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


def _auth_org_id(h):
    ag = db.agreements.get(h["agreement_id"])
    return ag["organization_id"] if ag else None


def _get_auth(hid):
    h = db.hosting_auths.get(hid)
    if h is None:
        err("ERR_NOT_FOUND", "Hosting authorization not found.", 404)
    return h


@bp.post("/licensing/agreements/<ag_id>/hosting-authorizations")
def create_authorization(ag_id):
    _, role, ag = authorize_agreement_path(("CustomerAdmin",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["product_id", "provider_name", "effective_on"])
    product = db.products.get(body["product_id"])
    if product is None:
        err("ERR_NOT_FOUND", "Product not found.", 404)
    if not isinstance(body["provider_name"], str):
        err("ERR_INVALID_REQUEST", "provider_name must be a string.", 400)
    try:
        effective_on = db.parse_date(body["effective_on"])
    except Exception:
        err("ERR_INVALID_REQUEST", "effective_on must be an ISO date.", 400)
    if effective_on < db.today():
        err("ERR_INVALID_DATE_RANGE", "effective_on must not be before the current date.", 422)
    if not product["license_mobility"]:
        err("ERR_LICENSE_MOBILITY_REQUIRED",
            "The product does not carry License Mobility rights.", 422)
    auth = {
        "agreement_id": ag["id"],
        "product_id": product["id"],
        "provider_name": body["provider_name"],
        "status": "PENDING_REVIEW",
        "effective_on": effective_on.isoformat(),
    }
    stamp_new(auth, with_version=True)
    db.hosting_auths[auth["id"]] = auth
    return success(auth, status=201, response_type="object")


@bp.get("/licensing/hosting-authorizations/<hid>")
def get_authorization(hid):
    user_id, role = authenticate()
    require_role(role, ALL)
    auth = _get_auth(hid)
    check_ownership(user_id, role, _auth_org_id(auth))
    return success(auth, status=200, response_type="object")


@bp.get("/licensing/agreements/<ag_id>/hosting-authorizations")
def list_agreement_authorizations(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    limit, offset = parse_pagination()
    items = [h for h in db.hosting_auths.values() if h["agreement_id"] == ag["id"]]
    status = flask.request.args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    return list_response(items, limit, offset)


@bp.post("/licensing/hosting-authorizations/<hid>/review")
def review(hid):
    _, role = authenticate()
    require_role(role, ("LicensingSpecialist",))
    auth = _get_auth(hid)
    if auth["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE", "Authorization is not PENDING_REVIEW.", 409)
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("APPROVE", "DENY"):
        err("ERR_INVALID_REQUEST", "decision must be APPROVE or DENY.", 400)
    if decision == "APPROVE":
        product = db.products.get(auth["product_id"])
        if product is None or not product["license_mobility"]:
            err("ERR_LICENSE_MOBILITY_REQUIRED",
                "The product does not carry License Mobility rights.", 422)
        auth["status"] = "APPROVED"
    else:
        auth["status"] = "DENIED"
    touch(auth)
    return success(auth, status=200, response_type="object")


@bp.post("/licensing/hosting-authorizations/<hid>/suspend")
def suspend(hid):
    _, role = authenticate()
    require_role(role, ("LicensingSpecialist",))
    auth = _get_auth(hid)
    if auth["status"] != "APPROVED":
        err("ERR_INVALID_STATE", "Authorization is not APPROVED.", 409)
    auth["status"] = "SUSPENDED"
    touch(auth)
    return success(auth, status=200, response_type="object")


@bp.post("/licensing/hosting-authorizations/<hid>/reinstate")
def reinstate(hid):
    _, role = authenticate()
    require_role(role, ("LicensingSpecialist",))
    auth = _get_auth(hid)
    if auth["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", "Authorization is not SUSPENDED.", 409)
    auth["status"] = "APPROVED"
    touch(auth)
    return success(auth, status=200, response_type="object")


@bp.post("/licensing/hosting-authorizations/<hid>/revoke")
def revoke(hid):
    _, role = authenticate()
    require_role(role, ("LicensingSpecialist",))
    auth = _get_auth(hid)
    if auth["status"] not in ("APPROVED", "SUSPENDED"):
        err("ERR_INVALID_STATE", "Authorization is not APPROVED or SUSPENDED.", 409)
    auth["status"] = "REVOKED"
    touch(auth)
    return success(auth, status=200, response_type="object")


@bp.get("/licensing/hosting-authorizations")
def flat_list_authorizations():
    user_id, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    args = flask.request.args
    items = list(db.hosting_auths.values())
    aid = args.get("agreement_id")
    if aid is not None:
        items = [h for h in items if h["agreement_id"] == aid]
    pid = args.get("product_id")
    if pid is not None:
        items = [h for h in items if h["product_id"] == pid]
    status = args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    items = scope_filter_for(role, user_id, items, _auth_org_id)
    return list_response(items, limit, offset)

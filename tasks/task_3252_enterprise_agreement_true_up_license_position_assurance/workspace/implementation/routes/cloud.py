"""Cloud commitment and consumption event endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     parse_pagination, list_response, stamp_new, touch)
from middleware import (authenticate, require_role, check_ownership,
                        authorize_agreement_path, scope_filter_for)

bp = flask.Blueprint("cloud", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


def _commitment_org_id(c):
    ag = db.agreements.get(c["agreement_id"])
    return ag["organization_id"] if ag else None


def _event_org_id(e):
    c = db.commitments.get(e["commitment_id"])
    return _commitment_org_id(c) if c else None


@bp.post("/licensing/agreements/<ag_id>/cloud-commitments")
def create_commitment(ag_id):
    _, role, ag = authorize_agreement_path(("LicensingSpecialist",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["committed_amount_cents", "expires_on"])
    amount = require_int(body, "committed_amount_cents")
    if amount < 1:
        err("ERR_INVALID_REQUEST", "committed_amount_cents must be >= 1.", 400)
    try:
        expires = db.parse_date(body["expires_on"])
    except Exception:
        err("ERR_INVALID_REQUEST", "expires_on must be an ISO date.", 400)
    commitment = {
        "agreement_id": ag["id"],
        "committed_amount_cents": amount,
        "consumed_amount_cents": 0,
        "expires_on": expires.isoformat(),
        "status": "ACTIVE",
    }
    stamp_new(commitment, with_version=True)
    db.commitments[commitment["id"]] = commitment
    return success(commitment, status=201, response_type="object")


@bp.get("/licensing/cloud-commitments/<cid>")
def get_commitment(cid):
    user_id, role = authenticate()
    require_role(role, ALL)
    c = db.commitments.get(cid)
    if c is None:
        err("ERR_NOT_FOUND", "Cloud commitment not found.", 404)
    check_ownership(user_id, role, _commitment_org_id(c))
    return success(c, status=200, response_type="object")


@bp.get("/licensing/agreements/<ag_id>/cloud-commitments")
def list_agreement_commitments(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    limit, offset = parse_pagination()
    items = [c for c in db.commitments.values() if c["agreement_id"] == ag["id"]]
    status = flask.request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, limit, offset)


@bp.post("/licensing/cloud-commitments/<cid>/consumption-events")
def consume(cid):
    user_id, role = authenticate()
    require_role(role, ("CustomerAdmin",))
    c = db.commitments.get(cid)
    if c is None:
        err("ERR_NOT_FOUND", "Cloud commitment not found.", 404)
    check_ownership(user_id, role, _commitment_org_id(c))
    body = get_json_body()
    require_fields(body, ["requested_cents"])
    requested = require_int(body, "requested_cents")
    if requested < 1:
        err("ERR_INVALID_REQUEST", "requested_cents must be >= 1.", 400)
    if c["status"] == "ACTIVE" and db.parse_date(c["expires_on"]) < db.today():
        c["status"] = "EXPIRED"
        touch(c)
        err("ERR_COMMITMENT_EXPIRED", "The commitment has expired.", 422)
    if c["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Commitment is not ACTIVE.", 409)
    available = c["committed_amount_cents"] - c["consumed_amount_cents"]
    consumed = min(requested, available)
    event = {
        "commitment_id": c["id"],
        "requested_cents": requested,
        "consumed_cents": consumed,
        "occurred_on": db.today().isoformat(),
    }
    stamp_new(event, with_version=False)
    db.consumption_events[event["id"]] = event
    c["consumed_amount_cents"] += consumed
    if c["consumed_amount_cents"] == c["committed_amount_cents"]:
        c["status"] = "EXHAUSTED"
    touch(c)
    return success(event, status=201, response_type="object")


@bp.get("/licensing/cloud-commitments/<cid>/consumption-events")
def list_consumption_events(cid):
    user_id, role = authenticate()
    require_role(role, ALL)
    c = db.commitments.get(cid)
    if c is None:
        err("ERR_NOT_FOUND", "Cloud commitment not found.", 404)
    check_ownership(user_id, role, _commitment_org_id(c))
    limit, offset = parse_pagination()
    items = [e for e in db.consumption_events.values() if e["commitment_id"] == cid]
    return list_response(items, limit, offset)

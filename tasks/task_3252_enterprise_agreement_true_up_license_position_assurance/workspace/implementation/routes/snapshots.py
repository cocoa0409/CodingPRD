"""License position snapshot endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields,
                     parse_pagination, list_response, stamp_new)
from middleware import (authenticate, require_role, check_ownership,
                        authorize_agreement_path, scope_filter_for)
from services import compute_position_lines, sweep_expired_grants

bp = flask.Blueprint("snapshots", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


def _snapshot_org_id(s):
    ag = db.agreements.get(s["agreement_id"])
    return ag["organization_id"] if ag else None


def _new_snapshot(agreement_id, anniversary_id):
    snap = {
        "agreement_id": agreement_id,
        "anniversary_id": anniversary_id,
        "computed_at": db.now_iso(),
        "lines": compute_position_lines(agreement_id),
    }
    stamp_new(snap, with_version=False)
    db.snapshots[snap["id"]] = snap
    return snap


@bp.post("/licensing/agreements/<ag_id>/position-snapshots")
def create_snapshot(ag_id):
    _, role, ag = authorize_agreement_path(("LicensingSpecialist", "CustomerAdmin"), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["anniversary_id"])
    ann = db.anniversaries.get(body["anniversary_id"])
    if ann is None:
        err("ERR_NOT_FOUND", "Anniversary not found.", 404)
    if ann["agreement_id"] != ag["id"]:
        err("ERR_NOT_FOUND", "Anniversary does not belong to this agreement.", 404)
    if ann["true_up_closed"]:
        err("ERR_ANNIVERSARY_CLOSED", "The anniversary's true-up is closed.", 409)
    snap = _new_snapshot(ag["id"], ann["id"])
    sweep_expired_grants(ag["id"])
    return success(snap, status=201, response_type="object")


@bp.get("/licensing/position-snapshots/<sid>")
def get_snapshot(sid):
    user_id, role = authenticate()
    require_role(role, ALL)
    snap = db.snapshots.get(sid)
    if snap is None:
        err("ERR_NOT_FOUND", "Snapshot not found.", 404)
    check_ownership(user_id, role, _snapshot_org_id(snap))
    return success(snap, status=200, response_type="object")


@bp.get("/licensing/agreements/<ag_id>/position-snapshots")
def list_agreement_snapshots(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    limit, offset = parse_pagination()
    items = [s for s in db.snapshots.values() if s["agreement_id"] == ag["id"]]
    ann = flask.request.args.get("anniversary_id")
    if ann is not None:
        items = [s for s in items if s["anniversary_id"] == ann]
    return list_response(items, limit, offset)


@bp.get("/licensing/position-snapshots")
def flat_list_snapshots():
    user_id, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    items = list(db.snapshots.values())
    aid = flask.request.args.get("agreement_id")
    if aid is not None:
        items = [s for s in items if s["agreement_id"] == aid]
    ann = flask.request.args.get("anniversary_id")
    if ann is not None:
        items = [s for s in items if s["anniversary_id"] == ann]
    items = scope_filter_for(role, user_id, items, _snapshot_org_id)
    return list_response(items, limit, offset)

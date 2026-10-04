"""Requester accounts: create, read-own, vet, suspend (PRD §3.7)."""
from flask import Blueprint

import db
from auth import ROLE_CLEARINGHOUSE_OPS, ROLE_REQUESTER, authenticate, require_role
from core import (
    ERR_INVALID_STATE,
    ERR_REQUESTER_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_VALIDATION,
    get_body,
    ok_object,
    raise_err,
    req_enum,
    req_str,
)

bp = Blueprint("requesters", __name__)

KINDS = ("EMPLOYER", "BACKGROUND_SCREENER")


def _get_requester(rid):
    r = db.store.requesters.get(rid)
    if r is None:
        raise_err(ERR_REQUESTER_NOT_FOUND, "requester not found")
    return r


@bp.route("/requesters", methods=["POST"])
def create_requester():
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    data = get_body()
    org_name = req_str(data, "org_name")
    kind = req_enum(data, "requester_kind", KINDS)
    initial = data.get("initial_credit_cents", 0)
    if isinstance(initial, bool) or not isinstance(initial, int) or initial < 0:
        raise_err(ERR_VALIDATION, "initial_credit_cents must be a non-negative integer")
    r = db.new_entity(
        {
            "org_name": org_name,
            "requester_kind": kind,
            "status": "PENDING_VETTING",
            "credit_balance_cents": initial,
            "initial_credit_cents": initial,
            "vetted_at": None,
        }
    )
    db.store.requesters[r["id"]] = r
    return ok_object(db.serialize(r), 201)


@bp.route("/requesters/<rid>", methods=["GET"])
def get_requester(rid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS, ROLE_REQUESTER)
    # A requester reads its own account only (PRD §2.1).
    if caller.role == ROLE_REQUESTER and caller.user_id != rid:
        raise_err(ERR_UNAUTHORIZED, "a requester reads its own account only")
    return ok_object(db.serialize(_get_requester(rid)))


@bp.route("/requesters/<rid>/vet", methods=["POST"])
def vet_requester(rid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    data = get_body()
    outcome = req_enum(data, "outcome", ("VET", "DENY"))
    r = _get_requester(rid)
    if outcome == "VET":
        if r["status"] not in ("PENDING_VETTING", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE, "VET requires PENDING_VETTING or SUSPENDED")
        r["status"] = "VETTED"
        r["vetted_at"] = db.now()
    else:  # DENY
        if r["status"] != "PENDING_VETTING":
            raise_err(ERR_INVALID_STATE, "DENY requires PENDING_VETTING")
        r["status"] = "DENIED"
    db.touch(r)
    return ok_object(db.serialize(r))


@bp.route("/requesters/<rid>/suspend", methods=["POST"])
def suspend_requester(rid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    r = _get_requester(rid)
    if r["status"] != "VETTED":
        raise_err(ERR_INVALID_STATE, "only a VETTED requester can be suspended")
    r["status"] = "SUSPENDED"
    db.touch(r)
    return ok_object(db.serialize(r))

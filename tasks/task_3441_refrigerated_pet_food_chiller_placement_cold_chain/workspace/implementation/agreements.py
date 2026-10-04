"""PlacementAgreement lifecycle actions: revise (OCC), sign, terminate (PRD 3.2)."""
from flask import Blueprint

import cascade
from envelope import ok
from errors import ApiError
from serializers import ser_agreement
from state import DB, now, touch
from validate import auth, body, fields, require_role

bp = Blueprint("agreements", __name__)


def _get_agreement(aid):
    a = DB["agreements"].get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PlacementAgreement %s not found" % aid)
    return a


@bp.post("/cold-chain/placement-agreements/<aid>/revise")
def revise_agreement(aid):
    uid, role = auth()
    v = fields(body(), [
        ("expected_agreement_version", "int", True, {}),
        ("allocated_sqft", "int", False, {"gt0": True}),
        ("max_capex_cents", "int", False, {"gt0": True}),
        ("term_months", "int", False, {"min": 1, "max": 120}),
    ])
    require_role(role, ["PlacementManager"])
    a = _get_agreement(aid)
    # tier 4 state precondition first, then OCC (same tier, after state per 2.7)
    if a["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROPOSED agreement can be revised")
    if v["expected_agreement_version"] != a["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_agreement_version does not match current version")
    for k in ("allocated_sqft", "max_capex_cents", "term_months"):
        if k in v:
            a[k] = v[k]
    touch(a)
    return ok(ser_agreement(a), "object", 200)


@bp.post("/cold-chain/placement-agreements/<aid>/sign")
def sign_agreement(aid):
    uid, role = auth()
    fields(body(), [])
    require_role(role, ["PlacementManager"])
    a = _get_agreement(aid)
    if a["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROPOSED agreement can be signed")
    a["status"] = "SIGNED"
    a["signed_at"] = now()
    touch(a)
    return ok(ser_agreement(a), "object", 200)


@bp.post("/cold-chain/placement-agreements/<aid>/terminate")
def terminate_agreement(aid):
    uid, role = auth()
    fields(body(), [])
    require_role(role, ["PlacementManager"])
    a = _get_agreement(aid)
    if a["status"] not in ("PROPOSED", "SIGNED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Agreement is already TERMINATED")
    cascade.terminate_agreement(a)
    return ok(ser_agreement(a), "object", 200)

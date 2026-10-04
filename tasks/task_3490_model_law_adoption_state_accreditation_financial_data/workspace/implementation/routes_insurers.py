"""Insurer registry (PRD 3.4)."""

from flask import Blueprint

from auth import authenticate, require_role, ALL_ROLES, ROLE_ASSOCIATION_STAFF
from db import store, base_record
from errors import ApiError
from serialize import serialize_insurer
from util import get_body, req_str, ok_object

bp = Blueprint("insurers", __name__)


def get_insurer_or_404(insurer_id):
    ins = store.insurers.get(insurer_id)
    if ins is None:
        raise ApiError("ERR_INSURER_NOT_FOUND", "Insurer not found: %s" % insurer_id, 404)
    return ins


@bp.post("/naic/insurers")
def create_insurer():
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    body = get_body()
    # Stage 4 body reference: domicile_state_code must name a registered state.
    if body.get("domicile_state_code") is not None:
        code = body["domicile_state_code"]
        found = False
        if isinstance(code, str):
            found = any(s["code"] == code for s in store.states.values())
        if not found:
            raise ApiError(
                "ERR_STATE_NOT_FOUND",
                "domicile_state_code does not match a registered state",
                404,
            )
    naic_code = req_str(body, "naic_code")
    name = req_str(body, "name")
    domicile_state_code = req_str(body, "domicile_state_code")
    for ins in store.insurers.values():
        if ins["naic_code"] == naic_code:
            raise ApiError(
                "ERR_DUPLICATE_NAIC_CODE",
                "Insurer naic_code already exists: %s" % naic_code,
                409,
            )
    rec = base_record()
    rec.update({
        "naic_code": naic_code,
        "name": name,
        "domicile_state_code": domicile_state_code,
        "status": "ACTIVE",
        "latest_rbc_ratio": None,
        "latest_action_level": None,
    })
    store.insurers[rec["id"]] = rec
    return ok_object(serialize_insurer(rec), 201)


@bp.get("/naic/insurers/<insurer_id>")
def read_insurer(insurer_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    return ok_object(serialize_insurer(get_insurer_or_404(insurer_id)), 200)

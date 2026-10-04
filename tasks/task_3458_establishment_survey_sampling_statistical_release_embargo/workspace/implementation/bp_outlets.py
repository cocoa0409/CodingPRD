"""/survey/media-outlets: create, list, accreditation (PRD 3.9)."""
from flask import Blueprint, request

from authz import get_auth, require_role
from envelope import ok, ok_list, paginate
from errors import raise_err, ERR_VALIDATION, ERR_OUTLET_NOT_FOUND, ERR_INVALID_STATE
from releases_util import revoke_grants
from store import DB, new_entity, sorted_entities, touch
from validate import get_body, req_str

bp = Blueprint("outlets", __name__)

ACTIONS = {"ACCREDIT", "SUSPEND", "REINSTATE", "REVOKE"}


@bp.post("/media-outlets")
def create_outlet():
    _user, role = get_auth()
    require_role(role, {"ReleaseManager"})
    data = get_body()
    name = req_str(data, "name")
    outlet_code = req_str(data, "outlet_code")

    if any(o["outlet_code"] == outlet_code for o in DB["outlets"].values()):
        raise_err(ERR_VALIDATION, f"outlet_code '{outlet_code}' already exists")

    outlet = new_entity("outlets", {
        "name": name,
        "outlet_code": outlet_code,
        "accreditation_status": "PENDING",
    })
    return ok(outlet, status=201)


@bp.get("/media-outlets")
def list_outlets():
    get_auth()
    items = sorted_entities("outlets")
    value = request.args.get("accreditation_status")
    if value is not None:
        items = [o for o in items if o["accreditation_status"] == value]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


def _revoke_outlet_grants(outlet):
    """SUSPEND/REVOKE cascade: every grant of this outlet in ISSUED/ACCESSED
    moves to REVOKED; each affected release's counter is recomputed.
    Reinstatement never restores revoked grants."""
    revoke_grants(
        [g for g in DB["grants"].values() if g["media_outlet_id"] == outlet["id"]])


@bp.post("/media-outlets/<oid>/accreditation")
def accreditation(oid):
    _user, role = get_auth()
    require_role(role, {"ReleaseManager"})
    outlet = DB["outlets"].get(oid)
    if outlet is None:
        raise_err(ERR_OUTLET_NOT_FOUND, "media outlet not found")
    data = get_body()
    action = req_str(data, "action")
    if action not in ACTIONS:
        raise_err(ERR_VALIDATION, f"unknown accreditation action '{action}'")

    status = outlet["accreditation_status"]
    if action == "ACCREDIT":
        if status != "PENDING":
            raise_err(ERR_INVALID_STATE, f"cannot accredit an outlet in {status}")
        outlet["accreditation_status"] = "ACCREDITED"
    elif action == "SUSPEND":
        if status != "ACCREDITED":
            raise_err(ERR_INVALID_STATE, f"cannot suspend an outlet in {status}")
        outlet["accreditation_status"] = "SUSPENDED"
        _revoke_outlet_grants(outlet)
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise_err(ERR_INVALID_STATE, f"cannot reinstate an outlet in {status}")
        outlet["accreditation_status"] = "ACCREDITED"
    elif action == "REVOKE":
        if status not in ("ACCREDITED", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE, f"cannot revoke an outlet in {status}")
        outlet["accreditation_status"] = "REVOKED"
        _revoke_outlet_grants(outlet)
    touch(outlet)
    return ok(outlet)

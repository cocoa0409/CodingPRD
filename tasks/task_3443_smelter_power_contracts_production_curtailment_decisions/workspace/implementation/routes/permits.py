"""Environmental permits: register and suspend (PRD 3.8)."""
from flask import Blueprint

from auth import require_roles
from constants import PERMIT_TYPES
from db import STORE, bump, new_id, stamp_new
from envelope import ok_object
from errors import raise_err
from serializers import permit_json
from services.core import expire_permits, lazy_expire_permit
from util import as_datetime, as_enum, as_str, get_body, req

bp = Blueprint("permits", __name__, url_prefix="/smelter-ops")


@bp.post("/environmental-permits")
@require_roles("EHSManager")
def create_permit():
    body = get_body()
    smelter_id = as_str(req(body, "smelter_id"), "smelter_id")
    if STORE["smelters"].get(smelter_id) is None:
        raise_err("ERR_NOT_FOUND", "Smelter not found.")
    permit_type = as_enum(req(body, "permit_type"), "permit_type", PERMIT_TYPES)
    valid_from = as_datetime(req(body, "valid_from"), "valid_from")
    valid_to = as_datetime(req(body, "valid_to"), "valid_to")
    if not valid_from < valid_to:
        raise_err(
            "ERR_INVALID_REQUEST", "valid_from must be strictly before valid_to."
        )
    expire_permits(smelter_id)
    for p in STORE["environmental_permits"].values():
        if (
            p["smelter_id"] == smelter_id
            and p["permit_type"] == permit_type
            and p["status"] == "ACTIVE"
        ):
            raise_err(
                "ERR_PERMIT_DUPLICATE_TYPE",
                "An ACTIVE permit of this type already exists for the smelter.",
            )
    rec = stamp_new(
        {
            "id": new_id(),
            "smelter_id": smelter_id,
            "permit_type": permit_type,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "status": "ACTIVE",
        }
    )
    STORE["environmental_permits"][rec["id"]] = rec
    return ok_object(permit_json(rec), 201)


@bp.post("/environmental-permits/<permit_id>/suspend")
@require_roles("EHSManager")
def suspend_permit(permit_id):
    p = STORE["environmental_permits"].get(permit_id)
    if p is None:
        raise_err("ERR_NOT_FOUND", "EnvironmentalPermit not found.")
    lazy_expire_permit(p)
    if p["status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_LIFECYCLE_STATE",
            "Only an ACTIVE permit can be suspended.",
        )
    p["status"] = "SUSPENDED"
    bump(p)
    return ok_object(permit_json(p))

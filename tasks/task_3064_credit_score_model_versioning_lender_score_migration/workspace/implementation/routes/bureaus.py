"""Bureau registry endpoints."""

from flask import Blueprint, request

from core import (
    DB, new_record, store, ok, ok_list, resolve_actor, bureau,
    body_of, reject_unknown, require_fields, as_str, as_enum, as_bool,
    read_pagination, paginate, ordered_rows,
)
from errors import ApiError

bp = Blueprint("bureaus", __name__)

ALL_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ReasonCodeAdministrator", "ScoreConsumer",
]

BUREAU_CODES = {"TUC", "EXP", "EQF"}


@bp.post("/bureaus")
def create_bureau():
    resolve_actor(request, ["BureauAdministrator"])
    body = body_of(request)
    reject_unknown(body, {"bureau_code", "display_name", "is_active"})
    require_fields(body, ["bureau_code", "display_name"])

    bureau_code = as_enum(body["bureau_code"], BUREAU_CODES, "bureau_code")
    display_name = as_str(body["display_name"], "display_name")
    is_active = as_bool(body["is_active"]) if "is_active" in body else True

    for existing in DB["bureaus"].values():
        if existing["bureau_code"] == bureau_code:
            raise ApiError("ERR_DUPLICATE_BUREAU_CODE")

    rec = new_record()
    rec.update({
        "bureau_code": bureau_code,
        "display_name": display_name,
        "is_active": is_active,
    })
    store("bureaus", rec)
    return ok(rec, 201)


@bp.get("/bureaus/<bureau_id>")
def get_bureau(bureau_id):
    resolve_actor(request, ALL_ROLES)
    rec = bureau(bureau_id)
    return ok(rec)


@bp.get("/bureaus")
def list_bureaus():
    resolve_actor(request, ALL_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("bureaus")

    code = request.args.get("bureau_code")
    if code is not None:
        rows = [r for r in rows if r["bureau_code"] == code]
    active = request.args.get("is_active")
    if active is not None:
        wanted = as_bool(active)
        rows = [r for r in rows if r["is_active"] is wanted]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)
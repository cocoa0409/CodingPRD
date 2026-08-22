"""Payers (PRD 3.1)."""
from flask import Blueprint, request

import auth
import db
import derive
import response
import validation as v
from errors import ApiError

bp = Blueprint("payers", __name__)


@bp.post("/payers")
@auth.require(auth.SYSTEM_ADMIN)
def create_payer():
    data = v.body()
    # rank 6 - body shape
    name = v.req_str(data, "name")
    payer_code = v.req_str(data, "payer_code", min_len=2, max_len=16)
    payer_type = v.req_enum(data, "payer_type", v.PAYER_TYPES)
    take_back_allowed = v.opt_bool(data, "take_back_allowed", True)
    refund_remit_days = v.opt_int(data, "refund_remit_days", 30, minimum=0)
    # rank 29 - payer_code uniqueness
    for existing in db.payers.values():
        if existing["payer_code"] == payer_code:
            raise ApiError("ERR_DUPLICATE_PAYER_CODE")

    row = db.base_row()
    row.update({
        "name": name,
        "payer_code": payer_code,
        "payer_type": payer_type,
        "take_back_allowed": take_back_allowed,
        "refund_remit_days": refund_remit_days,
    })
    db.payers[row["id"]] = row
    return response.ok(derive.payer(row), 201)


@bp.get("/payers")
@auth.require(*auth.ALL_ROLES)
def list_payers():
    rows = db.ordered(list(db.payers.values()))
    payer_type = request.args.get("payer_type")
    if payer_type:
        rows = [r for r in rows if r["payer_type"] == payer_type]
    return response.page(rows, derive.payer)


@bp.get("/payers/<payer_id>")
@auth.require(*auth.ALL_ROLES)
def read_payer(payer_id):
    return response.ok(derive.payer(v.must_exist("payer", payer_id)))

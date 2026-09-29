"""Landowner onboarding and payable administration (PRD section 3.1)."""

from flask import Blueprint

import access
import serializers as ser
import validation as v
from auth import (
    LANDOWNER,
    LAND_AGENT,
    OPERATOR_ROLES,
    PAYMENT_ADMINISTRATOR,
    require,
)
from envelope import ok, ok_list
from store import db, insert, ordered, touch

bp = Blueprint("landowners", __name__, url_prefix="/land-origination")

ENTITY_TYPES = ("INDIVIDUAL", "TRUST", "LLC", "PARTNERSHIP")
POSTURES = ("PROSPECT", "ENGAGED", "UNDER_OPTION", "UNDER_LEASE")


@bp.get("/landowners/<landowner_id>")
@require(*(OPERATOR_ROLES + (LANDOWNER,)))
def get_landowner(landowner_id):
    row = access.landowner(landowner_id)
    access.own(row["id"])
    return ok(ser.landowner(row))


@bp.get("/landowners")
@require(*OPERATOR_ROLES)
def list_landowners():
    limit, offset = v.pagination()
    rows = ordered(db.landowners.values())
    rows = v.apply_filters(rows, [
        ("status", v.query_str("status")),
        ("payment_hold", v.query_bool("payment_hold")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.landowner, page), limit, offset, total)


@bp.post("/landowners")
@require(LAND_AGENT)
def create_landowner():
    body = v.json_body()
    legal_name = v.req_str(body, "legal_name", min_len=1, max_len=200)
    entity_type = v.req_enum(body, "entity_type", ENTITY_TYPES)
    mailing_state = v.req_str(body, "mailing_state", min_len=2, max_len=2,
                              pattern=r"^[A-Z]{2}$")
    contact_email = v.req_email(body, "contact_email")
    w9_on_file = v.opt_bool(body, "w9_on_file", False)
    payment_hold = v.opt_bool(body, "payment_hold", False)

    row = insert("landowners", {
        "legal_name": legal_name,
        "entity_type": entity_type,
        "mailing_state": mailing_state,
        "contact_email": contact_email,
        "w9_on_file": w9_on_file,
        "payment_hold": payment_hold,
        "status": "PROSPECT",
        "total_paid_cents": 0,
    })
    return ok(ser.landowner(row), 201)


@bp.patch("/landowners/<landowner_id>")
@require(PAYMENT_ADMINISTRATOR)
def patch_landowner(landowner_id):
    row = access.landowner(landowner_id)
    body = v.json_body()
    contact_email = v.opt_email(body, "contact_email")
    w9_on_file = v.opt_bool(body, "w9_on_file", None)
    payment_hold = v.opt_bool(body, "payment_hold", None)

    if contact_email is not None:
        row["contact_email"] = contact_email
    if w9_on_file is not None:
        row["w9_on_file"] = w9_on_file
    if payment_hold is not None:
        row["payment_hold"] = payment_hold
    touch(row)
    return ok(ser.landowner(row))

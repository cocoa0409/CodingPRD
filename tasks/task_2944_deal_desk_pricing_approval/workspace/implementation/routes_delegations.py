"""Delegation grants (PRD 2.10)."""
from decimal import Decimal

from flask import Blueprint, request as flask_request

import auth
import clock
import common
import db
import response
import validation
from auth import require_roles
from errors import fail
from validation import validate, json_body

bp = Blueprint("delegations", __name__)

ALL = auth.ALL_ROLES

GRANT_SPEC = {
    "grantee_user_id": {"type": "string", "required": True},
    "tier_level": {"type": "integer", "required": True, "ge": 1, "le": 4},
    "max_discount_pct": {"type": "number", "required": True, "gt": Decimal(0), "le": Decimal(1)},
    "starts_at": {"type": "datetime", "required": True},
    "ends_at": {"type": "datetime", "required": True},
}


@bp.post("/delegation-grants")
@require_roles("SalesDirector", "VPSales", "CFO")
def create_delegation_grant():
    body = validate(json_body(), GRANT_SPEC)
    grantor = auth.current_user_id()
    if not body["starts_at"] < body["ends_at"]:
        fail("ERR_INVALID_REQUEST", "starts_at must be strictly before ends_at.")
    if body["grantee_user_id"] == grantor:
        fail("ERR_INVALID_REQUEST", "A grantor may not delegate to themselves.")

    for existing in db.all_records("delegation_grants"):
        if existing["status"] != "ACTIVE":
            continue
        if existing["grantor_user_id"] != grantor:
            continue
        if existing["tier_level"] != body["tier_level"]:
            continue
        if body["starts_at"] < existing["ends_at"] and existing["starts_at"] < body["ends_at"]:
            fail("ERR_DELEGATION_WINDOW_OVERLAP")

    record = {
        "grantor_user_id": grantor,
        "grantee_user_id": body["grantee_user_id"],
        "tier_level": body["tier_level"],
        "max_discount_pct": body["max_discount_pct"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "status": "ACTIVE",
        "used_step_count": 0,
        "revoked_at": None,
    }
    db.insert("delegation_grants", record)
    return response.created(record)


@bp.get("/delegation-grants")
@require_roles(ALL)
def list_delegation_grants():
    rows = db.all_records("delegation_grants")
    grantee = flask_request.args.get("grantee_user_id")
    if grantee is not None:
        rows = [r for r in rows if r["grantee_user_id"] == grantee]
    tier_level = flask_request.args.get("tier_level")
    if tier_level is not None:
        rows = [r for r in rows if str(r["tier_level"]) == tier_level]
    status = flask_request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["starts_at"], r["_seq"]))
    window, total, limit, offset = validation.paginate(rows)
    return response.listing(window, total, limit, offset)


@bp.post("/delegation-grants/<grant_id>/revoke")
@require_roles("SalesDirector", "VPSales", "CFO")
def revoke_delegation_grant(grant_id):
    grant = common.must_get("delegation_grants", grant_id)
    validate(json_body(), {})
    if auth.current_user_id() != grant["grantor_user_id"]:
        fail("ERR_NOT_GRANT_GRANTOR", "Only the grantor may revoke a delegation grant.")
    if grant["status"] != "ACTIVE":
        fail("ERR_DELEGATION_STATE_INVALID")
    grant["status"] = "REVOKED"
    grant["revoked_at"] = clock.now()
    db.touch(grant)
    return response.ok(grant)

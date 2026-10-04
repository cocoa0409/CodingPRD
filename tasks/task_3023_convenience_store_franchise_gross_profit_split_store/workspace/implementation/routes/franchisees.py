"""Franchisee resource routes."""

from flask import Blueprint

import db
import middleware
import schemas
import services
from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("franchisees", __name__)

ENTITY_TYPES = ("INDIVIDUAL", "LLC", "CORPORATION")


@bp.post("/franchisees")
@middleware.auth(("FranchisorAdmin",))
def create_franchisee():
    payload = middleware.body(
        required=("legal_name", "owner_name", "stated_net_worth_cents"),
        optional=("entity_type",),
        defaults={"entity_type": "LLC"},
    )
    legal_name = middleware.string_value(payload["legal_name"], "legal_name")
    owner_name = middleware.string_value(payload["owner_name"], "owner_name")
    entity_type = middleware.enum_value(payload["entity_type"], ENTITY_TYPES, "entity_type")
    net_worth = middleware.non_negative_int(payload["stated_net_worth_cents"], "stated_net_worth_cents")

    record = db.insert("franchisees", {
        "legal_name": legal_name,
        "owner_name": owner_name,
        "entity_type": entity_type,
        "stated_net_worth_cents": net_worth,
        "draw_outstanding_cents": 0,
        "open_shrink_charge_cents": 0,
        "audit_adjusted_net_worth_cents": net_worth,
        "risk_band": "A" if net_worth >= 15000000 else ("B" if net_worth >= 5000000 else "C"),
        "status": "ACTIVE",
    })
    return ok(schemas.dump("franchisees", record), 201)


@bp.get("/franchisees")
@middleware.auth(SHARED)
def list_franchisees():
    return list_records("franchisees", ("status", "entity_type"))


@bp.get("/franchisees/<franchisee_id>")
@middleware.auth(SHARED)
def get_franchisee(franchisee_id):
    franchisee = services.require("franchisees", franchisee_id)
    return ok(schemas.dump("franchisees", franchisee))


@bp.post("/franchisees/<franchisee_id>/suspend")
@middleware.auth(("FranchisorAdmin",))
def suspend_franchisee(franchisee_id):
    franchisee = services.require("franchisees", franchisee_id)
    services.require_state(franchisee, "ACTIVE")
    if services.dec(franchisee["draw_outstanding_cents"]) > services.DRAW_CEILING_CENTS:
        fail("ERR_DRAW_EXCEEDS_LIMIT")
    franchisee["status"] = "SUSPENDED"
    db.touch(franchisee)
    services.cascade_stores_out_of_active(franchisee["id"])
    services.recalculate_franchisee(franchisee)
    return ok(schemas.dump("franchisees", franchisee))


@bp.post("/franchisees/<franchisee_id>/reinstate")
@middleware.auth(("FranchisorAdmin",))
def reinstate_franchisee(franchisee_id):
    franchisee = services.require("franchisees", franchisee_id)
    services.require_state(franchisee, "SUSPENDED")
    if services.dec(franchisee["open_shrink_charge_cents"]) != 0:
        fail("ERR_SHRINK_OVERAGE_NOT_CHARGEABLE")
    if services.dec(franchisee["audit_adjusted_net_worth_cents"]) < services.RISK_BAND_B_MIN_CENTS:
        fail("ERR_MIN_NET_WORTH_NOT_MET")
    franchisee["status"] = "ACTIVE"
    db.touch(franchisee)
    services.cascade_reinstate(franchisee)
    return ok(schemas.dump("franchisees", franchisee))


@bp.post("/franchisees/<franchisee_id>/terminate")
@middleware.auth(("FranchisorAdmin",))
def terminate_franchisee(franchisee_id):
    franchisee = services.require("franchisees", franchisee_id)
    status = franchisee["status"]
    if status == "ACTIVE":
        if services.dec(franchisee["draw_outstanding_cents"]) != 0:
            fail("ERR_DRAW_EXCEEDS_LIMIT")
    elif status != "SUSPENDED":
        fail("ERR_INVALID_STATE")
    franchisee["status"] = "TERMINATED"
    db.touch(franchisee)
    services.cascade_stores_out_of_active(franchisee["id"])
    return ok(schemas.dump("franchisees", franchisee))
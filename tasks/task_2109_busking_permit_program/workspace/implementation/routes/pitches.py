"""Designated pitches (PRD section 3.1)."""
from flask import Blueprint, request

import db
from body import Body
from errors import raise_err
from gates import (P_BODY, P_BODY_FK, P_PATH, P_PITCH_ZONE_MISMATCH, P_UNIQUE,
                   resolve, resolve_body_fk, run_gates)
from listing import listing
from middleware import NOISE_INSPECTOR, PERFORMER, PERMIT_OFFICER, require_roles
from response import ok_object
from services.serializers import serialize
from utils import new_entity

bp = Blueprint("pitches", __name__, url_prefix="/busking")


@bp.post("/pitches")
def create_pitch():
    require_roles([PERMIT_OFFICER])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        # Input-list order: zone_id first, fallback_pitch_id last.
        ctx["zone"] = resolve_body_fk("zones", raw, "zone_id")
        ctx["fallback"] = resolve_body_fk("pitches", raw, "fallback_pitch_id")

    def check_body():
        ctx["fields"] = {
            "zone_id": body.req_id("zone_id"),
            "code": body.req_str("code", max_len=16),
            "tier": body.req_enum("tier", {"PREMIUM", "STANDARD"}),
            "amplification_allowed": body.opt_bool("amplification_allowed", False),
            "noise_cap_db": body.req_int("noise_cap_db", 55, 100),
            "max_session_minutes": body.opt_int("max_session_minutes", 120, 15, 240),
            "daily_session_cap": body.opt_int("daily_session_cap", 3, 1, 12),
            "premium_slots_per_draw": body.opt_int("premium_slots_per_draw", 1, 1, 5),
            "fallback_pitch_id": body.opt_id("fallback_pitch_id"),
            "availability_status": "OPEN",
        }

    def check_unique():
        code = ctx["fields"]["code"]
        if any(pitch["code"] == code for pitch in db.all_of("pitches")):
            raise_err("ERR_PITCH_CODE_TAKEN", "A pitch with code %s already exists" % code)

    def check_fallback():
        fallback = ctx["fallback"]
        if fallback is None:
            return
        if fallback["zone_id"] != ctx["fields"]["zone_id"]:
            raise_err("ERR_PITCH_ZONE_MISMATCH",
                      "The fallback pitch must belong to the same district")

    run_gates([
        (P_BODY_FK, check_fks),
        (P_BODY, check_body),
        (P_UNIQUE, check_unique),
        (P_PITCH_ZONE_MISMATCH, check_fallback),
    ])
    return ok_object(serialize(new_entity("pitches", ctx["fields"])), status=201)


@bp.get("/pitches/<pitch_id>")
def read_pitch(pitch_id):
    require_roles([PERMIT_OFFICER, PERFORMER, NOISE_INSPECTOR])
    ctx = {}
    run_gates([(P_PATH, lambda: ctx.update(pitch=resolve("pitches", pitch_id)))])
    return ok_object(serialize(ctx["pitch"]))


@bp.get("/pitches")
def list_pitches():
    require_roles([PERMIT_OFFICER, PERFORMER, NOISE_INSPECTOR])
    return listing("pitches",
                   ["zone_id", "fallback_pitch_id", "tier", "availability_status"],
                   request.args)

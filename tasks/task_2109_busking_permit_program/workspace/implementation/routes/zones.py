"""Ordinance districts (PRD section 3.1)."""
from flask import Blueprint, request

import db
from body import Body
from errors import raise_err
from gates import P_BODY, P_PATH, P_UNIQUE, resolve, run_gates
from middleware import NOISE_INSPECTOR, PERFORMER, PERMIT_OFFICER, require_roles
from response import ok_object
from services.serializers import serialize
from utils import new_entity

bp = Blueprint("zones", __name__, url_prefix="/busking")


@bp.post("/zones")
def create_zone():
    require_roles([PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["fields"] = {
            "name": body.req_str("name"),
            "code": body.req_str("code", max_len=16),
            "base_noise_cap_db": body.req_int("base_noise_cap_db", 55, 100),
            "weekend_noise_bonus_db": body.opt_int("weekend_noise_bonus_db", 0, 0, 10),
            "evening_start_minute": body.req_int("evening_start_minute", 0, 1439),
            "evening_penalty_db": body.opt_int("evening_penalty_db", 0, 0, 20),
            "quiet_hours_start_minute": body.req_int("quiet_hours_start_minute", 0, 1439),
            "quiet_hours_end_minute": body.req_int("quiet_hours_end_minute", 0, 1439),
            "max_concurrent_closures": body.opt_int("max_concurrent_closures", 1, 1, 5),
            "active_closure_count": 0,
        }

    def check_unique():
        code = ctx["fields"]["code"]
        if any(zone["code"] == code for zone in db.all_of("zones")):
            raise_err("ERR_ZONE_CODE_TAKEN", "A district with code %s already exists" % code)

    run_gates([(P_BODY, check_body), (P_UNIQUE, check_unique)])
    return ok_object(serialize(new_entity("zones", ctx["fields"])), status=201)


@bp.get("/zones/<zone_id>")
def read_zone(zone_id):
    require_roles([PERMIT_OFFICER, PERFORMER, NOISE_INSPECTOR])
    ctx = {}
    run_gates([(P_PATH, lambda: ctx.update(zone=resolve("zones", zone_id)))])
    return ok_object(serialize(ctx["zone"]))

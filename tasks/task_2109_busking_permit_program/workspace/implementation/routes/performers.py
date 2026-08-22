"""Street performers (PRD section 3.2)."""
from flask import Blueprint, request

import db
from body import Body
from errors import raise_err
from gates import P_BODY, P_OWNER, P_PATH, P_UNIQUE, resolve, run_gates
from middleware import PERFORMER, PERMIT_OFFICER, require_owner, require_roles
from response import ok_object
from services.calc import ACT_TYPES
from services.serializers import serialize
from utils import new_entity

bp = Blueprint("performers", __name__, url_prefix="/busking")


@bp.post("/performers")
def create_performer():
    require_roles([PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["fields"] = {
            "legal_name": body.req_str("legal_name"),
            "stage_name": body.req_str("stage_name"),
            "email": body.req_str("email"),
            "act_type": body.req_enum("act_type", ACT_TYPES),
            "conduct_score": 100,
            "renewal_conduct_score": 100,
            "standing": "GOOD",
            "upheld_complaint_count": 0,
            "premium_wins_this_season": 0,
        }

    def check_unique():
        email = ctx["fields"]["email"].lower()
        if any(row["email"].lower() == email for row in db.all_of("performers")):
            raise_err("ERR_PERFORMER_EMAIL_TAKEN", "That email is already enrolled")

    run_gates([(P_BODY, check_body), (P_UNIQUE, check_unique)])
    return ok_object(serialize(new_entity("performers", ctx["fields"])), status=201)


@bp.get("/performers/<performer_id>")
def read_performer(performer_id):
    user_id, role = require_roles([PERMIT_OFFICER, PERFORMER])
    ctx = {}
    run_gates([
        (P_PATH, lambda: ctx.update(performer=resolve("performers", performer_id))),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["performer"]["id"])),
    ])
    return ok_object(serialize(ctx["performer"]))

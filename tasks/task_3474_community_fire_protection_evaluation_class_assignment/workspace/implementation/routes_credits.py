"""Community risk-reduction credits (PRD §3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import db
from cascade import window_or_fail, recompute_draft_if_scoring
from errors import fail
from middleware import auth, require_role, require_owner
from response import ok, ok_list
from scoring import CRR_ITEM_CAP
from util import (body, need, v_num, v_str, v_enum, v_range,
                  pagination_params, page_of, dec)

bp = Blueprint("credits", __name__)

PROGRAM_TYPES = ("PREVENTION_INSPECTION", "CODE_ENFORCEMENT", "PUBLIC_EDUCATION", "FIRE_INVESTIGATION")
CREDIT_TARGETS = ("VERIFIED", "REJECTED")
CREDIT_EDGES = {
    ("PENDING", "VERIFIED"),
    ("PENDING", "REJECTED"),
    ("VERIFIED", "REJECTED"),  # revoke
}


@bp.route("/ppc/risk-reduction-credits", methods=["POST"])
def create_credit():
    uid, role = auth()
    require_role(role, "CommunityOfficial")
    b = body()
    cycle_id = v_str(need(b, "cycle_id"), "cycle_id")
    cycle = db.find("cycles", cycle_id)
    if cycle is None:
        fail("ERR_CYCLE_NOT_FOUND", "evaluation cycle does not exist")
    require_owner(cycle["community_id"] == uid)
    window_or_fail(cycle["community_id"], ("DATA_COLLECTION", "FIELD_VERIFICATION"))
    program_type = v_enum(need(b, "program_type"), "program_type", PROGRAM_TYPES)
    points = v_range(v_num(need(b, "activity_points"), "activity_points"),
                     "activity_points", lo=Decimal("0"), lo_inclusive=False)
    note = v_str(need(b, "evidence_note"), "evidence_note")

    credit = db.new_entity("credits", {
        "cycle_id": cycle_id,
        "program_type": program_type,
        "activity_points": points,
        "evidence_note": note,
        "status": "PENDING",
        "credited_points": Decimal("0"),
        "verified_by": None,
    })
    return ok(db.pub(credit), 201)


@bp.route("/ppc/risk-reduction-credits", methods=["GET"])
def list_credits():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("credits")
    for f in ("cycle_id", "status", "program_type"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if str(c[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(c) for c in page], total, limit, offset)


@bp.route("/ppc/risk-reduction-credits/<creditId>", methods=["GET"])
def get_credit(creditId):
    auth()
    credit = db.find("credits", creditId)
    if credit is None:
        fail("ERR_CREDIT_NOT_FOUND", "risk-reduction credit does not exist")
    return ok(db.pub(credit))


@bp.route("/ppc/risk-reduction-credits/<creditId>/transition", methods=["POST"])
def transition_credit(creditId):
    uid, role = auth()
    require_role(role, "FieldAnalyst")
    credit = db.find("credits", creditId)
    if credit is None:
        fail("ERR_CREDIT_NOT_FOUND", "risk-reduction credit does not exist")
    b = body()
    target = v_str(need(b, "target_state"), "target_state")
    if target not in CREDIT_TARGETS or (credit["status"], target) not in CREDIT_EDGES:
        fail("ERR_CREDIT_INVALID_STATE",
             "credit cannot move from %s to %s" % (credit["status"], target))
    cycle = db.find("cycles", credit["cycle_id"])
    window_or_fail(cycle["community_id"], ("FIELD_VERIFICATION", "SCORING"))

    if target == "VERIFIED":
        credit["status"] = "VERIFIED"
        credit["credited_points"] = min(dec(credit["activity_points"]), CRR_ITEM_CAP)
        credit["verified_by"] = uid
    else:
        credit["status"] = "REJECTED"
        credit["credited_points"] = Decimal("0")
    db.touch(credit)
    recompute_draft_if_scoring(cycle["community_id"])
    return ok(db.pub(credit))

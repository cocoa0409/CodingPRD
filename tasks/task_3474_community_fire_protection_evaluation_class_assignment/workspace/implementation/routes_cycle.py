"""Evaluation cycles, score sheets, and classification publication."""
from flask import Blueprint, request

import db
from cascade import scoring_gate_ok, sheet_values
from errors import fail
from middleware import auth, require_role
from response import ok, ok_list
from scoring import MODIFIER_TABLE
from util import (body, need, v_str, v_int, v_date, parse_date,
                  pagination_params, page_of)

bp = Blueprint("cycle", __name__)

CYCLE_TERMINAL = ("EFFECTIVE", "WITHDRAWN")
TRANSITION_TARGETS = ("INTAKE", "DATA_COLLECTION", "FIELD_VERIFICATION",
                      "SCORING", "CLASSIFICATION_REVIEW", "WITHDRAWN")
CYCLE_EDGES = {
    ("SCHEDULED", "INTAKE"),
    ("INTAKE", "DATA_COLLECTION"),
    ("DATA_COLLECTION", "FIELD_VERIFICATION"),
    ("FIELD_VERIFICATION", "SCORING"),
    ("SCORING", "CLASSIFICATION_REVIEW"),
    ("DISPUTED", "FIELD_VERIFICATION"),
}
WITHDRAWABLE = ("SCHEDULED", "INTAKE", "DATA_COLLECTION", "FIELD_VERIFICATION",
                "SCORING", "CLASSIFICATION_REVIEW", "PUBLISHED", "DISPUTED")


def _window_conflicts(field_analyst_id, open_d, freeze_d, exclude_id=None):
    """Half-open [open, freeze) overlap; touching endpoints do not overlap."""
    for other in db.all_of("cycles"):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["field_analyst_id"] != field_analyst_id:
            continue
        if other["status"] in CYCLE_TERMINAL:
            continue
        o_open = parse_date(other["scheduled_open_date"])
        o_freeze = parse_date(other["data_freeze_date"])
        if o_open < freeze_d and o_freeze > open_d:
            return True
    return False


@bp.route("/ppc/evaluation-cycles", methods=["POST"])
def create_cycle():
    uid, role = auth()
    require_role(role, "EvaluationCoordinator")
    b = body()
    community_id = v_str(need(b, "community_id"), "community_id")
    community = db.find("communities", community_id)
    if community is None:
        fail("ERR_COMMUNITY_NOT_FOUND", "community does not exist")
    field_analyst_id = v_str(need(b, "field_analyst_id"), "field_analyst_id")
    open_d = v_date(need(b, "scheduled_open_date"), "scheduled_open_date")
    freeze_d = v_date(need(b, "data_freeze_date"), "data_freeze_date")

    if community["status"] not in ("REGISTERED", "CLASSIFIED"):
        fail("ERR_COMMUNITY_INVALID_STATE",
             "community status %s does not allow opening a cycle" % community["status"])
    if _window_conflicts(field_analyst_id, open_d, freeze_d):
        fail("ERR_CYCLE_WINDOW_CONFLICT",
             "field analyst already assigned an overlapping non-terminal cycle")
    if not (freeze_d > open_d):
        fail("ERR_INVALID_REQUEST", "data_freeze_date must be after scheduled_open_date")

    cycle = db.new_entity("cycles", {
        "community_id": community_id,
        "cycle_number": db.next_cycle_number(community_id),
        "field_analyst_id": field_analyst_id,
        "scheduled_open_date": open_d.isoformat(),
        "data_freeze_date": freeze_d.isoformat(),
        "status": "SCHEDULED",
        "opened_at": None,
    })
    community["status"] = "UNDER_EVALUATION"
    db.touch(community)
    return ok(db.pub(cycle), 201)


@bp.route("/ppc/evaluation-cycles", methods=["GET"])
def list_cycles():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("cycles")
    for f in ("community_id", "status", "field_analyst_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if str(c[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(c) for c in page], total, limit, offset)


@bp.route("/ppc/evaluation-cycles/<cycleId>", methods=["GET"])
def get_cycle(cycleId):
    auth()
    cycle = db.find("cycles", cycleId)
    if cycle is None:
        fail("ERR_CYCLE_NOT_FOUND", "evaluation cycle does not exist")
    return ok(db.pub(cycle))


@bp.route("/ppc/evaluation-cycles/<cycleId>/transition", methods=["POST"])
def transition_cycle(cycleId):
    uid, role = auth()
    require_role(role, "EvaluationCoordinator")
    b = body()
    target = v_str(need(b, "target_state"), "target_state")
    cycle = db.find("cycles", cycleId)
    if cycle is None:
        fail("ERR_CYCLE_NOT_FOUND", "evaluation cycle does not exist")

    if target not in TRANSITION_TARGETS:
        fail("ERR_CYCLE_INVALID_STATE", "target_state %s is not reachable via this endpoint" % target)

    if target == "WITHDRAWN":
        if cycle["status"] not in WITHDRAWABLE:
            fail("ERR_CYCLE_INVALID_STATE",
                 "cycle in %s cannot be withdrawn" % cycle["status"])
        cycle["status"] = "WITHDRAWN"
        db.touch(cycle)
        community = db.find("communities", cycle["community_id"])
        community["status"] = ("CLASSIFIED" if community["current_class_number"] is not None
                               else "REGISTERED")
        db.touch(community)
        return ok(db.pub(cycle))

    if (cycle["status"], target) not in CYCLE_EDGES:
        fail("ERR_CYCLE_INVALID_STATE",
             "cycle cannot move from %s to %s" % (cycle["status"], target))

    if target == "INTAKE":
        if db.clock_date() < parse_date(cycle["scheduled_open_date"]):
            fail("ERR_CYCLE_NOT_OPEN_YET", "logical clock date precedes scheduled_open_date")
        cycle["opened_at"] = db.clock_iso()
    elif target == "SCORING":
        if not scoring_gate_ok(cycle["community_id"]):
            fail("ERR_CYCLE_DATA_INCOMPLETE",
                 "pending flow tests, unattested comms, or unsubmitted department data")
    elif target == "CLASSIFICATION_REVIEW":
        if not any(s for s in db.all_of("sheets")
                   if s["cycle_id"] == cycle["id"] and s["status"] == "FINAL"):
            fail("ERR_NO_FINAL_SCORE_SHEET", "no FINAL score sheet exists for the cycle")
    elif target == "FIELD_VERIFICATION" and cycle["status"] == "DISPUTED":
        found = False
        for a in db.all_of("appeals"):
            cl = db.find("classifications", a["classification_id"])
            if cl and cl["cycle_id"] == cycle["id"] and a["status"] == "DATA_VERIFICATION":
                found = True
                break
        if not found:
            fail("ERR_NO_APPEAL_IN_VERIFICATION",
                 "DISPUTED exit requires an appeal in DATA_VERIFICATION")

    cycle["status"] = target
    db.touch(cycle)
    return ok(db.pub(cycle))


@bp.route("/ppc/evaluation-cycles/<cycleId>/score-sheets", methods=["POST"])
def create_score_sheet(cycleId):
    uid, role = auth()
    require_role(role, "FieldAnalyst")
    cycle = db.find("cycles", cycleId)
    if cycle is None:
        fail("ERR_CYCLE_NOT_FOUND", "evaluation cycle does not exist")
    if cycle["status"] != "SCORING":
        fail("ERR_CYCLE_INVALID_STATE",
             "cycle must be in a scoring-phase state (SCORING), not %s" % cycle["status"])
    b = body()
    expected = v_int(need(b, "expected_cycle_version"), "expected_cycle_version")
    if expected != cycle["version"]:
        fail("ERR_STALE_VERSION", "expected_cycle_version does not match the cycle's version")
    if not scoring_gate_ok(cycle["community_id"]):
        fail("ERR_CYCLE_DATA_INCOMPLETE",
             "pending flow tests, unattested comms, or unsubmitted department data")

    values = sheet_values(cycle)
    for other in db.all_of("sheets"):
        if other["cycle_id"] == cycle["id"] and other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            db.touch(other)
    sheet = db.new_entity("sheets", dict(values, cycle_id=cycle["id"], status="DRAFT"))
    db.touch(cycle)
    return ok(db.pub(sheet), 201)


@bp.route("/ppc/score-sheets", methods=["GET"])
def list_score_sheets():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("sheets")
    for f in ("cycle_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if str(s[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(s) for s in page], total, limit, offset)


@bp.route("/ppc/score-sheets/<sheetId>", methods=["GET"])
def get_score_sheet(sheetId):
    auth()
    sheet = db.find("sheets", sheetId)
    if sheet is None:
        fail("ERR_SCORE_SHEET_NOT_FOUND", "score sheet does not exist")
    return ok(db.pub(sheet))


@bp.route("/ppc/score-sheets/<sheetId>/finalize", methods=["POST"])
def finalize_score_sheet(sheetId):
    uid, role = auth()
    require_role(role, "FieldAnalyst")
    sheet = db.find("sheets", sheetId)
    if sheet is None:
        fail("ERR_SCORE_SHEET_NOT_FOUND", "score sheet does not exist")
    cycle = db.find("cycles", sheet["cycle_id"])
    if sheet["status"] != "DRAFT" or cycle["status"] not in ("SCORING", "CLASSIFICATION_REVIEW"):
        fail("ERR_SHEET_INVALID_STATE",
             "sheet must be DRAFT and its cycle in SCORING or CLASSIFICATION_REVIEW")
    sheet["status"] = "FINAL"
    db.touch(sheet)
    for other in db.all_of("sheets"):
        if other["cycle_id"] == cycle["id"] and other["id"] != sheet["id"] \
                and other["status"] != "SUPERSEDED":
            other["status"] = "SUPERSEDED"
            db.touch(other)
    return ok(db.pub(sheet))


@bp.route("/ppc/evaluation-cycles/<cycleId>/publish-classification", methods=["POST"])
def publish_classification(cycleId):
    uid, role = auth()
    require_role(role, "ClassRegistrar")
    cycle = db.find("cycles", cycleId)
    if cycle is None:
        fail("ERR_CYCLE_NOT_FOUND", "evaluation cycle does not exist")
    if cycle["status"] != "CLASSIFICATION_REVIEW":
        fail("ERR_CYCLE_INVALID_STATE", "publish requires CLASSIFICATION_REVIEW")
    if uid == cycle["field_analyst_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "publishing registrar must differ from the cycle's field analyst")
    b = body()
    sheet_id = v_str(need(b, "score_sheet_id"), "score_sheet_id")
    sheet = db.find("sheets", sheet_id)
    if sheet is None or sheet["status"] != "FINAL" or sheet["cycle_id"] != cycle["id"]:
        fail("ERR_INVALID_REQUEST", "score_sheet_id must reference a FINAL sheet of this cycle")

    classification = db.new_entity("classifications", {
        "community_id": cycle["community_id"],
        "cycle_id": cycle["id"],
        "score_sheet_id": sheet["id"],
        "base_class": sheet["base_class"],
        "split_class_beyond_hydrant": sheet["split_class_beyond_hydrant"],
        "premium_modifier": MODIFIER_TABLE[sheet["base_class"]],
        "status": "PUBLISHED",
        "published_by": uid,
        "published_at": db.clock_iso(),
        "effective_from": None,
        "effective_until": None,
    })
    cycle["status"] = "PUBLISHED"
    db.touch(cycle)
    return ok(db.pub(classification), 201)

"""Reevaluation requests (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import fail
from middleware import auth, require_role, require_owner
from response import ok, ok_list
from scoring import REEVAL_MIN_MONTHS
from util import (body, need, v_str, v_int, v_evidence_items,
                  pagination_params, page_of, parse_date, add_calendar_months,
                  add_days)

bp = Blueprint("reeval", __name__)

REQUEST_TERMINAL = ("APPROVED", "DENIED", "WITHDRAWN")
REQUEST_TARGET_ROLES = {
    "DOCUMENTATION_REVIEW": "EvaluationCoordinator",
    "SUBMITTED": "EvaluationCoordinator",
    "FIELD_REVERIFICATION": "FieldAnalyst",
    "DENIED": "ClassRegistrar",
    "WITHDRAWN": "CommunityOfficial",
}
REQUEST_EDGES = {
    ("SUBMITTED", "DOCUMENTATION_REVIEW"),
    ("DOCUMENTATION_REVIEW", "SUBMITTED"),
    ("DOCUMENTATION_REVIEW", "FIELD_REVERIFICATION"),
    ("FIELD_REVERIFICATION", "DENIED"),
    ("SUBMITTED", "WITHDRAWN"),
    ("DOCUMENTATION_REVIEW", "WITHDRAWN"),
}
ENDPOINT_ROLES = ("EvaluationCoordinator", "FieldAnalyst", "ClassRegistrar", "CommunityOfficial")


@bp.route("/ppc/reevaluation-requests", methods=["POST"])
def create_request():
    uid, role = auth()
    require_role(role, "CommunityOfficial")
    b = body()
    community_id = v_str(need(b, "community_id"), "community_id")
    require_owner(community_id == uid)
    community = db.find("communities", community_id)
    if community is None:
        fail("ERR_COMMUNITY_NOT_FOUND", "community does not exist")
    if community["status"] != "CLASSIFIED":
        fail("ERR_COMMUNITY_INVALID_STATE",
             "community must be CLASSIFIED to request reevaluation, not %s" % community["status"])
    effective = db.effective_classification_of_community(community_id)
    if effective is None or db.clock_date() < add_calendar_months(
            parse_date(effective["effective_from"]), REEVAL_MIN_MONTHS):
        fail("ERR_REEVALUATION_TOO_EARLY",
             "fewer than 12 months since the current classification's effective_from")
    justification = v_str(need(b, "justification"), "justification")
    evidence = v_evidence_items(need(b, "evidence_items"))
    for r in db.all_of("requests"):
        if r["community_id"] == community_id and r["status"] not in REQUEST_TERMINAL:
            fail("ERR_DUPLICATE_ACTIVE_REQUEST",
                 "community already has a non-terminal reevaluation request")

    req = db.new_entity("requests", {
        "community_id": community_id,
        "justification": justification,
        "evidence_items": evidence,
        "status": "SUBMITTED",
        "submitted_by": uid,
        "decision_note": None,
    })
    community["status"] = "REEVALUATION_REQUESTED"
    db.touch(community)
    return ok(db.pub(req), 201)


@bp.route("/ppc/reevaluation-requests", methods=["GET"])
def list_requests():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("requests")
    for f in ("community_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if str(r[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(r) for r in page], total, limit, offset)


@bp.route("/ppc/reevaluation-requests/<requestId>", methods=["GET"])
def get_request(requestId):
    auth()
    req = db.find("requests", requestId)
    if req is None:
        fail("ERR_REQUEST_NOT_FOUND", "reevaluation request does not exist")
    return ok(db.pub(req))


@bp.route("/ppc/reevaluation-requests/<requestId>", methods=["PATCH"])
def patch_request(requestId):
    uid, role = auth()
    require_role(role, "CommunityOfficial")
    req = db.find("requests", requestId)
    if req is None:
        fail("ERR_REQUEST_NOT_FOUND", "reevaluation request does not exist")
    require_owner(req["community_id"] == uid)
    if req["status"] != "SUBMITTED":
        fail("ERR_REQUEST_INVALID_STATE",
             "evidence may only be replaced while the request is SUBMITTED")
    b = body()
    req["evidence_items"] = v_evidence_items(need(b, "evidence_items"))
    db.touch(req)
    return ok(db.pub(req))


@bp.route("/ppc/reevaluation-requests/<requestId>/transition", methods=["POST"])
def transition_request(requestId):
    uid, role = auth()
    require_role(role, *ENDPOINT_ROLES)
    b = body()
    target = v_str(need(b, "target_state"), "target_state")
    if target in REQUEST_TARGET_ROLES and role != REQUEST_TARGET_ROLES[target]:
        fail("ERR_FORBIDDEN", "role %s does not own target_state %s" % (role, target))
    req = db.find("requests", requestId)
    if req is None:
        fail("ERR_REQUEST_NOT_FOUND", "reevaluation request does not exist")
    if target == "WITHDRAWN":
        require_owner(req["community_id"] == uid)
    if (req["status"], target) not in REQUEST_EDGES:
        fail("ERR_REQUEST_INVALID_STATE",
             "request cannot move from %s to %s" % (req["status"], target))

    req["status"] = target
    if target == "DENIED":
        note = b.get("note")
        if note is not None:
            req["decision_note"] = v_str(note, "note")
    db.touch(req)
    if target in ("DENIED", "WITHDRAWN"):
        community = db.find("communities", req["community_id"])
        community["status"] = "CLASSIFIED"
        db.touch(community)
    return ok(db.pub(req))


@bp.route("/ppc/reevaluation-requests/<requestId>/approve", methods=["POST"])
def approve_request(requestId):
    uid, role = auth()
    require_role(role, "ClassRegistrar")
    req = db.find("requests", requestId)
    if req is None:
        fail("ERR_REQUEST_NOT_FOUND", "reevaluation request does not exist")
    if req["status"] != "FIELD_REVERIFICATION":
        fail("ERR_REQUEST_INVALID_STATE",
             "request must be in FIELD_REVERIFICATION to approve, not %s" % req["status"])
    b = body()
    community = db.find("communities", req["community_id"])
    expected = v_int(need(b, "expected_community_version"), "expected_community_version")
    if expected != community["version"]:
        fail("ERR_STALE_VERSION", "expected_community_version does not match the community's version")
    field_analyst_id = v_str(need(b, "field_analyst_id"), "field_analyst_id")
    note = b.get("note")
    if note is not None:
        note = v_str(note, "note")

    open_d = db.clock_date()
    freeze_d = add_days(open_d, 90)
    for other in db.all_of("cycles"):
        if other["field_analyst_id"] != field_analyst_id:
            continue
        if other["status"] in ("EFFECTIVE", "WITHDRAWN"):
            continue
        o_open = parse_date(other["scheduled_open_date"])
        o_freeze = parse_date(other["data_freeze_date"])
        if o_open < freeze_d and o_freeze > open_d:
            fail("ERR_CYCLE_WINDOW_CONFLICT",
                 "field analyst already assigned an overlapping non-terminal cycle")

    req["status"] = "APPROVED"
    req["decision_note"] = note
    db.touch(req)
    db.new_entity("cycles", {
        "community_id": community["id"],
        "cycle_number": db.next_cycle_number(community["id"]),
        "field_analyst_id": field_analyst_id,
        "scheduled_open_date": open_d.isoformat(),
        "data_freeze_date": freeze_d.isoformat(),
        "status": "SCHEDULED",
        "opened_at": None,
    })
    community["status"] = "UNDER_REEVALUATION"
    db.touch(community)
    return ok(db.pub(req))

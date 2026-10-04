"""Appeals: filing, verification, adjudication (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import fail
from middleware import auth, require_role, require_owner
from response import ok, ok_list
from scoring import MODIFIER_TABLE, APPEAL_WINDOW_DAYS
from util import (body, need, v_str, v_enum, v_evidence_items,
                  pagination_params, page_of, parse_iso_dt)

bp = Blueprint("appeals", __name__)

GROUNDS = ("DATA_ERROR", "PROCEDURAL_ERROR", "NEW_EVIDENCE")
NON_TERMINAL_APPEAL = ("FILED", "DATA_VERIFICATION")
APPEAL_TARGET_ROLES = {
    "DATA_VERIFICATION": "FieldAnalyst",
    "FILED": "FieldAnalyst",
    "ADJUDICATED_UPHELD": "ClassRegistrar",
    "ADJUDICATED_REVISED": "ClassRegistrar",
    "WITHDRAWN": "CommunityOfficial",
}
APPEAL_EDGES = {
    ("FILED", "DATA_VERIFICATION"),
    ("DATA_VERIFICATION", "FILED"),
    ("DATA_VERIFICATION", "ADJUDICATED_UPHELD"),
    ("DATA_VERIFICATION", "ADJUDICATED_REVISED"),
    ("FILED", "WITHDRAWN"),
}
ENDPOINT_ROLES = ("FieldAnalyst", "ClassRegistrar", "CommunityOfficial")


@bp.route("/ppc/appeals", methods=["POST"])
def create_appeal():
    uid, role = auth()
    require_role(role, "CommunityOfficial")
    b = body()
    community_id = v_str(need(b, "community_id"), "community_id")
    require_owner(community_id == uid)
    classification_id = v_str(need(b, "classification_id"), "classification_id")
    community = db.find("communities", community_id)
    if community is None:
        fail("ERR_COMMUNITY_NOT_FOUND", "community does not exist")
    cl = db.find("classifications", classification_id)
    if cl is None:
        fail("ERR_CLASSIFICATION_NOT_FOUND", "classification does not exist")
    if cl["status"] not in ("PUBLISHED", "EFFECTIVE"):
        fail("ERR_CLASSIFICATION_INVALID_STATE",
             "classification must be PUBLISHED or EFFECTIVE to appeal, not %s" % cl["status"])
    published_at = parse_iso_dt(cl["published_at"])
    if db.clock_dt() > published_at + timedelta(days=APPEAL_WINDOW_DAYS):
        fail("ERR_APPEAL_WINDOW_EXPIRED",
             "more than 90 days since the classification was published")
    grounds = v_enum(need(b, "grounds"), "grounds", GROUNDS)
    evidence = v_evidence_items(need(b, "evidence_items"))
    if cl["community_id"] != community_id:
        fail("ERR_INVALID_REQUEST", "community_id must be the classification's own community")
    for a in db.all_of("appeals"):
        if a["classification_id"] == cl["id"] and a["status"] in NON_TERMINAL_APPEAL:
            fail("ERR_DUPLICATE_ACTIVE_APPEAL",
                 "classification already has a non-terminal appeal")

    appeal = db.new_entity("appeals", {
        "classification_id": classification_id,
        "community_id": community_id,
        "grounds": grounds,
        "evidence_items": evidence,
        "status": "FILED",
        "filed_by": uid,
        "adjudicated_by": None,
        "new_score_sheet_id": None,
    })
    cycle = db.find("cycles", cl["cycle_id"])
    if cycle is not None and cycle["status"] == "PUBLISHED":
        cycle["status"] = "DISPUTED"
        db.touch(cycle)
    return ok(db.pub(appeal), 201)


@bp.route("/ppc/appeals", methods=["GET"])
def list_appeals():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("appeals")
    for f in ("classification_id", "community_id", "status", "new_score_sheet_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if str(a[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(a) for a in page], total, limit, offset)


@bp.route("/ppc/appeals/<appealId>", methods=["GET"])
def get_appeal(appealId):
    auth()
    appeal = db.find("appeals", appealId)
    if appeal is None:
        fail("ERR_APPEAL_NOT_FOUND", "appeal does not exist")
    return ok(db.pub(appeal))


def _cycle_return_to_published(classification):
    cycle = db.find("cycles", classification["cycle_id"])
    if cycle is not None and cycle["status"] == "DISPUTED":
        cycle["status"] = "PUBLISHED"
        db.touch(cycle)


@bp.route("/ppc/appeals/<appealId>/transition", methods=["POST"])
def transition_appeal(appealId):
    uid, role = auth()
    require_role(role, *ENDPOINT_ROLES)
    b = body()
    target = v_str(need(b, "target_state"), "target_state")
    if target in APPEAL_TARGET_ROLES and role != APPEAL_TARGET_ROLES[target]:
        fail("ERR_FORBIDDEN", "role %s does not own target_state %s" % (role, target))
    appeal = db.find("appeals", appealId)
    if appeal is None:
        fail("ERR_APPEAL_NOT_FOUND", "appeal does not exist")
    if target == "WITHDRAWN":
        require_owner(appeal["community_id"] == uid)
    if (appeal["status"], target) not in APPEAL_EDGES:
        fail("ERR_APPEAL_INVALID_STATE",
             "appeal cannot move from %s to %s" % (appeal["status"], target))
    cl = db.find("classifications", appeal["classification_id"])

    if target == "WITHDRAWN":
        appeal["status"] = "WITHDRAWN"
        db.touch(appeal)
        _cycle_return_to_published(cl)
        return ok(db.pub(appeal))

    if target in ("DATA_VERIFICATION", "FILED"):
        appeal["status"] = target
        db.touch(appeal)
        return ok(db.pub(appeal))

    # Adjudication: segregated from the original publisher (PRD §2.9)
    if uid == cl["published_by"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "adjudicating registrar must differ from the classification's publisher")

    if target == "ADJUDICATED_UPHELD":
        appeal["status"] = "ADJUDICATED_UPHELD"
        appeal["adjudicated_by"] = uid
        db.touch(appeal)
        _cycle_return_to_published(cl)
        return ok(db.pub(appeal))

    # ADJUDICATED_REVISED
    new_sheet_id = b.get("new_score_sheet_id")
    if not isinstance(new_sheet_id, str):
        fail("ERR_INVALID_REQUEST", "new_score_sheet_id must be supplied")
    sheet = db.find("sheets", new_sheet_id)
    if sheet is None or sheet["status"] != "FINAL" \
            or sheet["cycle_id"] != cl["cycle_id"] or new_sheet_id == cl["score_sheet_id"]:
        fail("ERR_INVALID_REQUEST",
             "new_score_sheet_id must be FINAL, belong to the classification's cycle, "
             "and differ from the classification's current score_sheet_id")
    cycle = db.find("cycles", cl["cycle_id"])
    if cycle["status"] != "CLASSIFICATION_REVIEW":
        fail("ERR_CYCLE_INVALID_STATE",
             "adjudicating revised requires the classification's cycle in CLASSIFICATION_REVIEW")

    cl["status"] = "VACATED"
    db.touch(cl)
    old_sheet = db.find("sheets", cl["score_sheet_id"])
    if old_sheet is not None and old_sheet["status"] == "FINAL":
        old_sheet["status"] = "SUPERSEDED"
        db.touch(old_sheet)

    db.new_entity("classifications", {
        "community_id": cl["community_id"],
        "cycle_id": cl["cycle_id"],
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
    appeal["status"] = "ADJUDICATED_REVISED"
    appeal["adjudicated_by"] = uid
    appeal["new_score_sheet_id"] = new_sheet_id
    db.touch(appeal)
    cycle["status"] = "PUBLISHED"
    db.touch(cycle)
    return ok(db.pub(appeal))

"""Policy initiative endpoints: creation with the initial pattern-count
derivation and the research / draft / adopt / stall / resume lifecycle."""

from flask import Blueprint

import db
from auth import require_roles
from calculations import POLICY_PATTERN_THRESHOLD, policy_pattern_count
from db import touch
from envelope import ok
from errors import (
    ERR_INSUFFICIENT_PATTERN_EVIDENCE,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_POLICY_INITIATIVE_NOT_FOUND,
    raise_err,
)
from validation import (
    as_string,
    body_json,
    reject_unknown,
    req_choice,
    req_field,
    req_str,
)

bp = Blueprint("policy_initiatives", __name__)

TOPICS = ("EVIDENCE_PRESERVATION", "COMPENSATION_REFORM", "DATABASE_ACCESS",
          "RECORDS_TRANSPARENCY")
ADVANCE_EVENTS = ("BEGIN_RESEARCH", "SUBMIT_DRAFT", "ADOPT", "STALL", "RESUME")


@bp.post("/policy-initiatives")
def create_policy_initiative():
    require_roles("PolicyDirector")
    body = body_json()
    if "jurisdiction_id" in body:
        db.lookup(db.jurisdictions, body.get("jurisdiction_id"),
                  ERR_JURISDICTION_NOT_FOUND)
    reject_unknown(body, {"jurisdiction_id", "topic", "title"})
    jurisdiction_id = req_str(body, "jurisdiction_id")
    topic = req_choice(body, "topic", TOPICS)
    title = req_str(body, "title")
    initiative = db.new_entity()
    initiative.update({
        "jurisdiction_id": jurisdiction_id,
        "topic": topic,
        "title": title,
        "status": "PROPOSED",
        "pattern_case_count": policy_pattern_count(topic, jurisdiction_id),
    })
    db.policy_initiatives[initiative["id"]] = initiative
    return ok(initiative, 201)


@bp.post("/policy-initiatives/<pid>/advance")
def advance_policy_initiative(pid):
    require_roles("PolicyDirector")
    initiative = db.lookup(db.policy_initiatives, pid,
                           ERR_POLICY_INITIATIVE_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ADVANCE_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for policy-initiative advance: %s" % event)
    status = initiative["status"]
    if event == "BEGIN_RESEARCH":
        if status != "PROPOSED":
            raise_err(ERR_INVALID_STATE, "BEGIN_RESEARCH requires status PROPOSED")
        initiative["status"] = "RESEARCHING"
    elif event == "SUBMIT_DRAFT":
        if status != "RESEARCHING":
            raise_err(ERR_INVALID_STATE, "SUBMIT_DRAFT requires status RESEARCHING")
        if initiative["pattern_case_count"] < POLICY_PATTERN_THRESHOLD:
            raise_err(ERR_INSUFFICIENT_PATTERN_EVIDENCE,
                      "SUBMIT_DRAFT requires pattern_case_count >= %d"
                      % POLICY_PATTERN_THRESHOLD)
        initiative["status"] = "DRAFTED"
    elif event == "ADOPT":
        if status != "DRAFTED":
            raise_err(ERR_INVALID_STATE, "ADOPT requires status DRAFTED")
        initiative["status"] = "ADOPTED"
    elif event == "STALL":
        if status not in ("RESEARCHING", "DRAFTED"):
            raise_err(ERR_INVALID_STATE,
                      "STALL requires status RESEARCHING or DRAFTED")
        initiative["status"] = "STALLED"
    else:  # RESUME
        if status != "STALLED":
            raise_err(ERR_INVALID_STATE, "RESUME requires status STALLED")
        initiative["status"] = "RESEARCHING"
    touch(initiative)
    return ok(initiative)

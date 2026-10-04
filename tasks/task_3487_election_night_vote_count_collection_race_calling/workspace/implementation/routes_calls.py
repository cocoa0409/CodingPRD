"""Race calls: proposal by the DecisionAnalyst, PUBLISH/RETRACT by the
DecisionDeskChief (PRD §3.6). Certainty is evaluated only at publish."""
from flask import Blueprint, request

from auth import require_roles, body
from clock import now as clock_now
from envelope import ok_object, paginate
from errors import raise_err
from loaders import (
    get_contest, get_call, get_event, require_posture, versioned_record, touch,
)
from serializers import call_json
from services_rules import certainty_passes
from services_delivery import fanout_call, compensate_call
from store import db
from util import is_int

bp = Blueprint("calls", __name__)

CALL_READ_ROLES = (
    "ElectionOpsAdmin", "TabulationClerk", "DecisionAnalyst",
    "DecisionDeskChief", "RecountOfficer",
)
CALL_STATUSES = ("PROPOSED", "PUBLISHED", "RETRACTED")


@bp.post("/contests/<rid>/calls")
def propose_call(rid):
    uid, _ = require_roles("DecisionAnalyst")
    contest = get_contest(rid)
    event = get_event(contest["event_id"])
    require_posture(event, "TABULATION")  # priority 5
    data = body()
    # Priority 7: OCC precedes the membership problem (PRD §3.6).
    ev = data.get("expected_contest_version")
    if ev is None or not is_int(ev):
        raise_err("ERR_INVALID_REQUEST", "expected_contest_version is required")
    if ev != contest["version"]:
        raise_err(
            "ERR_STALE_VERSION",
            "expected_contest_version does not match the contest version",
        )
    # Priority 11: winner membership (certainty is NOT evaluated at proposal).
    winner = data.get("winner_candidate_id")
    if winner is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: winner_candidate_id")
    member = any(
        c["contest_id"] == contest["id"] and c["id"] == winner
        for c in db["candidates"].values()
    )
    if not member:
        raise_err(
            "ERR_CANDIDATE_NOT_IN_CONTEST",
            "winner_candidate_id does not belong to the contest",
        )
    rec = versioned_record()
    rec.update({
        "contest_id": contest["id"],
        "winner_candidate_id": winner,
        "proposed_by": uid,
        "published_by": None,
        "status": "PROPOSED",
        "published_at": None,
        "retract_reason": None,
    })
    db["calls"][rec["id"]] = rec
    touch(contest)  # proposal advances Contest.version by 1
    return ok_object(call_json(rec), 201)


@bp.get("/contests/<rid>/calls")
def list_calls(rid):
    require_roles(*CALL_READ_ROLES)
    contest = get_contest(rid)
    rows = [c for c in db["calls"].values() if c["contest_id"] == contest["id"]]
    status = request.args.get("status")
    if status is not None:
        if status not in CALL_STATUSES:
            raise_err("ERR_INVALID_REQUEST", "status filter out of range")
        rows = [c for c in rows if c["status"] == status]
    return paginate(rows, call_json)


def retract_published(contest, call, reason):
    """Shared PUBLISHED -> RETRACTED path for the desk action and the recount
    cascade (PRD §3.6/§3.7): contest UNCALLED, version +1, delivery
    compensation."""
    call["status"] = "RETRACTED"
    call["retract_reason"] = reason
    touch(call)
    contest["call_status"] = "UNCALLED"
    contest["called_candidate_id"] = None
    touch(contest)
    compensate_call(contest)


@bp.post("/calls/<rid>/decisions")
def call_decision(rid):
    uid, _ = require_roles("DecisionDeskChief")
    call = get_call(rid)
    contest = db["contests"][call["contest_id"]]
    event = get_event(contest["event_id"])
    data = body()
    action = data.get("action")
    if action not in ("PUBLISH", "RETRACT"):
        raise_err("ERR_INVALID_REQUEST", "action must be PUBLISH or RETRACT")

    if action == "PUBLISH":
        require_posture(event, "TABULATION")  # priority 5
        # Priority 6 sub-order (PRD §2.9/§3.6): the two specific guards ahead
        # of the generic from-state violation.
        if any(
            case["contest_id"] == contest["id"] and case["status"] == "ACTIVE"
            for case in db["recounts"].values()
        ):
            raise_err(
                "ERR_RECOUNT_ACTIVE_BLOCKS_CALL",
                "A recount case of the contest is ACTIVE",
            )
        if contest["call_status"] == "CALLED":
            raise_err("ERR_CALL_ALREADY_PUBLISHED", "Contest already has a published call")
        if call["status"] != "PROPOSED":
            raise_err("ERR_INVALID_STATE", "PUBLISH requires a PROPOSED call")
        if contest["tabulation_status"] not in ("REPORTING", "COMPLETE"):
            raise_err(
                "ERR_INVALID_STATE",
                "PUBLISH requires tabulation_status REPORTING or COMPLETE",
            )
        # Priority 8: segregation of duties.
        if uid == call["proposed_by"]:
            raise_err(
                "ERR_SEGREGATION_OF_DUTIES",
                "The proposer may never publish their own call",
            )
        # Priority 9: the certainty standard, evaluated only now.
        if not certainty_passes(contest, call["winner_candidate_id"]):
            raise_err(
                "ERR_CERTAINTY_NOT_MET",
                "A trailing candidate could still catch up on the outstanding vote",
            )
        call["status"] = "PUBLISHED"
        call["published_at"] = clock_now()
        call["published_by"] = uid
        touch(call)
        contest["call_status"] = "CALLED"
        contest["called_candidate_id"] = call["winner_candidate_id"]
        touch(contest)
        fanout_call(contest)
    else:  # RETRACT
        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise_err("ERR_INVALID_REQUEST", "reason must be a string")
        if call["status"] == "PROPOSED":
            # Nothing was published: record the reason, no delivery effects,
            # no contest version advance (PRD §2.7).
            call["status"] = "RETRACTED"
            call["retract_reason"] = reason
            touch(call)
        elif call["status"] == "PUBLISHED":
            retract_published(contest, call, reason)
        else:
            raise_err("ERR_INVALID_STATE", "RETRACT requires a PROPOSED or PUBLISHED call")
    return ok_object(call_json(call))

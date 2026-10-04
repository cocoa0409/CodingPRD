"""Recount cases: filing, ACTIVATE (drives the CERTIFICATION -> TABULATION
posture reopen), DISMISS, RESOLVE with the OVERTURNED cascade (PRD §3.7)."""
from flask import Blueprint, request

from auth import require_roles, body
from envelope import ok_object, paginate
from errors import raise_err
from loaders import (
    get_contest, get_recount, get_event, require_posture, versioned_record, touch,
)
from serializers import recount_json
from services_rules import RECOUNT_MARGIN_THRESHOLD
from routes_calls import retract_published
from store import db

bp = Blueprint("recounts", __name__)

RECOUNT_READ_ROLES = (
    "ElectionOpsAdmin", "TabulationClerk", "DecisionAnalyst",
    "DecisionDeskChief", "RecountOfficer",
)
RECOUNT_STATUSES = ("FILED", "ACTIVE", "DISMISSED", "RESOLVED_CONFIRMED", "RESOLVED_OVERTURNED")


@bp.post("/contests/<rid>/recount-cases")
def file_recount(rid):
    require_roles("RecountOfficer")
    contest = get_contest(rid)
    event = get_event(contest["event_id"])
    require_posture(event, "TABULATION", "CERTIFICATION")
    if contest["tabulation_status"] != "COMPLETE":
        raise_err("ERR_INVALID_STATE", "Recount filing requires tabulation COMPLETE")
    # Threshold is inclusive: exactly 0.005 is fileable.
    if contest["margin_pct"] > RECOUNT_MARGIN_THRESHOLD:
        raise_err(
            "ERR_RECOUNT_MARGIN_EXCEEDED",
            "margin_pct exceeds the 0.005 recount threshold",
        )
    rec = versioned_record()
    rec.update({
        "contest_id": contest["id"],
        "status": "FILED",
        "filed_margin_pct": contest["margin_pct"],  # snapshot at filing time
        "resolution_note": None,
    })
    db["recounts"][rec["id"]] = rec
    return ok_object(recount_json(rec), 201)


@bp.get("/contests/<rid>/recount-cases")
def list_recounts(rid):
    require_roles(*RECOUNT_READ_ROLES)
    contest = get_contest(rid)
    rows = [c for c in db["recounts"].values() if c["contest_id"] == contest["id"]]
    return paginate(rows, recount_json)


def _reopen_for_active_recounts(event):
    """CERTIFICATION -> TABULATION reopen: every contest holding an ACTIVE
    recount case reopens COMPLETE -> REPORTING (PRD §2.5/§3.7)."""
    event["posture"] = "TABULATION"
    touch(event)
    active_contest_ids = {
        case["contest_id"] for case in db["recounts"].values()
        if case["status"] == "ACTIVE"
    }
    for cid in active_contest_ids:
        contest = db["contests"][cid]
        if contest["event_id"] == event["id"] and contest["tabulation_status"] == "COMPLETE":
            contest["tabulation_status"] = "REPORTING"


@bp.post("/recount-cases/<rid>/decisions")
def recount_decision(rid):
    require_roles("RecountOfficer")
    case = get_recount(rid)
    contest = db["contests"][case["contest_id"]]
    event = get_event(contest["event_id"])
    data = body()
    action = data.get("action")
    if action not in ("ACTIVATE", "DISMISS", "RESOLVE"):
        raise_err("ERR_INVALID_REQUEST", "action must be ACTIVATE, DISMISS or RESOLVE")
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise_err("ERR_INVALID_REQUEST", "note must be a string")

    if action == "ACTIVATE":
        if case["status"] != "FILED":
            raise_err("ERR_INVALID_STATE", "ACTIVATE requires status FILED")
        case["status"] = "ACTIVE"
        touch(case)
        if event["posture"] == "CERTIFICATION":
            _reopen_for_active_recounts(event)
    elif action == "DISMISS":
        if case["status"] != "FILED":
            raise_err("ERR_INVALID_STATE", "DISMISS requires status FILED")
        # The dismissal note is accepted but resolution_note stays null.
        case["status"] = "DISMISSED"
        touch(case)
    else:  # RESOLVE
        if case["status"] != "ACTIVE":
            raise_err("ERR_INVALID_STATE", "RESOLVE requires status ACTIVE")
        outcome = data.get("outcome")
        if outcome not in ("CONFIRMED", "OVERTURNED"):
            raise_err("ERR_INVALID_REQUEST", "outcome must be CONFIRMED or OVERTURNED")
        case["resolution_note"] = note
        if outcome == "CONFIRMED":
            case["status"] = "RESOLVED_CONFIRMED"
            touch(case)
        else:
            case["status"] = "RESOLVED_OVERTURNED"
            touch(case)
            # Three-hop cascade: retract the contest's published call (fixed
            # reason), flip the contest back to UNCALLED, compensate CALL
            # deliveries with CALL_CREDITs.
            published = next(
                (c for c in db["calls"].values()
                 if c["contest_id"] == contest["id"] and c["status"] == "PUBLISHED"),
                None,
            )
            if published is not None:
                retract_published(contest, published, "RECOUNT_OVERTURNED")
    return ok_object(recount_json(case))

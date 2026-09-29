"""Stakeholder interviews: scheduling with facilitator buffers, completion and cancellation."""

from datetime import timedelta

from flask import Blueprint

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, fail, filter_eq, fmt_instant,
                  new_record, now_iso, ok, ok_list, paginate, parse_instant,
                  public, sorted_asc, touch, v_concern_ratings, v_enum, v_instant,
                  v_int, v_str)

bp = Blueprint("interviews", __name__)

BUFFER = timedelta(minutes=K.FACILITATOR_BUFFER_MINUTES)
OCCUPYING = ("SCHEDULED", "COMPLETED")


def _dt(session, field):
    return parse_instant(session[field])


@bp.post("/stakeholder-interviews")
def create_interview():
    authenticate([K.CBO])
    body = body_or_empty()
    cycle_id = v_str(body, "cycle_id", 1, None)
    facilitator_party_id = v_str(body, "facilitator_party_id", 1, None)
    organization_name = v_str(body, "organization_name", 1, 120)
    sector = v_enum(body, "sector", K.SECTORS)
    starts_at = v_instant(body, "starts_at")
    ends_at = v_instant(body, "ends_at")
    if not ends_at > starts_at:
        fail("ERR_VALIDATION", "'ends_at' must be strictly later than 'starts_at'.")
    if (ends_at - starts_at) > timedelta(minutes=K.MAX_SESSION_MINUTES):
        fail("ERR_VALIDATION", "A session may last at most %d minutes." % K.MAX_SESSION_MINUTES)

    cycle = D.cycle_or_404(cycle_id)
    party = D.party_or_404(facilitator_party_id)
    if party["party_type"] != "INTERNAL":
        fail("ERR_PARTY_TYPE_MISMATCH")

    D.gate_child_write(cycle, restricted=True)
    if cycle["status"] != "INPUT_GATHERING":
        fail("ERR_INPUT_WINDOW_CLOSED")

    for other in db.interviews.values():
        if other["facilitator_party_id"] != party["id"]:
            continue
        if other["status"] not in OCCUPYING:
            continue
        other_start = _dt(other, "starts_at")
        other_end = _dt(other, "ends_at")
        if starts_at < other_end + BUFFER and other_start < ends_at + BUFFER:
            fail("ERR_FACILITATOR_WINDOW_CONFLICT")

    for other in db.interviews.values():
        if (other["cycle_id"] == cycle["id"]
                and other["organization_name"] == organization_name
                and other["status"] in OCCUPYING):
            fail("ERR_DUPLICATE_ORGANIZATION")

    rec = new_record()
    rec.update({
        "cycle_id": cycle["id"],
        "facilitator_party_id": party["id"],
        "organization_name": organization_name,
        "sector": sector,
        "starts_at": fmt_instant(starts_at),
        "ends_at": fmt_instant(ends_at),
        "status": "SCHEDULED",
        "concern_ratings": None,
        "attendee_count": None,
        "completed_at": None,
        "cancel_reason": None,
    })
    db.interviews[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/stakeholder-interviews")
def list_interviews():
    authenticate([K.CBO, K.BC, K.CO])
    rows = list(db.interviews.values())
    rows = filter_eq(rows, "cycle_id")
    rows = filter_eq(rows, "facilitator_party_id")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/stakeholder-interviews/<interview_id>")
def get_interview(interview_id):
    authenticate([K.CBO, K.BC, K.CO])
    return ok(public(D.interview_or_404(interview_id)))


@bp.post("/stakeholder-interviews/<interview_id>/complete")
def complete_interview(interview_id):
    authenticate([K.CBO])
    session = D.interview_or_404(interview_id)
    body = body_or_empty()
    ratings = v_concern_ratings(body, "concern_ratings")
    attendee_count = v_int(body, "attendee_count", 1)

    cycle = db.cycles.get(session["cycle_id"])
    D.gate_child_write(cycle, restricted=True)
    if session["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    if cycle is None or cycle["status"] not in ("INPUT_GATHERING", "PRIORITIZATION"):
        fail("ERR_INVALID_STATE")

    session["concern_ratings"] = ratings
    session["attendee_count"] = attendee_count
    session["status"] = "COMPLETED"
    session["completed_at"] = now_iso()
    touch(session)

    # Late community input makes already-scored candidates stale.
    for cand in sorted(db.candidates.values(), key=lambda c: c["_seq"]):
        if cand["cycle_id"] != cycle["id"] or cand["status"] != "SCORED":
            continue
        indicator = db.indicators.get(cand["indicator_id"])
        if indicator is None or indicator["domain"] not in ratings:
            continue
        if not cand["concern_input_dirty"]:
            cand["concern_input_dirty"] = True
            touch(cand)

    D.sync_cycle(cycle)
    return ok(public(session))


@bp.post("/stakeholder-interviews/<interview_id>/cancel")
def cancel_interview(interview_id):
    authenticate([K.CBO])
    session = D.interview_or_404(interview_id)
    body = body_or_empty()
    reason = v_str(body, "reason", 1, None)

    cycle = db.cycles.get(session["cycle_id"])
    D.gate_child_write(cycle, restricted=True)
    if session["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    if cycle is None or cycle["status"] not in ("INPUT_GATHERING", "PRIORITIZATION"):
        fail("ERR_INVALID_STATE")

    session["cancel_reason"] = reason
    session["status"] = "CANCELLED"
    touch(session)
    D.sync_cycle(cycle)
    return ok(public(session))

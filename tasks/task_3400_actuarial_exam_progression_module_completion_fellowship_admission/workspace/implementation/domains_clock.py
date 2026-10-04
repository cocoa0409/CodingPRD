"""POST /actuarial/_clock/set_current_utc — logical clock + ops-run sweep.

Each window advances directly to its furthest due status as ONE mutation
(version +1 per window per sweep), marking REGISTERED registrations SAT when it
reaches SCORING. Sessions past ends_at become HELD; SUSPENDED candidates whose
suspended_until has been reached (>= boundary) return to ACTIVE. A set that
changes nothing performs no mutations (PRD §2.4).
"""

from flask import Blueprint

from auth import require
from errors import bad_request
from helpers import body, ok_object, req_str
from store import db, parse_dt, fmt_clock, touch

bp = Blueprint("clock", __name__)

# (from_status, threshold_field, to_status); thresholds use >= semantics.
_WINDOW_STEPS = [
    ("SCHEDULED", "registration_opens_at", "REGISTRATION_OPEN"),
    ("REGISTRATION_OPEN", "registration_deadline", "REGISTRATION_CLOSED"),
    ("REGISTRATION_CLOSED", "testing_starts_at", "TESTING"),
    ("TESTING", "testing_ends_at", "SCORING"),
]


def _sweep(counters):
    now = db.clock
    for window in sorted(db.exam_windows.values(), key=lambda w: w["_seq"]):
        if window["status"] in ("CANCELLED", "RESULTS_PUBLISHED"):
            continue
        original = window["status"]
        reached_scoring = False
        while True:
            nxt = None
            for frm, field, to in _WINDOW_STEPS:
                if window["status"] == frm and now >= window[field]:
                    nxt = to
                    break
            if nxt is None:
                break
            if nxt == "SCORING":
                reached_scoring = True
            window["status"] = nxt
        if window["status"] != original:
            if reached_scoring:
                for reg in sorted((r for r in db.exam_registrations.values()
                                   if r["exam_window_id"] == window["id"]
                                   and r["logistics_status"] == "REGISTERED"),
                                  key=lambda r: r["_seq"]):
                    reg["logistics_status"] = "SAT"
                    reg["sat_at"] = now
                    touch(reg)
                    counters["registrations_marked_sat"] += 1
            touch(window)
            counters["windows_advanced"] += 1
    for session in sorted(db.course_sessions.values(), key=lambda s: s["_seq"]):
        if session["status"] == "SCHEDULED" and now >= session["ends_at"]:
            session["status"] = "HELD"
            touch(session)
            counters["sessions_held"] += 1
    for cand in sorted(db.candidates.values(), key=lambda c: c["_seq"]):
        if (cand["status"] == "SUSPENDED"
                and cand["suspended_until"] is not None
                and now >= cand["suspended_until"]):
            cand["status"] = "ACTIVE"
            cand["suspended_until"] = None
            touch(cand)
            counters["suspensions_lifted"] += 1


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require("Registrar")
    b = body()
    raw = req_str(b, "to_iso8601")
    try:
        target = parse_dt(raw)
    except (ValueError, OverflowError):
        bad_request("to_iso8601 must be a valid ISO 8601 timestamp")
    if target < db.clock:
        bad_request("the logical clock is monotonic; cannot move it backwards")
    counters = {
        "windows_advanced": 0,
        "registrations_marked_sat": 0,
        "sessions_held": 0,
        "suspensions_lifted": 0,
    }
    # PRD §2.4: EACH clock-set call runs the operations sweep, even one that
    # sets the clock to the value it already reads (only a backwards set is
    # rejected). A sweep that finds nothing due performs no mutations, so a
    # "changes nothing" call still reports all-zero counters.
    if target > db.clock:
        db.clock = target
    _sweep(counters)
    out = {"current_utc": fmt_clock(db.clock)}
    out.update(counters)
    return ok_object(out, 200)

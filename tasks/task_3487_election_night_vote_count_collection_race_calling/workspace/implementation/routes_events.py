"""Clock endpoint + ElectionEvent CRUD + posture transitions (PRD §2.4, §2.5,
§3.1)."""
from flask import Blueprint

from auth import require_roles, body
from clock import CLOCK, now as clock_now
from envelope import ok_object
from errors import raise_err
from loaders import get_event, versioned_record, touch
from serializers import event_json
from store import db
from util import parse_datetime, parse_date, is_int, nonblank, event_day_window, fmt_dt

bp = Blueprint("events", __name__)

EVENT_TYPES = ("GENERAL", "PRIMARY", "SPECIAL", "RUNOFF")
SELECTION_MODES = ("CAREER", "RECENT_FORM")
POSTURES = ("SETUP", "CANDIDATES_LOCKED", "LIVE", "TABULATION", "CERTIFICATION", "ARCHIVED")
EVENT_READ_ROLES = (
    "ElectionOpsAdmin", "CoveragePlanner", "StringerCoordinator",
    "TabulationClerk", "DecisionAnalyst", "DecisionDeskChief", "RecountOfficer",
)

# Declared next posture per current posture. CERTIFICATION -> TABULATION is
# system-only (recount activation) and is rejected at this endpoint.
NEXT_POSTURE = {
    "SETUP": "CANDIDATES_LOCKED",
    "CANDIDATES_LOCKED": "LIVE",
    "LIVE": "TABULATION",
    "TABULATION": "CERTIFICATION",
    "CERTIFICATION": "ARCHIVED",
}


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("ElectionOpsAdmin")
    data = body()
    raw = data.get("current_utc")
    dt = parse_datetime(raw)
    if dt is None:
        raise_err("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 UTC instant")
    CLOCK.set(dt)
    return ok_object({"current_utc": fmt_dt(CLOCK.now())})


@bp.post("/election-events")
def create_event():
    require_roles("ElectionOpsAdmin")
    data = body()
    for f in ("event_name", "event_date", "event_type", "total_stringer_hour_budget"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not nonblank(data["event_name"]):
        raise_err("ERR_INVALID_REQUEST", "event_name must be a non-blank string")
    if parse_date(data["event_date"]) is None:
        raise_err("ERR_INVALID_REQUEST", "event_date must be an ISO date YYYY-MM-DD")
    if data["event_type"] not in EVENT_TYPES:
        raise_err("ERR_INVALID_REQUEST", "event_type out of range")
    if not is_int(data["total_stringer_hour_budget"]) or data["total_stringer_hour_budget"] < 1:
        raise_err("ERR_INVALID_REQUEST", "total_stringer_hour_budget must be an integer >= 1")
    mode = data.get("stringer_selection_mode", "CAREER")
    if mode is None:
        mode = "CAREER"
    if mode not in SELECTION_MODES:
        raise_err("ERR_INVALID_REQUEST", "stringer_selection_mode out of range")

    rec = versioned_record()
    rec.update({
        "event_name": data["event_name"],
        "event_date": data["event_date"].strip(),
        "event_type": data["event_type"],
        "total_stringer_hour_budget": data["total_stringer_hour_budget"],
        "stringer_selection_mode": mode,
        "posture": "SETUP",
    })
    db["events"][rec["id"]] = rec
    return ok_object(event_json(rec), 201)


@bp.get("/election-events/<rid>")
def read_event(rid):
    require_roles(*EVENT_READ_ROLES)
    return ok_object(event_json(get_event(rid)))


@bp.post("/election-events/<rid>/posture-transitions")
def posture_transition(rid):
    require_roles("ElectionOpsAdmin")
    event = get_event(rid)
    data = body()
    target = data.get("target_posture")
    if target is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: target_posture")
    if target not in POSTURES:
        raise_err("ERR_INVALID_REQUEST", "target_posture out of range")
    declared_next = NEXT_POSTURE.get(event["posture"])
    if target != declared_next:
        # Covers skipping ahead, stepping backward, the terminal ARCHIVED
        # state, and the system-only CERTIFICATION -> TABULATION reopen.
        raise_err(
            "ERR_INVALID_STATE",
            f"Posture {event['posture']} does not admit target {target}",
        )
    _check_preconditions(event, target)
    event["posture"] = target
    touch(event)
    return ok_object(event_json(event))


def _check_preconditions(event, target):
    """PRD §2.5 transition preconditions; failures are ERR_INVALID_STATE."""
    eid = event["id"]
    if target == "CANDIDATES_LOCKED":
        contests = [c for c in db["contests"].values() if c["event_id"] == eid]
        if not contests:
            raise_err("ERR_INVALID_STATE", "Candidate lock requires at least one contest")
        for c in contests:
            n_cand = sum(1 for x in db["candidates"].values() if x["contest_id"] == c["id"])
            n_link = sum(1 for x in db["links"].values() if x["contest_id"] == c["id"])
            if n_cand < 2 or n_link < 1:
                raise_err(
                    "ERR_INVALID_STATE",
                    "Every contest needs >= 2 candidates and >= 1 county link",
                )
        if event["event_type"] in ("PRIMARY", "SPECIAL"):
            for c in contests:
                covered = any(
                    d["contest_id"] == c["id"] and d["status"] in ("APPROVED", "FUNDED")
                    for d in db["coverages"].values()
                )
                if not covered:
                    raise_err(
                        "ERR_INVALID_STATE",
                        "PRIMARY/SPECIAL events require an APPROVED or FUNDED "
                        "coverage decision per contest",
                    )
    elif target == "LIVE":
        start, end = event_day_window(event["event_date"])
        if not (start <= clock_now() < end):
            raise_err("ERR_INVALID_STATE", "Logical clock is not within election day")
    elif target == "TABULATION":
        has_report = any(
            db["contests"][r["contest_id"]]["event_id"] == eid
            and r["status"] in ("RECEIVED", "FLAGGED", "ACCEPTED")
            for r in db["reports"].values()
        )
        if not has_report:
            raise_err(
                "ERR_INVALID_STATE",
                "TABULATION requires a vote report in RECEIVED, FLAGGED or ACCEPTED",
            )
    elif target == "CERTIFICATION":
        for c in db["contests"].values():
            if c["event_id"] == eid and c["tabulation_status"] != "COMPLETE":
                raise_err(
                    "ERR_INVALID_STATE",
                    "CERTIFICATION requires every contest COMPLETE",
                )
    elif target == "ARCHIVED":
        for case in db["recounts"].values():
            contest = db["contests"][case["contest_id"]]
            if contest["event_id"] == eid and case["status"] in ("FILED", "ACTIVE"):
                raise_err(
                    "ERR_INVALID_STATE",
                    "ARCHIVED is blocked while a recount case is FILED or ACTIVE",
                )

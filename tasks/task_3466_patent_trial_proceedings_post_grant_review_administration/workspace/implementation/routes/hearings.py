"""Oral hearings: request, scheduling (which closes the briefing record),
and three-way resolution (PRD 3.7)."""

from flask import Blueprint

from db import store, strip_internal, parse_iso
from calculations import hearing_conflicts
from errors import (
    raise_err, ERR_VALIDATION, ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_PHASE, ERR_INVALID_STATE, ERR_HEARING_ALREADY_PENDING,
    ERR_HEARING_PAST_FWD_DATE, ERR_INVALID_INTERVAL, ERR_HEARING_ROOM_CONFLICT,
)
from helpers import (
    require_roles, get_body, req_string, req_enum, opt_int, success_object,
    list_response, request_arg, ALL_ROLES,
)
from lookups import (
    get_proceeding, get_hearing, get_room, is_party_to_proceeding,
)

bp = Blueprint("hearings", __name__)

REQUEST_PHASES = (
    "INSTITUTED", "REPLY_WINDOW", "SUR_REPLY_WINDOW", "HEARING_PHASE",
    "REMANDED",
)
SCHEDULE_PHASES = ("REPLY_WINDOW", "SUR_REPLY_WINDOW", "HEARING_PHASE")
HEARING_OUTCOMES = ("HELD", "WAIVED", "CONTINUED")


@bp.post("/ptab/proceedings/<proceedingId>/oral-hearings")
def request_hearing(proceedingId):
    user_id, _ = require_roles("Petitioner", "PatentOwner")
    proceeding = get_proceeding(proceedingId)
    if not is_party_to_proceeding(user_id, proceeding):
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "only a party to the proceeding may request oral argument")
    body = get_body()
    argument_minutes = 60
    if "argument_minutes" in body and body.get("argument_minutes") is not None:
        argument_minutes = opt_int(body, "argument_minutes")

    if proceeding["phase"] not in REQUEST_PHASES:
        raise_err(ERR_INVALID_PHASE,
                  f"oral argument may not be requested in phase "
                  f"{proceeding['phase']}")
    for other in store.hearings.values():
        if (other["proceeding_id"] == proceeding["id"]
                and other["status"] in ("REQUESTED", "SCHEDULED")):
            raise_err(ERR_HEARING_ALREADY_PENDING,
                      "a hearing in REQUESTED or SCHEDULED status already "
                      "exists for this proceeding")

    hearing = store.new_common()
    hearing.update({
        "proceeding_id": proceeding["id"],
        "hearing_room_id": None,
        "start_at": None,
        "end_at": None,
        "argument_minutes": argument_minutes,
        "status": "REQUESTED",
        "_start_dt": None,
        "_end_dt": None,
    })
    store.hearings[hearing["id"]] = hearing
    return success_object(strip_internal(hearing), status=201)


@bp.get("/ptab/oral-hearings")
def list_hearings():
    require_roles(*ALL_ROLES)
    proceeding_id = request_arg("proceeding_id")
    hearing_room_id = request_arg("hearing_room_id")
    status = request_arg("status")
    items = store.hearings.values()
    if proceeding_id is not None:
        items = [h for h in items if h["proceeding_id"] == proceeding_id]
    if hearing_room_id is not None:
        items = [h for h in items if h["hearing_room_id"] == hearing_room_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    return list_response(list(items))


@bp.get("/ptab/oral-hearings/<hearingId>")
def get_hearing_route(hearingId):
    require_roles(*ALL_ROLES)
    return success_object(strip_internal(get_hearing(hearingId)))


@bp.patch("/ptab/oral-hearings/<hearingId>")
def schedule_hearing(hearingId):
    require_roles("BoardPanel")
    hearing = get_hearing(hearingId)
    body = get_body()

    # Body-reference existence (priority 3): the named room.
    raw_room_id = body.get("hearing_room_id")
    room = None
    if isinstance(raw_room_id, str):
        room = get_room(raw_room_id)

    # Schema (priority 5).
    hearing_room_id = req_string(body, "hearing_room_id")
    start_at = req_string(body, "start_at")
    end_at = req_string(body, "end_at")
    if room is None:
        raise_err(ERR_VALIDATION, "hearing_room_id must be a string")
    try:
        start_dt = parse_iso(start_at)
    except (ValueError, TypeError):
        raise_err(ERR_VALIDATION, "start_at must be a valid ISO 8601 datetime")
    try:
        end_dt = parse_iso(end_at)
    except (ValueError, TypeError):
        raise_err(ERR_VALIDATION, "end_at must be a valid ISO 8601 datetime")

    # State (priority 7).
    if hearing["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE,
                  "only a REQUESTED hearing may be scheduled")
    proceeding = store.proceedings.get(hearing["proceeding_id"])
    if proceeding["phase"] not in SCHEDULE_PHASES:
        raise_err(ERR_INVALID_PHASE,
                  f"a hearing may not be scheduled while the proceeding is "
                  f"in phase {proceeding['phase']}")

    # Statutory clock (priority 8): the hearing must start on or before the
    # final-decision deadline.
    if start_dt > proceeding["_fwd_dt"]:
        raise_err(ERR_HEARING_PAST_FWD_DATE,
                  "start_at is after the proceeding's fwd_due_date")

    # Domain (priority 9): interval validity, then buffered room conflict.
    if not end_dt > start_dt:
        raise_err(ERR_INVALID_INTERVAL, "end_at must be strictly after start_at")
    if hearing_conflicts(room["id"], start_dt, end_dt,
                         exclude_hearing_id=hearing["id"]):
        raise_err(ERR_HEARING_ROOM_CONFLICT,
                  "the requested interval intersects another scheduled "
                  "hearing's buffered interval in this room")

    hearing["hearing_room_id"] = room["id"]
    hearing["start_at"] = start_at
    hearing["end_at"] = end_at
    hearing["_start_dt"] = start_dt
    hearing["_end_dt"] = end_dt
    hearing["status"] = "SCHEDULED"
    store.touch(hearing)
    # Scheduling closes the briefing record.
    if proceeding["phase"] != "HEARING_PHASE":
        proceeding["phase"] = "HEARING_PHASE"
        store.touch(proceeding)
    return success_object(strip_internal(hearing), status=200)


@bp.post("/ptab/oral-hearings/<hearingId>/resolve")
def resolve_hearing(hearingId):
    user_id, role = require_roles("BoardPanel", "Petitioner", "PatentOwner")
    body = get_body()
    outcome = body.get("outcome")
    # Per-outcome role split (priority 2): held/continued are panel-only;
    # waiver belongs to a party.
    if outcome in ("HELD", "CONTINUED") and role != "BoardPanel":
        raise_err(ERR_FORBIDDEN_ROLE,
                  f"only BoardPanel may resolve a hearing {outcome}")
    if outcome == "WAIVED" and role not in ("Petitioner", "PatentOwner"):
        raise_err(ERR_FORBIDDEN_ROLE,
                  "only a party may waive a hearing")

    hearing = get_hearing(hearingId)
    proceeding = store.proceedings.get(hearing["proceeding_id"])
    if outcome == "WAIVED" and not is_party_to_proceeding(user_id, proceeding):
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "only a party to the proceeding may waive its hearing")

    outcome = req_enum(body, "outcome", HEARING_OUTCOMES)

    if hearing["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE,
                  "only a SCHEDULED hearing may be resolved")

    if outcome in ("HELD", "WAIVED"):
        hearing["status"] = outcome
        store.touch(hearing)
        proceeding["phase"] = "DECISION_PHASE"
        store.touch(proceeding)
    else:
        # CONTINUED: the booking is released and the hearing returns to
        # REQUESTED; the proceeding's phase is left unchanged.
        hearing["status"] = "REQUESTED"
        hearing["hearing_room_id"] = None
        hearing["start_at"] = None
        hearing["end_at"] = None
        hearing["_start_dt"] = None
        hearing["_end_dt"] = None
        store.touch(hearing)
    return success_object(strip_internal(hearing), status=200)

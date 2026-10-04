# routes/hearings.py — hearing scheduling (full 11-tier pipeline + OCC),
# completion, no-show recording, and per-hearing notice listing.
import uuid
from datetime import timedelta

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_hearing, serialize_notice
from constants import (
    ROLE_COURT_ADMINISTRATOR, ROLE_IMMIGRATION_JUDGE,
    CASE_CALENDAR, CASE_MERITS, CASE_IN_ABSENTIA,
    CASE_COMPLETED, CUSTODY_DETAINED,
    HEARING_MASTER, HEARING_MERITS, HEARING_TYPES, HEARING_SCHEDULED,
    HEARING_COMPLETED, HEARING_NO_SHOW,
    NOTICE_SERVED, OUTCOME_IN_ABSENTIA, DEC_ISSUED, REQ_PENDING,
    DETAINED_MASTER_HEARING_DAYS, DETAINED_MERITS_HEARING_DAYS,
    APPEAL_WINDOW_DAYS, REOPEN_WINDOW_DAYS,
)
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_enum, req_datetime, opt_bool,
                    req_version, fk, pagination_params, filter_param,
                    sorted_page)
from scheduling import (compute_duration_minutes, judge_has_conflict,
                        judge_day_minutes_ok, detained_capacity_ok,
                        select_interpreter, build_hearing)
from timeutil import parse_iso

bp = Blueprint("hearings", __name__)


def _load_hearing(hearing_id):
    h = db.hearings.get(hearing_id)
    if h is None:
        raise ApiError("ERR_HEARING_NOT_FOUND", "Hearing id does not exist")
    return h


@bp.post("/hearings")
def create_hearing():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # ---- tier 3: body FKs in declared input order (case_id) ----
    case_id = fk(body, "case_id")
    case = db.cases.get(case_id) if case_id is not None else None
    if case_id is not None and case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")

    # Raw (unvalidated) views used by early tiers; checks that depend on a
    # malformed value are skipped and left for tier 10 to report.
    hearing_type = fk(body, "hearing_type")
    start = parse_iso(body.get("scheduled_start"))

    if case is not None:
        # ---- tier 5: terminality, then the case's own phase, then the
        # type-stage gate (PRD §2.6 tier-5 intra-order) ----
        if case["status"] == CASE_COMPLETED:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                           "Case has reached COMPLETED")
        if case["status"] not in (CASE_CALENDAR, CASE_MERITS):
            raise ApiError("ERR_CASE_STATE_FORBIDS_HEARING",
                           "Hearing creation requires CALENDAR or MERITS")
        if hearing_type in HEARING_TYPES:
            if hearing_type == HEARING_MASTER \
                    and case["status"] != CASE_CALENDAR:
                raise ApiError(
                    "ERR_HEARING_TYPE_STAGE_MISMATCH",
                    "MASTER_CALENDAR hearings are valid only while CALENDAR")
            if hearing_type == HEARING_MERITS and case["status"] != CASE_MERITS:
                raise ApiError(
                    "ERR_HEARING_TYPE_STAGE_MISMATCH",
                    "INDIVIDUAL_MERITS hearings are valid only while MERITS")
        # ---- tier 8: temporal rules, in PRD listing order ----
        if start is not None and start < db.get_clock():
            raise ApiError("ERR_HEARING_IN_PAST",
                           "scheduled_start is earlier than the current clock")
        if (case["custody_status"] == CUSTODY_DETAINED
                and hearing_type in HEARING_TYPES and start is not None):
            days = DETAINED_MASTER_HEARING_DAYS if hearing_type == HEARING_MASTER \
                else DETAINED_MERITS_HEARING_DAYS
            if start > case["filed_at"] + timedelta(days=days):
                raise ApiError(
                    "ERR_DETAINED_HEARING_PAST_EXPEDITED_DEADLINE",
                    "Detained %s hearing must start within %d days of filing "
                    "(inclusive)" % (hearing_type, days))
        # ---- tier 9: capacity / conflict, in PRD §2.6 listing order ----
        # These need a valid type and start; skip (defer to tier 10) otherwise.
        if hearing_type in HEARING_TYPES and start is not None:
            judge_id = case["assigned_judge_id"]
            duration = compute_duration_minutes(case, hearing_type)
            end = start + timedelta(minutes=duration)
            if judge_has_conflict(judge_id, start, end):
                raise ApiError("ERR_JUDGE_SCHEDULE_CONFLICT",
                               "Judge has a SCHEDULED hearing overlapping "
                               "[start, end)")
            if not judge_day_minutes_ok(judge_id, start.date(), duration):
                raise ApiError("ERR_JUDGE_DAILY_MINUTES_EXCEEDED",
                               "Judge's rounded daily minutes would exceed 120")
            if case["custody_status"] == CUSTODY_DETAINED:
                court = db.courts[case["court_id"]]
                if not detained_capacity_ok(court, start.date()):
                    raise ApiError(
                        "ERR_DETAINED_DAILY_CAPACITY_REACHED",
                        "Court's detained daily hearing capacity is reached "
                        "on that date")
                if body.get("is_remote") is not True:
                    raise ApiError(
                        "ERR_DETAINED_REQUIRES_REMOTE",
                        "Detained-case hearings require is_remote = true")
            if any(h for h in db.hearings.values()
                   if h["case_id"] == case["id"]
                   and h["status"] == HEARING_SCHEDULED):
                raise ApiError("ERR_CASE_HAS_SCHEDULED_HEARING",
                               "Case already holds a SCHEDULED hearing")

    # ---- tier 10: shape, then interpreter selection (semantic) ----
    case_id = req_str(body, "case_id")
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    hearing_type = req_enum(body, "hearing_type", HEARING_TYPES)
    start = req_datetime(body, "scheduled_start")
    is_remote = opt_bool(body, "is_remote", default=False)
    expected_version = req_version(body, "expected_case_version")
    interpreter = None
    if case["interpreter_required"]:
        end = start + timedelta(
            minutes=compute_duration_minutes(case, hearing_type))
        interpreter = select_interpreter(case, start, end)
    # ---- tier 11: OCC, immediately before commit ----
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION",
                       "expected_case_version does not equal the case's "
                       "current version")
    h = build_hearing(case, hearing_type, start, is_remote,
                      auto_created=False, supersedes_hearing_id=None,
                      interpreter=interpreter)
    db.touch(case)  # increments Case.version by 1
    return success(serialize_hearing(h), response_type="object", status=201)


@bp.get("/hearings")
def list_hearings():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.hearings.values())
    for name in ("case_id", "judge_id", "interpreter_id",
                 "supersedes_hearing_id", "status"):
        v = filter_param(name)
        if v is not None:
            records = [h for h in records if h.get(name) == v]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_hearing(h) for h in page], total, limit,
                         offset)


@bp.get("/hearings/<hearingId>")
def get_hearing(hearingId):
    get_auth()  # all roles
    return success(serialize_hearing(_load_hearing(hearingId)),
                   response_type="object", status=200)


@bp.post("/hearings/<hearingId>/complete")
def complete_hearing(hearingId):
    user_id, role = get_auth()
    require_role(role, (ROLE_IMMIGRATION_JUDGE,))
    # tier 3
    h = _load_hearing(hearingId)
    # tier 4: ownership binds to the hearing's judge
    if h["judge_id"] != user_id:
        raise ApiError("ERR_NOT_HEARING_JUDGE",
                       "X-User-ID must equal the hearing's judge_id")
    # tier 5
    if h["status"] != HEARING_SCHEDULED:
        raise ApiError("ERR_HEARING_NOT_SCHEDULED",
                       "Hearing is not SCHEDULED")
    # tier 8
    if db.get_clock() < h["scheduled_start"]:
        raise ApiError("ERR_HEARING_NOT_YET_DUE",
                       "Clock has not reached the hearing's scheduled_start")
    h["status"] = HEARING_COMPLETED
    db.touch(h)
    # master-calendar completion is the only path into the merits phase
    case = db.cases.get(h["case_id"])
    if case is not None and h["hearing_type"] == HEARING_MASTER \
            and case["status"] == CASE_CALENDAR:
        case["status"] = CASE_MERITS
        db.touch(case)  # increments Case.version by 1
    return success(serialize_hearing(h), response_type="object", status=200)


@bp.post("/hearings/<hearingId>/record-no-show")
def record_no_show(hearingId):
    user_id, role = get_auth()
    require_role(role, (ROLE_IMMIGRATION_JUDGE,))
    # tier 3
    h = _load_hearing(hearingId)
    # tier 4: ownership binds to the hearing's judge
    if h["judge_id"] != user_id:
        raise ApiError("ERR_NOT_HEARING_JUDGE",
                       "X-User-ID must equal the hearing's judge_id")
    # tier 5: terminality heads the tier (PRD §3.2 blanket rule: any mutation
    # against a COMPLETED case is rejected outright, whatever the operation)
    case = db.cases[h["case_id"]]
    if case["status"] == CASE_COMPLETED:
        raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                       "Case has reached COMPLETED and admits no further "
                       "mutation")
    if h["status"] != HEARING_SCHEDULED:
        raise ApiError("ERR_HEARING_NOT_SCHEDULED",
                       "Hearing is not SCHEDULED")
    # tier 7: due process — a notice must exist and be SERVED
    notice = next((n for n in db.notices.values() if n["hearing_id"] == h["id"]),
                  None)
    if notice is None:
        raise ApiError("ERR_NOTICE_NOT_SERVED",
                       "No HearingNotice has been recorded for the hearing")
    if notice["status"] != NOTICE_SERVED:
        raise ApiError(
            "ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA",
            "An in absentia order may not rest on a defective notice")
    # tier 8
    if db.get_clock() < h["scheduled_start"]:
        raise ApiError("ERR_HEARING_NOT_YET_DUE",
                       "Clock has not reached the hearing's scheduled_start")
    # tier 9
    if any(r for r in db.continuances.values()
           if r["hearing_id"] == h["id"] and r["status"] == REQ_PENDING):
        raise ApiError("ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW",
                       "A PENDING continuance targets the hearing")
    # ---- commit: the widest cascade in the system (PRD §3.5) ----
    clock = db.get_clock()
    h["status"] = HEARING_NO_SHOW
    db.touch(h)
    case = db.cases[h["case_id"]]
    case["status"] = CASE_IN_ABSENTIA  # assigned_judge_id retained
    db.touch(case)  # increments Case.version by 1
    decision = {
        "id": str(uuid.uuid4()),
        "case_id": case["id"],
        "judge_id": h["judge_id"],
        "outcome": OUTCOME_IN_ABSENTIA,
        "source_hearing_id": h["id"],
        "issued_at": clock,
        "appeal_deadline": clock + timedelta(days=APPEAL_WINDOW_DAYS),
        "reopen_deadline": clock + timedelta(days=REOPEN_WINDOW_DAYS),
        "status": DEC_ISSUED,
    }
    db.stamp_new(decision)
    db.stamp_common(decision)
    db.decisions[decision["id"]] = decision
    return success(serialize_hearing(h), response_type="object", status=200)


@bp.get("/hearings/<hearingId>/notices")
def list_hearing_notices(hearingId):
    get_auth()  # all roles
    limit, offset = pagination_params()
    _load_hearing(hearingId)  # tier 3: hearing must exist first (PRD §2.10)
    records = [n for n in db.notices.values() if n["hearing_id"] == hearingId]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_notice(n) for n in page], total, limit,
                         offset)

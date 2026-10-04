"""Examination: authorization, scheduling, scoring, rolling clock (PRD 3.4)."""
from flask import Blueprint, request

from auth import get_body, require_candidate_identity, require_roles
from dates import add_days, add_months, parse_date
from envelope import ok, paginate
from errors import fail
from serializers import ser_authorization, ser_division
from services import (ATTEMPT_LIMIT_COUNT, ATTEMPT_LIMIT_WINDOW_DAYS,
                      DIVISION_CODES, RETAKE_WAIT_DAYS, ROLLING_CLOCK_MONTHS,
                      all_divisions_passed, exam_day_conflict,
                      jurisdiction_by_code, recompute_eligibility)
from store import db, new_id, stamp_new, today, touch

bp = Blueprint("exam", __name__)


def _get_division_or_404(did):
    d = db["divisions"].get(did)
    if d is None:
        fail("ERR_NOT_FOUND", "exam division progress not found")
    return d


@bp.post("/candidates/<cid>/exam-authorizations")
def create_exam_authorization(cid):
    require_roles("BoardAdministrator")
    cand = db["candidates"].get(cid)
    if cand is None:
        fail("ERR_NOT_FOUND", "candidate not found")
    body = get_body()
    jc = body.get("jurisdiction_code")
    if jc is not None and jurisdiction_by_code(jc) is None:
        fail("ERR_JURISDICTION_UNKNOWN", "jurisdiction_code does not resolve")
    # Tier 4: authorization is only legal from NOT_AUTHORIZED.
    if cand["exam_status"] != "NOT_AUTHORIZED":
        fail("ERR_INVALID_STATE", "candidate is already authorized to test")
    if jc is None:
        fail("ERR_INVALID_REQUEST", "jurisdiction_code is required")
    auth = stamp_new({
        "id": new_id(),
        "candidate_id": cid,
        "jurisdiction_code": jc,
        "status": "ACTIVE",
    })
    db["authorizations"][auth["id"]] = auth
    # One progress row per division, all ELIGIBLE.
    for code in DIVISION_CODES:
        row = stamp_new({
            "id": new_id(),
            "candidate_id": cid,
            "authorization_id": auth["id"],
            "division_code": code,
            "status": "ELIGIBLE",
            "scheduled_date": None,
            "attempt_count": 0,
            "attempt_dates": [],
            "last_failed_at": None,
            "passed_at": None,
            "expires_at": None,
            "result": None,
            "scaled_score": None,
        })
        db["divisions"][row["id"]] = row
    cand["exam_status"] = "AUTHORIZED"
    recompute_eligibility(cand)
    touch(cand)
    return ok(ser_authorization(auth), 201)


@bp.get("/candidates/<cid>/exam-progress")
def list_exam_progress(cid):
    uid, role = require_roles("Candidate", "BoardAdministrator", "NcarbAdministrator")
    if role == "Candidate":
        require_candidate_identity(uid, cid)
    if cid not in db["candidates"]:
        fail("ERR_NOT_FOUND", "candidate not found")
    division_code = request.args.get("division_code")
    status = request.args.get("status")
    rows = [d for d in db["divisions"].values() if d["candidate_id"] == cid]
    if division_code is not None:
        rows = [d for d in rows if d["division_code"] == division_code]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    # Ordered by division_code ascending: CE, PA, PCM, PDD, PJM, PPD.
    return paginate([ser_division(d) for d in rows],
                    sort_key=lambda d: d["division_code"])


@bp.post("/exam-progress/<did>/schedule")
def schedule_division(did):
    uid, _ = require_roles("Candidate")
    row = _get_division_or_404(did)
    require_candidate_identity(uid, row["candidate_id"])
    # Tier 4: state legality (dedicated codes for PASSED / SCHEDULED).
    if row["status"] == "PASSED":
        fail("ERR_DIVISION_ALREADY_PASSED", "division is already PASSED")
    if row["status"] == "SCHEDULED":
        fail("ERR_DIVISION_ALREADY_SCHEDULED", "division is already SCHEDULED")
    # ELIGIBLE, FAILED, and EXPIRED may be scheduled.
    body = get_body()
    sd_raw = body.get("scheduled_date")
    try:
        sd = parse_date(sd_raw)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "scheduled_date must be an ISO date")
    # Tier 7 in PRD 2.6 order: retake wait, attempt window, date in past.
    if row["status"] == "FAILED":
        earliest = add_days(parse_date(row["last_failed_at"]), RETAKE_WAIT_DAYS)
        if sd < earliest:
            fail("ERR_RETAKE_WAIT_NOT_ELAPSED",
                 "retake requires scheduled_date >= last_failed_at + 60 days")
    cutoff = add_days(sd, -ATTEMPT_LIMIT_WINDOW_DAYS)
    recent = sum(1 for d in row["attempt_dates"] if parse_date(d) > cutoff)
    if recent >= ATTEMPT_LIMIT_COUNT:
        fail("ERR_ATTEMPT_LIMIT_EXCEEDED",
             "3 scored attempts within the preceding 365 days")
    if sd < today():
        fail("ERR_SCHEDULE_DATE_PAST", "scheduled_date is before the current date")
    # Tier 8: same-calendar-day exam conflict.
    if exam_day_conflict(row["candidate_id"], sd.isoformat(),
                         exclude_division_id=row["id"]):
        fail("ERR_EXAM_DAY_CONFLICT",
             "another sitting occupies that calendar day")
    row["status"] = "SCHEDULED"
    row["scheduled_date"] = sd.isoformat()
    touch(row)
    return ok(ser_division(row))


@bp.post("/exam-progress/<did>/report-score")
def report_score(did):
    require_roles("NcarbAdministrator")
    row = _get_division_or_404(did)
    if row["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "only a SCHEDULED division may be scored")
    if today() < parse_date(row["scheduled_date"]):
        fail("ERR_INVALID_STATE", "the sitting date has not yet arrived")
    body = get_body()
    result = body.get("result")
    if result not in ("PASS", "FAIL"):
        fail("ERR_INVALID_REQUEST", "result must be PASS or FAIL")
    scaled = body.get("scaled_score")
    if not isinstance(scaled, int) or isinstance(scaled, bool) \
            or scaled < 0 or scaled > 100:
        fail("ERR_INVALID_REQUEST", "scaled_score must be an integer 0..100")
    sitting = row["scheduled_date"]
    row["attempt_count"] += 1
    row["attempt_dates"].append(sitting)
    row["result"] = result
    row["scaled_score"] = scaled
    row["scheduled_date"] = None
    if result == "PASS":
        row["status"] = "PASSED"
        row["passed_at"] = sitting
        row["expires_at"] = add_months(parse_date(sitting),
                                       ROLLING_CLOCK_MONTHS).isoformat()
    else:
        row["status"] = "FAILED"
        row["last_failed_at"] = sitting
    touch(row)
    if result == "PASS":
        cand = db["candidates"].get(row["candidate_id"])
        if cand is not None:
            changed = False
            if cand["exam_status"] == "AUTHORIZED" \
                    and all_divisions_passed(row["candidate_id"]):
                cand["exam_status"] = "ALL_PASSED"
                changed = True
            if recompute_eligibility(cand):
                changed = True
            if changed:
                touch(cand)
    return ok(ser_division(row))

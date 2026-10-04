"""Supplemental examinations: registration and board-reported results (PRD 3.5)."""
from flask import Blueprint, request

from auth import get_body, require_candidate_identity, require_roles
from dates import add_days, parse_date
from envelope import ok, paginate
from errors import fail
from serializers import ser_supplemental
from services import (SUPPLEMENTAL_RETAKE_DAYS, exam_day_conflict,
                      jurisdiction_by_code, recompute_eligibility)
from store import db, new_id, stamp_new, today, touch

bp = Blueprint("supplemental", __name__)


@bp.post("/candidates/<cid>/supplemental-exams")
def create_supplemental(cid):
    uid, _ = require_roles("Candidate")
    require_candidate_identity(uid, cid)
    if cid not in db["candidates"]:
        fail("ERR_NOT_FOUND", "candidate not found")
    body = get_body()
    jc = body.get("jurisdiction_code")
    # Tier 3: jurisdiction resolution.
    juris = None
    if jc is not None:
        juris = jurisdiction_by_code(jc)
        if juris is None:
            fail("ERR_JURISDICTION_UNKNOWN", "jurisdiction_code does not resolve")
    # Tier 6: only boards that require a supplemental exam accept registrations.
    if juris is not None and not juris["requires_supplemental_exam"]:
        fail("ERR_SUPPLEMENTAL_NOT_REQUIRED",
             "jurisdiction does not require a supplemental exam")
    if jc is None:
        fail("ERR_INVALID_REQUEST", "jurisdiction_code is required")
    try:
        exam_date = parse_date(body.get("exam_date"))
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "exam_date must be an ISO date")
    # Tier 7 (PRD 2.6 order): date not in past, then the 90-day retake wait.
    if exam_date < today():
        fail("ERR_SCHEDULE_DATE_PAST", "exam_date is before the current date")
    prev_failed = [s for s in db["supplementals"].values()
                   if s["candidate_id"] == cid
                   and s["jurisdiction_code"] == jc
                   and s["status"] == "FAILED"]
    if prev_failed:
        last_failed = max(parse_date(s["exam_date"]) for s in prev_failed)
        if exam_date < add_days(last_failed, SUPPLEMENTAL_RETAKE_DAYS):
            fail("ERR_SUPPLEMENTAL_RETAKE_WAIT",
                 "retake requires exam_date >= previous FAILED exam_date + 90 days")
    # Tier 8: same-calendar-day conflict with SCHEDULED divisions / REGISTERED
    # supplemental exams of this candidate.
    if exam_day_conflict(cid, exam_date.isoformat()):
        fail("ERR_EXAM_DAY_CONFLICT", "another sitting occupies that calendar day")
    rec = stamp_new({
        "id": new_id(),
        "candidate_id": cid,
        "jurisdiction_code": jc,
        "exam_date": exam_date.isoformat(),
        "status": "REGISTERED",
        "result": None,
    })
    db["supplementals"][rec["id"]] = rec
    return ok(ser_supplemental(rec), 201)


@bp.get("/candidates/<cid>/supplemental-exams")
def list_supplementals(cid):
    uid, role = require_roles("Candidate", "BoardAdministrator", "NcarbAdministrator")
    if role == "Candidate":
        require_candidate_identity(uid, cid)
    if cid not in db["candidates"]:
        fail("ERR_NOT_FOUND", "candidate not found")
    status = request.args.get("status")
    rows = [s for s in db["supplementals"].values() if s["candidate_id"] == cid]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return paginate([ser_supplemental(s) for s in rows])


@bp.post("/supplemental-exams/<sid>/report-result")
def report_supplemental_result(sid):
    require_roles("BoardAdministrator")
    s = db["supplementals"].get(sid)
    if s is None:
        fail("ERR_NOT_FOUND", "supplemental exam not found")
    if s["status"] != "REGISTERED":
        fail("ERR_INVALID_STATE", "only a REGISTERED supplemental exam may be reported")
    if today() < parse_date(s["exam_date"]):
        fail("ERR_INVALID_STATE", "the exam date has not yet arrived")
    body = get_body()
    result = body.get("result")
    if result not in ("PASS", "FAIL"):
        fail("ERR_INVALID_REQUEST", "result must be PASS or FAIL")
    s["status"] = "PASSED" if result == "PASS" else "FAILED"
    s["result"] = result
    touch(s)
    if result == "PASS":
        cand = db["candidates"].get(s["candidate_id"])
        if cand is not None and recompute_eligibility(cand):
            touch(cand)
    return ok(ser_supplemental(s))

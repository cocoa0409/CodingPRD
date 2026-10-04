"""Experience reporting: credit tiering, verification, reassignment (PRD 3.3)."""
from flask import Blueprint, request

from auth import get_body, require_candidate_identity, require_roles
from dates import add_days, parse_date
from envelope import ok, paginate
from errors import fail
from serializers import ser_report
from services import (MAX_REPORT_HOURS, MIN_REPORT_HOURS, PRACTICE_AREAS,
                      REASSIGN_WINDOW_DAYS, credit_tier_for, credited_for,
                      experience_gate_met, period_has_overlap,
                      recompute_eligibility)
from store import db, new_id, now_iso, stamp_new, today, touch

bp = Blueprint("experience", __name__)

WORK_SETTINGS = ("ARCHITECTURAL_FIRM", "GOVERNMENT", "OTHER")


def _get_report_or_404(rid):
    r = db["reports"].get(rid)
    if r is None:
        fail("ERR_NOT_FOUND", "experience report not found")
    return r


@bp.post("/experience-reports")
def create_report():
    uid, _ = require_roles("Candidate")
    body = get_body()
    candidate_id = body.get("candidate_id")
    # Tier 2: Candidate callers act only on their own resources.
    if candidate_id is not None:
        require_candidate_identity(uid, candidate_id)
    # Tier 3: body references resolve.
    supervisor_id = body.get("supervisor_id")
    if candidate_id is not None and candidate_id not in db["candidates"]:
        fail("ERR_NOT_FOUND", "candidate_id does not resolve")
    if supervisor_id is not None and supervisor_id not in db["supervisors"]:
        fail("ERR_NOT_FOUND", "supervisor_id does not resolve")
    # Tier 8: required fields, enums, ranges (overlap/supervisor checks are
    # deliberately deferred to submission).
    if candidate_id is None:
        fail("ERR_INVALID_REQUEST", "candidate_id is required")
    if supervisor_id is None:
        fail("ERR_INVALID_REQUEST", "supervisor_id is required")
    practice_area = body.get("practice_area")
    if practice_area not in PRACTICE_AREAS:
        fail("ERR_INVALID_REQUEST", "practice_area is invalid")
    work_setting = body.get("work_setting", "ARCHITECTURAL_FIRM")
    if work_setting not in WORK_SETTINGS:
        fail("ERR_INVALID_REQUEST", "work_setting is invalid")
    hours = body.get("hours")
    if hours is None or isinstance(hours, bool) or not isinstance(hours, (int, float)):
        fail("ERR_INVALID_REQUEST", "hours is required")
    ws_raw = body.get("work_period_start")
    we_raw = body.get("work_period_end")
    try:
        ws = parse_date(ws_raw)
        we = parse_date(we_raw)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "work_period_start and work_period_end must be ISO dates")
    if we <= ws:
        fail("ERR_WORK_PERIOD_INVALID", "work_period_end must be after work_period_start")
    if hours < MIN_REPORT_HOURS or hours > MAX_REPORT_HOURS:
        fail("ERR_HOURS_OUT_OF_RANGE", "hours must be between 1 and 2000")
    rec = stamp_new({
        "id": new_id(),
        "candidate_id": candidate_id,
        "supervisor_id": supervisor_id,
        "practice_area": practice_area,
        "hours": hours,
        "work_period_start": ws.isoformat(),
        "work_period_end": we.isoformat(),
        "work_setting": work_setting,
        "status": "DRAFT",
        "submitted_at": None,
        "credit_pct": 0,
        "credited_hours": 0,
        "return_reason": None,
    })
    db["reports"][rec["id"]] = rec
    return ok(ser_report(rec), 201)


@bp.get("/experience-reports/<rid>")
def get_report(rid):
    uid, role = require_roles("Candidate", "Supervisor", "NcarbAdministrator")
    r = _get_report_or_404(rid)
    if role == "Candidate":
        require_candidate_identity(uid, r["candidate_id"])
    return ok(ser_report(r))


@bp.get("/experience-reports")
def list_reports():
    uid, role = require_roles("Candidate", "Supervisor", "NcarbAdministrator")
    candidate_id = request.args.get("candidate_id")
    supervisor_id = request.args.get("supervisor_id")
    status = request.args.get("status")
    practice_area = request.args.get("practice_area")
    if role == "Candidate":
        # Candidate callers act only on their own resources.
        if candidate_id is not None and candidate_id != uid:
            fail("ERR_UNAUTHORIZED", "candidates may list only their own reports")
        candidate_id = uid
    rows = list(db["reports"].values())
    if candidate_id is not None:
        rows = [r for r in rows if r["candidate_id"] == candidate_id]
    if supervisor_id is not None:
        rows = [r for r in rows if r["supervisor_id"] == supervisor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if practice_area is not None:
        rows = [r for r in rows if r["practice_area"] == practice_area]
    return paginate([ser_report(r) for r in rows])


@bp.post("/experience-reports/<rid>/submit")
def submit_report(rid):
    uid, _ = require_roles("Candidate")
    r = _get_report_or_404(rid)
    require_candidate_identity(uid, r["candidate_id"])
    # Tier 4: DRAFT or RETURNED only.
    if r["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_STATE", "only a DRAFT or RETURNED report may be submitted")
    # Tier 6: assigned supervisor exists and holds an ACTIVE license.
    sup = db["supervisors"].get(r["supervisor_id"])
    if sup is None or sup["license_status"] != "ACTIVE":
        fail("ERR_SUPERVISOR_NOT_ACTIVE", "assigned supervisor is not ACTIVE")
    # Tier 7: no older than sixty calendar months after the work period end.
    submit_date = today()
    we = parse_date(r["work_period_end"])
    tier = credit_tier_for(submit_date, we)
    if tier is None:
        fail("ERR_EXPERIENCE_TOO_OLD",
             "submitted more than 60 calendar months after work_period_end")
    # Tier 8: half-open work period must not overlap SUBMITTED/VERIFIED reports.
    ws = parse_date(r["work_period_start"])
    if period_has_overlap(r["candidate_id"], ws, we, exclude_id=r["id"]):
        fail("ERR_WORK_PERIOD_OVERLAP",
             "work period overlaps a SUBMITTED or VERIFIED report")
    r["status"] = "SUBMITTED"
    r["submitted_at"] = now_iso()
    r["credit_pct"] = tier  # locked tier: permanent once stamped
    r["return_reason"] = None
    touch(r)
    return ok(ser_report(r))


@bp.post("/experience-reports/<rid>/verify")
def verify_report(rid):
    uid, _ = require_roles("Supervisor")
    r = _get_report_or_404(rid)
    # Tier 4: SUBMITTED only.
    if r["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED report may be verified")
    # Tier 6 (per PRD 2.6 order): supervisor ACTIVE, then caller match.
    sup = db["supervisors"].get(r["supervisor_id"])
    if sup is None or sup["license_status"] != "ACTIVE":
        fail("ERR_SUPERVISOR_NOT_ACTIVE", "assigned supervisor is not ACTIVE")
    if uid != r["supervisor_id"]:
        fail("ERR_SUPERVISOR_MISMATCH", "caller is not the assigned supervisor")
    r["status"] = "VERIFIED"
    # Per-report round-half-up first; aggregation sums the rounded integers.
    r["credited_hours"] = credited_for(r["hours"], r["credit_pct"])
    touch(r)
    # Verify cascade link 1: experience_status progression.
    cand = db["candidates"].get(r["candidate_id"])
    if cand is not None:
        changed = False
        if cand["experience_status"] == "NOT_STARTED":
            cand["experience_status"] = "IN_PROGRESS"
            changed = True
        if cand["experience_status"] == "IN_PROGRESS" and experience_gate_met(cand):
            cand["experience_status"] = "COMPLETE"
            changed = True
        # Link 2: certificate_eligible recompute.
        if recompute_eligibility(cand):
            changed = True
        if changed:
            touch(cand)
    return ok(ser_report(r))


@bp.post("/experience-reports/<rid>/return")
def return_report(rid):
    uid, _ = require_roles("Supervisor")
    r = _get_report_or_404(rid)
    if r["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED report may be returned")
    if uid != r["supervisor_id"]:
        fail("ERR_SUPERVISOR_MISMATCH", "caller is not the assigned supervisor")
    body = get_body()
    reason = body.get("return_reason")
    if not isinstance(reason, str) or not reason.strip():
        fail("ERR_INVALID_REQUEST", "return_reason is required")
    r["status"] = "RETURNED"
    r["return_reason"] = reason
    touch(r)
    return ok(ser_report(r))


@bp.post("/experience-reports/<rid>/reassign")
def reassign_report(rid):
    uid, _ = require_roles("Candidate")
    r = _get_report_or_404(rid)
    require_candidate_identity(uid, r["candidate_id"])
    body = get_body()
    new_sup_id = body.get("new_supervisor_id")
    # Tier 3: new supervisor reference resolves.
    new_sup = None
    if new_sup_id is not None:
        new_sup = db["supervisors"].get(new_sup_id)
        if new_sup is None:
            fail("ERR_NOT_FOUND", "new_supervisor_id does not resolve")
    # Tier 4: SUBMITTED only.
    if r["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED report may be reassigned")
    if new_sup_id is None:
        fail("ERR_INVALID_REQUEST", "new_supervisor_id is required")
    # Tier 7: the 45-day reassignment window must be open, and the new
    # supervisor must differ from the current one and be ACTIVE.
    submitted_date = parse_date(r["submitted_at"][:10])
    if today() < add_days(submitted_date, REASSIGN_WINDOW_DAYS):
        fail("ERR_REASSIGN_WINDOW_NOT_OPEN",
             "reassignment window opens 45 days after submission")
    if new_sup_id == r["supervisor_id"] or new_sup["license_status"] != "ACTIVE":
        fail("ERR_REASSIGN_WINDOW_NOT_OPEN",
             "new supervisor must differ from the current one and be ACTIVE")
    # Locked tier survives the handoff: submitted_at and credit_pct preserved.
    r["supervisor_id"] = new_sup_id
    touch(r)
    return ok(ser_report(r))

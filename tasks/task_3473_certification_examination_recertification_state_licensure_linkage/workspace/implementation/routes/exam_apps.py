"""Exam applications (PRD §3.4): apply, decide (approval mints the ATT),
deny-resubmit cycle; plus AuthorizationToTest reads."""

from flask import Blueprint, request

from db import (ATTEMPT_HARD_CAP, ATT_VALID_DAYS, REMEDIAL_GATE, STORE,
                attempts_consumed, base_entity, disciplinary_hold, now_dt,
                program_accredited_at_completion, serialize, touch,
                within_validity_window)
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, opt_str,
                        req_enum, req_str)
from util import add_days

bp = Blueprint("exam_apps", __name__)


def _remedial_gate_satisfied(candidate_id, level_id, basis_id, level):
    """True unless the basis has consumed >= REMEDIAL_GATE attempts without a
    qualifying remedial record (hours >= level.remedial_hours_required and
    completed_date strictly after the 3rd SCORED_FAIL's delivered date)."""
    consumed = sorted(
        (a for a in STORE.attempts.values()
         if a["basis_completion_record_id"] == basis_id
         and a["status"] in ("SCORED_PASS", "SCORED_FAIL")),
        key=lambda a: a["delivered_at"])
    if len(consumed) < REMEDIAL_GATE:
        return True
    fails = [a for a in consumed if a["status"] == "SCORED_FAIL"]
    anchor = fails[2] if len(fails) >= 3 else consumed[2]
    threshold_date = anchor["delivered_at"].date()
    for r in STORE.remedials.values():
        if (r["candidate_id"] == candidate_id
                and r["level_id"] == level_id
                and float(r["hours"]) >= float(level["remedial_hours_required"])
                and r["completed_date"] > threshold_date):
            return True
    return False


@bp.post("/registry/exam-applications")
def create_exam_application():
    uid, _ = authn(["Candidate"])
    b = body()
    level_id = req_str(b, "level_id")
    completion_record_id = req_str(b, "completion_record_id")

    candidate = STORE.candidates.get(uid)
    if not candidate:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % uid)
    level = STORE.levels.get(level_id)
    if not level:
        raise_err("ERR_NOT_FOUND", "LevelDefinition %s does not exist" % level_id)
    record = STORE.completions.get(completion_record_id)
    if not record:
        raise_err("ERR_NOT_FOUND", "ProgramCompletionRecord %s does not exist" % completion_record_id)

    if candidate["status"] == "BARRED":
        raise_err("ERR_PERMANENTLY_BARRED", "Candidate is BARRED")
    if disciplinary_hold(uid):
        raise_err("ERR_DISCIPLINARY_HOLD",
                  "Candidate is under a HOLD_NEW_APPLICATIONS interim action")

    program = STORE.programs.get(record["program_id"])
    if record["candidate_id"] != uid or (program and program["level_id"] != level_id):
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Completion record does not belong to this candidate and level")

    e = base_entity()
    e.update({
        "candidate_id": uid,
        "level_id": level_id,
        "completion_record_id": completion_record_id,
        "application_fee_cents": level["initial_application_fee_cents"],
        "status": "SUBMITTED",
        "denial_reason": None,
        "decided_at": None,
        "att_id": None,
        "resubmission_count": 0,
    })
    STORE.exam_apps[e["id"]] = e
    return ok_object(serialize(e), 201)


@bp.get("/registry/exam-applications")
def list_exam_applications():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    level_id = request.args.get("level_id")
    completion_record_id = request.args.get("completion_record_id")
    status = request.args.get("status")
    items = []
    for a in STORE.exam_apps.values():
        if candidate_id is not None and a["candidate_id"] != candidate_id:
            continue
        if level_id is not None and a["level_id"] != level_id:
            continue
        if completion_record_id is not None and a["completion_record_id"] != completion_record_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(a)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(a) for a in page], total, limit, offset)


@bp.get("/registry/exam-applications/<aid>")
def get_exam_application(aid):
    authn(ALL_AUTHENTICATED_ROLES)
    a = STORE.exam_apps.get(aid)
    if not a:
        raise_err("ERR_NOT_FOUND", "ExamApplication %s does not exist" % aid)
    return ok_object(serialize(a), 200)


@bp.post("/registry/exam-applications/<aid>/decision")
def decide_exam_application(aid):
    authn(["RegistryAdmin"])
    b = body()
    outcome = req_enum(b, "outcome", ["APPROVED", "DENIED"])
    reason = opt_str(b, "reason", None)
    app = STORE.exam_apps.get(aid)
    if not app:
        raise_err("ERR_NOT_FOUND", "ExamApplication %s does not exist" % aid)
    if app["status"] != "SUBMITTED":
        raise_err("ERR_APPLICATION_NOT_SUBMITTED",
                  "Exam application is %s, not SUBMITTED" % app["status"])

    if outcome == "DENIED":
        app["status"] = "DENIED"
        app["denial_reason"] = reason
        app["decided_at"] = now_dt()
        touch(app)
        return ok_object(serialize(app), 200)

    # APPROVED — full gate set in the §2.8 precedence order.
    candidate = STORE.candidates.get(app["candidate_id"])
    if candidate and candidate["status"] == "BARRED":
        raise_err("ERR_PERMANENTLY_BARRED", "Candidate is BARRED")
    if disciplinary_hold(app["candidate_id"]):
        raise_err("ERR_DISCIPLINARY_HOLD",
                  "Candidate is under a HOLD_NEW_APPLICATIONS interim action")

    record = STORE.completions.get(app["completion_record_id"])
    if not record:
        raise_err("ERR_NOT_FOUND", "ProgramCompletionRecord %s does not exist"
                  % app["completion_record_id"])
    if not program_accredited_at_completion(record):
        raise_err("ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION",
                  "Program accreditation at the completion date was not ACCREDITED or PROVISIONAL")

    program = STORE.programs.get(record["program_id"])
    if record["candidate_id"] != app["candidate_id"] or (program and program["level_id"] != app["level_id"]):
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Completion record does not belong to this candidate and level")

    if record["status"] != "VERIFIED" or not within_validity_window(record):
        raise_err("ERR_EDUCATION_VALIDITY_EXPIRED",
                  "Completion record is not VERIFIED and inside its 24-month validity window")

    level = STORE.levels.get(app["level_id"])
    consumed = attempts_consumed(record["id"])
    if consumed >= ATTEMPT_HARD_CAP:
        raise_err("ERR_ATTEMPT_LIMIT_REACHED",
                  "Attempt budget of %d on this basis is exhausted" % ATTEMPT_HARD_CAP)
    if level and not _remedial_gate_satisfied(app["candidate_id"], app["level_id"],
                                              record["id"], level):
        raise_err("ERR_REMEDIAL_REQUIRED",
                  "A qualifying remedial education record is required for attempts 4-6")

    now = now_dt()
    att = base_entity()
    att.update({
        "exam_application_id": app["id"],
        "candidate_id": app["candidate_id"],
        "issued_on": now,
        "expires_on": add_days(now, ATT_VALID_DAYS),
        "attempt_id": None,
        "status": "ISSUED",
    })
    STORE.atts[att["id"]] = att
    app["status"] = "APPROVED"
    app["att_id"] = att["id"]
    app["decided_at"] = now
    touch(app)
    return ok_object(serialize(app), 200)


@bp.post("/registry/exam-applications/<aid>/resubmit")
def resubmit_exam_application(aid):
    uid, _ = authn(["Candidate"])
    app = STORE.exam_apps.get(aid)
    if not app:
        raise_err("ERR_NOT_FOUND", "ExamApplication %s does not exist" % aid)
    if app["candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the owning candidate may resubmit")
    b = body()
    new_record_id = opt_str(b, "completion_record_id", None)
    if new_record_id is not None and new_record_id not in STORE.completions:
        raise_err("ERR_NOT_FOUND",
                  "ProgramCompletionRecord %s does not exist" % new_record_id)
    if app["status"] != "DENIED":
        raise_err("ERR_APPLICATION_NOT_DENIED",
                  "Exam application is %s, not DENIED" % app["status"])
    if new_record_id is not None:
        app["completion_record_id"] = new_record_id
    app["status"] = "SUBMITTED"
    app["denial_reason"] = None
    app["resubmission_count"] += 1
    touch(app)
    return ok_object(serialize(app), 200)


# --- AuthorizationToTest reads ----------------------------------------------

@bp.get("/registry/authorizations-to-test")
def list_atts():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    exam_application_id = request.args.get("exam_application_id")
    status = request.args.get("status")
    items = []
    for a in STORE.atts.values():
        if candidate_id is not None and a["candidate_id"] != candidate_id:
            continue
        if exam_application_id is not None and a["exam_application_id"] != exam_application_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(a)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(a) for a in page], total, limit, offset)


@bp.get("/registry/authorizations-to-test/<aid>")
def get_att(aid):
    authn(ALL_AUTHENTICATED_ROLES)
    a = STORE.atts.get(aid)
    if not a:
        raise_err("ERR_NOT_FOUND", "AuthorizationToTest %s does not exist" % aid)
    return ok_object(serialize(a), 200)

"""Routes: applicants, contact attempts, applications, decisions,
withdrawals, and transfer credit evaluations."""

from datetime import timedelta

from flask import Blueprint

from auth import require_roles
from domain import (
    counselor_assignment,
    current_auth_row,
    degree_path,
    ser_applicant,
    ser_application,
    ser_tce,
    MAX_CONTACTS_PER_7D,
    CADENCE_WINDOW_HOURS,
)
from errors import raise_err
from response import ok_list, ok_object
from store import STORE, CLOCK, bump, new_entity, now_ts
from validate import (
    get_body,
    opt_bool,
    opt_str,
    paginate,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("funnel", __name__)

READ_ROLES = ("SystemAdmin", "RegistrarAdmin", "Counselor", "Advisor", "Applicant")
APP_STATUSES = ("SUBMITTED", "ADMITTED", "DENIED", "WITHDRAWN", "CONVERTED")
TCE_STATUSES = ("DRAFT", "IN_REVIEW", "COMPLETED", "VOID")


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------

@bp.post("/api/applicants")
def create_applicant():
    require_roles("RegistrarAdmin", "Counselor")
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    state_code = req_str(body, "state_code")
    counselor = counselor_assignment()
    applicant = new_entity(
        {
            "full_name": full_name,
            "email": email,
            "state_code": state_code,
            "status": "PROSPECT",
            "assigned_counselor_id": counselor["id"] if counselor else None,
            "contact_log": [],
        }
    )
    STORE.applicants[applicant["id"]] = applicant
    return ok_object(ser_applicant(applicant), 201)


@bp.get("/api/applicants/<aid>")
def get_applicant(aid):
    require_roles(*READ_ROLES)
    applicant = STORE.applicants.get(aid)
    if applicant is None:
        raise_err("ERR_NOT_FOUND", "applicant not found")
    return ok_object(ser_applicant(applicant))


@bp.post("/api/applicants/<aid>/contact-attempts")
def contact_attempt(aid):
    uid, _role = require_roles("Counselor")
    applicant = STORE.applicants.get(aid)
    if applicant is None:
        raise_err("ERR_NOT_FOUND", "applicant not found")
    if applicant["assigned_counselor_id"] != uid:
        raise_err("ERR_FORBIDDEN", "caller must be the applicant's assigned counselor")
    body = get_body()
    channel = req_str(body, "channel")
    outcome = req_str(body, "outcome")

    now = CLOCK.now()
    window_start = now - timedelta(hours=CADENCE_WINDOW_HOURS)
    in_window = [
        e
        for e in applicant["contact_log"]
        if window_start < e["_attempted_dt"] <= now
    ]
    if len(in_window) >= MAX_CONTACTS_PER_7D:
        raise_err(
            "ERR_CONTACT_CADENCE_EXCEEDED",
            "3 contact attempts already logged in the rolling 168h window",
        )
    applicant["contact_log"].append(
        {
            "channel": channel,
            "outcome": outcome,
            "attempted_at": now_ts(),
            "_attempted_dt": now,
        }
    )
    bump(applicant)
    return ok_object(ser_applicant(applicant), 201)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.post("/api/applications")
def create_application():
    uid, role = require_roles("Applicant", "Counselor")
    body = get_body()
    applicant_id = req_str(body, "applicant_id")
    term_id = req_str(body, "term_id")
    program_id = req_str(body, "program_id")
    disclosure = opt_bool(body, "disclosure_acknowledged", False)
    licensure = opt_bool(body, "licensure_disclosure_acknowledged", False)

    if role == "Applicant" and uid != applicant_id:
        raise_err("ERR_FORBIDDEN", "an applicant may only create applications for itself")

    applicant = STORE.applicants.get(applicant_id)
    if applicant is None:
        raise_err("ERR_NOT_FOUND", "applicant not found")
    term = STORE.terms.get(term_id)
    if term is None:
        raise_err("ERR_NOT_FOUND", "term not found")
    program = STORE.programs.get(program_id)
    if program is None:
        raise_err("ERR_NOT_FOUND", "program not found")

    # Duplicate check runs before the term-open temporal gate.
    for app in STORE.applications.values():
        if (
            app["applicant_id"] == applicant_id
            and app["term_id"] == term_id
            and app["status"] in ("SUBMITTED", "ADMITTED")
        ):
            raise_err(
                "ERR_DUPLICATE_APPLICATION",
                "an active application already exists for this applicant and term",
            )
    if term["status"] != "ENROLLMENT_OPEN":
        raise_err("ERR_TERM_NOT_OPEN", "term must be ENROLLMENT_OPEN to accept applications")

    application = new_entity(
        {
            "applicant_id": applicant_id,
            "term_id": term_id,
            "program_id": program_id,
            "disclosure_acknowledged": disclosure,
            "licensure_disclosure_acknowledged": licensure,
            "status": "SUBMITTED",
            "decision_reason": None,
        }
    )
    STORE.applications[application["id"]] = application
    if applicant["status"] == "PROSPECT":
        applicant["status"] = "APPLIED"
        bump(applicant)
    return ok_object(ser_application(application), 201)


@bp.get("/api/applications")
def list_applications():
    require_roles("SystemAdmin", "RegistrarAdmin", "Counselor", "Advisor")
    items = sorted(STORE.applications.values(), key=lambda a: a["_seq"])
    f_applicant = _qp("applicant_id")
    f_term = _qp("term_id")
    f_program = _qp("program_id")
    f_status = _qp("status")
    if f_applicant is not None:
        items = [a for a in items if a["applicant_id"] == f_applicant]
    if f_term is not None:
        items = [a for a in items if a["term_id"] == f_term]
    if f_program is not None:
        items = [a for a in items if a["program_id"] == f_program]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    page, limit, offset, total = paginate([ser_application(a) for a in items])
    return ok_list(page, limit, offset, total)


def _qp(name):
    from flask import request

    return request.args.get(name)


@bp.get("/api/applications/<aid>")
def get_application(aid):
    require_roles(*READ_ROLES)
    application = STORE.applications.get(aid)
    if application is None:
        raise_err("ERR_NOT_FOUND", "application not found")
    return ok_object(ser_application(application))


@bp.post("/api/applications/<aid>/decision")
def decide_application(aid):
    require_roles("RegistrarAdmin")
    body = get_body()
    decision = req_enum(body, "decision", ("ADMIT", "DENY"))
    reason = opt_str(body, "reason")
    application = STORE.applications.get(aid)
    if application is None:
        raise_err("ERR_NOT_FOUND", "application not found")
    if application["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "decisions are defined only on SUBMITTED applications")

    if decision == "ADMIT":
        applicant = STORE.applicants.get(application["applicant_id"])
        row = current_auth_row(application["program_id"], applicant["state_code"])
        if row is None or row["authorization_status"] in ("PENDING", "PROHIBITED"):
            raise_err(
                "ERR_STATE_NOT_AUTHORIZED",
                "no current AUTHORIZED/RESTRICTED state authorization for this program and state",
            )
        if row["authorization_status"] == "RESTRICTED" and not application["disclosure_acknowledged"]:
            raise_err(
                "ERR_DISCLOSURE_REQUIRED",
                "RESTRICTED state authorization requires disclosure_acknowledged",
            )
        if "reason" in body:
            application["decision_reason"] = reason
        application["status"] = "ADMITTED"
        bump(application)
        if applicant["status"] == "APPLIED":
            applicant["status"] = "ADMITTED"
            bump(applicant)
    else:
        if "reason" in body:
            application["decision_reason"] = reason
        application["status"] = "DENIED"
        bump(application)
    return ok_object(ser_application(application))


@bp.post("/api/applications/<aid>/withdraw")
def withdraw_application(aid):
    uid, role = require_roles("Applicant", "Counselor")
    application = STORE.applications.get(aid)
    if application is None:
        raise_err("ERR_NOT_FOUND", "application not found")
    applicant = STORE.applicants.get(application["applicant_id"])
    if role == "Applicant":
        if uid != application["applicant_id"]:
            raise_err("ERR_FORBIDDEN", "an applicant may only withdraw its own applications")
    else:  # Counselor
        if applicant is None or applicant["assigned_counselor_id"] != uid:
            raise_err("ERR_FORBIDDEN", "caller must be the applicant's assigned counselor")
    if application["status"] not in ("SUBMITTED", "ADMITTED"):
        raise_err(
            "ERR_INVALID_STATE",
            "only SUBMITTED or ADMITTED applications may be withdrawn",
        )
    was_admitted = application["status"] == "ADMITTED"
    application["status"] = "WITHDRAWN"
    bump(application)
    if was_admitted and applicant is not None and applicant["status"] == "ADMITTED":
        applicant["status"] = "APPLIED"
        bump(applicant)
    return ok_object(ser_application(application))


# ---------------------------------------------------------------------------
# Transfer credit evaluations
# ---------------------------------------------------------------------------

@bp.get("/api/applications/<aid>/transfer-credit-evaluations")
def list_tces(aid):
    require_roles(*READ_ROLES)
    application = STORE.applications.get(aid)
    if application is None:
        raise_err("ERR_NOT_FOUND", "application not found")
    items = sorted(
        (t for t in STORE.tces.values() if t["application_id"] == aid),
        key=lambda t: t["_seq"],
    )
    page, limit, offset, total = paginate([ser_tce(t) for t in items])
    return ok_list(page, limit, offset, total)


@bp.post("/api/applications/<aid>/transfer-credit-evaluations")
def create_tce(aid):
    require_roles("RegistrarAdmin")
    application = STORE.applications.get(aid)
    if application is None:
        raise_err("ERR_NOT_FOUND", "application not found")
    body = get_body()
    accepted = req_int(body, "accepted_credits")
    in_progress = req_int(body, "in_progress_credits")
    tce = new_entity(
        {
            "application_id": aid,
            "status": "DRAFT",
            "accepted_credits": accepted,
            "in_progress_credits": in_progress,
            "capped_credits": 0,
            "remaining_credits": 0,
        }
    )
    STORE.tces[tce["id"]] = tce
    return ok_object(ser_tce(tce), 201)


@bp.post("/api/transfer-credit-evaluations/<tid>/advance")
def advance_tce(tid):
    require_roles("RegistrarAdmin")
    body = get_body()
    to_state = req_enum(body, "to_state", TCE_STATUSES)
    tce = STORE.tces.get(tid)
    if tce is None:
        raise_err("ERR_NOT_FOUND", "transfer credit evaluation not found")

    cur = tce["status"]
    if to_state == "IN_REVIEW" and cur == "DRAFT":
        pass
    elif to_state == "COMPLETED" and cur == "IN_REVIEW":
        application = STORE.applications.get(tce["application_id"])
        program = STORE.programs.get(application["program_id"]) if application else None
        total = program["total_credits_required"] if program else 0
        capped, remaining = degree_path(
            total, tce["accepted_credits"], tce["in_progress_credits"]
        )
        tce["capped_credits"] = capped
        tce["remaining_credits"] = remaining
    elif to_state == "IN_REVIEW" and cur == "COMPLETED":
        # Re-evaluation cycle: blocked once the degree path is locked by a
        # live enrollment from the same application.
        for enr in STORE.enrollments.values():
            if enr["application_id"] == tce["application_id"] and enr["status"] in (
                "REGISTERED",
                "ACTIVE",
                "DEFERRED",
            ):
                raise_err(
                    "ERR_INVALID_STATE",
                    "degree path is locked once enrolled",
                )
    elif to_state == "VOID" and cur in ("DRAFT", "IN_REVIEW"):
        pass
    else:
        raise_err(
            "ERR_INVALID_STATE",
            "cannot advance transfer credit evaluation from %s to %s" % (cur, to_state),
        )

    tce["status"] = to_state
    bump(tce)
    return ok_object(ser_tce(tce))

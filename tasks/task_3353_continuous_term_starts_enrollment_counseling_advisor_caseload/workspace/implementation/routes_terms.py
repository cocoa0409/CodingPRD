"""Routes: terms, sections, programs, state authorizations, staff."""

import uuid
from datetime import timedelta

from flask import Blueprint

from auth import require_roles
from domain import (
    adjuncts_required,
    auth_windows_overlap,
    current_auth_row,
    packages_for_enrollment,
    recompute_package_totals,
    ser_program,
    ser_section,
    ser_staff,
    ser_state_auth,
    ser_term,
)
from errors import raise_err
from response import ok_list, ok_object
from store import STORE, CLOCK, bump, new_entity, parse_date
from validate import (
    get_body,
    is_int,
    opt_str,
    paginate,
    req_bool,
    req_date,
    req_enum,
    req_int,
    req_str,
    opt_date,
)

bp = Blueprint("terms_programs_staff", __name__)

ALL_ROLES = (
    "SystemAdmin",
    "RegistrarAdmin",
    "ComplianceOfficer",
    "FinancialAidOfficer",
    "Counselor",
    "Advisor",
    "Applicant",
)

TERM_STATUSES = ("SCHEDULED", "ENROLLMENT_OPEN", "IN_SESSION", "CLOSED")
SECTION_STATUSES = ("PLANNED", "STAFFING", "STAFFED", "OPEN", "LOCKED")
AUTH_STATUSES = ("AUTHORIZED", "RESTRICTED", "PROHIBITED", "PENDING")


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------

@bp.post("/api/terms")
def create_term():
    require_roles("RegistrarAdmin")
    body = get_body()
    name = req_str(body, "name")
    sd_raw, sd = req_date(body, "start_date")
    ad_raw, ad = req_date(body, "add_drop_end_date")
    cd_raw, cd = req_date(body, "census_date")
    ed_raw, ed = req_date(body, "end_date")
    if not (sd < ad <= cd < ed):
        raise_err(
            "ERR_TERM_DATE_INVALID",
            "term dates must satisfy start_date < add_drop_end_date <= census_date < end_date",
        )
    term = new_entity(
        {
            "name": name,
            "start_date": sd_raw,
            "add_drop_end_date": ad_raw,
            "census_date": cd_raw,
            "end_date": ed_raw,
            "status": "SCHEDULED",
        }
    )
    STORE.terms[term["id"]] = term
    return ok_object(ser_term(term), 201)


@bp.get("/api/terms/<tid>")
def get_term(tid):
    require_roles(*ALL_ROLES)
    term = STORE.terms.get(tid)
    if term is None:
        raise_err("ERR_NOT_FOUND", "term not found")
    return ok_object(ser_term(term))


@bp.post("/api/terms/<tid>/advance")
def advance_term(tid):
    require_roles("RegistrarAdmin")
    body = get_body()
    to_state = req_enum(body, "to_state", TERM_STATUSES)
    term = STORE.terms.get(tid)
    if term is None:
        raise_err("ERR_NOT_FOUND", "term not found")

    edges = {
        "SCHEDULED": {"ENROLLMENT_OPEN"},
        "ENROLLMENT_OPEN": {"IN_SESSION"},
        "IN_SESSION": {"CLOSED"},
        "CLOSED": set(),
    }
    if to_state not in edges.get(term["status"], set()):
        raise_err(
            "ERR_INVALID_STATE",
            "cannot advance term from %s to %s" % (term["status"], to_state),
        )

    today = CLOCK.today()
    start = parse_date(term["start_date"])
    end = parse_date(term["end_date"])

    if to_state == "ENROLLMENT_OPEN":
        if today < start - timedelta(days=30):
            raise_err("ERR_TERM_CLOCK_NOT_REACHED", "enrollment opens no earlier than 30 days before start_date")
    elif to_state == "IN_SESSION":
        if today < start:
            raise_err("ERR_TERM_CLOCK_NOT_REACHED", "term cannot enter session before start_date")
        # Cascade: REGISTERED enrollments -> ACTIVE; their CERTIFIED packages
        # -> DISBURSING with due entries released.
        for enr in STORE.enrollments.values():
            if enr["term_id"] == term["id"] and enr["status"] == "REGISTERED":
                enr["status"] = "ACTIVE"
                bump(enr)
                for pkg in packages_for_enrollment(enr["id"]):
                    if pkg["status"] != "CERTIFIED":
                        continue
                    pkg["status"] = "DISBURSING"
                    for entry in pkg["disbursement_schedule"]:
                        if entry["entry_status"] == "SCHEDULED" and parse_date(entry["release_date"]) <= today:
                            entry["entry_status"] = "DISBURSED"
                    recompute_package_totals(pkg)
                    bump(pkg)
    elif to_state == "CLOSED":
        if today < end:
            raise_err("ERR_TERM_CLOCK_NOT_REACHED", "term cannot close before end_date")
        # Cascade: ACTIVE enrollments -> COMPLETED; affected packages settle.
        for enr in STORE.enrollments.values():
            if enr["term_id"] == term["id"] and enr["status"] == "ACTIVE":
                enr["status"] = "COMPLETED"
                bump(enr)
                for pkg in packages_for_enrollment(enr["id"]):
                    if pkg["status"] not in ("CERTIFIED", "DISBURSING"):
                        continue
                    changed = False
                    for entry in pkg["disbursement_schedule"]:
                        if entry["entry_status"] != "SCHEDULED":
                            continue
                        if parse_date(entry["release_date"]) <= end:
                            entry["entry_status"] = "DISBURSED"
                        else:
                            entry["entry_status"] = "CANCELLED"
                        changed = True
                    recompute_package_totals(pkg)
                    if pkg["disbursement_schedule"] and all(
                        e["entry_status"] in ("DISBURSED", "CANCELLED", "RETURNED")
                        for e in pkg["disbursement_schedule"]
                    ):
                        pkg["status"] = "SETTLED"
                        changed = True
                    if changed:
                        bump(pkg)

    term["status"] = to_state
    bump(term)
    return ok_object(ser_term(term))


# ---------------------------------------------------------------------------
# Course sections
# ---------------------------------------------------------------------------

@bp.post("/api/terms/<tid>/sections")
def create_section(tid):
    require_roles("RegistrarAdmin")
    term = STORE.terms.get(tid)
    if term is None:
        raise_err("ERR_NOT_FOUND", "term not found")
    body = get_body()
    course_code = req_str(body, "course_code")
    capacity = req_int(body, "capacity")
    forecast = req_int(body, "forecast_enrollment")
    section = new_entity(
        {
            "term_id": term["id"],
            "course_code": course_code,
            "capacity": capacity,
            "forecast_enrollment": forecast,
            "adjuncts_required": adjuncts_required(forecast, capacity),
            "adjunct_hires": 0,
            "enrolled_count": 0,
            "seats_available": capacity,
            "status": "PLANNED",
            "_roster": [],
        }
    )
    STORE.sections[section["id"]] = section
    return ok_object(ser_section(section), 201)


@bp.get("/api/terms/<tid>/sections")
def list_sections(tid):
    require_roles(*ALL_ROLES)
    term = STORE.terms.get(tid)
    if term is None:
        raise_err("ERR_NOT_FOUND", "term not found")
    items = sorted(
        (s for s in STORE.sections.values() if s["term_id"] == tid),
        key=lambda s: s["_seq"],
    )
    page, limit, offset, total = paginate([ser_section(s) for s in items])
    return ok_list(page, limit, offset, total)


@bp.post("/api/sections/<sid>/advance")
def advance_section(sid):
    require_roles("RegistrarAdmin")
    body = get_body()
    to_state = req_enum(body, "to_state", SECTION_STATUSES)
    section = STORE.sections.get(sid)
    if section is None:
        raise_err("ERR_NOT_FOUND", "section not found")

    cur = section["status"]
    # State legality first; temporal gates after.
    if to_state == "STAFFING" and cur == "PLANNED":
        if section["adjuncts_required"] <= 0:
            raise_err("ERR_INVALID_STATE", "no staffing gap to fill")
    elif to_state == "STAFFED" and cur == "PLANNED":
        if section["adjuncts_required"] != 0:
            raise_err("ERR_INVALID_STATE", "adjunct gap unfilled")
    elif to_state == "STAFFED" and cur == "STAFFING":
        hires = body.get("adjunct_hires")
        if hires is not None and not is_int(hires):
            raise_err("ERR_INVALID_REQUEST", "adjunct_hires must be an integer")
        if hires is None or hires < section["adjuncts_required"]:
            raise_err("ERR_INVALID_STATE", "insufficient adjunct hires")
        section["adjunct_hires"] = hires
    elif to_state == "OPEN" and cur == "STAFFED":
        term = STORE.terms.get(section["term_id"])
        if term is None or term["status"] != "ENROLLMENT_OPEN":
            raise_err("ERR_TERM_NOT_OPEN", "term must be ENROLLMENT_OPEN to open a section")
    else:
        raise_err(
            "ERR_INVALID_STATE",
            "cannot advance section from %s to %s" % (cur, to_state),
        )

    section["status"] = to_state
    bump(section)
    return ok_object(ser_section(section))


@bp.post("/api/sections/<sid>/roster")
def roster_add(sid):
    require_roles("RegistrarAdmin")
    body = get_body()
    enrollment_id = req_str(body, "enrollment_id")
    section = STORE.sections.get(sid)
    if section is None:
        raise_err("ERR_NOT_FOUND", "section not found")
    enr = STORE.enrollments.get(enrollment_id)
    if enr is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")

    # Section's own status before the add-drop deadline.
    if section["status"] == "LOCKED":
        raise_err("ERR_SECTION_FULL", "section is full (0 seats available)")
    if section["status"] != "OPEN":
        raise_err("ERR_SECTION_NOT_OPEN", "section is not open for roster adds")
    term = STORE.terms.get(section["term_id"])
    if term is None or CLOCK.today() > parse_date(term["add_drop_end_date"]):
        raise_err("ERR_ADD_DROP_CLOSED", "roster adds are closed for this term")

    if enrollment_id not in section["_roster"]:
        section["_roster"].append(enrollment_id)
        section["enrolled_count"] += 1
        section["seats_available"] -= 1
        if section["seats_available"] == 0:
            section["status"] = "LOCKED"
        bump(section)
    return ok_object(ser_section(section))


# ---------------------------------------------------------------------------
# Programs and state authorizations
# ---------------------------------------------------------------------------

@bp.post("/api/programs")
def create_program():
    require_roles("RegistrarAdmin")
    body = get_body()
    code = req_str(body, "code")
    title = req_str(body, "title")
    total = req_int(body, "total_credits_required")
    licensure = req_bool(body, "licensure_flag")
    program = new_entity(
        {
            "code": code,
            "title": title,
            "total_credits_required": total,
            "licensure_flag": licensure,
        }
    )
    STORE.programs[program["id"]] = program
    return ok_object(ser_program(program), 201)


@bp.get("/api/programs/<pid>")
def get_program(pid):
    require_roles(*ALL_ROLES)
    program = STORE.programs.get(pid)
    if program is None:
        raise_err("ERR_NOT_FOUND", "program not found")
    return ok_object(ser_program(program))


@bp.post("/api/programs/<pid>/state-authorizations")
def create_state_auth(pid):
    require_roles("ComplianceOfficer")
    program = STORE.programs.get(pid)
    if program is None:
        raise_err("ERR_NOT_FOUND", "program not found")
    body = get_body()
    state_code = req_str(body, "state_code")
    status = req_enum(body, "authorization_status", AUTH_STATUSES)
    from_raw, from_d = req_date(body, "effective_from")
    to_raw, to_d = opt_date(body, "effective_to")
    disclosure = opt_str(body, "disclosure_text")
    if status == "RESTRICTED" and not disclosure:
        raise_err(
            "ERR_INVALID_REQUEST",
            "disclosure_text is required when authorization_status is RESTRICTED",
        )
    for row in STORE.state_auths.values():
        if row["program_id"] != pid or row["state_code"] != state_code:
            continue
        r_from = parse_date(row["effective_from"])
        r_to = parse_date(row["effective_to"]) if row["effective_to"] else None
        if auth_windows_overlap(from_d, to_d, r_from, r_to):
            raise_err(
                "ERR_AUTHORIZATION_WINDOW_OVERLAP",
                "overlapping authorization window for this program and state",
            )
    row = {
        "id": str(uuid.uuid4()),
        "program_id": pid,
        "state_code": state_code,
        "authorization_status": status,
        "effective_from": from_raw,
        "effective_to": to_raw,
        "disclosure_text": disclosure,
    }
    # StateAuthorization carries only id + created_at (no updated_at/version).
    from store import now_ts

    row["created_at"] = now_ts()
    row["_seq"] = STORE.next_seq()
    STORE.state_auths[row["id"]] = row
    return ok_object(ser_state_auth(row), 201)


@bp.get("/api/programs/<pid>/state-authorizations")
def list_state_auths(pid):
    require_roles(*ALL_ROLES)
    program = STORE.programs.get(pid)
    if program is None:
        raise_err("ERR_NOT_FOUND", "program not found")
    items = sorted(
        (r for r in STORE.state_auths.values() if r["program_id"] == pid),
        key=lambda r: r["_seq"],
    )
    page, limit, offset, total = paginate([ser_state_auth(r) for r in items])
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

@bp.post("/api/staff")
def create_staff():
    require_roles("SystemAdmin")
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    staff_type = req_enum(body, "staff_type", ("COUNSELOR", "ADVISOR"))
    caseload_cap = req_int(body, "caseload_cap")
    comp = req_enum(body, "compensation_plan", ("NON_INCENTIVE", "INCENTIVE")) if "compensation_plan" in body else "NON_INCENTIVE"
    staff = new_entity(
        {
            "full_name": full_name,
            "email": email,
            "staff_type": staff_type,
            "compensation_plan": comp,
            "caseload_cap": caseload_cap,
        }
    )
    STORE.staff[staff["id"]] = staff
    return ok_object(ser_staff(staff), 201)


@bp.get("/api/staff/<sid>")
def get_staff(sid):
    require_roles(*ALL_ROLES)
    staff = STORE.staff.get(sid)
    if staff is None:
        raise_err("ERR_NOT_FOUND", "staff not found")
    return ok_object(ser_staff(staff))


@bp.get("/api/staff/<sid>/applicants")
def list_staff_applicants(sid):
    uid, role = require_roles("SystemAdmin", "RegistrarAdmin", "Counselor")
    staff = STORE.staff.get(sid)
    if staff is None:
        raise_err("ERR_NOT_FOUND", "staff not found")
    if role == "Counselor" and uid != sid:
        raise_err("ERR_FORBIDDEN", "counselors may only list their own caseload")
    items = sorted(
        (a for a in STORE.applicants.values() if a["assigned_counselor_id"] == sid),
        key=lambda a: a["_seq"],
    )
    from domain import ser_applicant

    page, limit, offset, total = paginate([ser_applicant(a) for a in items])
    return ok_list(page, limit, offset, total)

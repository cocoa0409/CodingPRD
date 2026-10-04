"""Stage-setting resources: applicants, country programs, assignment openings."""
from flask import Blueprint, request

from authz import auth, require_roles
from cascade import cancel_opening_cascade
from db import ROLES, SECTORS, SKILL_CATALOG, STORE, fmt_ts, new_record, touch
from errors import err, ok_object, paginate
from validate import (as_dt, as_enum, as_enum_list, as_int, as_number, as_str,
                      as_str_list, body)

bp = Blueprint("stage", __name__)

PROGRAM_TRANSITIONS = {
    "OPEN": {"SUSPENDED", "CLOSED"},
    "SUSPENDED": {"OPEN", "CLOSED"},
    "CLOSED": set(),
}


# --- Applicant ---------------------------------------------------------------
@bp.post("/volunteer-portal/applicants")
def create_applicant():
    auth()
    require_roles(request.headers.get("X-User-Role"), ("SystemAdmin",))
    data = body()
    # Field shape (priority 10)
    full_name = as_str(data, "full_name")
    email = as_str(data, "email")
    dob = as_dt(data, "date_of_birth")
    citizenship = as_str(data, "citizenship_country")
    skills = as_enum_list(data, "skills", SKILL_CATALOG)
    languages = as_str_list(data, "languages", required=False) or []
    # Uniqueness of email across all applicants (no dedicated error -> 400)
    for existing in STORE["applicants"].values():
        if existing["email"] == email:
            err("ERR_VALIDATION", 400, "email already registered")
    rec = new_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "date_of_birth": fmt_ts(dob),
        "citizenship_country": citizenship,
        "skills": list(skills),
        "languages": list(languages),
    })
    STORE["applicants"][rec["id"]] = rec
    return ok_object(rec, 201)


# --- CountryProgram ----------------------------------------------------------
@bp.post("/volunteer-portal/country-programs")
def create_program():
    auth()
    require_roles(request.headers.get("X-User-Role"), ("SystemAdmin",))
    data = body()
    country_code = as_str(data, "country_code")
    name = as_str(data, "name")
    tier = as_int(data, "medical_support_tier", minimum=1, maximum=3)
    language = as_str(data, "required_language")
    threshold = as_number(data, "language_threshold_score", minimum=1.0, maximum=5.0)
    capacity = as_int(data, "training_capacity", minimum=1)
    for existing in STORE["country_programs"].values():
        if existing["country_code"] == country_code:
            err("ERR_VALIDATION", 400, "country_code already registered")
    rec = new_record()
    rec.update({
        "country_code": country_code,
        "name": name,
        "medical_support_tier": tier,
        "required_language": language,
        "language_threshold_score": threshold,
        "training_capacity": capacity,
        "status": "OPEN",
    })
    STORE["country_programs"][rec["id"]] = rec
    return ok_object(rec, 201)


def get_program_or_404(pid):
    program = STORE["country_programs"].get(pid)
    if program is None:
        err("ERR_PROGRAM_NOT_FOUND", 404, "Country program not found")
    return program


@bp.get("/volunteer-portal/country-programs/<pid>")
def get_program(pid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    return ok_object(get_program_or_404(pid))


@bp.patch("/volunteer-portal/country-programs/<pid>")
def patch_program(pid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("SystemAdmin",))
    program = get_program_or_404(pid)
    data = body()
    # State guard (priority 6): machine transition must exist when status given.
    new_status = data.get("status")
    if new_status is not None and new_status in ("OPEN", "SUSPENDED", "CLOSED"):
        if new_status not in PROGRAM_TRANSITIONS[program["status"]]:
            err("ERR_INVALID_STATE", 409,
                "No country program transition %s -> %s" % (program["status"], new_status))
    # Field shape (priority 10)
    if "status" in data and data["status"] is not None:
        new_status = as_enum(data, "status", ("OPEN", "SUSPENDED", "CLOSED"))
    tier = as_int(data, "medical_support_tier", required=False, minimum=1, maximum=3)
    capacity = as_int(data, "training_capacity", required=False, minimum=1)
    threshold = as_number(data, "language_threshold_score", required=False,
                          minimum=1.0, maximum=5.0)
    changed = False
    if new_status is not None and new_status != program["status"]:
        program["status"] = new_status
        changed = True
    if tier is not None and tier != program["medical_support_tier"]:
        program["medical_support_tier"] = tier
        changed = True
    if capacity is not None and capacity != program["training_capacity"]:
        program["training_capacity"] = capacity
        changed = True
    if threshold is not None and threshold != program["language_threshold_score"]:
        program["language_threshold_score"] = threshold
        changed = True
    if changed:
        touch(program)
    return ok_object(program)


# --- AssignmentOpening -------------------------------------------------------
@bp.post("/volunteer-portal/assignment-openings")
def create_opening():
    auth()
    require_roles(request.headers.get("X-User-Role"), ("SystemAdmin",))
    data = body()
    # Existence (priority 4): body FK present-but-unknown -> 404.
    program = None
    if data.get("country_program_id") is not None:
        program = STORE["country_programs"].get(data["country_program_id"])
        if program is None:
            err("ERR_PROGRAM_NOT_FOUND", 404, "Country program not found")
    # Business constraint (priority 8): new openings require an OPEN program.
    if program is not None and program["status"] != "OPEN":
        err("ERR_OPENING_NOT_OPEN", 409, "Country program is not OPEN")
    # Field shape (priority 10)
    program_id = as_str(data, "country_program_id")
    sector = as_enum(data, "sector", SECTORS)
    title = as_str(data, "title")
    required = as_enum_list(data, "required_skills", SKILL_CATALOG)
    preferred = as_enum_list(data, "preferred_skills", SKILL_CATALOG, required=False) or []
    seats_total = as_int(data, "seats_total", minimum=1)
    departure = as_dt(data, "departure_date")
    issue_deadline = as_dt(data, "invitation_issue_deadline")
    rec = new_record()
    rec.update({
        "country_program_id": program_id,
        "sector": sector,
        "title": title,
        "required_skills": list(required),
        "preferred_skills": list(preferred),
        "seats_total": seats_total,
        "seats_provisional": 0,
        "seats_committed": 0,
        "departure_date": fmt_ts(departure),
        "invitation_issue_deadline": fmt_ts(issue_deadline),
        "status": "OPEN",
    })
    STORE["assignment_openings"][rec["id"]] = rec
    return ok_object(rec, 201)


def get_opening_or_404(oid):
    opening = STORE["assignment_openings"].get(oid)
    if opening is None:
        err("ERR_OPENING_NOT_FOUND", 404, "Assignment opening not found")
    return opening


@bp.get("/volunteer-portal/assignment-openings/<oid>")
def get_opening(oid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    return ok_object(get_opening_or_404(oid))


@bp.get("/volunteer-portal/assignment-openings")
def list_openings():
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    args = request.args
    records = sorted(STORE["assignment_openings"].values(),
                     key=lambda r: r["created_at"])
    if args.get("country_program_id") is not None:
        records = [r for r in records
                   if r["country_program_id"] == args["country_program_id"]]
    if args.get("status") is not None:
        records = [r for r in records if r["status"] == args["status"]]
    if args.get("sector") is not None:
        records = [r for r in records if r["sector"] == args["sector"]]
    return paginate(records)


@bp.post("/volunteer-portal/assignment-openings/<oid>/cancel")
def cancel_opening(oid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("SystemAdmin",))
    opening = get_opening_or_404(oid)
    # State guard (priority 6): cancellation exists only from OPEN | FILLED.
    if opening["status"] not in ("OPEN", "FILLED"):
        err("ERR_OPENING_NOT_OPEN", 409,
            "Opening cannot be cancelled from status %s" % opening["status"])
    opening["status"] = "CANCELLED"
    touch(opening)
    cancel_opening_cascade(opening)
    return ok_object(opening)

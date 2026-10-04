"""Applications: creation, submit/withdraw/review/reject, and the match list."""
from flask import Blueprint, request

from authz import auth, require_owner, require_roles
from calc import country_bonus, strict_met, strict_score, weighted_score
from cascade import withdraw_cascade
from db import (ROLES, SECTORS, STORE, logical_now, new_record, parse_dt,
                touch, ts_sec)
from errors import err, ok_object, paginate
from validate import as_enum_list, as_str, as_str_list, body

bp = Blueprint("applications", __name__)

NON_TERMINAL = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "INTERVIEWING", "EVALUATED",
                "INVITED", "ACCEPTED", "CLEARED_TO_DEPART", "IN_TRAINING")


def get_application_or_404(aid):
    app = STORE["applications"].get(aid)
    if app is None:
        err("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    return app


@bp.post("/volunteer-portal/applications")
def create_application():
    user_id, role = auth()
    require_roles(role, ("Applicant",))
    data = body()
    # Ownership (priority 3): X-User-ID must equal the payload's applicant_id.
    applicant_id = data.get("applicant_id")
    if applicant_id is not None:
        require_owner(user_id, applicant_id)
    # Existence (priority 4): applicant FK and each country preference entry.
    if applicant_id is not None and applicant_id not in STORE["applicants"]:
        err("ERR_APPLICANT_NOT_FOUND", 404, "Applicant not found")
    prefs = data.get("country_preference_ids")
    if isinstance(prefs, list):
        for pid in prefs:
            if pid not in STORE["country_programs"]:
                err("ERR_PROGRAM_NOT_FOUND", 404, "Country program not found")
    # Field shape (priority 10)
    applicant_id = as_str(data, "applicant_id")
    sector_prefs = as_enum_list(data, "sector_preferences", SECTORS, required=False) or []
    prefs = as_str_list(data, "country_preference_ids", required=False) or []
    if len(set(prefs)) != len(prefs):
        err("ERR_VALIDATION", 400, "country_preference_ids must not contain duplicates")
    statement = as_str(data, "statement", required=False) or ""
    rec = new_record()
    rec.update({
        "applicant_id": applicant_id,
        "country_preference_ids": list(prefs),
        "sector_preferences": list(sector_prefs),
        "statement": statement,
        "status": "DRAFT",
    })
    STORE["applications"][rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/volunteer-portal/applications/<aid>")
def get_application(aid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    return ok_object(get_application_or_404(aid))


@bp.get("/volunteer-portal/applications")
def list_applications():
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    args = request.args
    records = sorted(STORE["applications"].values(), key=lambda r: r["created_at"])
    if args.get("applicant_id") is not None:
        records = [r for r in records if r["applicant_id"] == args["applicant_id"]]
    if args.get("status") is not None:
        records = [r for r in records if r["status"] == args["status"]]
    return paginate(records)


@bp.post("/volunteer-portal/applications/<aid>/submit")
def submit_application(aid):
    user_id, role = auth()
    require_roles(role, ("Applicant",))
    app = get_application_or_404(aid)
    require_owner(user_id, app["applicant_id"])
    if app["status"] != "DRAFT":
        err("ERR_INVALID_APPLICATION_STATE", 409,
            "submit requires DRAFT, found %s" % app["status"])
    if len(app["sector_preferences"]) < 1:
        err("ERR_VALIDATION", 400, "submit requires at least one sector preference")
    app["status"] = "SUBMITTED"
    touch(app)
    return ok_object(app)


@bp.post("/volunteer-portal/applications/<aid>/withdraw")
def withdraw_application(aid):
    user_id, role = auth()
    require_roles(role, ("Applicant",))
    app = get_application_or_404(aid)
    require_owner(user_id, app["applicant_id"])
    if app["status"] not in NON_TERMINAL:
        err("ERR_INVALID_APPLICATION_STATE", 409,
            "withdraw is not available from %s" % app["status"])
    withdraw_cascade(app)
    app["status"] = "WITHDRAWN"
    touch(app)
    return ok_object(app)


@bp.post("/volunteer-portal/applications/<aid>/begin-review")
def begin_review(aid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("PlacementOfficer",))
    app = get_application_or_404(aid)
    if app["status"] != "SUBMITTED":
        err("ERR_INVALID_APPLICATION_STATE", 409,
            "begin-review requires SUBMITTED, found %s" % app["status"])
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return ok_object(app)


@bp.post("/volunteer-portal/applications/<aid>/reject")
def reject_application(aid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("PlacementOfficer",))
    app = get_application_or_404(aid)
    if app["status"] not in ("UNDER_REVIEW", "EVALUATED"):
        err("ERR_INVALID_APPLICATION_STATE", 409,
            "reject requires UNDER_REVIEW or EVALUATED, found %s" % app["status"])
    app["status"] = "NOT_SELECTED"
    touch(app)
    return ok_object(app)


@bp.get("/volunteer-portal/applications/<aid>/matches")
def application_matches(aid):
    user_id, role = auth()
    require_roles(role, ("PlacementOfficer", "Applicant"))
    app = get_application_or_404(aid)
    if role == "Applicant":
        require_owner(user_id, app["applicant_id"])
    if app["status"] == "DRAFT":
        err("ERR_INVALID_APPLICATION_STATE", 409,
            "matches require the application to have left DRAFT")
    applicant = STORE["applicants"].get(app["applicant_id"])
    skills = applicant["skills"] if applicant is not None else []
    prefs = app["country_preference_ids"]
    now = ts_sec(logical_now())
    candidates = []
    for opening in STORE["assignment_openings"].values():
        if opening["status"] != "OPEN":
            continue
        deadline = parse_dt(opening["invitation_issue_deadline"])
        if deadline is not None and ts_sec(deadline) < now:
            continue
        if opening["seats_provisional"] + opening["seats_committed"] >= opening["seats_total"]:
            continue
        if not strict_met(opening["required_skills"], skills):
            continue
        if prefs and opening["country_program_id"] not in prefs:
            continue
        strict = strict_score(opening["required_skills"], skills)
        sector_bonus = 1.0 if opening["sector"] in app["sector_preferences"] else 0.0
        c_bonus = country_bonus(prefs, opening["country_program_id"])
        w = weighted_score(strict, sector_bonus, c_bonus)
        candidates.append({
            "assignment_opening_id": opening["id"],
            "country_program_id": opening["country_program_id"],
            "sector": opening["sector"],
            "departure_date": opening["departure_date"],
            "strict_score": float(strict),
            "weighted_score": w,
            "_departure": parse_dt(opening["departure_date"]),
            "_created": opening["created_at"],
        })
    candidates.sort(key=lambda c: (-c["weighted_score"], c["_departure"], c["_created"]))
    matches = [{k: v for k, v in c.items() if not k.startswith("_")}
               for c in candidates]
    return ok_object({"matches": matches})

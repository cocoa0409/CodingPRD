"""Employer partnership and job opening endpoints — PRD sections 3.4 and 3.6."""

from flask import Blueprint

from cascades import terminate_partnership
from common import list_result, match_filters, READ_ROLES, resolve
from domain import (
    INDUSTRIES, RECORD_CATEGORIES, openings_of_partnership,
    placements_of_partnership, rows,
)
from envelope import created, ok
from errors import fail
from matching import blocking_error, score_match
from store import db, new_row, public, touch
from validation import (
    body, opt_bool, opt_enum_array, opt_str, req_date, req_enum, req_int,
    req_num, req_str, require_roles,
)

bp = Blueprint("partnerships", __name__)

LIAISON = ["EmployerLiaison"]
PARTNERSHIP_TARGETS = ["ENGAGED", "ACTIVE", "SUSPENDED", "TERMINATED"]
PARTNERSHIP_EDGES = {
    ("PROSPECT", "ENGAGED"),
    ("ENGAGED", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
}


# --------------------------------------------------------------------------
# employer partnerships
# --------------------------------------------------------------------------

@bp.post("/employer-partnerships")
def create_partnership():
    require_roles(LIAISON)
    payload = body()
    employer_name = req_str(payload, "employer_name")
    industry = req_enum(payload, "industry", INDUSTRIES)
    max_concurrent = req_int(payload, "max_concurrent_placements", minimum=1)
    wotc = opt_bool(payload, "wotc_certified", default=False)
    excluded = opt_enum_array(payload, "excluded_record_categories",
                              RECORD_CATEGORIES, default=[])

    row = new_row(
        employer_name=employer_name,
        industry=industry,
        max_concurrent_placements=max_concurrent,
        wotc_certified=wotc,
        excluded_record_categories=excluded,
        status="PROSPECT",
        active_placement_count=0,
        fidelity_bond_enabled=False,
        bond_coverage_cents=None,
        bond_effective_date=None,
    )
    db.partnerships[row["id"]] = row
    return created(public(row))


@bp.get("/employer-partnerships/<partnership_id>")
def read_partnership(partnership_id):
    require_roles(READ_ROLES)
    partnership = resolve("partnerships", db.partnerships, partnership_id)
    return ok(public(partnership))


@bp.get("/employer-partnerships")
def list_partnerships():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.partnerships),
        string_filters=["status"],
        bool_filters=["wotc_certified", "fidelity_bond_enabled"],
    )
    return list_result(result)


@bp.post("/employer-partnerships/<partnership_id>/status")
def drive_partnership_status(partnership_id):
    require_roles(LIAISON)
    payload = body()
    to_status = req_enum(payload, "to_status", PARTNERSHIP_TARGETS)

    partnership = resolve("partnerships", db.partnerships, partnership_id)
    if (partnership["status"], to_status) not in PARTNERSHIP_EDGES:
        fail("ERR_PARTNERSHIP_INVALID_STATE",
             "That partnership transition is not declared")

    if to_status == "TERMINATED":
        active = [p for p in placements_of_partnership(partnership_id)
                  if p["employment_status"] == "ACTIVE"]
        if int(partnership["active_placement_count"]) != 0 or active:
            fail("ERR_PARTNERSHIP_HAS_ACTIVE_PLACEMENTS",
                 "Drain every active placement before terminating")
        partnership["status"] = "TERMINATED"
        touch(partnership)
        terminate_partnership(partnership)
    else:
        partnership["status"] = to_status
        touch(partnership)
    return ok(public(partnership))


@bp.post("/employer-partnerships/<partnership_id>/bonding-agreement")
def record_bonding_agreement(partnership_id):
    require_roles(LIAISON)
    payload = body()
    coverage = req_int(payload, "bond_coverage_cents", minimum=1)
    req_date(payload, "bond_effective_date")

    partnership = resolve("partnerships", db.partnerships, partnership_id)
    if partnership["status"] in ("SUSPENDED", "TERMINATED"):
        fail("ERR_PARTNERSHIP_INVALID_STATE",
             "A suspended or terminated partnership may not record bonding")
    if partnership["fidelity_bond_enabled"]:
        fail("ERR_BOND_ALREADY_RECORDED",
             "This partnership already carries a fidelity bond")

    partnership["fidelity_bond_enabled"] = True
    partnership["bond_coverage_cents"] = coverage
    partnership["bond_effective_date"] = payload["bond_effective_date"]
    touch(partnership)
    return ok(public(partnership))


@bp.get("/employer-partnerships/<partnership_id>/job-openings")
def list_partnership_openings(partnership_id):
    require_roles(READ_ROLES)
    resolve("partnerships", db.partnerships, partnership_id)
    result = match_filters(openings_of_partnership(partnership_id),
                           string_filters=["status"])
    return list_result(result)


# --------------------------------------------------------------------------
# job openings
# --------------------------------------------------------------------------

@bp.post("/job-openings")
def create_opening():
    require_roles(LIAISON)
    payload = body()
    partnership_id = req_str(payload, "partnership_id")
    title = req_str(payload, "title")
    occupation_code = req_str(payload, "occupation_code")
    wage = req_int(payload, "hourly_wage_cents", minimum=725)
    weekly_hours = req_num(payload, "weekly_hours", maximum=60,
                           exclusive_min=0)
    openings_count = req_int(payload, "openings_count", minimum=1)
    barred = opt_enum_array(payload, "barred_record_categories",
                            RECORD_CATEGORIES, default=[])
    requires_license = opt_bool(payload, "requires_license", default=False)
    license_code = opt_str(payload, "license_occupation_code")
    requires_bond = opt_bool(payload, "requires_fidelity_bond", default=False)
    transit = opt_bool(payload, "transit_accessible", default=False)

    if partnership_id not in db.partnerships:
        fail("ERR_PARTNERSHIP_NOT_FOUND", "partnership_id matches no partnership")

    row = new_row(
        partnership_id=partnership_id,
        title=title,
        occupation_code=occupation_code,
        hourly_wage_cents=wage,
        weekly_hours=weekly_hours,
        openings_count=openings_count,
        barred_record_categories=barred,
        requires_license=requires_license,
        license_occupation_code=license_code,
        requires_fidelity_bond=requires_bond,
        transit_accessible=transit,
        status="OPEN",
        offered_count=0,
        filled_count=0,
        remaining_openings=openings_count,
    )
    db.job_openings[row["id"]] = row
    return created(public(row))


@bp.get("/job-openings/<opening_id>")
def read_opening(opening_id):
    require_roles(READ_ROLES)
    opening = resolve("job_openings", db.job_openings, opening_id)
    return ok(public(opening))


@bp.get("/job-openings")
def list_openings():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.job_openings),
        string_filters=["partnership_id", "status"],
        bool_filters=["requires_license", "transit_accessible"],
    )
    return list_result(result)


@bp.get("/job-openings/<opening_id>/match-preview")
def match_preview(opening_id):
    require_roles(["CaseManager", "EmployerLiaison", "ProgramDirector"])
    from flask import request
    participant_id = request.args.get("participant_id")
    if participant_id is None or participant_id.strip() == "":
        fail("ERR_VALIDATION", "participant_id is required")

    opening = resolve("job_openings", db.job_openings, opening_id)
    participant = resolve("participants", db.participants, participant_id)
    partnership = db.partnerships.get(opening["partnership_id"])

    score, breakdown = score_match(participant, opening, partnership)
    blocking = blocking_error(participant, opening, partnership)
    return ok({
        "job_opening_id": opening["id"],
        "participant_id": participant["id"],
        "match_score": score,
        "match_breakdown": breakdown,
        "eligible": blocking is None,
        "blocking_error_id": blocking,
    })

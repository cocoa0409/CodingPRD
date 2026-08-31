"""The development slate and its two independent state axes."""

from flask import Blueprint

import calc
from core import (
    Field, add_months, authenticate, collection_rows, created, db, fail, filter_eq,
    fmt_dt, json_body, lookup, new_row, now, now_str, ok, ok_list, paginate,
    pagination, parse_dt, parse_fields, qp, qp_int, touch,
)

bp = Blueprint("project", __name__)

PROJECT_READ_ROLES = ("SlateAdmin", "DevelopmentExec", "BusinessAffairs", "StoryEditor",
                      "CommitteeMember")


@bp.post("/development-projects")
def create_project():
    user_id, _role = authenticate(("DevelopmentExec",))
    body = json_body()
    prop = None
    option = None
    if body.get("property_id") is not None:
        prop = lookup("properties", body.get("property_id"), "ERR_PROPERTY_NOT_FOUND")
    if body.get("option_agreement_id") is not None:
        option = lookup("options", body.get("option_agreement_id"), "ERR_OPTION_NOT_FOUND")
    data = parse_fields(body, [
        Field("property_id", "string", required=True),
        Field("option_agreement_id", "string", required=True),
        Field("budget_cents", "integer", required=True, lo=1),
        Field("slate_year", "integer", required=True),
    ])
    if option["property_id"] != prop["id"]:
        fail("ERR_OPTION_MISMATCH",
             "The option agreement does not belong to the named property.")
    row = new_row("projects", {
        "property_id": prop["id"],
        "option_agreement_id": option["id"],
        "owning_exec_user_id": user_id,
        "budget_cents": data["budget_cents"],
        "slate_year": data["slate_year"],
        "rights_status": "OPTIONED",
        "development_status": "SETUP",
        "committed_writer_fee_cents": 0,
        "writer_budget_cap_cents": calc.project_writer_budget_cap(data["budget_cents"]),
        "turnaround_start_at": None,
        "turnaround_eligible_at": None,
        "turnaround_reason": None,
        "greenlight_ready": False,
    })
    calc.option_pricing(option)
    touch(option)
    for submission in calc.rows_where("submissions", property_id=prop["id"]):
        if submission["status"] == "TRACKED":
            submission["status"] = "IN_DEVELOPMENT"
            touch(submission)
    return created(row)


@bp.get("/development-projects/<pid>")
def read_project(pid):
    authenticate(PROJECT_READ_ROLES)
    return ok(lookup("projects", pid, "ERR_PROJECT_NOT_FOUND"))


@bp.get("/development-projects")
def list_projects():
    authenticate(PROJECT_READ_ROLES)
    limit, offset = pagination()
    rows = collection_rows("projects")
    rows = filter_eq(rows, "property_id", qp("property_id"))
    rows = filter_eq(rows, "option_agreement_id", qp("option_agreement_id"))
    rows = filter_eq(rows, "development_status", qp("development_status"))
    rows = filter_eq(rows, "rights_status", qp("rights_status"))
    rows = filter_eq(rows, "slate_year", qp_int("slate_year"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/development-projects/<pid>/place-in-turnaround")
def place_in_turnaround(pid):
    authenticate(("DevelopmentExec",))
    project = lookup("projects", pid, "ERR_PROJECT_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("reason", "string", required=True)])
    if project["development_status"] in ("GREENLIT", "TURNAROUND", "DEAD"):
        fail("ERR_INVALID_STATE", "This project may not be placed in turnaround.")
    start = now()
    project["development_status"] = "TURNAROUND"
    project["turnaround_start_at"] = fmt_dt(start)
    project["turnaround_eligible_at"] = fmt_dt(
        add_months(start, calc.TURNAROUND_REVERSION_MONTHS))
    project["turnaround_reason"] = data["reason"]
    calc.recompute_greenlight_ready(project)
    calc.terminate_open_engagements(project, None)
    touch(project)
    calc.withdraw_open_reviews(project, "PROJECT_IN_TURNAROUND")
    return ok(project)


@bp.post("/development-projects/<pid>/reversion-notice")
def reversion_notice(pid):
    authenticate(("BusinessAffairs",))
    project = lookup("projects", pid, "ERR_PROJECT_NOT_FOUND")
    if project["development_status"] != "TURNAROUND":
        fail("ERR_INVALID_STATE", "Only a project in TURNAROUND may take a reversion notice.")
    eligible = project.get("turnaround_eligible_at")
    if eligible is None or now() < parse_dt(eligible):
        fail("ERR_TURNAROUND_NOT_MATURE", "The eighteen-month reversion clock has not matured.")
    option = db.options.get(project["option_agreement_id"])
    if option is None or option["status"] != "EXERCISED":
        fail("ERR_INVALID_STATE", "The linked option agreement is not EXERCISED.")
    option["status"] = "REVERTED"
    touch(option)
    project["development_status"] = "DEAD"
    project["rights_status"] = "REVERTED"
    calc.recompute_greenlight_ready(project)
    touch(project)
    prop = db.properties.get(project["property_id"])
    if prop is not None:
        calc.recompute_encumbrance(prop)
        if prop["rights_chain_status"] == "CLEAR":
            prop["rights_chain_status"] = "PARTIAL"
        touch(prop)
    return ok(project)

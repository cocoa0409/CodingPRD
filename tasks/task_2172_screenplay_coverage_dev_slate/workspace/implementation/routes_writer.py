"""Writers, engagements and the milestone ladder."""

from flask import Blueprint

import calc
from core import (
    Field, authenticate, collection_rows, created, db, fail, filter_eq, fmt_dt,
    json_body, lookup, new_row, now, now_str, ok, ok_list, paginate, pagination,
    parse_date, parse_fields, qp, qp_bool, sort_rows, touch,
)

bp = Blueprint("writer", __name__)

WRITER_READ_ROLES = ("SlateAdmin", "DevelopmentExec", "BusinessAffairs", "Writer")
WRITER_LIST_ROLES = ("SlateAdmin", "DevelopmentExec", "BusinessAffairs")


# --------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------
@bp.post("/writers")
def create_writer():
    authenticate(("SlateAdmin",))
    body = json_body()
    data = parse_fields(body, [
        Field("name", "string", required=True),
        Field("guild_member", "boolean", default=True),
        Field("quote_cents", "integer", required=True),
        Field("status", "enum", default="ACTIVE", enum=calc.WRITER_STATUSES),
    ])
    row = new_row("writers", {
        "name": data["name"],
        "guild_member": data["guild_member"],
        "quote_cents": data["quote_cents"],
        "status": data["status"],
        "committed_fee_cents": 0,
        "paid_fee_cents": 0,
        "active_engagement_count": 0,
    })
    return created(row)


@bp.get("/writers/<wid>")
def read_writer(wid):
    authenticate(WRITER_READ_ROLES)
    return ok(lookup("writers", wid, "ERR_WRITER_NOT_FOUND"))


@bp.get("/writers")
def list_writers():
    authenticate(WRITER_LIST_ROLES)
    limit, offset = pagination()
    rows = collection_rows("writers")
    rows = filter_eq(rows, "status", qp("status"))
    rows = filter_eq(rows, "guild_member", qp_bool("guild_member"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# --------------------------------------------------------------------------
# Engagements
# --------------------------------------------------------------------------
@bp.post("/writer-engagements")
def create_engagement():
    authenticate(("DevelopmentExec",))
    body = json_body()
    project = None
    writer = None
    if body.get("project_id") is not None:
        project = lookup("projects", body.get("project_id"), "ERR_PROJECT_NOT_FOUND")
    if body.get("writer_id") is not None:
        writer = lookup("writers", body.get("writer_id"), "ERR_WRITER_NOT_FOUND")
    data = parse_fields(body, [
        Field("project_id", "string", required=True),
        Field("writer_id", "string", required=True),
        Field("engagement_type", "enum", required=True, enum=calc.ENGAGEMENT_TYPES),
        Field("total_fee_cents", "integer", required=True, lo=1),
        Field("start_date", "date", required=True),
        Field("end_date", "date", required=True),
        Field("expected_project_version", "integer", required=True),
    ])
    parse_date(data["start_date"])
    parse_date(data["end_date"])
    if data["expected_project_version"] != project["version"]:
        fail("ERR_STALE_VERSION", "The project has changed since it was last observed.")
    if project["development_status"] in calc.DEV_BLOCKED_FOR_CREATE:
        fail("ERR_INVALID_STATE", "This project may not take a new engagement proposal.")
    if (project["committed_writer_fee_cents"] + data["total_fee_cents"]
            > project["writer_budget_cap_cents"]):
        fail("ERR_BUDGET_EXCEEDED", "The project's writer budget headroom is exhausted.")
    guild_minimum = (calc.GUILD_MINIMUM_FEE_CENTS[data["engagement_type"]]
                     if writer["guild_member"] else 0)
    if data["total_fee_cents"] < guild_minimum:
        fail("ERR_GUILD_MINIMUM_VIOLATION", "The fee is below the guild minimum.")
    row = new_row("engagements", {
        "project_id": project["id"],
        "writer_id": writer["id"],
        "engagement_type": data["engagement_type"],
        "total_fee_cents": data["total_fee_cents"],
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "status": "PROPOSED",
        "guild_minimum_cents": guild_minimum,
        "milestone_count": 0,
        "termination_reason": None,
    })
    for existing in calc.engagements_of_project(project["id"]):
        if existing["id"] == row["id"]:
            continue
        if (existing["status"] == "PROPOSED"
                and existing["engagement_type"] == row["engagement_type"]):
            existing["status"] = "TERMINATED"
            existing["termination_reason"] = "SUPERSEDED_BY_NEW_PROPOSAL"
            touch(existing)
    touch(project)
    return created(row)


@bp.get("/writer-engagements/<eid>")
def read_engagement(eid):
    authenticate(WRITER_READ_ROLES)
    return ok(lookup("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND"))


@bp.get("/writer-engagements")
def list_engagements():
    authenticate(WRITER_READ_ROLES)
    limit, offset = pagination()
    rows = collection_rows("engagements")
    rows = filter_eq(rows, "project_id", qp("project_id"))
    rows = filter_eq(rows, "writer_id", qp("writer_id"))
    rows = filter_eq(rows, "status", qp("status"))
    rows = filter_eq(rows, "engagement_type", qp("engagement_type"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


def _advance_development_axis(project, engagement_type):
    status = project["development_status"]
    if status == "SETUP" and engagement_type in ("ORIGINAL_DRAFT", "REWRITE",
                                                 "PRODUCTION_REWRITE"):
        project["development_status"] = "WRITING"
    elif status == "DRAFT_DELIVERED" and engagement_type == "REWRITE":
        project["development_status"] = "WRITING"
    elif status == "DRAFT_DELIVERED" and engagement_type == "POLISH":
        project["development_status"] = "POLISH"


@bp.post("/writer-engagements/<eid>/attach")
def attach_engagement(eid):
    authenticate(("DevelopmentExec",))
    engagement = lookup("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if engagement["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a PROPOSED engagement may be attached.")
    writer = db.writers.get(engagement["writer_id"])
    project = db.projects.get(engagement["project_id"])
    if writer is None or writer["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The writer is not ACTIVE.")
    option = db.options.get(project["option_agreement_id"]) if project else None
    if option is None or option["status"] not in calc.OPTION_ENCUMBERING:
        fail("ERR_OPTION_NOT_ACTIVE", "The project's option agreement is not active.")
    if project["development_status"] in calc.DEV_BLOCKED_FOR_CREATE:
        fail("ERR_INVALID_STATE", "This project may not take a writer attachment.")
    if (calc.writer_overlap_count(writer["id"], engagement)
            > calc.WRITER_MAX_CONCURRENT_ENGAGEMENTS - 1):
        fail("ERR_WRITER_OVERCOMMITTED", "The writer is already fully committed.")
    if (project["committed_writer_fee_cents"] + engagement["total_fee_cents"]
            > project["writer_budget_cap_cents"]):
        fail("ERR_BUDGET_EXCEEDED", "The project's writer budget headroom is exhausted.")

    engagement["status"] = "ATTACHED"
    lines = calc.milestone_schedule(engagement)
    for line in lines:
        row = new_row("milestones", {
            "engagement_id": engagement["id"],
            "milestone_type": line["milestone_type"],
            "sequence_index": line["sequence_index"],
            "percentage_bps": line["percentage_bps"],
            "gross_amount_cents": line["gross_amount_cents"],
            "status": "SCHEDULED",
            "due_on": line["due_on"],
            "approved_by_user_id": None,
            "paid_at": None,
        })
        if line["sequence_index"] == 0:
            row["status"] = "DUE"
            touch(row)
    engagement["milestone_count"] = len(lines)
    touch(engagement)
    calc.recompute_writer_ledger(writer)
    touch(writer)
    _advance_development_axis(project, engagement["engagement_type"])
    calc.recompute_project_commitment(project)
    calc.recompute_greenlight_ready(project)
    touch(project)
    return ok(engagement)


@bp.post("/writer-engagements/<eid>/deliver")
def deliver_engagement(eid):
    user_id, _role = authenticate(("Writer",))
    engagement = lookup("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [
        Field("milestone_type", "enum", required=True, enum=calc.MILESTONE_TYPES),
    ])
    if engagement["writer_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This engagement belongs to another writer.")
    if engagement["status"] not in ("ATTACHED", "ACTIVE"):
        fail("ERR_INVALID_STATE", "Only an ATTACHED or ACTIVE engagement may take a delivery.")
    target = None
    for milestone in calc.milestones_of(engagement["id"]):
        if (milestone["milestone_type"] == data["milestone_type"]
                and milestone["status"] == "SCHEDULED"):
            target = milestone
            break
    if target is None:
        fail("ERR_INVALID_STATE", "No SCHEDULED milestone of that type exists.")
    target["status"] = "DUE"
    touch(target)
    project = db.projects.get(engagement["project_id"])
    if project is not None:
        changed = False
        if (data["milestone_type"] == "FIRST_DRAFT_DELIVERY"
                and project["development_status"] == "WRITING"):
            project["development_status"] = "DRAFT_DELIVERED"
            changed = True
        elif (data["milestone_type"] == "POLISH_DELIVERY"
              and project["development_status"] == "POLISH"):
            project["development_status"] = "POLISH_DELIVERED"
            changed = True
        if changed:
            calc.recompute_greenlight_ready(project)
            touch(project)
    return ok(engagement)


@bp.post("/writer-engagements/<eid>/complete")
def complete_engagement(eid):
    authenticate(("DevelopmentExec",))
    engagement = lookup("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if engagement["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE engagement may be completed.")
    for milestone in calc.milestones_of(engagement["id"]):
        if milestone["status"] not in ("PAID", "VOIDED"):
            fail("ERR_INVALID_STATE", "Every milestone must be settled before completion.")
    engagement["status"] = "COMPLETED"
    touch(engagement)
    writer = db.writers.get(engagement["writer_id"])
    if writer is not None:
        calc.recompute_writer_ledger(writer)
        touch(writer)
    return ok(engagement)


@bp.post("/writer-engagements/<eid>/terminate")
def terminate_engagement(eid):
    authenticate(("DevelopmentExec",))
    engagement = lookup("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("reason", "string", required=True)])
    if engagement["status"] in calc.ENGAGEMENT_TERMINAL:
        fail("ERR_TERMINAL_STATE", "This engagement is already in a terminal state.")
    was_attached = engagement["status"] in ("ATTACHED", "ACTIVE")
    engagement["status"] = "TERMINATED"
    engagement["termination_reason"] = data["reason"]
    touch(engagement)
    if was_attached:
        calc.void_engagement_milestones(engagement)
        writer = db.writers.get(engagement["writer_id"])
        if writer is not None:
            calc.recompute_writer_ledger(writer)
            touch(writer)
        project = db.projects.get(engagement["project_id"])
        if project is not None:
            calc.recompute_project_commitment(project)
            touch(project)
    return ok(engagement)


# --------------------------------------------------------------------------
# Milestone payments
# --------------------------------------------------------------------------
@bp.get("/milestone-payments/<mid>")
def read_milestone(mid):
    authenticate(WRITER_READ_ROLES)
    return ok(lookup("milestones", mid, "ERR_MILESTONE_NOT_FOUND"))


@bp.get("/milestone-payments")
def list_milestones():
    authenticate(WRITER_READ_ROLES)
    limit, offset = pagination()
    rows = collection_rows("milestones")
    rows = filter_eq(rows, "engagement_id", qp("engagement_id"))
    rows = filter_eq(rows, "milestone_type", qp("milestone_type"))
    rows = filter_eq(rows, "status", qp("status"))
    rows = sorted(rows, key=lambda m: (m["sequence_index"], m.get("created_at") or "",
                                       m.get("_seq") or 0))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/milestone-payments/<mid>/approve")
def approve_milestone(mid):
    user_id, _role = authenticate(("BusinessAffairs",))
    milestone = lookup("milestones", mid, "ERR_MILESTONE_NOT_FOUND")
    if milestone["status"] != "DUE":
        fail("ERR_INVALID_STATE", "Only a DUE milestone payment may be approved.")
    for other in calc.milestones_of(milestone["engagement_id"]):
        if other["sequence_index"] < milestone["sequence_index"]:
            if other["status"] not in ("PAID", "VOIDED"):
                fail("ERR_MILESTONE_SEQUENCE_VIOLATION",
                     "An earlier milestone on this engagement is unsettled.")
    milestone["status"] = "APPROVED"
    milestone["approved_by_user_id"] = user_id
    touch(milestone)
    return ok(milestone)


@bp.post("/milestone-payments/<mid>/pay")
def pay_milestone(mid):
    user_id, _role = authenticate(("BusinessAffairs",))
    milestone = lookup("milestones", mid, "ERR_MILESTONE_NOT_FOUND")
    if milestone["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED milestone payment may be paid.")
    if milestone["approved_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The paying user may not be the user who approved the milestone.")
    milestone["status"] = "PAID"
    milestone["paid_at"] = now_str()
    touch(milestone)
    engagement = db.engagements.get(milestone["engagement_id"])
    if engagement is not None:
        if milestone["sequence_index"] == 0 and engagement["status"] == "ATTACHED":
            engagement["status"] = "ACTIVE"
            touch(engagement)
        writer = db.writers.get(engagement["writer_id"])
        if writer is not None:
            calc.recompute_writer_ledger(writer)
            touch(writer)
    return ok(milestone)

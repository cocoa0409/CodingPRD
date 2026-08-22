"""Submittal endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_CX_AUTHORITY, ROLE_DESIGN_TEAM, authenticate, body_json, db, fail,
    new_row, ok, ok_list, paginate, public, q, sorted_rows, touch, v_enum, v_string,
)
from finders import get_equipment, get_project, get_submittal

bp = Blueprint("submittals", __name__)


@bp.post("/submittals")
def create_submittal():
    authenticate([ROLE_DESIGN_TEAM])
    body = body_json()
    project_id = v_string(body, "project_id")
    title = v_string(body, "title")
    submittal_kind = v_enum(body, "submittal_kind", calc.SUBMITTAL_KINDS)
    equipment_id = v_string(body, "equipment_id", required=False, default=None)

    get_project(project_id)
    equipment_row = get_equipment(equipment_id) if equipment_id is not None else None

    if equipment_row is not None and equipment_row["project_id"] != project_id:
        fail("ERR_PROJECT_SCOPE_MISMATCH",
             "The equipment unit belongs to a different engagement.")

    row = new_row(db.submittals, {
        "project_id": project_id,
        "equipment_id": equipment_id,
        "title": title,
        "submittal_kind": submittal_kind,
        "status": "RECEIVED",
        "review_round": 1,
        "last_decision": None,
        "review_comment": None,
        "escalation_issue_id": None,
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/submittals")
def list_submittals():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.submittals.values()))
    project_id = q("project_id")
    equipment_id = q("equipment_id")
    status = q("status")
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if equipment_id is not None:
        rows = [r for r in rows if r["equipment_id"] == equipment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/submittals/<submittal_id>")
def read_submittal(submittal_id):
    authenticate(ALL_ROLES)
    return ok(public(get_submittal(submittal_id)))


@bp.post("/submittals/<submittal_id>/review")
def review_submittal(submittal_id):
    authenticate([ROLE_CX_AUTHORITY])
    submittal = get_submittal(submittal_id)
    body = body_json()
    decision = v_enum(body, "decision", calc.REVIEW_DECISIONS)
    comment = v_string(body, "comment")

    if submittal["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "Only a RECEIVED submittal may be reviewed.")

    project = db.projects.get(submittal["project_id"])
    submittal["last_decision"] = decision
    submittal["review_comment"] = comment

    if decision == "APPROVED":
        submittal["status"] = "APPROVED"
    elif decision == "APPROVED_AS_NOTED":
        submittal["status"] = "APPROVED_AS_NOTED"
        services.create_issue(
            project,
            origin="DESIGN_REVIEW",
            severity="S4",
            description="Submittal approved as noted: %s" % comment,
            equipment_id=submittal["equipment_id"],
            source_ref_id=submittal["id"],
            opened_by_user_id="SYSTEM",
        )
    else:
        submittal["status"] = "REVISE_AND_RESUBMIT"
        if submittal["review_round"] == calc.MAX_REVIEW_ROUNDS:
            issue = services.create_issue(
                project,
                origin="SUBMITTAL",
                severity="S2",
                description="Submittal escalated after %d review rounds."
                            % calc.MAX_REVIEW_ROUNDS,
                equipment_id=submittal["equipment_id"],
                source_ref_id=submittal["id"],
                opened_by_user_id="SYSTEM",
            )
            submittal["escalation_issue_id"] = issue["id"]

    touch(submittal)
    services.reconcile()
    return ok(public(submittal))


@bp.post("/submittals/<submittal_id>/resubmit")
def resubmit_submittal(submittal_id):
    authenticate([ROLE_DESIGN_TEAM])
    submittal = get_submittal(submittal_id)
    body = body_json()
    title = v_string(body, "title", required=False, default=None)

    if submittal["status"] != "REVISE_AND_RESUBMIT":
        fail("ERR_INVALID_STATE", "Only a REVISE_AND_RESUBMIT submittal may be resubmitted.")
    if submittal["review_round"] >= calc.MAX_REVIEW_ROUNDS:
        fail("ERR_REVIEW_ROUNDS_EXCEEDED",
             "The submittal has already reached review round %d." % calc.MAX_REVIEW_ROUNDS)

    submittal["status"] = "RECEIVED"
    submittal["review_round"] = submittal["review_round"] + 1
    if title is not None:
        submittal["title"] = title
    touch(submittal)
    services.reconcile()
    return ok(public(submittal))

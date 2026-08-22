"""The demo round: pitching, revising, shortlisting and selecting (PRD 3.3)."""

from flask import Blueprint, g, request

import clock
import db
import ledger
import money
import response
import validators as v
from auth import ALL_ROLES, endpoint, require_demo_owner, require_project_owner
from errors import ApiError

bp = Blueprint("demos", __name__)

REVISION_SURCHARGE_PCT = 15
MAX_REVISION_ROUNDS = 3


def revision_surcharge(demo):
    """Flat: always keyed on the ORIGINAL demo_fee_cents (PRD 3.3)."""
    return money.round_half_up(money.pct(demo["demo_fee_cents"], REVISION_SURCHARGE_PCT))


@bp.post("/projects/<project_id>/demos")
@endpoint(["Composer"])
def create_demo(project_id):
    project = v.path_lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    body = v.get_body()
    title = v.v_string(body, "title")
    demo_fee_cents = v.v_int(body, "demo_fee_cents", minimum=1)
    submitted_length_seconds = v.v_int(body, "submitted_length_seconds", minimum=1)

    if project["status"] != "IN_DEMO":
        raise ApiError("ERR_PROJECT_NOT_IN_DEMO")
    if project["available_cents"] < demo_fee_cents:
        raise ApiError("ERR_PROJECT_BUDGET_EXCEEDED")

    record = db.create(db.demos, {
        "project_id": project["id"],
        "composer_id": g.user_id,
        "title": title,
        "demo_fee_cents": demo_fee_cents,
        "submitted_length_seconds": submitted_length_seconds,
        "revision_count": 0,
        "accrued_fee_cents": demo_fee_cents,
        "last_revision_note": None,
        "selected_at": None,
        "status": "DRAFT",
    })

    ledger.reserve(project, demo_fee_cents)
    ledger.recompute_posture(project)
    db.touch(project)

    return response.created(db.serialize(record))


@bp.get("/demos/<demo_id>")
@endpoint(ALL_ROLES)
def get_demo(demo_id):
    demo = v.path_lookup(db.demos, demo_id, "ERR_DEMO_NOT_FOUND")
    return response.ok(db.serialize(demo))


@bp.get("/demos")
@endpoint(ALL_ROLES)
def list_demos():
    rows = list(db.demos.values())
    project_id = request.args.get("project_id")
    composer_id = request.args.get("composer_id")
    status = request.args.get("status")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if composer_id:
        rows = [r for r in rows if r["composer_id"] == composer_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)


@bp.post("/demos/<demo_id>/submit")
@endpoint(["Composer"])
def submit_demo(demo_id):
    demo = v.path_lookup(db.demos, demo_id, "ERR_DEMO_NOT_FOUND")
    require_demo_owner(demo)
    project = db.projects[demo["project_id"]]

    if demo["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_DEMO_INVALID_STATE")
    if project["status"] != "IN_DEMO":
        raise ApiError("ERR_PROJECT_NOT_IN_DEMO")

    demo["status"] = "SUBMITTED"
    db.touch(demo)
    return response.ok(db.serialize(demo))


@bp.post("/demos/<demo_id>/request-revision")
@endpoint(["ClientRep"])
def request_revision(demo_id):
    demo = v.path_lookup(db.demos, demo_id, "ERR_DEMO_NOT_FOUND")
    project = db.projects[demo["project_id"]]
    require_project_owner(project)

    body = v.get_body()
    revision_note = v.v_string(body, "revision_note")

    if demo["status"] not in ("SUBMITTED", "SHORTLISTED"):
        raise ApiError("ERR_DEMO_INVALID_STATE")
    if project["status"] != "IN_DEMO":
        raise ApiError("ERR_PROJECT_NOT_IN_DEMO")
    if demo["revision_count"] >= MAX_REVISION_ROUNDS:
        raise ApiError("ERR_DEMO_REVISION_LIMIT_REACHED")

    surcharge = revision_surcharge(demo)
    if project["available_cents"] < surcharge:
        raise ApiError("ERR_PROJECT_BUDGET_EXCEEDED")

    demo["status"] = "REVISION_REQUESTED"
    demo["revision_count"] += 1
    demo["last_revision_note"] = revision_note
    demo["accrued_fee_cents"] += surcharge
    db.touch(demo)

    ledger.reserve(project, surcharge)
    ledger.recompute_posture(project)
    db.touch(project)

    return response.ok(db.serialize(demo))


@bp.post("/demos/<demo_id>/shortlist")
@endpoint(["ClientRep"])
def shortlist_demo(demo_id):
    demo = v.path_lookup(db.demos, demo_id, "ERR_DEMO_NOT_FOUND")
    project = db.projects[demo["project_id"]]
    require_project_owner(project)

    if demo["status"] != "SUBMITTED":
        raise ApiError("ERR_DEMO_INVALID_STATE")
    if project["status"] != "IN_DEMO":
        raise ApiError("ERR_PROJECT_NOT_IN_DEMO")

    demo["status"] = "SHORTLISTED"
    db.touch(demo)
    return response.ok(db.serialize(demo))


@bp.post("/demos/<demo_id>/select")
@endpoint(["ClientRep"])
def select_demo(demo_id):
    demo = v.path_lookup(db.demos, demo_id, "ERR_DEMO_NOT_FOUND")
    project = db.projects[demo["project_id"]]
    require_project_owner(project)

    if demo["status"] != "SHORTLISTED":
        raise ApiError("ERR_DEMO_INVALID_STATE")
    if project["status"] != "IN_DEMO":
        raise ApiError("ERR_PROJECT_NOT_IN_DEMO")

    # HOP 1 -- the winning pitch is paid for.
    demo["status"] = "SELECTED"
    demo["selected_at"] = clock.now_iso()
    db.touch(demo)
    ledger.settle(project, demo["accrued_fee_cents"])

    # HOP 2 -- the engagement moves into production.
    project["status"] = "IN_PRODUCTION"

    # HOP 3 / 4 -- siblings are archived and their reservations released.
    siblings = db.by_created([
        d for d in db.demos.values()
        if d["project_id"] == project["id"]
        and d["id"] != demo["id"]
        and d["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "SHORTLISTED")
    ])
    for sibling in siblings:
        sibling["status"] = "ARCHIVED"
        db.touch(sibling)
        ledger.release(project, sibling["accrued_fee_cents"])

    # HOP 5 -- posture recomputed, suspended calls swept back when HEALTHY.
    ledger.recompute_posture(project)
    db.touch(project)

    return response.ok(db.serialize(demo))

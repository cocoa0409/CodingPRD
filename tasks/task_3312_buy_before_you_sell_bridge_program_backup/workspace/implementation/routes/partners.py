"""Referral and coordination-task routes (PRD 3.7)."""

from flask import Blueprint

from constants import ROLES, TASK_KINDS
from errors import ERR_INVALID_STATE, ERR_OVERLAPPING_TASK, ApiError
from routes import endpoint, json_body, query_params
from services import agency, coordination
from services import current_time, create, touch
from services.lookup import get_bridge_program, get_coordination_task, get_referral
from store import db
from timeutil import format_iso
from validation import body_of, get_datetime, get_enum, get_int, get_str

bp = Blueprint("partners", __name__)

COORDINATOR = ROLES[0]
AGENT = ROLES[3]


# --- Referrals -------------------------------------------------------------

@bp.post("/knock/referrals")
@endpoint([COORDINATOR], status=201)
def create_referral(actor):
    return agency.create_referral(json_body())


@bp.get("/knock/referrals")
@endpoint([COORDINATOR, AGENT])
def list_referrals(actor):
    params = query_params()
    records = db.all("referrals")
    for field in ("agent_id", "bridge_program_id", "status"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/referrals/<referral_id>")
@endpoint([COORDINATOR, AGENT])
def read_referral(actor, referral_id):
    return get_referral(referral_id)


@bp.patch("/knock/referrals/<referral_id>")
@endpoint([COORDINATOR])
def update_referral(actor, referral_id):
    return agency.update_referral(referral_id, json_body())


@bp.post("/knock/referrals/<referral_id>/complete")
@endpoint([COORDINATOR])
def complete_referral(actor, referral_id):
    return agency.complete_referral(referral_id)


@bp.post("/knock/referrals/<referral_id>/void")
@endpoint([COORDINATOR])
def void_referral(actor, referral_id):
    return agency.void_referral(referral_id)


@bp.post("/knock/referrals/<referral_id>/reopen")
@endpoint([COORDINATOR])
def reopen_referral(actor, referral_id):
    return agency.reopen_referral(referral_id, json_body())


# --- Coordination tasks ----------------------------------------------------

@bp.post("/knock/coordination-tasks")
@endpoint([COORDINATOR], status=201)
def create_task(actor):
    data = body_of(json_body())
    program_id = get_str(data, "bridge_program_id", required=True)
    referral_id = get_str(data, "referral_id", required=True)
    task_kind = get_enum(data, "task_kind", TASK_KINDS, required=True)
    due_date = get_datetime(data, "due_date", required=True)

    program = get_bridge_program(program_id)
    referral = get_referral(referral_id)

    if coordination.find_overlapping_task(referral["id"], due_date) is not None:
        raise ApiError(
            ERR_OVERLAPPING_TASK,
            "The new task's slot overlaps a non-terminal task for this referral.",
        )

    record = {
        "bridge_program_id": program["id"],
        "referral_id": referral["id"],
        "task_kind": task_kind,
        "due_date": format_iso(due_date),
        "status": "OPEN",
        "completed_at": None,
    }
    create("coordination_tasks", record)
    return record


@bp.get("/knock/coordination-tasks")
@endpoint([COORDINATOR, AGENT])
def list_tasks(actor):
    params = query_params()
    records = db.all("coordination_tasks")
    for field in ("bridge_program_id", "referral_id", "status"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/coordination-tasks/<task_id>")
@endpoint([COORDINATOR, AGENT])
def read_task(actor, task_id):
    return get_coordination_task(task_id)


@bp.post("/knock/coordination-tasks/<task_id>/complete")
@endpoint([AGENT, COORDINATOR])
def complete_task(actor, task_id):
    task = get_coordination_task(task_id)
    referral = get_referral(task["referral_id"])
    program = get_bridge_program(task["bridge_program_id"])

    if task.get("status") not in ("OPEN", "IN_PROGRESS"):
        raise ApiError(ERR_INVALID_STATE, "Only an OPEN or IN_PROGRESS task may be completed.")

    task["status"] = "COMPLETED"
    task["completed_at"] = format_iso(current_time())
    touch(task)

    # Completing the terminal task re-evaluates the referral's backfill.
    if referral.get("status") == "OPEN":
        if coordination.all_tasks_completed(referral["id"]) and int(
            referral.get("qualifying_volume_cents") or 0
        ) > 0:
            referral["status"] = "COMPLETED"
            referral["completed_at"] = format_iso(current_time())
            touch(referral)

    agent = db.get("agents", referral.get("agent_id"))
    if agent is not None:
        agency.recompute_agent_active_referrals(agent)
        touch(agent)

    from services import referral as referral_service

    referral_service.refresh_fee_fields(referral, agent)
    return task
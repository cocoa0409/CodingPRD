"""Outages: authoring, safety review, approval and the deepest cascade (PRD 3.9)."""
from flask import Blueprint, request

import calc
import cascade
import serialize
import validate as v
from auth import ALL_ROLES, PROCESS_ENGINEER, SAFETY_OFFICER, actor
from envelope import list_response, object_response, paging
from guards import duplicate, filtered, load, state
from mutate import touch
from store import by_seq, db, stamp_new
from util import D, whole_days

bp = Blueprint("turnarounds", __name__)
PREFIX = "/nitrogen-ops/turnarounds"
SCOPES = ("CATALYST_CHANGE", "VESSEL_INSPECTION", "COMBINED")
TURNAROUND_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED",
                       "IN_PROGRESS", "COMPLETED")
NEIGHBOUR_STATUSES = ("APPROVED", "IN_PROGRESS", "COMPLETED")


def _buffer_conflict(turnaround):
    """Rung 20: closed-window intersection or less than 14 whole days of separation."""
    ws, we = turnaround["window_start"], turnaround["window_end"]
    for other in db.turnarounds.values():
        if other["id"] == turnaround["id"] or other["plant_id"] != turnaround["plant_id"]:
            continue
        if other["status"] not in NEIGHBOUR_STATUSES:
            continue
        if other["window_start"] <= we and other["window_end"] >= ws:
            return True
        if other["window_end"] < ws:
            gap = whole_days(ws, other["window_end"])
        else:
            gap = whole_days(other["window_start"], we)
        if gap < calc.TURNAROUND_BUFFER_DAYS:
            return True
    return False


def _feasible(turnaround):
    _, critical = calc.task_schedule(turnaround["id"])
    return critical <= turnaround["window_days"]


@bp.post(PREFIX)
def create_turnaround():
    who = actor([PROCESS_ENGINEER])
    body = v.get_body()
    plant_id = v.s_id(body, "plant_id")
    train_id = v.s_id(body, "train_id")
    code = v.s_code(body, "turnaround_code", 2, 16)
    scope = v.s_enum(body, "scope", SCOPES)
    window_start = v.s_dt(body, "window_start")
    window_end = v.s_dt(body, "window_end")
    if window_end <= window_start:
        v.bad("window_end must be strictly after window_start.")
    load("plants", plant_id)
    load("trains", train_id)
    duplicate("turnarounds", "turnaround_code", code, scope=("plant_id", plant_id))
    days = whole_days(window_end, window_start)
    row = {
        "plant_id": plant_id,
        "train_id": train_id,
        "turnaround_code": code,
        "scope": scope,
        "window_start": window_start,
        "window_end": window_end,
        "window_days": days if days >= 1 else 1,
        "authored_by_user_id": who["user_id"],
        "psm_review_decision": "NONE",
        "psm_reviewed_by_user_id": None,
        "psm_findings_count": None,
        "approved_by_user_id": None,
        "status": "DRAFT",
        "rejection_reason": None,
    }
    stamp_new(row)
    db.turnarounds[row["id"]] = row
    return object_response(serialize.turnaround_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_turnaround(id):
    actor(ALL_ROLES)
    return object_response(serialize.turnaround_json(load("turnarounds", id)))


@bp.get(PREFIX)
def list_turnarounds():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("turnarounds", [
        ("plant_id", v.query_str("plant_id")),
        ("train_id", v.query_str("train_id")),
        ("status", v.query_enum("status", TURNAROUND_STATUSES)),
        ("scope", v.query_enum("scope", SCOPES)),
    ])
    return list_response(serialize.dump("turnarounds", rows), limit, offset)


@bp.post(PREFIX + "/<id>/submit")
def submit_turnaround(id):
    actor([PROCESS_ENGINEER])
    v.get_body()
    turnaround = load("turnarounds", id)
    state(turnaround["status"] == "DRAFT")
    state(len(calc.tasks_of(turnaround["id"])) >= 1,
          message="The outage carries no work steps.")
    state(_feasible(turnaround), "ERR_OUTAGE_WINDOW_TOO_SHORT")
    turnaround["status"] = "SUBMITTED"
    touch(turnaround)
    return object_response(serialize.turnaround_json(turnaround))


@bp.post(PREFIX + "/<id>/psm-review")
def psm_review(id):
    who = actor([SAFETY_OFFICER])
    body = v.get_body()
    decision = v.s_enum(body, "decision", ("ENDORSED", "OBJECTED"))
    findings = v.s_int(body, "findings_count", ge=0)
    turnaround = load("turnarounds", id)
    state(turnaround["status"] == "SUBMITTED")
    turnaround["psm_review_decision"] = decision
    turnaround["psm_findings_count"] = findings
    turnaround["psm_reviewed_by_user_id"] = who["user_id"]
    touch(turnaround)
    return object_response(serialize.turnaround_json(turnaround))


@bp.post(PREFIX + "/<id>/approve")
def approve_turnaround(id):
    who = actor([SAFETY_OFFICER])
    v.get_body()
    turnaround = load("turnarounds", id)
    state(turnaround["status"] == "SUBMITTED")
    state(who["user_id"] != turnaround["authored_by_user_id"]
          and who["user_id"] != turnaround["psm_reviewed_by_user_id"],
          "ERR_SEGREGATION_OF_DUTIES")
    state(turnaround["psm_review_decision"] == "ENDORSED", "ERR_PSM_REVIEW_MISSING")
    state(not _buffer_conflict(turnaround), "ERR_TURNAROUND_BUFFER_CONFLICT")
    state(_feasible(turnaround), "ERR_OUTAGE_WINDOW_TOO_SHORT")
    turnaround["approved_by_user_id"] = who["user_id"]
    turnaround["status"] = "APPROVED"
    touch(turnaround)
    touch(db.plants[turnaround["plant_id"]])
    return object_response(serialize.turnaround_json(turnaround))


@bp.post(PREFIX + "/<id>/reject")
def reject_turnaround(id):
    who = actor([SAFETY_OFFICER])
    body = v.get_body()
    reason = v.s_str(body, "rejection_reason", min_len=1)
    turnaround = load("turnarounds", id)
    state(turnaround["status"] == "SUBMITTED")
    state(who["user_id"] != turnaround["authored_by_user_id"],
          "ERR_SEGREGATION_OF_DUTIES")
    turnaround["status"] = "REJECTED"
    turnaround["rejection_reason"] = reason
    turnaround["psm_review_decision"] = "VOID"
    turnaround["psm_findings_count"] = None
    touch(turnaround)
    for task in calc.tasks_of(turnaround["id"]):
        if task["status"] in ("PENDING", "READY"):
            task["status"] = "BLOCKED"
            touch(task)
    return object_response(serialize.turnaround_json(turnaround))


@bp.post(PREFIX + "/<id>/revise")
def revise_turnaround(id):
    who = actor([PROCESS_ENGINEER])
    v.get_body()
    turnaround = load("turnarounds", id)
    state(turnaround["status"] == "REJECTED")
    state(who["user_id"] == turnaround["authored_by_user_id"],
          "ERR_SEGREGATION_OF_DUTIES")
    turnaround["status"] = "DRAFT"
    turnaround["rejection_reason"] = None
    turnaround["psm_review_decision"] = "NONE"
    turnaround["psm_reviewed_by_user_id"] = None
    touch(turnaround)
    for task in calc.tasks_of(turnaround["id"]):
        if task["status"] == "BLOCKED":
            task["status"] = "PENDING"
            touch(task)
    return object_response(serialize.turnaround_json(turnaround))


@bp.post(PREFIX + "/<id>/start")
def start_turnaround(id):
    actor([PROCESS_ENGINEER])
    v.get_body()
    turnaround = load("turnarounds", id)
    state(turnaround["status"] == "APPROVED")
    state(db.clock >= turnaround["window_start"],
          message="The logical clock has not reached window_start.")
    state(turnaround["psm_review_decision"] == "ENDORSED", "ERR_PSM_REVIEW_MISSING")
    turnaround["status"] = "IN_PROGRESS"
    touch(turnaround)
    cascade.outage_start_cascade(turnaround)
    return object_response(serialize.turnaround_json(turnaround))


@bp.post(PREFIX + "/<id>/complete")
def complete_turnaround(id):
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    new_code = v.s_code(body, "new_charge_code", 2, 16, required=False)
    new_life = v.s_num(body, "new_charge_design_life_hours", 1, required=False, gt=0)
    turnaround = load("turnarounds", id)
    swaps_charge = turnaround["scope"] in ("CATALYST_CHANGE", "COMBINED")
    if swaps_charge:
        if new_code is None:
            v.bad("Field 'new_charge_code' is required for this outage scope.")
        if new_life is None:
            v.bad("Field 'new_charge_design_life_hours' is required for this outage scope.")
        duplicate("charges", "charge_code", new_code,
                  scope=("train_id", turnaround["train_id"]))
    total, done = calc.turnaround_counters(turnaround["id"])
    state(turnaround["status"] == "IN_PROGRESS")
    state(done == total, message="Not every work step of the outage is DONE.")
    state(turnaround["psm_review_decision"] == "ENDORSED", "ERR_PSM_REVIEW_MISSING")
    train = db.trains[turnaround["train_id"]]
    plant = db.plants[turnaround["plant_id"]]
    if swaps_charge:
        outgoing = calc.active_charge(train["id"])
        if outgoing is None:
            spent = [c for c in db.charges.values()
                     if c["train_id"] == train["id"] and c["status"] == "SPENT"]
            outgoing = by_seq(spent)[0] if spent else None
        if outgoing is not None:
            outgoing["status"] = "RETIRED"
            touch(outgoing)
        replacement = {
            "train_id": train["id"],
            "charge_code": new_code,
            "design_life_hours": new_life,
            "baseline_operating_hours": D("0.0"),
            "poisoning_index": D("0.00"),
            "regeneration_count": 0,
            "installed_at": db.clock,
            "status": "ACTIVE",
        }
        stamp_new(replacement)
        db.charges[replacement["id"]] = replacement
    if turnaround["scope"] in ("VESSEL_INSPECTION", "COMBINED"):
        plant["last_vessel_inspection_at"] = db.clock
    turnaround["status"] = "COMPLETED"
    touch(turnaround)
    plant["psm_program_status"] = "CURRENT"
    touch(plant)
    cascade.rederive_posture(plant)
    charge = calc.active_charge(train["id"])
    if charge is not None and calc.charge_activity_pct(charge) >= calc.CATALYST_MIN_ACTIVITY_PCT:
        train["status"] = "IDLE"
    else:
        train["status"] = "DERATED"
    touch(train)
    return object_response(serialize.turnaround_json(turnaround))

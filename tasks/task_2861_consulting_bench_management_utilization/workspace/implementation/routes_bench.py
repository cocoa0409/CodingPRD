"""Bench spells, reskilling cohorts, internal projects, separation and the
operations checkpoint (PRD 3.8 and 3.9)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import serial
from derive import (
    ASSIGNED_ALLOCATION_THRESHOLD_PCT,
    INTERNAL_PROJECT_MAX_DAYS,
    allocated_pct,
    assignments_of,
    availability,
    effective_end,
    level_target,
    open_spell,
    spell_age_days,
    spells_of,
)
from envelope import collection, empty, obj
from errors import bad_request, fail
from ops import need, now, open_new_spell, settle, today
from reqctx import (
    begin,
    body,
    filter_enum,
    filter_value,
    opt_int,
    opt_str,
    pagination,
    present,
    req_date,
    req_enum,
    req_id,
    req_int,
    req_str,
    window,
)
from store import bump, db

bp = Blueprint("bench", __name__)

SPELL_READ_ROLES = ("ResourceManager", "PracticePartner", "FinanceController")
SPELL_STATES = (
    "MONITORING",
    "ESCALATED_L1",
    "ESCALATED_L2",
    "RESKILLING",
    "INTERNAL_PROJECT",
    "SEPARATION_PROPOSED",
    "CLOSED",
    "SEPARATED",
)
PROGRAM_STATUSES = ("PLANNED", "RUNNING", "COMPLETED")
ESCALATED = ("ESCALATED_L1", "ESCALATED_L2")


# --------------------------------------------------------------- bench spells
@bp.get("/bench-spells")
def list_bench_spells():
    begin(*SPELL_READ_ROLES)
    limit, offset = pagination()
    consultant_id = filter_value("consultant_id")
    program_id = filter_value("reskilling_program_id")
    state = filter_enum("state", SPELL_STATES)
    rows = db.all("bench_spells")
    if consultant_id is not None:
        rows = [r for r in rows if r["consultant_id"] == consultant_id]
    if program_id is not None:
        rows = [r for r in rows if r.get("reskilling_program_id") == program_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/bench-spells/<spell_id>")
def read_bench_spell(spell_id):
    begin(*SPELL_READ_ROLES)
    return obj(serial.bench_spell(need("bench_spells", spell_id)))


@bp.post("/bench-spells/<spell_id>/internal-project")
def park_on_internal_project(spell_id):
    begin("ResourceManager")
    spell = need("bench_spells", spell_id)
    payload = body(allowed=("internal_project_code",), required=("internal_project_code",))
    code = req_str(payload, "internal_project_code", 1, 40)
    if spell["state"] not in ESCALATED:
        fail("ERR_BENCH_SPELL_STATE_INVALID", "Only an escalated bench spell may be parked on internal work.")
    consultant = db.get("consultants", spell["consultant_id"])
    if allocated_pct(consultant) >= ASSIGNED_ALLOCATION_THRESHOLD_PCT:
        fail("ERR_BENCH_SPELL_STATE_INVALID", "A consultant at half capacity or more is not parked on internal work.")
    spell["state"] = "INTERNAL_PROJECT"
    spell["internal_project_code"] = code
    spell["investment_started_on"] = today()
    spell["investment_ended_on"] = None
    bump(spell)
    bump(consultant)
    settle()
    return obj(serial.bench_spell(spell))


@bp.post("/bench-spells/<spell_id>/separation-proposal")
def propose_separation(spell_id):
    ctx = begin("ResourceManager")
    spell = need("bench_spells", spell_id)
    payload = body(allowed=("rationale",))
    if present(payload, "rationale"):
        opt_str(payload, "rationale", 1, 500)
    if spell["state"] != "ESCALATED_L2":
        fail("ERR_BENCH_SPELL_STATE_INVALID", "Only an ESCALATED_L2 spell may carry a separation proposal.")
    if spell["escalation_count"] < 2:
        fail("ERR_SEPARATION_NOT_ELIGIBLE", "The spell has not escalated twice.")
    spell["state"] = "SEPARATION_PROPOSED"
    spell["separation_proposed_by_user_id"] = ctx.user_id
    bump(spell)
    settle()
    return obj(serial.bench_spell(spell))


@bp.post("/bench-spells/<spell_id>/separation-decision")
def decide_separation(spell_id):
    ctx = begin("PracticePartner")
    spell = need("bench_spells", spell_id)
    payload = body(allowed=("decision", "note"), required=("decision",))
    decision = req_enum(payload, "decision", ("APPROVED", "REJECTED"))
    if present(payload, "note"):
        opt_str(payload, "note", 1, 500)
    if spell["state"] != "SEPARATION_PROPOSED":
        fail("ERR_BENCH_SPELL_STATE_INVALID", "Only a proposed separation may be decided.")
    if ctx.user_id == spell.get("separation_proposed_by_user_id"):
        fail("ERR_SELF_APPROVAL_FORBIDDEN", "The proposer may not decide their own separation proposal.")
    consultant = db.get("consultants", spell["consultant_id"])
    if decision == "APPROVED":
        if allocated_pct(consultant) != Decimal("0.00"):
            fail("ERR_SEPARATION_NOT_ELIGIBLE", "A consultant still committed to client work is not separated.")
        spell["state"] = "SEPARATED"
        spell["separation_decision"] = "APPROVED"
        spell["separation_decided_by_user_id"] = ctx.user_id
        spell["ended_on"] = today()
        consultant["separated_on"] = now()
        bump(consultant)
    else:
        spell["state"] = "ESCALATED_L2"
        spell["separation_decision"] = "REJECTED"
        spell["separation_decided_by_user_id"] = ctx.user_id
    bump(spell)
    settle()
    return obj(serial.bench_spell(spell))


# ------------------------------------------------------- reskilling programmes
@bp.post("/reskilling-programs")
def create_program():
    begin("ResourceManager")
    payload = body(
        allowed=(
            "skill_id",
            "target_proficiency_level",
            "cohort_start_on",
            "cohort_end_on",
            "seat_capacity",
            "cooldown_days",
        ),
        required=(
            "skill_id",
            "target_proficiency_level",
            "cohort_start_on",
            "cohort_end_on",
            "seat_capacity",
        ),
    )
    skill_id = req_id(payload, "skill_id")
    target_level = req_int(payload, "target_proficiency_level", 1, 5)
    start = req_date(payload, "cohort_start_on")
    end = req_date(payload, "cohort_end_on")
    if end < start:
        bad_request("Field 'cohort_end_on' must be on or after 'cohort_start_on'.")
    capacity = req_int(payload, "seat_capacity", 1, 50)
    cooldown = opt_int(payload, "cooldown_days", 0, 30, 3)
    skill = need("skills", skill_id)
    if skill["retired"]:
        fail("ERR_SKILL_RETIRED", "A retired skill may not open a new cohort.")
    row = db.new_row("reskilling_programs")
    row.update(
        {
            "skill_id": skill_id,
            "target_proficiency_level": target_level,
            "cohort_start_on": start,
            "cohort_end_on": end,
            "seat_capacity": capacity,
            "cooldown_days": cooldown,
            "status": "PLANNED",
        }
    )
    db.insert("reskilling_programs", row)
    return obj(serial.program(row), 201)


@bp.get("/reskilling-programs")
def list_programs():
    begin(*SPELL_READ_ROLES)
    limit, offset = pagination()
    skill_id = filter_value("skill_id")
    status = filter_enum("status", PROGRAM_STATUSES)
    rows = db.all("reskilling_programs")
    if skill_id is not None:
        rows = [r for r in rows if r["skill_id"] == skill_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/reskilling-programs/<program_id>")
def read_program(program_id):
    begin(*SPELL_READ_ROLES)
    return obj(serial.program(need("reskilling_programs", program_id)))


def _clashing_assignment(consultant_id, start, end):
    """The cohort's CLOSED window against each assignment's HALF-OPEN interval."""
    for assignment in assignments_of(consultant_id):
        if assignment["status"] not in ("CONFIRMED", "ACTIVE"):
            continue
        if assignment["start_date"] <= end and start < effective_end(assignment):
            return assignment
    return None


def _cooldown_blocked(consultant_id, program):
    latest = None
    for spell in spells_of(consultant_id):
        prior = db.get("reskilling_programs", spell.get("reskilling_program_id"))
        if prior is None or prior["status"] != "COMPLETED":
            continue
        if latest is None or prior["cohort_end_on"] > latest["cohort_end_on"]:
            latest = prior
    if latest is None:
        return False
    earliest = latest["cohort_end_on"] + timedelta(days=program["cooldown_days"])
    return program["cohort_start_on"] <= earliest


@bp.post("/reskilling-programs/<program_id>/enrollments")
def enrol_consultant(program_id):
    begin("ResourceManager")
    program = need("reskilling_programs", program_id)
    payload = body(allowed=("consultant_id",), required=("consultant_id",))
    consultant = need("consultants", req_id(payload, "consultant_id"))
    if availability(consultant) == "SEPARATED":
        fail("ERR_CONSULTANT_SEPARATED", "A separated consultant may not be enrolled.")
    spell = open_spell(consultant["id"])
    if spell is None or spell["state"] not in ESCALATED:
        fail("ERR_BENCH_SPELL_STATE_INVALID", "Only an escalated bench spell may join a cohort.")
    if program["status"] not in ("PLANNED", "RUNNING"):
        fail("ERR_PROGRAM_STATE_INVALID", "Only a PLANNED or RUNNING cohort takes enrolments.")
    if _clashing_assignment(consultant["id"], program["cohort_start_on"], program["cohort_end_on"]):
        fail(
            "ERR_COHORT_CONFLICTS_WITH_ASSIGNMENT",
            "The cohort window overlaps committed client work.",
        )
    if _cooldown_blocked(consultant["id"], program):
        fail("ERR_RESKILLING_COOLDOWN_ACTIVE", "The consultant is still inside the reskilling cooldown.")
    if serial.seats_taken(program) >= program["seat_capacity"]:
        fail("ERR_COHORT_CAPACITY_EXCEEDED", "The cohort is full.")
    spell["state"] = "RESKILLING"
    spell["reskilling_program_id"] = program["id"]
    spell["investment_started_on"] = today()
    spell["investment_ended_on"] = None
    bump(spell)
    bump(consultant)
    bump(program)
    settle()
    return obj(serial.bench_spell(spell))


def _graduate_assertion(consultant_id, skill_id, target_level):
    for row in db.all("skill_assertions"):
        if row["consultant_id"] == consultant_id and row["skill_id"] == skill_id:
            if row["proficiency_level"] < target_level:
                row["proficiency_level"] = target_level
                bump(row)
            return row
    row = db.new_row("skill_assertions")
    row.update(
        {
            "consultant_id": consultant_id,
            "skill_id": skill_id,
            "proficiency_level": target_level,
            "certification_code": None,
            "certification_expires_on": None,
            "last_used_on": None,
        }
    )
    return db.insert("skill_assertions", row)


@bp.post("/reskilling-programs/<program_id>/complete")
def complete_program(program_id):
    begin("ResourceManager")
    program = need("reskilling_programs", program_id)
    body(allowed=())
    if program["status"] != "RUNNING":
        fail("ERR_PROGRAM_STATE_INVALID", "Only a RUNNING cohort may be graduated.")
    if program["cohort_end_on"] > today():
        fail("ERR_PROGRAM_STATE_INVALID", "The cohort window has not finished yet.")
    program["status"] = "COMPLETED"
    bump(program)
    for spell in db.all("bench_spells"):
        if spell.get("reskilling_program_id") != program["id"] or spell["state"] != "RESKILLING":
            continue
        spell["state"] = "MONITORING"
        spell["age_reset_on"] = today()
        spell["investment_ended_on"] = today()
        bump(spell)
        consultant = db.get("consultants", spell["consultant_id"])
        _graduate_assertion(consultant["id"], program["skill_id"], program["target_proficiency_level"])
        bump(consultant)
    settle()
    return obj(serial.program(program))


# ------------------------------------------------------- operations checkpoint
def _age_ladder(day):
    """At most one rung per spell per checkpoint, in ascending (started_on,
    created_at) order (PRD 3.8)."""
    open_spells = [s for s in db.all("bench_spells") if s["state"] in ("MONITORING",) + ESCALATED]
    open_spells.sort(key=lambda s: (s["started_on"], s["created_at"], s["_seq"]))
    for spell in open_spells:
        consultant = db.get("consultants", spell["consultant_id"])
        if consultant is None:
            continue
        targets = level_target(consultant)
        age = spell_age_days(spell)
        if spell["state"] == "MONITORING" and age >= targets["bench_escalation_l1_days"]:
            spell["state"] = "ESCALATED_L1"
            spell["escalation_count"] = spell["escalation_count"] + 1
            bump(spell)
        elif spell["state"] == "ESCALATED_L1" and age >= targets["bench_escalation_l2_days"]:
            spell["state"] = "ESCALATED_L2"
            spell["escalation_count"] = spell["escalation_count"] + 1
            bump(spell)


def _return_internal_projects(day):
    for spell in db.all("bench_spells"):
        if spell["state"] != "INTERNAL_PROJECT":
            continue
        started = spell.get("investment_started_on")
        if started is None or (day - started).days < INTERNAL_PROJECT_MAX_DAYS:
            continue
        spell["state"] = "MONITORING"
        spell["age_reset_on"] = day
        spell["investment_ended_on"] = day
        bump(spell)
        bump(db.get("consultants", spell["consultant_id"]))


def _activate_due(day):
    for assignment in db.all("assignments"):
        if assignment["status"] == "CONFIRMED" and assignment["start_date"] <= day:
            assignment["status"] = "ACTIVE"
            assignment["activated_on"] = day
            bump(assignment)
    for placement in db.all("external_placements"):
        if placement["status"] == "APPROVED" and placement["start_date"] <= day:
            placement["status"] = "ACTIVE"
            bump(placement)
    for program in db.all("reskilling_programs"):
        if program["status"] == "PLANNED" and program["cohort_start_on"] <= day:
            program["status"] = "RUNNING"
            bump(program)


@bp.post("/bench-runs")
def run_checkpoint():
    begin("ResourceManager")
    body(allowed=())
    day = today()
    _age_ladder(day)
    _return_internal_projects(day)
    _activate_due(day)
    settle()
    return empty(200)

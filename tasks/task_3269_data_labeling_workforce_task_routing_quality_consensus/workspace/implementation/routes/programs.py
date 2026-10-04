"""Engagement registration and lifecycle routes (PRD sections 3.1, 3.2, 3.11, 3.13)."""

from flask import Blueprint

import auth
import db
import services
from envelope import ok
from errors import (
    ERR_CAPACITY_INFEASIBLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PROGRAM_NOT_FOUND,
    ERR_UNIT_CODE_DUPLICATE,
    fail,
)
from helpers import (
    json_body,
    opt_enum,
    opt_int,
    opt_number,
    query_str,
    require_datetime,
    require_enum,
    require_enum_ci,
    require_str,
)

bp = Blueprint("programs", __name__)

ADMIN = auth.ROLE_ADMIN
REVIEWER = auth.ROLE_REVIEWER
WORKER = auth.ROLE_WORKER


@bp.post("/api/programs")
def register_program():
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))
    body = json_body()

    program_code = require_str(body, "program_code")
    name = require_str(body, "name")
    language_code = require_enum(body, "language_code", services.LANGUAGES)
    instruction_model = require_enum(body, "instruction_model", services.INSTRUCTION_MODELS)
    # PRD §2.5: an engagement "declares a sensitivity_class ... defaulting to
    # STANDARD", and the only stated required inputs are the code, the name, the
    # language, the instruction model and the three scheduling instants, so the
    # class is optional and takes its declared default when omitted (an unknown
    # value is still refused at the envelope gate).
    sensitivity_class = opt_enum(
        body, "sensitivity_class", services.SENSITIVITY_CLASSES, "STANDARD"
    )
    deadline_utc = require_datetime(body, "deadline_utc")
    blackout_start_utc = require_datetime(body, "blackout_start_utc")
    blackout_end_utc = require_datetime(body, "blackout_end_utc")

    for candidate in db.programs.values():
        if candidate.get("program_code") == program_code:
            fail(ERR_UNIT_CODE_DUPLICATE)

    record = {
        "program_code": program_code,
        "name": name,
        "language_code": language_code,
        "instruction_model": instruction_model,
        "sensitivity_class": sensitivity_class,
        "incident_severity": "NONE",
        "open_incident_count": 0,
        "operational_restricted": False,
        "min_consensus_agreement": opt_number(
            body, "min_consensus_agreement", services.DEFAULT_MIN_CONSENSUS_AGREEMENT
        ),
        "commitment_quorum": opt_int(
            body, "commitment_quorum", services.DEFAULT_COMMITMENT_QUORUM
        ),
        "commit_deadline_seconds": opt_int(
            body, "commit_deadline_seconds", services.DEFAULT_COMMIT_DEADLINE_SECONDS
        ),
        "patience_seconds": opt_int(body, "patience_seconds", services.DEFAULT_PATIENCE_SECONDS),
        "coverage_hours": opt_number(body, "coverage_hours", services.DEFAULT_COVERAGE_HOURS),
        "capacity_points": opt_int(body, "capacity_points", services.DEFAULT_CAPACITY_POINTS),
        "point_cost_high_accuracy": opt_int(
            body, "point_cost_high_accuracy", services.DEFAULT_POINT_COST_HIGH
        ),
        "point_cost_medium_accuracy": opt_int(
            body, "point_cost_medium_accuracy", services.DEFAULT_POINT_COST_MEDIUM
        ),
        "point_cost_fallback": opt_int(
            body, "point_cost_fallback", services.DEFAULT_POINT_COST_FALLBACK
        ),
        "accuracy_floor_pct": opt_number(
            body, "accuracy_floor_pct", services.DEFAULT_ACCURACY_FLOOR_PCT
        ),
        "accuracy_high_watermark_pct": opt_number(
            body, "accuracy_high_watermark_pct", services.DEFAULT_ACCURACY_HIGH_WATERMARK_PCT
        ),
        "weekly_earning_cap_cents": opt_int(
            body, "weekly_earning_cap_cents", services.DEFAULT_WEEKLY_EARNING_CAP_CENTS
        ),
        "deadline_utc": deadline_utc,
        "blackout_start_utc": blackout_start_utc,
        "blackout_end_utc": blackout_end_utc,
        "demand_points": 0,
        "capacity_requirement_points": 0,
        "capacity_multiplier": 1.0,
        "capacity_feasible": False,
        "projected_miss_deadline": False,
        "accuracy_floor_variant_below": False,
        "accepted_accuracy_pct": 0.0,
        "provisional_accuracy_pct": 0.0,
        "accuracy_denominator_count": 0,
        "on_time": False,
        "qa_sample_rate": 0.0,
        "current_week_epoch_index": db.current_epoch_index(),
        "status": "DRAFT",
    }
    db.seal(record)
    db.programs[record["id"]] = record
    services.refresh_program_plan(record)
    return ok(services.program_view(record), status=201)


@bp.get("/api/programs/<program_id>")
def read_program(program_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER, WORKER))
    program = db.programs.get(program_id)
    if program is None:
        fail(ERR_PROGRAM_NOT_FOUND)
    variant = query_str("plan_variant")
    if variant is not None:
        upper = variant.upper()
        if upper not in services.PLAN_MULT:
            fail(ERR_INVALID_REQUEST, "Unknown plan_variant.")
        variant = upper
    return ok(services.program_view(program, variant))


@bp.post("/api/programs/<program_id>/program-state")
def program_state(program_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))
    program = db.programs.get(program_id)
    if program is None:
        fail(ERR_PROGRAM_NOT_FOUND)

    body = json_body()
    action = require_enum_ci(
        body, "program_action", ("OPEN", "ASSESS_CAPACITY", "RECALL", "FREEZE")
    )
    variant = body.get("plan_variant")
    if isinstance(variant, str):
        variant = variant.upper()
    else:
        variant = None

    if program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)

    if action == "OPEN":
        return ok(_open_program(program))
    if action == "ASSESS_CAPACITY":
        return ok(_assess_capacity(program, variant))
    if action == "RECALL":
        return ok(_recall(program))
    return ok(_freeze(program))


def _open_program(program):
    if program.get("status") != "DRAFT":
        fail(ERR_INVALID_STATE)

    units = db.units_of_program(program["id"])
    if not any(u.get("status") in ("DRAFT", "ACTIVE") for u in units):
        fail(ERR_INVALID_STATE)

    program["status"] = "ACTIVE"

    for unit in units:
        if unit.get("parent_unit_id") is not None:
            continue
        if unit.get("status") != "DRAFT":
            continue
        if services.unit_gate_failure(unit) is None:
            services.activate_unit(unit)

    # Opening sets the status and increments the version by exactly 1 (PRD §3.2).
    services.refresh_program_plan(program)
    db.touch(program)
    return services.program_view(program)


def _assess_capacity(program, variant):
    services.refresh_program_plan(program, variant)
    if not program.get("capacity_feasible"):
        fail(ERR_CAPACITY_INFEASIBLE)
    db.touch(program)
    return services.program_view(program, variant)


def _recall(program):
    if program.get("status") != "QUALITY_EMBARGO":
        fail(ERR_INVALID_STATE)
    services.refresh_program_accuracy(program)
    if float(program.get("accepted_accuracy_pct", 0.0)) < float(
        program.get("accuracy_floor_pct", services.DEFAULT_ACCURACY_FLOOR_PCT)
    ):
        fail(ERR_INVALID_STATE)
    program["status"] = "ACTIVE"
    services.refresh_program_plan(program)
    services.refresh_incident_flags(program)
    # Recall increments the version by exactly 1 (PRD §3.13).
    db.touch(program)
    return services.program_view(program)


def _freeze(program):
    status = program.get("status")
    if status not in ("ACTIVE", "QUALITY_EMBARGO"):
        fail(ERR_INVALID_STATE)
    if status == "ACTIVE":
        if any(u.get("piece_status") == "CONSENSUS" for u in db.units_of_program(program["id"])):
            fail(ERR_INVALID_STATE)
    services.freeze_program(program)
    services.refresh_program_plan(program)
    # Freezing increments the version by exactly 1 (PRD §3.13).
    db.touch(program)
    return services.program_view(program)
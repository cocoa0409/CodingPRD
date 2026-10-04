"""Spec unit decomposition, activation and piece attachment (PRD sections 3.1-3.3)."""

from flask import Blueprint

import auth
import db
import services
from envelope import list_ok, ok, paginate
from errors import (
    ERR_COVERAGE_WINDOW_OVERLAP,
    ERR_EDGE_CASE_GUIDANCE_CONFLICT,
    ERR_INSTRUCTION_NOT_PUBLISHED,
    ERR_INVALID_STATE,
    ERR_PROGRAM_NOT_FOUND,
    ERR_PROGRAM_OPERATIONALLY_RESTRICTED,
    ERR_SPEC_UNIT_CYCLE,
    ERR_SPEC_UNIT_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_UNIT_CODE_DUPLICATE,
    fail,
)
from helpers import (
    json_body,
    opt_bool,
    opt_enum,
    opt_int,
    opt_number,
    opt_str,
    ordered_by_creation,
    pagination_params,
    query_enum,
    query_str,
    require_datetime,
    require_enum,
    require_enum_ci,
    require_int,
    require_list,
    require_str,
)

bp = Blueprint("units", __name__)

ADMIN = auth.ROLE_ADMIN
REVIEWER = auth.ROLE_REVIEWER


@bp.get("/api/spec-units")
def list_units():
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER))
    program_id = query_str("program_id")
    parent_unit_id = query_str("parent_unit_id")
    status = query_enum("status", services.UNIT_STATUSES)

    rows = list(db.spec_units.values())
    if program_id:
        rows = [u for u in rows if u.get("program_id") == program_id]
    if parent_unit_id:
        rows = [u for u in rows if u.get("parent_unit_id") == parent_unit_id]
    if status:
        rows = [u for u in rows if u.get("status") == status]

    rows = ordered_by_creation(rows)
    limit, offset = pagination_params()
    page, pagination = paginate(rows, limit, offset)
    return list_ok([services.unit_view(u) for u in page], pagination=pagination)


@bp.post("/api/spec-units")
def create_unit():
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))
    body = json_body()

    program_id = require_str(body, "program_id")
    unit_code = require_str(body, "unit_code")
    max_items = require_int(body, "max_items")
    instruction_revision = require_int(body, "instruction_revision")
    instruction_status = require_enum(body, "instruction_status", services.INSTRUCTION_STATUSES)
    field_schema = require_list(body, "field_schema")
    coverage_start_utc = require_datetime(body, "coverage_start_utc")
    coverage_end_utc = require_datetime(body, "coverage_end_utc")
    expected_program_version = require_int(body, "expected_program_version")

    # Rank 3 -- existence.
    program = db.programs.get(program_id)
    if program is None:
        fail(ERR_PROGRAM_NOT_FOUND)

    # Rank 4 -- optimistic concurrency.
    if int(expected_program_version) != int(program.get("version")):
        fail(ERR_STALE_VERSION)

    # Rank 5 -- state admissibility.
    if program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)

    # Rank 6 -- safety band.
    services.refresh_incident_flags(program)
    if program.get("operational_restricted"):
        fail(ERR_PROGRAM_OPERATIONALLY_RESTRICTED)

    parent_unit_id = opt_str(body, "parent_unit_id", None)
    has_edge_case_guidance = opt_bool(body, "has_edge_case_guidance", False)
    edge_case_count = opt_int(body, "edge_case_count", 0)
    # panel_size defaults to 3 and is never below 2; an explicit value is NOT
    # floored up, because PRD §3.1 pins the default (3) rather than a minimum
    # that overrides a smaller supplied request.
    panel_size = opt_int(body, "panel_size", services.DEFAULT_PANEL_SIZE)
    if panel_size is None or panel_size < 1:
        panel_size = services.DEFAULT_PANEL_SIZE
    gold_rate = opt_number(body, "gold_rate", services.DEFAULT_GOLD_RATE)

    # Rank 7 -- referential integrity. The cycle check runs before the unit_code
#    scope check because a cycle-closing submission necessarily reuses a code
#    already carried by an ancestor, and PRD §2.4 names the cycle condition as
#    the reason the submission is refused.
    if parent_unit_id is not None:
        if parent_unit_id not in db.spec_units:
            fail(ERR_SPEC_UNIT_NOT_FOUND)
        parent = db.spec_units[parent_unit_id]
        if parent.get("program_id") != program_id:
            fail(ERR_SPEC_UNIT_NOT_FOUND)
        if _would_close_cycle(parent_unit_id, unit_code, program_id):
            fail(ERR_SPEC_UNIT_CYCLE)

    for existing in db.units_of_program(program_id):
        if existing.get("unit_code") == unit_code:
            fail(ERR_UNIT_CODE_DUPLICATE)

    record = {
        "program_id": program_id,
        "unit_code": unit_code,
        "parent_unit_id": parent_unit_id,
        "max_items": max_items,
        "item_count": 0,
        "instruction_revision": instruction_revision,
        "instruction_status": instruction_status,
        "has_edge_case_guidance": bool(has_edge_case_guidance),
        "edge_case_count": edge_case_count,
        "field_schema": list(field_schema),
        "panel_size": panel_size,
        "gold_rate": gold_rate,
        "coverage_start_utc": coverage_start_utc,
        "coverage_end_utc": coverage_end_utc,
        "piece_status": "DECOMPOSED",
        "frozen_revision": None,
        "certified_item_count": 0,
        "remaining_item_slots": max_items,
        "unit_ceiling_points": 0,
        "unit_effective_points": 0,
        "rework_point_multiplier": 1.0,
        "unit_accuracy_pct": 0.0,
        "unit_provisional_accuracy_pct": 0.0,
        "status": "DRAFT",
    }
    db.seal(record)
    db.spec_units[record["id"]] = record
    services.refresh_unit_metrics(record)

    # The creation increments CustomerProgram.version by exactly 1 and raises
    # demand_points (PRD section 3.1).
    services.refresh_program_plan(program)
    db.touch(program)
    return ok(services.unit_view(record), status=201)


def _would_close_cycle(proposed_parent_id, unit_code, program_id, own_unit_id=None):
    """Walk the parent chain looking for the submitted unit itself.

    PRD §2.4 refuses "a submission whose `parent_unit_id` would close a cycle".
    A submission that renames an existing unit onto a descendant of itself is
    such a submission, and so is a brand-new unit that reuses the code of an
    ancestor in the chain it names. A chain that terminates (or loops among
    other units) does not touch the submitted unit and is therefore not a cycle
    of *this* submission.
    """
    seen = set()
    cursor = proposed_parent_id
    while cursor is not None and cursor not in seen:
        seen.add(cursor)
        if own_unit_id is not None and cursor == own_unit_id:
            return True
        parent = db.spec_units.get(cursor)
        if parent is None:
            return False
        if own_unit_id is None and parent.get("unit_code") == unit_code and parent.get("program_id") == program_id:
            return True
        cursor = parent.get("parent_unit_id")
    return False


@bp.get("/api/spec-units/<unit_id>")
def read_unit(unit_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER))
    unit = db.spec_units.get(unit_id)
    if unit is None:
        fail(ERR_SPEC_UNIT_NOT_FOUND)
    return ok(services.unit_view(unit))


@bp.post("/api/spec-units/<unit_id>/advance-unit")
def advance_unit(unit_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))
    unit = db.spec_units.get(unit_id)
    if unit is None:
        fail(ERR_SPEC_UNIT_NOT_FOUND)

    body = json_body()
    action = require_enum_ci(body, "unit_action", ("ACTIVATE", "REOPEN"))

    if action == "ACTIVATE":
        return ok(_activate(unit))
    return ok(_reopen(unit))


def _activate(unit):
    program = db.programs.get(unit.get("program_id"))

    # Rank 5 -- state admissibility, checked before the narrower gate errors.
    # PRD §3.2 lists the activation gates and none of them requires the
    # engagement to be live: a DRAFT unit may be activated directly, which is
    # what lets a unit be prepared before its engagement is opened. The only
    # engagement state that blocks the path is the terminal FROZEN.
    if program is None or program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    if unit.get("status") != "DRAFT":
        fail(ERR_INVALID_STATE)
    if services.has_open_child_unit(unit):
        fail(ERR_INVALID_STATE)

    if unit.get("instruction_status") != "PUBLISHED":
        fail(ERR_INSTRUCTION_NOT_PUBLISHED)
    if unit.get("has_edge_case_guidance") and int(unit.get("edge_case_count", 0) or 0) > 0:
        fail(ERR_EDGE_CASE_GUIDANCE_CONFLICT)
    if services.coverage_windows_overlap(unit, program):
        fail(ERR_COVERAGE_WINDOW_OVERLAP)

    services.activate_unit(unit)
    services.refresh_program_plan(program)
    db.touch(program)
    return services.unit_view(unit)  # one increment for the activation


def _reopen(unit):
    program = db.programs.get(unit.get("program_id"))
    if program is None or program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    if unit.get("status") != "COMPLETE":
        fail(ERR_INVALID_STATE)
    if program.get("status") not in ("ACTIVE", "QUALITY_EMBARGO"):
        fail(ERR_INVALID_STATE)

    attached = db.items_of_unit(unit["id"])
    if not any(i.get("consensus_status") == "REWORK" for i in attached):
        fail(ERR_INVALID_STATE)

    unit["status"] = "ACTIVE"
    unit["piece_status"] = "REWORK"
    db.touch(unit)
    services.refresh_unit_metrics(unit)
    return services.unit_view(unit)


@bp.post("/api/spec-units/<unit_id>/items")
def create_item(unit_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))
    unit = db.spec_units.get(unit_id)
    if unit is None:
        fail(ERR_SPEC_UNIT_NOT_FOUND)

    body = json_body()
    item_key = require_str(body, "item_key")
    payload_uri = require_str(body, "payload_uri")
    required_units = opt_int(body, "required_units", services.DEFAULT_REQUIRED_UNITS)

    program = db.programs.get(unit.get("program_id"))
    if program is not None and program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)

    if int(unit.get("item_count", 0)) >= int(unit.get("max_items", 0)):
        fail(ERR_INVALID_STATE)

    for existing in db.items_of_unit(unit_id):
        if existing.get("item_key") == item_key:
            fail(ERR_UNIT_CODE_DUPLICATE)

    record = {
        "spec_unit_id": unit_id,
        "item_key": item_key,
        "item_seq": services.next_item_seq(unit_id),
        "payload_uri": payload_uri,
        "required_units": required_units,
        "instruction_revision": unit.get("instruction_revision"),
        "item_status": "PENDING",
        "consensus_status": "PENDING",
        "non_abstaining_commit_count": 0,
        "modal_label": None,
        "agreement_ratio": 0.0,
        "gold_audits_this_week": 0,
        "gold_rotation": False,
        "holds_quorum": False,
        "rework_cycles": 0,
        "rework_round_limit": services.DEFAULT_REWORK_ROUND_LIMIT,
        "rework_started_at": None,
        "rework_window_seconds": services.DEFAULT_REWORK_WINDOW_SECONDS,
        "rework_window_remaining_seconds": None,
        "delivered_at": None,
        "payout_complete": False,
        "status": "DRAFT",
    }
    db.seal(record)
    db.items[record["id"]] = record

    # A piece attached to a unit that is already in production is released by the
    # same cascade §3.3 describes: it is "still at container status DRAFT" and so
    # moves to RELEASED with item_status remaining PENDING.
    if unit.get("status") == "ACTIVE" and unit.get("piece_status") in (
        "IN_PRODUCTION",
        "CONSENSUS",
        "REWORK",
    ):
        record["status"] = "RELEASED"

    unit["item_count"] = int(unit.get("item_count", 0)) + 1
    db.touch(unit)
    services.refresh_unit_metrics(unit)
    if program is not None:
        services.refresh_program_plan(program)
        db.touch(program)
    return ok(services.item_view(record), status=201)
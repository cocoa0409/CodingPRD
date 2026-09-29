"""Specification revisions, their lock, and production runs."""
from datetime import timedelta

from flask import Blueprint

import calculations as calc
import serializers as ser
from db import db, minutes, now
from domain import (
    available_budget,
    claims_of_round,
    commit_money,
    effective_landed_cost,
    get_artwork_round,
    get_cost_model,
    get_item,
    get_plant_line,
    get_run,
    get_specification,
    get_supplier,
    guard_not_frozen,
    guard_program_open,
    new_row,
    program_of_item,
    refresh_cached_composite,
    release_money,
    runs_of_item,
    specifications_of_item,
    touch,
)
from errors import fail
from listing import RUN_STATUS_SET, RUN_TYPE_SET, SPEC_STATUS_SET, no_query, paginate
from middleware import (
    ALL_ROLES,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_QUALITY_AUDITOR,
    ROLE_SOURCING_MANAGER,
    Field,
    authenticate,
    validate_body,
)
from response import object_response


bp = Blueprint("specs", __name__)


@bp.post("/private-label/specifications")
def create_specification():
    authenticate((ROLE_PROGRAM_DIRECTOR, ROLE_SOURCING_MANAGER))
    body = validate_body(
        {
            "item_id": Field("string", required=True),
            "pinned_cost_model_id": Field("string", required=True),
            "pinned_artwork_round_id": Field("string", required=True),
            "expected_item_version": Field("integer", required=True),
        }
    )
    item = get_item(body["item_id"])
    cost_model = get_cost_model(body["pinned_cost_model_id"])
    artwork_round = get_artwork_round(body["pinned_artwork_round_id"])
    if body["expected_item_version"] != item["version"]:
        fail("ERR_STALE_ITEM_VERSION")
    guard_program_open(program_of_item(item))
    if artwork_round["nutrition_status"] != "VALID":
        fail("ERR_NUTRITION_PANEL_INVALID")
    if (
        cost_model["status"] != "ACCEPTED"
        or cost_model["item_id"] != item["id"]
        or artwork_round["status"] != "APPROVED"
        or artwork_round["item_id"] != item["id"]
    ):
        fail("ERR_PIN_ITEM_MISMATCH")
    for existing in specifications_of_item(item["id"]):
        if existing["status"] == "DRAFT":
            fail("ERR_DRAFT_SPECIFICATION_EXISTS")
    item["spec_revision_count"] += 1
    touch(item)
    row = new_row(
        {
            "item_id": item["id"],
            "pinned_cost_model_id": cost_model["id"],
            "pinned_cost_model_version": cost_model["version"],
            "pinned_artwork_round_id": artwork_round["id"],
            "pinned_artwork_version": artwork_round["version"],
            "revision_no": item["spec_revision_count"],
            "slotting_fee_cents": None,
            "locked_at": None,
            "locked_by_user_id": None,
            "status": "DRAFT",
        }
    )
    db.specifications[row["id"]] = row
    return object_response(ser.specification_out(row), 201)


@bp.get("/private-label/specifications/<specification_id>")
def read_specification(specification_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.specification_out(get_specification(specification_id)))


@bp.get("/private-label/specifications")
def list_specifications():
    authenticate(ALL_ROLES)
    return paginate(
        db.specifications,
        {
            "item_id": "string",
            "pinned_cost_model_id": "string",
            "pinned_artwork_round_id": "string",
            "status": SPEC_STATUS_SET,
        },
        ser.specification_out,
    )


@bp.post("/private-label/specifications/<specification_id>/lock")
def lock_specification(specification_id):
    user_id, _role = authenticate((ROLE_PROGRAM_DIRECTOR,))
    validate_body({})
    spec = get_specification(specification_id)
    item = get_item(spec["item_id"])
    program = program_of_item(item)
    guard_program_open(program)
    guard_not_frozen(program)
    if spec["status"] != "DRAFT":
        fail("ERR_SPECIFICATION_NOT_DRAFT")
    if item["development_status"] not in ("PACKAGING_APPROVED", "RELAUNCH_PENDING"):
        fail("ERR_ITEM_STATE_INVALID")
    supplier = get_supplier(item["supplier_id"])
    if supplier["qualification_status"] != "QUALIFIED":
        fail("ERR_SUPPLIER_NOT_QUALIFIED")
    cost_model = get_cost_model(spec["pinned_cost_model_id"])
    artwork_round = get_artwork_round(spec["pinned_artwork_round_id"])
    if artwork_round["nutrition_status"] != "VALID":
        fail("ERR_NUTRITION_PANEL_INVALID")
    if artwork_round["status"] != "APPROVED":
        fail("ERR_PIN_ITEM_MISMATCH")
    if (
        spec["pinned_cost_model_version"] != cost_model["version"]
        or spec["pinned_artwork_version"] != artwork_round["version"]
    ):
        fail("ERR_PIN_VERSION_STALE")
    landed = effective_landed_cost(cost_model)
    slotting_fee, retail_price = calc.spec_lock_pricing(
        landed, item["tier"], cost_model["moq_units"]
    )
    if slotting_fee > available_budget(program):
        fail("ERR_PROGRAM_BUDGET_EXCEEDED")
    spec["slotting_fee_cents"] = slotting_fee
    spec["status"] = "LOCKED"
    spec["locked_at"] = now()
    spec["locked_by_user_id"] = user_id
    touch(spec)
    commit_money(program, slotting_fee)
    touch(program)
    for sibling in specifications_of_item(item["id"]):
        if sibling["id"] != spec["id"] and sibling["status"] in ("LOCKED", "SUPERSEDE_PENDING"):
            sibling["status"] = "SUPERSEDED"
            touch(sibling)
    item["retail_price_cents"] = retail_price
    if item["development_status"] == "PACKAGING_APPROVED":
        item["development_status"] = "SPEC_LOCKED"
    touch(item)
    return object_response(ser.specification_out(spec))


# --------------------------------------------------------------------------
# production runs
# --------------------------------------------------------------------------
OCCUPYING_STATUSES = ("SCHEDULED", "APPROVED", "HOLD", "COMPLETED")


def _line_capacity(line, window_start, window_end):
    span = calc.D(minutes(window_end - window_start))
    return calc.floor0(calc.D(line["daily_capacity_units"]) * span / calc.D(1440))


def _line_conflict(line, window_start, window_end, exclude_run_id=None):
    buffer_span = timedelta(minutes=line["changeover_buffer_minutes"])
    start = window_start - buffer_span
    end = window_end + buffer_span
    for other in db.production_runs.values():
        if other["plant_line_id"] != line["id"] or other["id"] == exclude_run_id:
            continue
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        other_start = other["window_start"] - buffer_span
        other_end = other["window_end"] + buffer_span
        if start <= other_end and other_start <= end:
            return True
    return False


def _run_agreements(run_item, spec, line):
    if spec["item_id"] != run_item["id"]:
        fail("ERR_SPECIFICATION_ITEM_MISMATCH")
    if spec["status"] != "LOCKED":
        fail("ERR_SPECIFICATION_NOT_LOCKED")
    if line["supplier_id"] != run_item["supplier_id"]:
        fail("ERR_PLANT_LINE_SUPPLIER_MISMATCH")


@bp.post("/private-label/production-runs")
def create_run():
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    body = validate_body(
        {
            "item_id": Field("string", required=True),
            "specification_id": Field("string", required=True),
            "plant_line_id": Field("string", required=True),
            "run_type": Field("string", required=True, enum=RUN_TYPE_SET),
            "window_start": Field("datetime", required=True),
            "window_end": Field("datetime", required=True),
            "planned_units": Field(
                "integer", required=True, check=lambda v: v > 0, detail="must be strictly greater than zero"
            ),
        }
    )
    item = get_item(body["item_id"])
    spec = get_specification(body["specification_id"])
    line = get_plant_line(body["plant_line_id"])
    program = program_of_item(item)
    guard_program_open(program)
    if item["quality_posture"] == "SUSPENDED":
        fail("ERR_ITEM_QUALITY_SUSPENDED")
    _run_agreements(item, spec, line)
    if body["window_end"] <= body["window_start"]:
        fail("ERR_WINDOW_INVALID")
    if _line_conflict(line, body["window_start"], body["window_end"]):
        fail("ERR_LINE_WINDOW_CONFLICT")
    cost_model = get_cost_model(spec["pinned_cost_model_id"])
    if body["run_type"] == "FIRST_PRODUCTION" and body["planned_units"] < cost_model["moq_units"]:
        fail("ERR_BELOW_MOQ")
    if body["planned_units"] > _line_capacity(line, body["window_start"], body["window_end"]):
        fail("ERR_LINE_CAPACITY_EXCEEDED")
    tooling = cost_model["tooling_cents"]
    if tooling > available_budget(program):
        fail("ERR_PROGRAM_BUDGET_EXCEEDED")
    row = new_row(
        {
            "item_id": item["id"],
            "specification_id": spec["id"],
            "plant_line_id": line["id"],
            "run_type": body["run_type"],
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "planned_units": body["planned_units"],
            "produced_units": None,
            "completed_on_time": None,
            "completed_at": None,
            "committed_tooling_cents": tooling,
            "approved_by_user_id": None,
            "hold_reason": None,
            "status": "SCHEDULED",
        }
    )
    db.production_runs[row["id"]] = row
    commit_money(program, tooling)
    touch(program)
    return object_response(ser.production_run_out(row), 201)


@bp.get("/private-label/production-runs/<production_run_id>")
def read_run(production_run_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.production_run_out(get_run(production_run_id)))


@bp.get("/private-label/production-runs")
def list_runs():
    authenticate(ALL_ROLES)
    return paginate(
        db.production_runs,
        {
            "item_id": "string",
            "specification_id": "string",
            "plant_line_id": "string",
            "run_type": RUN_TYPE_SET,
            "status": RUN_STATUS_SET,
        },
        ser.production_run_out,
    )


@bp.post("/private-label/production-runs/<production_run_id>/approve")
def approve_run(production_run_id):
    user_id, _role = authenticate((ROLE_PROGRAM_DIRECTOR,))
    validate_body({})
    run = get_run(production_run_id)
    item = get_item(run["item_id"])
    spec = get_specification(run["specification_id"])
    line = get_plant_line(run["plant_line_id"])
    if spec["locked_by_user_id"] == user_id:
        fail(
            "ERR_RUN_SELF_APPROVAL",
            "The director who locked the specification may not approve its runs.",
        )
    guard_program_open(program_of_item(item))
    if run["status"] != "SCHEDULED":
        fail("ERR_RUN_STATE_INVALID")
    if item["quality_posture"] == "SUSPENDED":
        fail("ERR_ITEM_QUALITY_SUSPENDED")
    _run_agreements(item, spec, line)
    run["status"] = "APPROVED"
    run["approved_by_user_id"] = user_id
    touch(run)
    return object_response(ser.production_run_out(run))


@bp.post("/private-label/production-runs/<production_run_id>/complete")
def complete_run(production_run_id):
    authenticate((ROLE_QUALITY_AUDITOR,))
    body = validate_body(
        {
            "produced_units": Field(
                "integer", required=True, check=lambda v: v >= 0, detail="must not be negative"
            ),
            "completed_on_time": Field("boolean", required=True),
        }
    )
    run = get_run(production_run_id)
    item = get_item(run["item_id"])
    guard_program_open(program_of_item(item))
    if run["status"] != "APPROVED":
        fail("ERR_RUN_STATE_INVALID")
    if now() < run["window_end"]:
        fail("ERR_RUN_WINDOW_NOT_ELAPSED")
    run["produced_units"] = body["produced_units"]
    run["completed_on_time"] = body["completed_on_time"]
    run["completed_at"] = now()
    run["status"] = "COMPLETED"
    touch(run)
    supplier = db.suppliers.get(item["supplier_id"])
    if supplier is not None:
        before = supplier["composite_score_cached"]
        refresh_cached_composite(supplier)
        if supplier["composite_score_cached"] != before:
            touch(supplier)
    return object_response(ser.production_run_out(run))


@bp.post("/private-label/production-runs/<production_run_id>/release-hold")
def release_hold(production_run_id):
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    validate_body({})
    run = get_run(production_run_id)
    item = get_item(run["item_id"])
    guard_program_open(program_of_item(item))
    if run["status"] != "HOLD":
        fail("ERR_RUN_STATE_INVALID")
    if item["quality_posture"] == "SUSPENDED":
        fail("ERR_ITEM_QUALITY_SUSPENDED")
    supplier = get_supplier(item["supplier_id"])
    if supplier["qualification_status"] != "QUALIFIED":
        fail("ERR_SUPPLIER_NOT_QUALIFIED")
    run["status"] = "SCHEDULED"
    touch(run)
    return object_response(ser.production_run_out(run))


@bp.post("/private-label/production-runs/<production_run_id>/cancel")
def cancel_run(production_run_id):
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    validate_body({})
    run = get_run(production_run_id)
    item = get_item(run["item_id"])
    program = program_of_item(item)
    guard_program_open(program)
    if run["status"] not in ("SCHEDULED", "APPROVED", "HOLD"):
        fail("ERR_RUN_STATE_INVALID")
    run["status"] = "CANCELLED"
    touch(run)
    release_money(program, run["committed_tooling_cents"])
    touch(program)
    return object_response(ser.production_run_out(run))

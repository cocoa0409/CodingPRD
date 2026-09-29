"""Qualifier loading and adjudication (PRD 3.2)."""

from flask import Blueprint

import calc
import serialize
from auth import ALL_ROLES, OPERATOR_ROLES, authorize, own_qualifier
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import body, f_id, f_int, f_str, raw_fk, validate
from store import db

bp = Blueprint("qualifiers", __name__)

LOAD_STATUSES = ("DESIGN", "SOURCING", "CONTRACTED")


@bp.post("/qualifiers")
def create_qualifier():
    authorize("SalesOpsAnalyst")
    payload = body()

    program_id = raw_fk(payload, "program_id")
    if program_id is not None:
        lookup("program", program_id)

    data = validate(payload, [
        f_id("program_id"),
        f_str("employee_code", max_len=40),
        f_str("full_name", max_len=160),
        f_int("baseline_metric", minimum=0),
        f_int("actual_metric", minimum=0),
        f_int("guest_count", required=False, default=0, minimum=0, maximum=2),
    ])
    program = lookup("program", data["program_id"])
    program_gate(program, LOAD_STATUSES)

    for existing in db.qualifiers.values():
        if (existing["program_id"] == data["program_id"]
                and existing["employee_code"] == data["employee_code"]):
            fail("ERR_DUPLICATE_EMPLOYEE_CODE")

    row = {
        "program_id": data["program_id"],
        "employee_code": data["employee_code"],
        "full_name": data["full_name"],
        "baseline_metric": data["baseline_metric"],
        "actual_metric": data["actual_metric"],
        "guest_count": data["guest_count"],
        "award_status": "PENDING_REVIEW",
        "tax_status": "NOT_APPLICABLE",
        "assigned_tier_id": None,
        "committed_cost_cents": 0,
        "taxable_award_cents": 0,
        "notified_at": None,
    }
    db.stamp_new(row)
    db.qualifiers[row["id"]] = row
    return created(serialize.qualifier(row))


@bp.get("/qualifiers/<qualifier_id>")
def read_qualifier(qualifier_id):
    actor = authorize(*ALL_ROLES)
    qualifier = lookup("qualifier", qualifier_id)
    own_qualifier(actor, qualifier["id"])
    return ok(serialize.qualifier(qualifier))


@bp.get("/qualifiers")
def list_qualifiers():
    authorize(*OPERATOR_ROLES)
    rows = filtered(db.ordered(db.qualifiers), [
        ("program_id", "program_id"),
        ("assigned_tier_id", "assigned_tier_id"),
        ("award_status", "award_status"),
        ("tax_status", "tax_status"),
        ("employee_code", "employee_code"),
    ])
    return paginate(rows, serialize.qualifier)


@bp.post("/qualifiers/<qualifier_id>/review")
def review_qualifier(qualifier_id):
    authorize("SalesOpsAnalyst")
    qualifier = lookup("qualifier", qualifier_id)
    body()
    program = db.programs.get(qualifier["program_id"])
    program_gate(program, LOAD_STATUSES)

    if qualifier["award_status"] != "PENDING_REVIEW":
        fail("ERR_QUALIFIER_STATE_INVALID")

    tier = calc.select_tier(db, qualifier)
    if tier is None:
        qualifier["award_status"] = "DISQUALIFIED"
        qualifier["assigned_tier_id"] = None
        qualifier["committed_cost_cents"] = 0
        db.touch(qualifier)
        return ok(serialize.qualifier(qualifier))

    if qualifier["guest_count"] > tier["guest_allowance"]:
        fail("ERR_GUEST_ALLOWANCE_EXCEEDED")

    committed = calc.qualifier_committed_cost(db, qualifier, tier)
    if committed > tier["budget_per_qualifier_cents"]:
        fail("ERR_TIER_BUDGET_EXCEEDED")

    qualifier["assigned_tier_id"] = tier["id"]
    qualifier["committed_cost_cents"] = committed
    qualifier["award_status"] = "QUALIFIED"
    db.touch(qualifier)

    calc.program_counts(db, program)
    calc.program_budget_rollup(db, program)
    return ok(serialize.qualifier(qualifier))

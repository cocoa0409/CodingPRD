"""Farming plans (draft, review loop, approval) and labor crews."""

from flask import Blueprint

import calc
import derive
import service
import store
from common import ApiError, invalid, respond_list, respond_object
from validate import F, auth, pagination, parse_payload

bp = Blueprint("plans", __name__)

QUALITY_TARGETS = ("PREMIUM", "STANDARD", "BULK")
PLAN_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED")
PAY_STRUCTURES = ("PIECE_RATE", "HOURLY")
TASK_TYPES = ("PRUNING", "SUCKERING", "LEAFING", "HARVEST")
CREW_STATUSES = ("ACTIVE", "INACTIVE")

PLAN_ROLES = ["VineyardManager", "Agronomist", "Controller"]

PLAN_SCHEMA = [
    F("block_id", "id", min_len=1),
    F("plan_year", "integer", ge=2000, le=2100),
    F("quality_target", "enum", values=QUALITY_TARGETS),
    F("pruning_budget_per_acre", "number", ge=0),
    F("canopy_budget_per_acre", "number", ge=0),
    F("irrigation_budget_per_acre", "number", ge=0),
    F("pest_budget_per_acre", "number", ge=0),
    F("seasonal_water_cap_inches", "number", ge=0),
]


@bp.route("/farming-plans", methods=["POST"])
def create_plan():
    auth(["VineyardManager", "Agronomist"])
    body = parse_payload(PLAN_SCHEMA)
    block = service.get_block(body["block_id"])
    service.require_block_live(block)

    for other in store.plans.values():
        if other["block_id"] == block["id"] and other["plan_year"] == body["plan_year"]:
            raise ApiError("ERR_DUPLICATE_PLAN_FOR_BLOCK_YEAR", 409)

    row = store.new_row()
    row.update({
        "block_id": block["id"],
        "plan_year": body["plan_year"],
        "quality_target": body["quality_target"],
        "pruning_budget_per_acre": body["pruning_budget_per_acre"],
        "canopy_budget_per_acre": body["canopy_budget_per_acre"],
        "irrigation_budget_per_acre": body["irrigation_budget_per_acre"],
        "pest_budget_per_acre": body["pest_budget_per_acre"],
        "seasonal_water_cap_inches": body["seasonal_water_cap_inches"],
        "plan_status": "DRAFT",
        "revision_count": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
    })
    row["total_budget"] = calc.plan_total_budget(row, block)
    store.plans[row["id"]] = row
    return respond_object(derive.serialize_plan(row), 201)


@bp.route("/farming-plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    auth(PLAN_ROLES)
    plan = service.get_plan(plan_id)
    return respond_object(derive.serialize_plan(plan))


@bp.route("/farming-plans", methods=["GET"])
def list_plans():
    auth(PLAN_ROLES)
    rows = service.filtered(store.plans, (
        ("block_id", "block_id"),
        ("plan_year", "plan_year"),
        ("plan_status", "plan_status"),
    ))
    items, limit, offset, total = service.page(rows, derive.serialize_plan)
    return respond_list(items, limit, offset, total)


SUBMIT_SCHEMA = [F("submission_note", "string", required=False, nullable=True,
                   max_len=1000, blank_ok=True)]


@bp.route("/farming-plans/<plan_id>/submit", methods=["POST"])
def submit_plan(plan_id):
    user_id, _role = auth(["VineyardManager"])
    parse_payload(SUBMIT_SCHEMA)
    plan = service.get_plan(plan_id)
    if plan["plan_status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", 409)
    block = store.blocks[plan["block_id"]]
    service.require_block_live(block)

    plan["plan_status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = user_id
    store.touch(plan)
    return respond_object(derive.serialize_plan(plan))


RETURN_SCHEMA = [F("revision_note", "string", min_len=1, max_len=1000)]


@bp.route("/farming-plans/<plan_id>/return-for-revision", methods=["POST"])
def return_plan(plan_id):
    auth(["Controller"])
    parse_payload(RETURN_SCHEMA)
    plan = service.get_plan(plan_id)
    if plan["plan_status"] != "SUBMITTED":
        raise ApiError("ERR_PLAN_NOT_SUBMITTED", 409)
    if plan["revision_count"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED", 409)

    plan["plan_status"] = "DRAFT"
    plan["revision_count"] = plan["revision_count"] + 1
    plan["submitted_by_user_id"] = None
    store.touch(plan)
    return respond_object(derive.serialize_plan(plan))


APPROVE_SCHEMA = [F("approval_note", "string", required=False, nullable=True,
                    max_len=1000, blank_ok=True)]


@bp.route("/farming-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(plan_id):
    user_id, _role = auth(["Controller"])
    parse_payload(APPROVE_SCHEMA)
    plan = service.get_plan(plan_id)
    if plan["plan_status"] != "SUBMITTED":
        raise ApiError("ERR_PLAN_NOT_SUBMITTED", 409)
    block = store.blocks[plan["block_id"]]
    service.require_block_live(block)
    service.require_distinct(user_id, [plan["submitted_by_user_id"]])

    plan["plan_status"] = "APPROVED"
    plan["approved_by_user_id"] = user_id
    store.touch(plan)

    # guarded cascade: third leaf drives ESTABLISHING -> BEARING
    if (block["farming_status"] == "ESTABLISHING"
            and plan["plan_year"] >= block["planting_year"] + 3):
        block["farming_status"] = "BEARING"
        store.touch(block)

    return respond_object(derive.serialize_plan(plan))


# --------------------------------------------------------------------------
# LaborCrew
# --------------------------------------------------------------------------

CREW_SCHEMA = [
    F("crew_name", "string", min_len=1, max_len=80),
    F("pay_structure", "enum", values=PAY_STRUCTURES),
    F("crew_size", "integer", ge=1),
    F("base_hourly_rate", "number", ge=0),
    F("piece_rate_per_vine", "number", ge=0),
    F("vines_per_hour_standard", "number", gt=0),
    F("task_capabilities", "enum_array", values=TASK_TYPES),
    F("pest_certified", "boolean"),
    F("crew_status", "enum", required=False, values=CREW_STATUSES),
]


@bp.route("/crews", methods=["POST"])
def create_crew():
    auth(["VineyardManager"])
    body = parse_payload(CREW_SCHEMA)

    # rung 6 — pay-structure coherence
    if body["pay_structure"] == "PIECE_RATE":
        if not body["piece_rate_per_vine"] > 0:
            raise invalid("piece_rate_per_vine must be greater than zero for a PIECE_RATE crew.")
    else:
        if body["piece_rate_per_vine"] != 0:
            raise invalid("piece_rate_per_vine must be exactly zero for an HOURLY crew.")

    row = store.new_row()
    row.update({
        "crew_name": body["crew_name"],
        "pay_structure": body["pay_structure"],
        "crew_size": body["crew_size"],
        "base_hourly_rate": body["base_hourly_rate"],
        "piece_rate_per_vine": body["piece_rate_per_vine"],
        "vines_per_hour_standard": body["vines_per_hour_standard"],
        "task_capabilities": list(body["task_capabilities"]),
        "pest_certified": body["pest_certified"],
        "crew_status": body.get("crew_status", "ACTIVE"),
    })
    store.crews[row["id"]] = row
    return respond_object(derive.serialize_crew(row), 201)


@bp.route("/crews/<crew_id>", methods=["GET"])
def read_crew(crew_id):
    auth(["VineyardManager", "Controller", "CrewSupervisor"])
    crew = service.get_crew(crew_id)
    return respond_object(derive.serialize_crew(crew))

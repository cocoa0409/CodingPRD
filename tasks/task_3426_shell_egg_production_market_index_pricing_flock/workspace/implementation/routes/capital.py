"""Capital projects (PRD §3.5): proposal under a commitment, approval,
run-ops-driven construction start, and commissioning — which flips the
house's housing_style and recomputes the commitment's transition progress."""

from datetime import timedelta

from flask import Blueprint, request

from auth import authenticate, require_role
from db import STORE, set_dt, stamp_new, touch
from errors import (
    ApiError,
    ERR_CONSTRUCTION_INCOMPLETE,
    ERR_CONVERSION_REDUNDANT,
    ERR_HOUSE_NOT_FOUND,
    ERR_INVALID_STATE,
)
from helpers import get_capital_project, get_commitment, get_house, list_response
from serialize import serialize_capital_project
from util import TARGET_STYLES, success_object
from validate import get_body, validate_payload

bp = Blueprint("capital", __name__)


@bp.route("/api/commitments/<cid>/capital-projects", methods=["POST"])
def create_capital_project(cid):
    _uid, role = authenticate()
    require_role(role, {"ProductionPlanner"})
    commitment = get_commitment(cid)
    body = get_body()
    # Priority 5: the body house_id resolves before payload shape is judged.
    raw_house = body.get("house_id") if isinstance(body, dict) else None
    if isinstance(raw_house, str) and raw_house not in STORE.houses:
        raise ApiError(ERR_HOUSE_NOT_FOUND, 404, "house not found: %s" % raw_house)
    values, _raws = validate_payload(
        body,
        {
            "house_id": {"kind": "string", "required": True},
            "investment_cents": {"kind": "int", "required": True, "gt": 0},
            "target_style": {
                "kind": "enum", "required": True, "enum": TARGET_STYLES,
            },
            "construction_weeks": {"kind": "int", "required": True, "gt": 0},
        },
    )
    house = get_house(values["house_id"])
    project = {
        "commitment_id": commitment["id"],
        "house_id": house["id"],
        "investment_cents": values["investment_cents"],
        "target_style": values["target_style"],
        "construction_weeks": values["construction_weeks"],
        "construction_started_at": None,
        "_dt_construction_started_at": None,
        "commissioned_at": None,
        "_dt_commissioned_at": None,
        "status": "PROPOSED",
    }
    stamp_new(project)
    STORE.capital_projects[project["id"]] = project
    return success_object(serialize_capital_project(project), 201)


@bp.route("/api/commitments/<cid>/capital-projects", methods=["GET"])
def list_commitment_capital_projects(cid):
    authenticate()
    commitment = get_commitment(cid)
    items = [
        p
        for p in STORE.capital_projects.values()
        if p["commitment_id"] == commitment["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, serialize_capital_project)


@bp.route("/api/capital-projects/<pid>/approve", methods=["POST"])
def approve_capital_project(pid):
    _uid, role = authenticate()
    require_role(role, {"ProductionPlanner"})
    project = get_capital_project(pid)
    validate_payload(get_body(), {})
    if project["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "project is not PROPOSED")
    commitment = STORE.commitments.get(project["commitment_id"])
    if commitment is None or commitment["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "commitment is not ACTIVE")
    house = STORE.houses.get(project["house_id"])
    if house is not None and house["housing_style"] == project["target_style"]:
        raise ApiError(
            ERR_CONVERSION_REDUNDANT,
            422,
            "target_style equals the house's current housing_style",
        )
    project["status"] = "APPROVED"
    touch(project)
    return success_object(serialize_capital_project(project))


@bp.route("/api/capital-projects/<pid>/commission", methods=["POST"])
def commission_capital_project(pid):
    _uid, role = authenticate()
    require_role(role, {"ProductionPlanner"})
    project = get_capital_project(pid)
    validate_payload(get_body(), {})
    if project["status"] != "IN_CONSTRUCTION":
        raise ApiError(ERR_INVALID_STATE, 409, "project is not IN_CONSTRUCTION")
    clock = STORE.clock
    earliest = project["_dt_construction_started_at"] + timedelta(
        weeks=project["construction_weeks"]
    )
    if clock < earliest:
        raise ApiError(
            ERR_CONSTRUCTION_INCOMPLETE,
            409,
            "construction duration has not elapsed",
        )
    project["status"] = "COMMISSIONED"
    set_dt(project, "commissioned_at", clock)
    touch(project)
    # LINK 1 — the house flips to the target style.
    house = STORE.houses.get(project["house_id"])
    if house is not None:
        house["housing_style"] = project["target_style"]
        touch(house)
    # LINK 2 — the commitment's transition progress recomputes (bumped).
    commitment = STORE.commitments.get(project["commitment_id"])
    if commitment is not None:
        touch(commitment)
    return success_object(serialize_capital_project(project))

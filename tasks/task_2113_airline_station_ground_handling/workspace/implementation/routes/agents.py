from flask import Blueprint

import constants as C
import validators as V
from auth import authorize, current_role, current_user
from domain import serialize_agent
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import db, new_record, ordered, require

bp = Blueprint("agents", __name__)

AGENT_WRITE_ROLES = [C.ROLE_STATION_MANAGER, C.ROLE_SUBCONTRACTOR_ADMIN]


@bp.post("/agents")
def create_agent():
    authorize(AGENT_WRITE_ROLES)
    payload = V.body()

    station_id = V.req_string(payload, "station_id")
    employee_code = V.req_string(payload, "employee_code")
    full_name = V.req_string(payload, "full_name")
    subcontractor_id = V.opt_string(payload, "subcontractor_id")

    station = require(db.stations, station_id, "Station")
    sub = None
    if subcontractor_id is not None:
        sub = require(db.subcontractors, subcontractor_id, "Subcontractor")
        if sub["station_id"] != station["id"]:
            raise ApiError("ERR_STATION_SCOPE_MISMATCH")

    if current_role() == C.ROLE_SUBCONTRACTOR_ADMIN:
        if sub is None or sub["id"] != current_user():
            raise ApiError("ERR_OWNERSHIP_VIOLATION")

    for existing in db.agents.values():
        if existing["station_id"] == station["id"] and existing["employee_code"] == employee_code:
            raise ApiError("ERR_DUPLICATE_CODE", "employee_code already exists at this station.")

    agent = new_record("Agent", {
        "station_id": station["id"],
        "subcontractor_id": sub["id"] if sub else None,
        "employee_code": employee_code,
        "full_name": full_name,
        "employment_type": "SUBCONTRACTED" if sub else "DIRECT",
        "status": "ACTIVE",
        "certification_posture": "LAPSED",
        "assigned_duty_minutes": 0,
    })
    db.agents[agent["id"]] = agent
    return respond_object(serialize_agent(agent), 201)


@bp.get("/agents/<agent_id>")
def read_agent(agent_id):
    authorize(C.ALL_ROLES)
    agent = require(db.agents, agent_id, "Agent")
    return respond_object(serialize_agent(agent))


@bp.get("/agents")
def list_agents():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.agents.values(), {
        "station_id": "station_id",
        "subcontractor_id": "subcontractor_id",
        "status": "status",
    })
    return paginate(ordered(records), serialize_agent)

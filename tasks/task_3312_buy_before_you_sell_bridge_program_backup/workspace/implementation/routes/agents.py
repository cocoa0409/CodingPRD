"""Agent roster routes (PRD 3.1)."""

from flask import Blueprint

from constants import ROLES
from routes import endpoint, json_body, query_params
from services import agency
from services.lookup import get_agent
from store import db

bp = Blueprint("agents", __name__)

COORDINATOR = ROLES[0]
AGENT = ROLES[3]


@bp.post("/knock/agents")
@endpoint([COORDINATOR], status=201)
def register_agent(actor):
    return agency.create_agent(json_body())


@bp.get("/knock/agents/<agent_id>")
@endpoint([COORDINATOR, AGENT])
def read_agent(actor, agent_id):
    return get_agent(agent_id)


@bp.post("/knock/agents/<agent_id>/qualify")
@endpoint([COORDINATOR])
def qualify(actor, agent_id):
    return agency.qualify_agent(agent_id)


@bp.post("/knock/agents/<agent_id>/suspend")
@endpoint([COORDINATOR])
def suspend(actor, agent_id):
    return agency.suspend_agent(agent_id)


@bp.patch("/knock/agents/<agent_id>")
@endpoint([COORDINATOR])
def reinstate(actor, agent_id):
    return agency.reinstate_agent(agent_id, json_body())
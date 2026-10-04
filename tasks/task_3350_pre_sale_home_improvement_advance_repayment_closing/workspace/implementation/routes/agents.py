"""Agent reference data (PRD 3.1)."""
from flask import Blueprint

from auth import require_roles
from db import store
from envelope import success_obj
from logic import get_or_404, new_record, serialize
from validate import body_json, req_str

bp = Blueprint("agents", __name__)


@bp.post("/concierge/agents")
@require_roles("PlatformAdmin")
def create_agent():
    body = body_json(required=True)
    rec = new_record({
        "display_name": req_str(body, "display_name"),
        "license_number": req_str(body, "license_number"),
        "brokerage": req_str(body, "brokerage"),
    })
    store.agents[rec["id"]] = rec
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/agents/<agentId>")
@require_roles("Any")
def get_agent(agentId):
    return success_obj(serialize(get_or_404(store.agents, agentId, "Agent")))

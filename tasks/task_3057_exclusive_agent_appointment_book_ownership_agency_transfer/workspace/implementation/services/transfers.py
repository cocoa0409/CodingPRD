"""Book transfers (PRD §3.7)."""

import clock
import db
import middleware
from errors import ApiError, ERR_INVALID_STATE
from services import calculations as calc
from services import factories, recompute


def post(agent, payload):
    from_agency_id = payload.get("from_agency_id")
    to_agency_id = payload.get("to_agency_id")
    if from_agency_id is not None and from_agency_id not in db.agency_rows():
        raise ApiError("ERR_AGENCY_NOT_FOUND")
    if to_agency_id is not None and to_agency_id not in db.agency_rows():
        raise ApiError("ERR_AGENCY_NOT_FOUND")

    transfer = factories.create_book_transfer({
        "agent_id": agent["id"],
        "from_agency_id": from_agency_id,
        "to_agency_id": to_agency_id,
        "for_cause": payload.get("for_cause"),
    })
    if payload.get("successor_agent_id"):
        transfer["successor_agent_id"] = payload.get("successor_agent_id")
    _attach_policies(transfer)
    recompute.recompute_book_transfer(transfer["id"])
    return transfer


def _attach_policies(transfer):
    """The transfer book is the agent's policies at the moment it is posted;
    every one counts as transferred, and only the ones still OPEN and held by
    the successor count as retained (PRD §3.7)."""
    for policy in db.policy_rows().values():
        if policy["holder_agent_id"] != transfer["agent_id"]:
            continue
        if policy.get("book_transfer_id") is not None:
            continue
        policy["book_transfer_id"] = transfer["id"]
        recompute.touch(policy)


def list_transfers(request):
    rows = list(db.transfer_rows().values())
    rows = middleware.filter_by(rows, {
        "agent_id": request.args.get("agent_id"),
        "from_agency_id": request.args.get("from_agency_id"),
        "to_agency_id": request.args.get("to_agency_id"),
        "successor_agent_id": request.args.get("successor_agent_id"),
        "status": request.args.get("status"),
    })
    rows.sort(key=lambda t: t["created_at"])
    return rows


def transfers_for_agent(agent, request):
    rows = [t for t in db.transfer_rows().values() if t["agent_id"] == agent["id"]]
    rows.sort(key=lambda t: t["created_at"])
    return rows
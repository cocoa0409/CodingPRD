"""Policy book maintenance (PRD §3.8)."""

import db
import middleware
from errors import (
    ApiError, ERR_AGENCY_NOT_FOUND, ERR_AGENT_NOT_FOUND, ERR_DUPLICATE_POLICY,
    ERR_INVALID_STATE,
)
from services import factories, recompute

TERMINAL = ("CANCELLED", "TRANSFERRED")


def create(payload):
    # Existence of the named owner agency and holder agent precedes every
    # business check, validated left to right agency-then-agent (PRD §2.6).
    agency_id = payload.get("owner_agency_id")
    if agency_id is None or agency_id not in db.agency_rows():
        raise ApiError(ERR_AGENCY_NOT_FOUND)
    holder_id = payload.get("holder_agent_id")
    if holder_id is None or holder_id not in db.agent_rows():
        raise ApiError(ERR_AGENT_NOT_FOUND)

    number = payload.get("policy_number")
    if number is not None:
        for existing in db.policy_rows().values():
            if existing["policy_number"] == number:
                raise ApiError(ERR_DUPLICATE_POLICY)

    policy = factories.create_policy(payload)
    if agency_id in db.agency_rows():
        recompute.recompute_agency_soft(agency_id)
    return policy


def list_policies(request, role=None, user_id=None):
    rows = list(db.policy_rows().values())
    if role == "AgencyPrincipal":
        rows = [p for p in rows if p["owner_agency_id"] == user_id]
    rows = middleware.filter_by(rows, {
        "holder_agent_id": request.args.get("holder_agent_id"),
        "owner_agency_id": request.args.get("owner_agency_id"),
        "book_transfer_id": request.args.get("book_transfer_id"),
        "status": request.args.get("status"),
    })
    rows.sort(key=lambda p: p["created_at"])
    return rows


def cancel(policy):
    if policy["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if policy["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    policy["status"] = "CANCELLED"
    recompute.touch(policy)

    agency_id = policy.get("owner_agency_id")
    if agency_id and agency_id in db.agency_rows():
        recompute.recompute_agency_soft(agency_id)
    return policy


def policies_for_agency(agency, request):
    rows = middleware.filter_by(
        [p for p in db.policy_rows().values() if p["owner_agency_id"] == agency["id"]],
        {"status": request.args.get("status")})
    rows.sort(key=lambda p: p["created_at"])
    return rows
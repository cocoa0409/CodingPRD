"""Governance exceptions and the technical-debt ledger (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import errors
from auth import (CONTRIBUTING_TEAM, DESIGN_SYSTEM_LEAD, actor_id, ensure_owner,
                  require_roles)
from entities import get_component, get_grant, get_team, grant_json
from errors import fail
from responses import created, ok
from routes.common import respond_list
from store import iso, sort_created_asc, store
from validation import (body, opt_string, pagination, query_enum, query_string,
                        req_datetime, req_enum, req_string)

bp = Blueprint("grants", __name__, url_prefix="/design-system")

EXCEPTION_KINDS = ("ONE_OFF_COMPONENT", "FORK_OF_SYSTEM_COMPONENT", "RAW_TOKEN_USAGE")
PLATFORM_SCOPES = ("WEB", "IOS", "ANDROID", "ALL")
GRANT_STATES = ("REQUESTED", "APPROVED", "DENIED", "EXPIRED", "REPAID")
DECISIONS = ("APPROVE", "DENY")


@bp.post("/exception-grants")
@require_roles(CONTRIBUTING_TEAM)
def request_grant():
    payload = body()
    requesting_team_id = req_string(payload, "requesting_team_id", 1, 200)
    substitute_for_component_id = req_string(payload, "substitute_for_component_id",
                                             1, 200)
    exception_kind = req_enum(payload, "exception_kind", EXCEPTION_KINDS)
    platform_scope = req_enum(payload, "platform_scope", PLATFORM_SCOPES)
    justification = req_string(payload, "justification", 1, 2000)
    expires_at = req_datetime(payload, "expires_at")

    team = get_team(requesting_team_id)
    get_component(substitute_for_component_id)
    ensure_owner(team["id"])

    row = store.new_row()
    row.update({
        "requesting_team_id": team["id"],
        "substitute_for_component_id": substitute_for_component_id,
        "exception_kind": exception_kind,
        "platform_scope": platform_scope,
        "justification": justification,
        "expires_at": iso(expires_at),
        "state": "REQUESTED",
        "debt_points": Decimal("0.00"),
        "pinned_maturity_level": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "repaid_at": None,
        "_expires_dt": expires_at,
    })
    store.grants[row["id"]] = row
    return created(grant_json(row))


@bp.get("/exception-grants")
@require_roles()
def list_grants():
    limit, offset = pagination()
    requesting_team_id = query_string("requesting_team_id")
    substitute_for_component_id = query_string("substitute_for_component_id")
    state = query_enum("state", GRANT_STATES)
    exception_kind = query_enum("exception_kind", EXCEPTION_KINDS)

    rows = list(store.grants.values())
    if requesting_team_id is not None:
        rows = [g for g in rows if g["requesting_team_id"] == requesting_team_id]
    if substitute_for_component_id is not None:
        rows = [g for g in rows
                if g["substitute_for_component_id"] == substitute_for_component_id]
    if state is not None:
        rows = [g for g in rows if g["state"] == state]
    if exception_kind is not None:
        rows = [g for g in rows if g["exception_kind"] == exception_kind]
    return respond_list(sort_created_asc(rows), grant_json, limit, offset)


@bp.get("/exception-grants/<grant_id>")
@require_roles()
def read_grant(grant_id):
    grant = get_grant(grant_id)
    ensure_owner(grant["requesting_team_id"])
    return ok(grant_json(grant))


@bp.post("/exception-grants/<grant_id>/decision")
@require_roles(DESIGN_SYSTEM_LEAD)
def decide_grant(grant_id):
    payload = body()
    decision = req_enum(payload, "decision", DECISIONS)
    opt_string(payload, "decision_notes", 1, 2000)

    grant = get_grant(grant_id)

    if grant["state"] != "REQUESTED":
        fail(errors.ERR_INVALID_EXCEPTION_GRANT_STATE,
             "A grant in %s cannot be decided." % grant["state"])

    component = store.components[grant["substitute_for_component_id"]]
    if component["lifecycle_state"] == "REMOVED":
        fail(errors.ERR_COMPONENT_LIFECYCLE_BLOCKS_SHIP,
             "The substitute component has been removed from the inventory.")

    team = store.teams[grant["requesting_team_id"]]

    if decision == "DENY":
        grant["state"] = "DENIED"
        grant["decided_by_user_id"] = actor_id()
        grant["decided_at"] = store.now_iso
        store.touch(grant)
        return ok(grant_json(grant))

    points = calc.grant_debt_points(grant["exception_kind"], grant["platform_scope"],
                                    component["maturity_level"])
    if team["outstanding_debt_points"] + points > team["debt_budget_points"]:
        fail(errors.ERR_TEAM_DEBT_BUDGET_EXCEEDED,
             "The grant would push the team past its technical-debt budget.")

    grant["pinned_maturity_level"] = component["maturity_level"]
    grant["debt_points"] = points
    grant["state"] = "APPROVED"
    grant["decided_by_user_id"] = actor_id()
    grant["decided_at"] = store.now_iso
    store.touch(grant)

    calc.recompute_team_debt(team)
    store.touch(team)

    calc.recompute_one_off_exception_count(component)
    store.touch(component, bump=False)

    return ok(grant_json(grant))


@bp.post("/exception-grants/<grant_id>/repay")
@require_roles(CONTRIBUTING_TEAM)
def repay_grant(grant_id):
    payload = body()
    req_string(payload, "remediation_notes", 1, 2000)

    grant = get_grant(grant_id)
    ensure_owner(grant["requesting_team_id"])

    if grant["state"] not in ("APPROVED", "EXPIRED"):
        fail(errors.ERR_INVALID_EXCEPTION_GRANT_STATE,
             "A grant in %s cannot be repaid." % grant["state"])

    grant["state"] = "REPAID"
    grant["repaid_at"] = store.now_iso
    store.touch(grant)

    team = store.teams[grant["requesting_team_id"]]
    calc.recompute_team_debt(team)
    store.touch(team)

    component = store.components.get(grant["substitute_for_component_id"])
    if component is not None:
        calc.recompute_one_off_exception_count(component)
        store.touch(component, bump=False)

    return ok(grant_json(grant))

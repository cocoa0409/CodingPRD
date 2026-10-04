"""Agent endpoints (PRD 3.2)."""

from flask import Blueprint, request

import auth
import constants as K
import lookup
import models
import recompute
from errors import (APIError, ERR_ACTIVE_BACKUP_SET_PRESENT,
                    ERR_AGENT_HOSTNAME_TAKEN, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_LICENSE_TIER_EXCEEDED, ERR_UNAUTHORIZED)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import pagination, req_enum, req_int, req_str

bp = Blueprint("agents", __name__, url_prefix="/backup-provider")


@bp.route("/agents", methods=["POST"])
def create_agent():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_AGENT_CREATE)
    body = request.get_json(silent=True) or {}

    # PRD 2.10: body ids validated left to right, account then group.
    account_id = req_str(body, "account_id")
    account = lookup.account(account_id)
    group_id = req_str(body, "group_id")
    group = lookup.group(group_id)
    if group["account_id"] != account["id"]:
        raise APIError(ERR_INVALID_REQUEST,
                       "group does not belong to the referenced account")

    hostname = req_str(body, "hostname")
    os_type = req_enum(body, "os_type", K.OS_TYPES)
    license_type = req_enum(body, "license_type", K.LICENSE_TYPES)
    throttle_month = req_int(body, "throttle_month")
    if throttle_month < 100000 or throttle_month > 999912:
        raise APIError(ERR_INVALID_REQUEST,
                       "throttle_month must be a four-digit year followed by a two-digit month")

    agent = models.agent(store, account["id"], group["id"], hostname, os_type,
                         license_type, throttle_month)
    store.agents[agent["id"]] = agent
    return object_response(models.public(agent), 201)


@bp.route("/agents", methods=["GET"])
def list_agents():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_AGENT_READ)
    limit, offset = pagination(request.args)

    account_id = request.args.get("account_id")
    group_id = request.args.get("group_id")
    status = request.args.get("status")
    rows = list(store.agents.values())
    if account_id:
        rows = [a for a in rows if a["account_id"] == account_id]
    if group_id:
        rows = [a for a in rows if a["group_id"] == group_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    if caller.is_account_owner:
        rows = [a for a in rows if a["account_id"] == caller.user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(a) for a in page], limit, offset, total)


@bp.route("/agents/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_AGENT_READ)
    agent = lookup.agent(lookup.ensure_id(agent_id, "id"))
    if caller.is_account_owner and not caller.owns(agent["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    return object_response(models.public(agent))


def _licence_ok(account_type, license_type):
    """PRD 3.2 ceiling: PERSONAL on PERSONAL; BUSINESS on BUSINESS/ENTERPRISE;
    ENTERPRISE only on ENTERPRISE."""
    return license_type in K.LICENSE_CEILING.get(account_type, ())


def _hostname_free(account_id, hostname, exclude_agent_id=None):
    for other in store.agents.values():
        if other["account_id"] != account_id:
            continue
        if exclude_agent_id is not None and other["id"] == exclude_agent_id:
            continue
        if other["hostname"] == hostname and other["status"] != "RETIRED":
            return False
    return True


@bp.route("/agents/<agent_id>/activate", methods=["POST"])
def activate_agent(agent_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_AGENT_MUTATE)
    agent = lookup.agent(lookup.ensure_id(agent_id, "id"))
    account = store.accounts.get(agent["account_id"])
    group = store.groups.get(agent["group_id"])

    if agent["status"] != "PENDING_AUTH":
        raise APIError(ERR_INVALID_STATE, "agent is not PENDING_AUTH")

    # Level 6: licence ceiling then hostname uniqueness, in that order
    # (PRD 3.2 states the ceiling first).
    if account is None or not _licence_ok(account["account_type"], agent["license_type"]):
        raise APIError(ERR_LICENSE_TIER_EXCEEDED,
                       "license_type %s exceeds the account ceiling" % agent["license_type"])
    if not _hostname_free(agent["account_id"], agent["hostname"], agent["id"]):
        raise APIError(ERR_AGENT_HOSTNAME_TAKEN,
                       "another agent of the account already uses this hostname")

    agent["status"] = "ACTIVE"
    if group is not None:
        recompute.recompute_group_metrics(store, group)
        lookup.bump(group)
    lookup.bump(agent)
    return object_response(models.public(agent))


@bp.route("/agents/<agent_id>/retire", methods=["POST"])
def retire_agent(agent_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_AGENT_MUTATE)
    agent = lookup.agent(lookup.ensure_id(agent_id, "id"))
    group = store.groups.get(agent["group_id"])

    if agent["status"] in ("RETIRED",):
        raise APIError(ERR_INVALID_STATE, "agent is already RETIRED")

    if agent["status"] == "ACTIVE":
        live = [s for s in store.sets_of_agent(agent["id"])
                if s["state"] in ("INITIAL_RUNNING", "ACTIVE", "SUSPENDED")]
        if live:
            raise APIError(ERR_ACTIVE_BACKUP_SET_PRESENT,
                           "agent still holds a live backup set")

    agent["status"] = "RETIRED"
    if group is not None:
        recompute.recompute_group_metrics(store, group)
        lookup.bump(group)
    lookup.bump(agent)
    return object_response(models.public(agent))


@bp.route("/agents/<agent_id>/block", methods=["POST"])
def block_agent(agent_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    agent = lookup.agent(lookup.ensure_id(agent_id, "id"))

    if agent["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "agent is not ACTIVE and cannot be blocked")

    agent["status"] = "BLOCKED"
    for bset in store.sets_of_agent(agent["id"]):
        if bset["state"] == "ACTIVE":
            bset["state"] = "SUSPENDED"
            lookup.bump(bset)
    lookup.bump(agent)
    return object_response(models.public(agent))


@bp.route("/agents/<agent_id>/unblock", methods=["POST"])
def unblock_agent(agent_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    agent = lookup.agent(lookup.ensure_id(agent_id, "id"))

    if agent["status"] != "BLOCKED":
        raise APIError(ERR_INVALID_STATE, "agent is not BLOCKED and cannot be unblocked")

    agent["status"] = "ACTIVE"
    for bset in store.sets_of_agent(agent["id"]):
        if bset["state"] == "SUSPENDED":
            bset["state"] = "ACTIVE"
            lookup.bump(bset)
    lookup.bump(agent)
    return object_response(models.public(agent))
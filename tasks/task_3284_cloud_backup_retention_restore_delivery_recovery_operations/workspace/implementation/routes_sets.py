"""Backup set endpoints (PRD 3.2, 3.3, 3.8)."""

from flask import Blueprint, request

import auth
import constants as K
import lookup
import models
import recompute
from errors import (APIError, ERR_INITIAL_BACKUP_EMPTY, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_RETENTION_HOLD_ACTIVE,
                    ERR_UNAUTHORIZED)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import pagination, req_enum, req_str

bp = Blueprint("sets", __name__, url_prefix="/backup-provider")


@bp.route("/backup-sets", methods=["POST"])
def create_backup_set():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SET_CREATE)
    body = request.get_json(silent=True) or {}

    # PRD 2.10: left to right in input-declaration order -> agent, account.
    agent_id = req_str(body, "agent_id")
    agent = lookup.agent(agent_id)
    account_id = req_str(body, "account_id")
    account = lookup.account(account_id)
    if agent["account_id"] != account["id"]:
        raise APIError(ERR_INVALID_REQUEST,
                       "agent does not belong to the referenced account")
    durability_class = req_enum(body, "durability_class", K.DURABILITY_CLASSES)

    bset = models.backup_set(store, agent["id"], account["id"], durability_class,
                             created_seq=store.next_set_seq(agent["id"]))
    store.sets[bset["id"]] = bset
    return object_response(models.public(bset), 201)


@bp.route("/backup-sets", methods=["GET"])
def list_backup_sets():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SET_READ)
    limit, offset = pagination(request.args)

    agent_id = request.args.get("agent_id")
    account_id = request.args.get("account_id")
    state = request.args.get("state")
    rows = list(store.sets.values())
    if agent_id:
        rows = [s for s in rows if s["agent_id"] == agent_id]
    if account_id:
        rows = [s for s in rows if s["account_id"] == account_id]
    if state:
        rows = [s for s in rows if s["state"] == state]
    if caller.is_account_owner:
        rows = [s for s in rows if s["account_id"] == caller.user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(s) for s in page], limit, offset, total)


@bp.route("/backup-sets/<set_id>", methods=["GET"])
def get_backup_set(set_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SET_READ)
    bset = lookup.backup_set(lookup.ensure_id(set_id, "id"))
    if caller.is_account_owner and not caller.owns(bset["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    return object_response(models.public(bset))


@bp.route("/backup-sets/<set_id>/complete-initial", methods=["POST"])
def complete_initial(set_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SET_CREATE)
    bset = lookup.backup_set(lookup.ensure_id(set_id, "id"))
    account = store.accounts.get(bset["account_id"])
    agent = store.agents.get(bset["agent_id"])

    if bset["state"] != "INITIAL_RUNNING":
        raise APIError(ERR_INVALID_STATE,
                       "backup set is not INITIAL_RUNNING")

    versions = store.all_versions_of_set(bset["id"])
    if not any(v["operation"] != "DELETE" for v in versions):
        raise APIError(ERR_INITIAL_BACKUP_EMPTY,
                       "the initial full backup has no non-DELETE version")

    bset["state"] = "ACTIVE"
    bset["is_initial_flush"] = False
    if agent is not None:
        agent["in_throttle_window"] = False
        lookup.bump(agent)

    recompute.recompute_set(store, bset)
    if account is not None:
        recompute.recompute_account_usage(store, account)
        lookup.bump(account)
    lookup.bump(bset)
    return object_response(models.public(bset))


@bp.route("/backup-sets/<set_id>/suspend", methods=["POST"])
def suspend_backup_set(set_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SET_CREATE)
    bset = lookup.backup_set(lookup.ensure_id(set_id, "id"))
    account = store.accounts.get(bset["account_id"])
    agent = store.agents.get(bset["agent_id"])

    if bset["state"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "backup set is not ACTIVE")

    # PRD 3.6: the customer-facing suspension is reserved for an OPEN period
    # whose total is at least the delinquency threshold.
    overdue = [p for p in store.periods_of_account(bset["account_id"])
               if p["state"] == "OPEN"
               and int(p["total_cents"] or 0) >= K.DELINQUENCY_THRESHOLD_CENTS]
    if not overdue:
        raise APIError(ERR_INVALID_STATE,
                       "the account carries no overdue open billing period")

    bset["state"] = "SUSPENDED"
    if agent is not None:
        agent["status"] = "BLOCKED"
        lookup.bump(agent)
    if account is not None:
        recompute.recompute_account_usage(store, account)
        lookup.bump(account)
    lookup.bump(bset)
    return object_response(models.public(bset))


@bp.route("/backup-sets/<set_id>/delete", methods=["POST"])
def delete_backup_set(set_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SET_MUTATE)
    bset = lookup.backup_set(lookup.ensure_id(set_id, "id"))
    account = store.accounts.get(bset["account_id"])

    if bset["state"] not in ("ACTIVE", "SUSPENDED"):
        raise APIError(ERR_INVALID_STATE,
                       "backup set is not in a deletable state")

    account_closed = account is not None and account["status"] == "CLOSED"
    if bset["state"] == "ACTIVE":
        versions = store.all_versions_of_set(bset["id"])
        grace_elapsed = all(v["is_expired"] for v in versions)
        # PRD 3.8: ACTIVE deletion needs an elapsed grace window or a CLOSED
        # account; SUSPENDED deletion needs the CLOSED account alone.
        if not (grace_elapsed or account_closed):
            raise APIError(ERR_RETENTION_HOLD_ACTIVE,
                           "the set's data is still within its retention grace window")
    else:
        if not account_closed:
            raise APIError(ERR_RETENTION_HOLD_ACTIVE,
                           "a SUSPENDED set may be deleted only when the account is CLOSED")

    for version in store.all_versions_of_set(bset["id"]):
        store.versions.pop(version["id"], None)
    bset["state"] = "DELETED"
    bset["storage_gb"] = 0.0
    bset["recovery_points"] = 0
    bset["retention_floor_utc"] = None

    if account is not None:
        recompute.recompute_account_usage(store, account)
        lookup.bump(account)
    lookup.bump(bset)
    return object_response(models.public(bset))
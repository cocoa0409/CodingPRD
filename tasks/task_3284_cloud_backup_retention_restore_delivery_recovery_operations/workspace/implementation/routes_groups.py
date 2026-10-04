"""Backup group endpoints (PRD 3.2, 3.4)."""

from flask import Blueprint, request

import auth
import constants as K
import lookup
import models
import recompute
from errors import (APIError, ERR_POLICY_FLOOR_SATISFIED,
                    ERR_RETENTION_BELOW_POLICY_FLOOR, ERR_UNAUTHORIZED)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import pagination, req_enum, req_int, req_str

bp = Blueprint("groups", __name__, url_prefix="/backup-provider")


@bp.route("/backup-groups", methods=["POST"])
def create_group():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_GROUP_CREATE)
    body = request.get_json(silent=True) or {}

    # PRD 2.10 / 2.6: account_id is a parent reference, validated left to right
    # and carrying no OCC guard.
    account_id = req_str(body, "account_id")
    account = lookup.account(account_id)
    if caller.is_account_owner and not caller.owns(account["id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")

    name = req_str(body, "name")
    tier = req_enum(body, "tier", K.GROUP_TIERS)
    override = req_int(body, "retention_days_override", required=False,
                       default=None, allow_null=True)

    group = models.backup_group(store, account["id"], name, tier,
                                retention_days_override=override,
                                created_seq=store.next_group_seq(account["id"]))
    store.groups[group["id"]] = group

    recompute.recompute_group_retention(store, group)
    recompute.recompute_account_retention(store, account)
    recompute.recompute_account_group_count(store, account)
    recompute.recompute_all_group_metrics(store, account["id"])
    lookup.bump(group, account)
    return object_response(models.public(group), 201)


@bp.route("/backup-groups", methods=["GET"])
def list_groups():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_GROUP_READ)
    limit, offset = pagination(request.args)

    account_id = request.args.get("account_id")
    status = request.args.get("status")
    rows = list(store.groups.values())
    if account_id:
        rows = [g for g in rows if g["account_id"] == account_id]
    if status:
        rows = [g for g in rows if g["status"] == status]
    if caller.is_account_owner:
        rows = [g for g in rows if g["account_id"] == caller.user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(g) for g in page], limit, offset, total)


@bp.route("/backup-groups/<group_id>", methods=["GET"])
def get_group(group_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_GROUP_READ)
    group = lookup.group(lookup.ensure_id(group_id, "id"))
    if caller.is_account_owner and not caller.owns(group["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    return object_response(models.public(group))


@bp.route("/backup-groups/<group_id>/suspend", methods=["POST"])
def suspend_group(group_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_GROUP_MUTATE)
    group = lookup.group(lookup.ensure_id(group_id, "id"))
    account = store.accounts.get(group["account_id"])

    # PRD 3.2: permitted only when the group's window is strictly below the
    # account's retention_days.
    account_days = int(account["retention_days"] or 0) if account else 0
    if not (int(group["group_retention_days"] or 0) < account_days):
        raise APIError(ERR_POLICY_FLOOR_SATISFIED,
                       "group retention already meets the account window")

    # reversible self-loop on the ACTIVE status (PRD 3.2)
    for agent in store.agents_of_group(group["id"]):
        if agent["status"] == "ACTIVE":
            agent["status"] = "BLOCKED"
            lookup.bump(agent)
    lookup.bump(group)
    return object_response(models.public(group))


@bp.route("/backup-groups/<group_id>/resume", methods=["POST"])
def resume_group(group_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_GROUP_MUTATE)
    group = lookup.group(lookup.ensure_id(group_id, "id"))

    policy = store.active_policy(group["id"], "RETENTION")
    floor = int(policy.get("min_retention_days") or 0) if policy else 0
    override = group.get("retention_days_override")
    override_days = int(override) if override is not None else 0
    if policy is not None and floor > override_days:
        raise APIError(ERR_RETENTION_BELOW_POLICY_FLOOR,
                       "retention_days_override is below the policy floor")

    for agent in store.agents_of_group(group["id"]):
        if agent["status"] == "BLOCKED":
            agent["status"] = "ACTIVE"
            lookup.bump(agent)
    lookup.bump(group)
    return object_response(models.public(group))
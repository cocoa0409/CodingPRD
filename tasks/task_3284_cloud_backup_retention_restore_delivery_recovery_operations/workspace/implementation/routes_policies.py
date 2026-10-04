"""Group policy endpoints (PRD 3.4)."""

from flask import Blueprint, request

import auth
import constants as K
import lookup
import models
import recompute
from errors import APIError, ERR_UNAUTHORIZED
from response import array_response, object_response, paginate
from store import store
from util import (fmt_ts, pagination, parse_instant, req_bool, req_enum, req_int,
                  req_str)

bp = Blueprint("policies", __name__, url_prefix="/backup-provider")


@bp.route("/backup-groups/<group_id>/policies", methods=["POST"])
def create_policy(group_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_POLICY_CREATE)
    group = lookup.group(lookup.ensure_id(group_id, "id"))
    account = store.accounts.get(group["account_id"])
    body = request.get_json(silent=True) or {}

    policy_kind = req_enum(body, "policy_kind", K.POLICY_KINDS)
    min_retention_days = req_int(body, "min_retention_days", required=False, default=0)
    max_extended_history_days = req_int(body, "max_extended_history_days")
    min_restore_point_age_hours = req_int(body, "min_restore_point_age_hours",
                                          required=False, default=0)
    require_mfa = req_bool(body, "require_mfa_for_restore", required=False,
                           default=True)
    if require_mfa is None:
        require_mfa = True
    effective_from_utc = parse_instant(req_str(body, "effective_from_utc"),
                                       "effective_from_utc")

    # PRD 3.4: a policy of a given kind supersedes any prior ACTIVE one.
    for prior in store.policies.values():
        if (prior["group_id"] == group["id"] and prior["policy_kind"] == policy_kind
                and prior["status"] == "ACTIVE"):
            prior["status"] = "SUPERSEDED"
            lookup.bump(prior)

    policy = models.group_policy(store, group["id"], policy_kind, min_retention_days,
                                 max_extended_history_days, min_restore_point_age_hours,
                                 require_mfa, fmt_ts(effective_from_utc))
    store.policies[policy["id"]] = policy

    # recompute the group's window and the account's roll-up
    recompute.recompute_group_retention(store, group)
    if account is not None:
        recompute.recompute_account_retention(store, account)
        lookup.bump(account)
    lookup.bump(group)
    return object_response(models.public(policy), 201)


@bp.route("/backup-groups/<group_id>/policies", methods=["GET"])
def list_policies(group_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_POLICY_READ)
    group = lookup.group(lookup.ensure_id(group_id, "id"))
    if caller.is_account_owner and not caller.owns(group["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    limit, offset = pagination(request.args)
    status = request.args.get("status")

    rows = [p for p in store.policies_of_group(group["id"])]
    if status:
        rows = [p for p in rows if p["status"] == status]
    # PRD 3.4: newly created policies appear ahead of older ones.
    rows = sorted(rows, key=lambda p: (p["created_at"], p["_order"]), reverse=True)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(p) for p in page], limit, offset, total)


@bp.route("/group-policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_POLICY_READ)
    policy = lookup.policy(lookup.ensure_id(policy_id, "id"))
    return object_response(models.public(policy))
"""Retention change request endpoints (PRD 3.4; OCC per PRD 2.6)."""

from flask import Blueprint, request

import auth
import constants as K
import lookup
import models
import recompute
from errors import (APIError, ERR_COOLING_OFF_ACTIVE, ERR_DUPLICATE_REQUEST,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_RETENTION_ABOVE_POLICY_CEILING,
                    ERR_RETENTION_BELOW_POLICY_FLOOR,
                    ERR_RETENTION_CHANGE_CONFLICT, ERR_STALE_VERSION,
                    ERR_UNAUTHORIZED)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import add_days, pagination, req_enum, req_int, req_str

bp = Blueprint("retention", __name__, url_prefix="/backup-provider")


@bp.route("/retention-change-requests", methods=["POST"])
def submit_retention_change():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RC_CREATE)
    body = request.get_json(silent=True) or {}

    # PRD 2.10: account then group, left to right.
    account_id = req_str(body, "account_id")
    account = lookup.account(account_id)
    group_id = req_str(body, "group_id")
    group = lookup.group(group_id)
    if group["account_id"] != account["id"]:
        raise APIError(ERR_INVALID_REQUEST,
                       "group does not belong to the referenced account")

    requested_retention_days = req_int(body, "requested_retention_days")
    reason_code = req_enum(body, "reason_code", K.RETENTION_REASONS)

    # PRD 2.6: the OCC guard on the group's version, at level 7.
    expected_version = req_int(body, "expected_group_version")
    if expected_version != int(group["version"]):
        raise APIError(ERR_STALE_VERSION,
                       "expected_group_version does not match the group's current version")

    change = models.retention_change_request(store, account["id"], group["id"],
                                             requested_retention_days, reason_code)
    store.retention_changes[change["id"]] = change
    lookup.bump(group)
    return object_response(models.public(change), 201)


@bp.route("/retention-change-requests", methods=["GET"])
def list_retention_changes():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RC_READ)
    limit, offset = pagination(request.args)

    account_id = request.args.get("account_id")
    group_id = request.args.get("group_id")
    state = request.args.get("state")
    reason_code = request.args.get("reason_code")
    rows = list(store.retention_changes.values())
    if account_id:
        rows = [r for r in rows if r["account_id"] == account_id]
    if group_id:
        rows = [r for r in rows if r["group_id"] == group_id]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if reason_code:
        rows = [r for r in rows if r["reason_code"] == reason_code]
    if caller.is_account_owner:
        rows = [r for r in rows if r["account_id"] == caller.user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(r) for r in page], limit, offset, total)


@bp.route("/retention-change-requests/<change_id>", methods=["GET"])
def get_retention_change(change_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RC_READ)
    change = lookup.retention_change(lookup.ensure_id(change_id, "id"))
    if caller.is_account_owner and not caller.owns(change["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    return object_response(models.public(change))


@bp.route("/retention-change-requests/<change_id>/begin-cooling-off", methods=["POST"])
def begin_cooling_off(change_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RC_MUTATE)
    change = lookup.retention_change(lookup.ensure_id(change_id, "id"))
    if change["state"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, "retention change is not SUBMITTED")

    group = lookup.group(change["group_id"])
    policy = store.active_policy(group["id"], "RETENTION")
    requested = int(change["requested_retention_days"])

    # PRD 3.4 level 5, floor then ceiling as the scaffold lists them.
    if policy is not None:
        floor = int(policy.get("min_retention_days") or 0)
        ceiling = policy.get("max_extended_history_days")
        if requested < floor:
            raise APIError(ERR_RETENTION_BELOW_POLICY_FLOOR,
                           "requested window is below the policy's min_retention_days")
        if ceiling is not None and requested > int(ceiling):
            raise APIError(ERR_RETENTION_ABOVE_POLICY_CEILING,
                           "requested window exceeds the policy's max_extended_history_days")

    change["submitted_at_utc"] = models.fmt_ts(store.now())
    change["cooling_off_until_utc"] = models.fmt_ts(
        add_days(store.now(), K.COOLING_OFF_DAYS))
    change["original_retention_days"] = int(group.get("group_retention_days") or 0)
    change["state"] = "COOLING_OFF"
    lookup.bump(change)
    return object_response(models.public(change))


def _rewrite_group_version_flags(store, group):
    """Applying a retention change rewrites recoverable_until_utc and
    is_expired on every file version of the group's sets (PRD 3.4)."""
    agent_ids = {a["id"] for a in store.agents_of_group(group["id"])}
    for bset in store.sets.values():
        if bset["agent_id"] in agent_ids:
            recompute.recompute_version_flags(store, bset)


@bp.route("/retention-change-requests/<change_id>/apply", methods=["POST"])
def apply_retention_change(change_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RC_MUTATE)
    change = lookup.retention_change(lookup.ensure_id(change_id, "id"))
    if change["state"] != "COOLING_OFF":
        raise APIError(ERR_INVALID_STATE, "retention change is not COOLING_OFF")

    # Level 5: a DOWNGRADE waits out its cooling-off window.
    if change["reason_code"] == "DOWNGRADE":
        if change["cooling_off_until_utc"] is None or \
                store.now() < models_parse(change["cooling_off_until_utc"]):
            raise APIError(ERR_COOLING_OFF_ACTIVE,
                           "the cooling-off window has not elapsed")

    # Level 6: only one in-flight change per group (PRD 3.4 -- "applying while
    # another ACTIVE change request exists for the same group").  A request
    # parked in SUBMITTED has not entered cooling-off and is not concurrent
    # with the one being applied.
    for other in store.retention_changes.values():
        if other["id"] == change["id"]:
            continue
        if other["group_id"] == change["group_id"] and other["state"] == "COOLING_OFF":
            raise APIError(ERR_RETENTION_CHANGE_CONFLICT,
                           "the group already has another in-flight retention change")

    group = lookup.group(change["group_id"])
    account = lookup.account(change["account_id"])

    group["retention_days_override"] = int(change["requested_retention_days"])
    recompute.recompute_group_retention(store, group)
    recompute.recompute_account_retention(store, account)
    _rewrite_group_version_flags(store, group)

    change["state"] = "APPLIED"
    lookup.bump(change)
    lookup.bump(group)
    lookup.bump(account)
    return object_response(models.public(change))


def models_parse(value):
    from util import parse_instant
    return parse_instant(value)


@bp.route("/retention-change-requests/<change_id>/reject", methods=["POST"])
def reject_retention_change(change_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RC_MUTATE)
    change = lookup.retention_change(lookup.ensure_id(change_id, "id"))
    if change["state"] != "COOLING_OFF":
        raise APIError(ERR_INVALID_STATE, "retention change is not COOLING_OFF")

    # the group window is untouched
    change["state"] = "REJECTED"
    lookup.bump(change)
    return object_response(models.public(change))


@bp.route("/retention-change-requests/<change_id>/resubmit", methods=["POST"])
def resubmit_retention_change(change_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RC_MUTATE)
    change = lookup.retention_change(lookup.ensure_id(change_id, "id"))
    if change["state"] != "REJECTED":
        raise APIError(ERR_INVALID_STATE, "retention change is not REJECTED")

    body = request.get_json(silent=True) or {}
    new_value = req_int(body, "requested_retention_days")
    if int(new_value) == int(change["requested_retention_days"]):
        raise APIError(ERR_DUPLICATE_REQUEST,
                       "resubmitting the rejected value unchanged is not allowed")

    change["requested_retention_days"] = int(new_value)
    change["state"] = "SUBMITTED"
    change["cooling_off_until_utc"] = None
    lookup.bump(change)
    return object_response(models.public(change))


@bp.route("/retention-change-requests/<change_id>/expire", methods=["POST"])
def expire_retention_change(change_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    change = lookup.retention_change(lookup.ensure_id(change_id, "id"))
    if change["state"] != "COOLING_OFF":
        raise APIError(ERR_INVALID_STATE, "retention change is not COOLING_OFF")

    if change["cooling_off_until_utc"] is None or store.now() < add_days(
            models_parse(change["cooling_off_until_utc"]), K.COOLING_OFF_EXPIRY_DAYS):
        raise APIError(ERR_COOLING_OFF_ACTIVE,
                       "the cooling-off expiry window has not elapsed")

    change["state"] = "EXPIRED"
    lookup.bump(change)
    return object_response(models.public(change))
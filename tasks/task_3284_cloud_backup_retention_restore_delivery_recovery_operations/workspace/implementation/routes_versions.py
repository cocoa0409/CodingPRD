"""File version endpoints (PRD 3.3)."""

from flask import Blueprint, request

import auth
import constants as K
import lookup
import models
import recompute
from errors import (APIError, ERR_AGENT_NOT_ACTIVE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NO_CHANGE_DETECTED, ERR_POLICY_REQUIRED,
                    ERR_THROTTLE_WINDOW_CLOSED, ERR_UNAUTHORIZED,
                    ERR_VERSION_CONFLICT)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import (fmt_ts, pagination, parse_instant, q_bool, req_enum, req_int,
                  req_str, yyyymm)

bp = Blueprint("versions", __name__, url_prefix="/backup-provider")

LIVE_STATES = ("PROVISIONING", "INITIAL_RUNNING", "ACTIVE")


def models_fmt_now(store):
    return fmt_ts(store.now())


def _versions_public(rows):
    return [models.public(v) for v in rows]


@bp.route("/backup-sets/<set_id>/file-versions", methods=["POST"])
def record_file_version(set_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SET_CREATE)
    bset = lookup.backup_set(lookup.ensure_id(set_id, "id"))
    body = request.get_json(silent=True) or {}

    file_path = req_str(body, "file_path")
    version_number = req_int(body, "version_number")
    operation = req_enum(body, "operation", K.OPERATIONS)
    size_bytes = req_int(body, "size_bytes")
    content_hash = req_str(body, "content_hash")
    event_utc = parse_instant(req_str(body, "event_utc"), "event_utc")

    agent = store.agents.get(bset["agent_id"])
    group = store.groups.get(agent["group_id"]) if agent else None
    account = store.accounts.get(bset["account_id"])

    # --- level 4: the set must admit the capture ---------------------------
    if bset["state"] not in LIVE_STATES:
        raise APIError(ERR_INVALID_STATE,
                       "backup set is in state %s and cannot capture changes" % bset["state"])

    # --- the initial full backup transition (PRD 3.3, three gates together) -
    starting_initial = bset["state"] == "PROVISIONING" and operation != "DELETE"
    if starting_initial:
        if agent is None or agent["status"] != "ACTIVE":
            raise APIError(ERR_AGENT_NOT_ACTIVE,
                           "the agent is not ACTIVE")
        if store.active_policy(agent["group_id"], "RETENTION") is None:
            raise APIError(ERR_POLICY_REQUIRED,
                           "the agent's group has no ACTIVE RETENTION policy")
        if int(agent["throttle_month"]) != yyyymm(store.now()):
            raise APIError(ERR_THROTTLE_WINDOW_CLOSED,
                           "the initial full backup may not start outside the "
                           "agent's reserved throttle month")

    # --- level 6: sequencing, then level 7: no-op modify --------------------
    existing = [v for v in store.all_versions_of_set(bset["id"])
                if v["file_path"] == file_path]
    highest = max([int(v["version_number"]) for v in existing], default=0)
    if version_number != highest + 1:
        raise APIError(ERR_VERSION_CONFLICT,
                       "version_number must be one greater than the current chain "
                       "head for that path")
    if operation == "MODIFY" and existing:
        prior = max(existing, key=lambda v: (v["version_number"], v["_order"]))
        if prior["content_hash"] == content_hash:
            raise APIError(ERR_NO_CHANGE_DETECTED,
                           "the MODIFY repeats the prior version's content_hash")

    version = models.file_version(store, bset["id"], file_path, version_number,
                                  operation, size_bytes, content_hash, event_utc)
    store.versions[version["id"]] = version

    if starting_initial:
        bset["state"] = "INITIAL_RUNNING"
        bset["initial_started_at"] = models_fmt_now(store)
        bset["is_initial_flush"] = True
        if agent is not None:
            agent["in_throttle_window"] = True

    # retention window is the group's, applied to the moment of change
    recompute.recompute_version_flags(store, bset)
    recompute.recompute_set(store, bset)
    recompute.recompute_set_last_backup(store, bset, version["event_utc"])

    if agent is not None:
        recompute.recompute_agent(store, agent)
        lookup.bump(agent)
    if account is not None:
        recompute.recompute_account_usage(store, account)
        recompute.recompute_initial_full_backup_gb(store, account)
        lookup.bump(account)
    if group is not None:
        recompute.recompute_group_metrics(store, group)
        lookup.bump(group)

    lookup.bump(bset)
    return object_response(models.public(version), 201)


@bp.route("/backup-sets/<set_id>/file-versions", methods=["GET"])
def list_file_versions(set_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_VERSION_READ)
    bset = lookup.backup_set(lookup.ensure_id(set_id, "id"))
    if caller.is_account_owner and not caller.owns(bset["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    limit, offset = pagination(request.args)

    rows = store.all_versions_of_set(bset["id"])
    file_path = request.args.get("file_path")
    operation = request.args.get("operation")
    is_expired = q_bool(request.args, "is_expired")
    is_deleted = q_bool(request.args, "is_deleted")
    include_expired = q_bool(request.args, "include_expired", False)

    if not include_expired:
        rows = [v for v in rows if not v["is_expired"]]
    if file_path:
        rows = [v for v in rows if v["file_path"] == file_path]
    if operation:
        rows = [v for v in rows if v["operation"] == operation]
    if is_expired is not None:
        rows = [v for v in rows if bool(v["is_expired"]) == is_expired]
    if is_deleted is not None:
        rows = [v for v in rows if bool(v["is_deleted"]) == is_deleted]

    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(_versions_public(page), limit, offset, total)


@bp.route("/file-versions/<version_id>", methods=["GET"])
def get_file_version(version_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_VERSION_READ)
    version = lookup.file_version(lookup.ensure_id(version_id, "id"))
    bset = store.sets.get(version["backup_set_id"])
    if caller.is_account_owner and bset is not None and not caller.owns(bset["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    return object_response(models.public(version))
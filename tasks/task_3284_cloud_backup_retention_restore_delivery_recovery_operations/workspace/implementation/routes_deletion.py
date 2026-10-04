"""Data deletion request endpoints (PRD 3.8; OCC per PRD 2.6)."""

from flask import Blueprint, request

import auth
import calc
import constants as K
import lookup
import models
import recompute
from errors import (APIError, ERR_DELETION_AUTHORIZATION_MISSING,
                    ERR_DELETION_COOLING_OFF_ACTIVE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_LITIGATION_HOLD_ACTIVE,
                    ERR_STALE_VERSION, ERR_UNAUTHORIZED)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import add_days, pagination, parse_instant, req_enum, req_int, req_str

bp = Blueprint("deletion", __name__, url_prefix="/backup-provider")

HOLD_STATES = ("SUBMITTED", "COOLING_OFF", "APPLIED")


@bp.route("/data-deletion-requests", methods=["POST"])
def submit_deletion_request():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_DELETION_CREATE)
    body = request.get_json(silent=True) or {}

    account_id = req_str(body, "account_id")
    account = lookup.account(account_id)
    auth.require(caller, auth.R_DELETION_CREATE, owned_account_id=account["id"])
    deletion_scope = req_enum(body, "deletion_scope", K.DELETION_SCOPES)
    authorization_ref = req_str(body, "authorization_ref", required=False, default="")

    # PRD 2.6: OCC on the account version, at level 7.
    expected_version = req_int(body, "expected_account_version")
    if expected_version != int(account["version"]):
        raise APIError(ERR_STALE_VERSION,
                       "expected_account_version does not match the account's "
                       "current version")

    deletion = models.data_deletion_request(store, account["id"], deletion_scope,
                                            authorization_ref)
    store.deletions[deletion["id"]] = deletion
    lookup.bump(account)
    return object_response(models.public(deletion), 201)


@bp.route("/data-deletion-requests", methods=["GET"])
def list_deletion_requests():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_DELETION_READ)
    limit, offset = pagination(request.args)

    account_id = request.args.get("account_id")
    state = request.args.get("state")
    deletion_scope = request.args.get("deletion_scope")
    rows = list(store.deletions.values())
    if account_id:
        rows = [d for d in rows if d["account_id"] == account_id]
    if state:
        rows = [d for d in rows if d["state"] == state]
    if deletion_scope:
        rows = [d for d in rows if d["deletion_scope"] == deletion_scope]
    if caller.is_account_owner:
        rows = [d for d in rows if d["account_id"] == caller.user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(d) for d in page], limit, offset, total)


@bp.route("/data-deletion-requests/<deletion_id>", methods=["GET"])
def get_deletion_request(deletion_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_DELETION_READ)
    deletion = lookup.deletion_request(lookup.ensure_id(deletion_id, "id"))
    if caller.is_account_owner and not caller.owns(deletion["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    return object_response(models.public(deletion))


def _litigation_hold_active(account_id):
    """PRD 3.8: any retention change for the account's groups in flight under a
    LITIGATION_HOLD reason blocks erasure."""
    group_ids = {g["id"] for g in store.groups_of_account(account_id)}
    for change in store.retention_changes.values():
        if change["group_id"] in group_ids and change["reason_code"] == "LITIGATION_HOLD" \
                and change["state"] in HOLD_STATES:
            return True
    return False


@bp.route("/data-deletion-requests/<deletion_id>/approve", methods=["POST"])
def approve_deletion_request(deletion_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "ComplianceOfficer")
    deletion = lookup.deletion_request(lookup.ensure_id(deletion_id, "id"))
    if deletion["state"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, "deletion request is not SUBMITTED")

    # Level 5, in the scaffold's precondition order: authorization, then hold.
    if not (deletion.get("authorization_ref") or "").strip():
        raise APIError(ERR_DELETION_AUTHORIZATION_MISSING,
                       "authorization_ref must be non-empty")
    if _litigation_hold_active(deletion["account_id"]):
        raise APIError(ERR_LITIGATION_HOLD_ACTIVE,
                       "a LITIGATION_HOLD retention change governs a group of the account")

    deletion["approved_at_utc"] = models.fmt_ts(store.now())
    deletion["executability_utc"] = models.fmt_ts(
        add_days(store.now(), K.DELETION_COOLING_OFF_DAYS))
    deletion["state"] = "APPROVED"

    if deletion["deletion_scope"] == "ACCOUNT_CLOSURE":
        for bset in store.sets_of_account(deletion["account_id"]):
            bset["state"] = "SUSPENDED"
            lookup.bump(bset)

    lookup.bump(deletion)
    return object_response(models.public(deletion))


@bp.route("/data-deletion-requests/<deletion_id>/reject", methods=["POST"])
def reject_deletion_request(deletion_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "ComplianceOfficer")
    deletion = lookup.deletion_request(lookup.ensure_id(deletion_id, "id"))
    if deletion["state"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, "deletion request is not SUBMITTED")

    deletion["state"] = "REJECTED"
    if deletion["deletion_scope"] == "ACCOUNT_CLOSURE":
        for bset in store.sets_of_account(deletion["account_id"]):
            if bset["state"] == "SUSPENDED":
                bset["state"] = "ACTIVE"
                lookup.bump(bset)
    lookup.bump(deletion)
    return object_response(models.public(deletion))


@bp.route("/data-deletion-requests/<deletion_id>/execute", methods=["POST"])
def execute_deletion_request(deletion_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "ComplianceOfficer")
    deletion = lookup.deletion_request(lookup.ensure_id(deletion_id, "id"))
    if deletion["state"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, "deletion request is not APPROVED")

    # Level 5: the erasure waits out its cooling-off window.
    if deletion["executability_utc"] is None or \
            store.now() < parse_instant(deletion["executability_utc"]):
        raise APIError(ERR_DELETION_COOLING_OFF_ACTIVE,
                       "the deletion cooling-off window has not elapsed")

    account = lookup.account(deletion["account_id"])
    targets = calc.deletion_targets(store, account["id"], deletion["deletion_scope"])
    purged_ids = [v["id"] for v in targets]
    files_purged = len(targets)
    bytes_purged = sum(int(v["size_bytes"] or 0) for v in targets)
    for version_id in purged_ids:
        store.versions.pop(version_id, None)

    # Cascade hop 1: every affected set's derived projections.
    affected_set_ids = {s["id"] for s in store.sets_of_account(account["id"])}
    for set_id in affected_set_ids:
        bset = store.sets.get(set_id)
        if bset is None:
            continue
        recompute.recompute_set(store, bset)
    # Cascade hop 2: the account's volume from the surviving sets.
    recompute.recompute_account_usage(store, account)

    if deletion["deletion_scope"] == "ACCOUNT_CLOSURE":
        account["status"] = "CLOSED"
        for agent in store.agents_of_account(account["id"]):
            agent["status"] = "RETIRED"
            lookup.bump(agent)
        for bset in store.sets_of_account(account["id"]):
            bset["state"] = "DELETED"
            lookup.bump(bset)

    deletion["state"] = "EXECUTING"
    deletion["_pending_files_purged"] = files_purged
    deletion["_pending_bytes_purged"] = bytes_purged
    lookup.bump(deletion)
    lookup.bump(account)
    return object_response(models.public(deletion))


@bp.route("/data-deletion-requests/<deletion_id>/complete", methods=["POST"])
def complete_deletion_request(deletion_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "ComplianceOfficer")
    deletion = lookup.deletion_request(lookup.ensure_id(deletion_id, "id"))
    if deletion["state"] != "EXECUTING":
        raise APIError(ERR_INVALID_STATE, "deletion request is not EXECUTING")

    deletion["files_purged"] = int(deletion.get("_pending_files_purged") or 0)
    deletion["bytes_purged"] = int(deletion.get("_pending_bytes_purged") or 0)
    deletion["state"] = "COMPLETED"
    lookup.bump(deletion)
    return object_response(models.public(deletion))
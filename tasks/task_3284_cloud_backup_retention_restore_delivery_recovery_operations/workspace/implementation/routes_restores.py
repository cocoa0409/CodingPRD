"""Restore request endpoints (PRD 3.5, 3.6, 3.9; OCC per PRD 2.6)."""

from flask import Blueprint, request

import auth
import calc
import constants as K
import lookup
import models
import recompute
from errors import (APIError, ERR_COOLING_OFF_ACTIVE, ERR_DRIVE_CAPACITY_EXCEEDED,
                    ERR_DRIVE_SHIPMENT_NOT_PERMITTED, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_MFA_REQUIRED, ERR_RESTORE_POINT_EXPIRED,
                    ERR_RESTORE_POINT_TOO_RECENT, ERR_SHIPMENT_ALREADY_CLOSED,
                    ERR_STALE_VERSION, ERR_UNAUTHORIZED)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import (add_hours, pagination, parse_instant, req_enum, req_int, req_num,
                  req_str)

bp = Blueprint("restores", __name__, url_prefix="/backup-provider")


def _subject(restore):
    """The set the restore reconstructs: the subject agent's live set."""
    agent = store.agents.get(restore["subject_agent_id"])
    if agent is None:
        return None
    sets = [s for s in store.sets_of_agent(agent["id"])
            if s["state"] in ("INITIAL_RUNNING", "ACTIVE", "SUSPENDED", "PROVISIONING")]
    if not sets:
        sets = store.sets_of_agent(agent["id"])
    if not sets:
        return None
    return sorted(sets, key=lambda s: (s["created_seq"], s["_order"]))[0]


def _subject_group(restore):
    agent = store.agents.get(restore["subject_agent_id"])
    if agent is None:
        return None
    return store.groups.get(agent["group_id"])


@bp.route("/restore-requests", methods=["POST"])
def create_restore_request():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_CREATE)
    body = request.get_json(silent=True) or {}

    # PRD 2.10: left to right -- account, then agent.
    account_id = req_str(body, "account_id")
    account = lookup.account(account_id)
    auth.require(caller, auth.R_RESTORE_CREATE, owned_account_id=account["id"])
    subject_agent_id = req_str(body, "subject_agent_id")
    agent = lookup.agent(subject_agent_id)

    # PRD 2.6: the OCC guard is expressed purely in stale-version terms and
    # sits at level 7 (the ERR_STALE_VERSION catalog entry), below the state
    # level, so it lands after the existence checks and before business logic.
    expected_version = req_int(body, "expected_account_version")
    if expected_version != int(account["version"]):
        raise APIError(ERR_STALE_VERSION,
                       "expected_account_version does not match the account's "
                       "current version")

    restore_point_in_utc = parse_instant(req_str(body, "restore_point_in_utc"),
                                         "restore_point_in_utc")
    restore_type = req_enum(body, "restore_type", K.RESTORE_TYPES)
    requested_file_count = req_int(body, "requested_file_count")
    requested_size_gb = req_num(body, "requested_size_gb")
    restore_transaction_count = req_int(body, "restore_transaction_count",
                                        required=False, default=0)
    requester_mfa_ticket = req_str(body, "requester_mfa_ticket", required=False,
                                   default=None)
    drive_capacity_gb = req_num(body, "drive_capacity_gb", required=False, default=None)
    drive_count = req_int(body, "drive_count", required=False, default=None)
    deposit_fee_cents = req_int(body, "deposit_fee_cents", required=False, default=None)

    if restore_type == "DRIVE_SHIPMENT":
        for field, value in (("drive_capacity_gb", drive_capacity_gb),
                             ("drive_count", drive_count),
                             ("deposit_fee_cents", deposit_fee_cents)):
            if value is None:
                raise APIError(ERR_INVALID_REQUEST,
                               "%s is required for a DRIVE_SHIPMENT restore" % field)

    restore = models.restore_request(
        store, account["id"], agent["id"], models.fmt_ts(restore_point_in_utc),
        restore_type, requested_file_count, requested_size_gb,
        restore_transaction_count, requester_mfa_ticket, drive_capacity_gb,
        drive_count, deposit_fee_cents)
    store.restores[restore["id"]] = restore
    lookup.bump(account)
    return object_response(models.public(restore), 201)


@bp.route("/restore-requests", methods=["GET"])
def list_restore_requests():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_READ)
    limit, offset = pagination(request.args)

    account_id = request.args.get("account_id")
    subject_agent_id = request.args.get("subject_agent_id")
    state = request.args.get("state")
    restore_type = request.args.get("restore_type")
    rows = list(store.restores.values())
    if account_id:
        rows = [r for r in rows if r["account_id"] == account_id]
    if subject_agent_id:
        rows = [r for r in rows if r["subject_agent_id"] == subject_agent_id]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if restore_type:
        rows = [r for r in rows if r["restore_type"] == restore_type]
    if caller.is_account_owner:
        rows = [r for r in rows if r["account_id"] == caller.user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(r) for r in page], limit, offset, total)


@bp.route("/restore-requests/<restore_id>", methods=["GET"])
def get_restore_request(restore_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_READ)
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    if caller.is_account_owner and not caller.owns(restore["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")
    return object_response(models.public(restore))


def _owned(restore, caller):
    if caller.is_account_owner and not caller.owns(restore["account_id"]):
        raise APIError(ERR_UNAUTHORIZED,
                       "AccountOwner does not own the referenced account")


@bp.route("/restore-requests/<restore_id>/validate", methods=["POST"])
def validate_restore(restore_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_OWNER)
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    _owned(restore, caller)
    if restore["state"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, "restore request is not REQUESTED")

    account = lookup.account(restore["account_id"])
    group = _subject_group(restore)
    policy = store.active_policy(group["id"], "RETENTION") if group else None
    rp_policy = store.active_policy(group["id"]) if group else None
    effective = rp_policy or policy

    body = request.get_json(silent=True) or {}
    ticket = body.get("requester_mfa_ticket", restore.get("requester_mfa_ticket"))

    # Level 5, in the scaffold's precondition order: shipment permission,
    # then MFA, then restore-point age.
    if restore["restore_type"] == "DRIVE_SHIPMENT":
        if account["account_type"] not in ("BUSINESS", "ENTERPRISE"):
            raise APIError(ERR_DRIVE_SHIPMENT_NOT_PERMITTED,
                           "drive shipment restores require a BUSINESS or "
                           "ENTERPRISE account")
    if effective is not None and effective.get("require_mfa_for_restore"):
        if not ticket or not str(ticket).strip():
            raise APIError(ERR_MFA_REQUIRED,
                           "the group policy requires an MFA ticket for restores")
    if effective is not None:
        bset = _subject(restore)
        if bset is not None:
            floor = add_hours(parse_instant(bset["created_at"]),
                              int(effective.get("min_restore_point_age_hours") or 0))
            if store.now() < floor:
                raise APIError(ERR_RESTORE_POINT_TOO_RECENT,
                               "the logical clock has not reached the minimum "
                               "restore-point age")

    if ticket is not None:
        restore["requester_mfa_ticket"] = ticket
    bset = _subject(restore)
    versions = store.all_versions_of_set(bset["id"]) if bset else []
    restore["archive_entry_count"] = calc.archive_entry_count(
        versions, restore["requested_file_count"])
    restore["is_ransomware_recovery"] = calc.ransomware_recovery_flag(
        versions, restore["restore_point_in_utc"])
    restore["state"] = "VALIDATING"
    lookup.bump(restore)
    return object_response(models.public(restore))


@bp.route("/restore-requests/<restore_id>/return-to-draft", methods=["POST"])
def return_to_draft(restore_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_OWNER)
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    _owned(restore, caller)
    if restore["state"] != "VALIDATING":
        raise APIError(ERR_INVALID_STATE, "restore request is not VALIDATING")

    restore["state"] = "REQUESTED"
    restore["is_ransomware_recovery"] = False
    restore["archive_entry_count"] = 0
    lookup.bump(restore)
    return object_response(models.public(restore))


@bp.route("/restore-requests/<restore_id>/begin", methods=["POST"])
def begin_restore(restore_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_OWNER)
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    _owned(restore, caller)
    if restore["state"] != "VALIDATING":
        raise APIError(ERR_INVALID_STATE, "restore request is not VALIDATING")

    # Level 7: shipment capacity (scaffold's begin precondition).
    if restore["restore_type"] == "DRIVE_SHIPMENT":
        capacity = float(restore.get("drive_capacity_gb") or 0) * int(restore.get("drive_count") or 0)
        if float(restore["requested_size_gb"]) > capacity:
            raise APIError(ERR_DRIVE_CAPACITY_EXCEEDED,
                           "requested size exceeds the total drive capacity")

    account = lookup.account(restore["account_id"])
    restore["egress_gb"] = calc.billable_egress_gb(
        restore["requested_size_gb"], bool(restore["is_ransomware_recovery"]))
    restore["egress_fee_cents"] = calc.restore_egress_fee_cents(
        restore["egress_gb"], account["storage_tier"], restore["restore_transaction_count"])

    if restore["restore_type"] == "DRIVE_SHIPMENT":
        shipment = models.drive_shipment(
            store, restore["id"], account["id"], restore["drive_capacity_gb"],
            restore["drive_count"], restore["deposit_fee_cents"])
        store.shipments[shipment["id"]] = shipment

    restore["state"] = "IN_PROGRESS"
    lookup.bump(restore)
    return object_response(models.public(restore))


@bp.route("/restore-requests/<restore_id>/prepare", methods=["POST"])
def prepare_restore(restore_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_OWNER)
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    _owned(restore, caller)
    if restore["state"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, "restore request is not IN_PROGRESS")

    bset = _subject(restore)
    versions = store.all_versions_of_set(bset["id"]) if bset else []
    # Level 7: outranks nothing here -- this is the only gate on prepare.
    if calc.restore_point_expired(versions, restore["restore_point_in_utc"]):
        raise APIError(ERR_RESTORE_POINT_EXPIRED,
                       "at least one requested file version has expired")

    restore["archive_entry_count"] = calc.archive_entry_count(
        versions, restore["requested_file_count"])
    restore["state"] = "READY"

    linked = store.shipments_of_restore(restore["id"])
    for shipment in linked:
        if shipment["state"] == "PREPARING":
            shipment["state"] = "SHIPPED"
            shipment["shipped_at"] = models.fmt_ts(store.now())
            recompute.recompute_shipment(store, shipment)
            account = store.accounts.get(shipment["account_id"])
            if account is not None:
                recompute.recompute_deposit_held(store, account)
                lookup.bump(account)
            lookup.bump(shipment)

    lookup.bump(restore)
    return object_response(models.public(restore))


@bp.route("/restore-requests/<restore_id>/complete", methods=["POST"])
def complete_restore(restore_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_OWNER)
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    _owned(restore, caller)
    if restore["state"] != "READY":
        raise APIError(ERR_INVALID_STATE, "restore request is not READY")

    account = lookup.account(restore["account_id"])
    account["restore_download_gb"] = calc.q2(
        calc.D(account.get("restore_download_gb") or 0)
        + calc.D(restore.get("egress_gb") or 0))
    account["transaction_count"] = int(account.get("transaction_count") or 0) + 1

    # Cascade hop 1: a shipment already RETURNED closes with the restore.
    for shipment in store.shipments_of_restore(restore["id"]):
        if shipment["state"] == "RETURNED":
            recompute.cascade_close_shipment(store, shipment, bump_shipment=True)

    restore["state"] = "COMPLETED"
    lookup.bump(restore)
    lookup.bump(account)
    return object_response(models.public(restore))


@bp.route("/restore-requests/<restore_id>/fail", methods=["POST"])
def fail_restore(restore_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    if restore["state"] != "READY":
        raise APIError(ERR_INVALID_STATE, "restore request is not READY")

    for shipment in store.shipments_of_restore(restore["id"]):
        shipment["state"] = "DELINQUENT"
        shipment["was_delinquent"] = True
        recompute.recompute_shipment(store, shipment)
        account = store.accounts.get(shipment["account_id"])
        if account is not None:
            recompute.recompute_deposit_held(store, account)
            lookup.bump(account)
        lookup.bump(shipment)

    restore["state"] = "FAILED"
    lookup.bump(restore)
    return object_response(models.public(restore))


@bp.route("/restore-requests/<restore_id>/cancel", methods=["POST"])
def cancel_restore(restore_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_RESTORE_OWNER)
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    _owned(restore, caller)
    if restore["state"] not in ("REQUESTED", "VALIDATING"):
        raise APIError(ERR_INVALID_STATE,
                       "only a REQUESTED or VALIDATING restore can be cancelled")

    restore["state"] = "CANCELLED"
    lookup.bump(restore)
    return object_response(models.public(restore))


@bp.route("/restore-requests/<restore_id>/reverse", methods=["POST"])
def reverse_restore(restore_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    restore = lookup.restore_request(lookup.ensure_id(restore_id, "id"))
    if restore["state"] != "READY":
        raise APIError(ERR_INVALID_STATE, "restore request is not READY")

    # The one precondition gating reversal (PRD 3.5).  A restore cannot be
    # reversed once its drive shipment has closed.
    for shipment in store.shipments_of_restore(restore["id"]):
        if shipment["state"] == "CLOSED":
            raise APIError(ERR_SHIPMENT_ALREADY_CLOSED,
                           "the drive shipment has already closed")

    account = lookup.account(restore["account_id"])
    # Compensating action: the exact inverse of the completion accrual.
    account["restore_download_gb"] = calc.q2(
        calc.D(account.get("restore_download_gb") or 0)
        - calc.D(restore.get("egress_gb") or 0))
    account["transaction_count"] = int(account.get("transaction_count") or 0) - 1

    restore["state"] = "REVERSED"
    lookup.bump(restore)
    lookup.bump(account)
    return object_response(models.public(restore))
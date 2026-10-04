"""Drive shipment endpoints (PRD 3.7)."""

from flask import Blueprint, request

import auth
import lookup
import models
import recompute
from errors import (APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_RETURN_WINDOW_OPEN)
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import pagination, parse_instant

bp = Blueprint("shipments", __name__, url_prefix="/backup-provider")


@bp.route("/drive-shipments", methods=["GET"])
def list_shipments():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SHIPMENT_READ)
    limit, offset = pagination(request.args)

    restore_request_id = request.args.get("restore_request_id")
    account_id = request.args.get("account_id")
    state = request.args.get("state")
    rows = list(store.shipments.values())
    if restore_request_id:
        rows = [s for s in rows if s["restore_request_id"] == restore_request_id]
    if account_id:
        rows = [s for s in rows if s["account_id"] == account_id]
    if state:
        rows = [s for s in rows if s["state"] == state]
    if caller.is_account_owner:
        rows = [s for s in rows if s["account_id"] == caller.user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(s) for s in page], limit, offset, total)


@bp.route("/drive-shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SHIPMENT_READ)
    shipment = lookup.shipment(lookup.ensure_id(shipment_id, "id"))
    auth.require(caller, auth.R_SHIPMENT_READ, owned_account_id=shipment["account_id"])
    return object_response(models.public(shipment))


@bp.route("/drive-shipments/<shipment_id>/ship", methods=["POST"])
def ship(shipment_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    shipment = lookup.shipment(lookup.ensure_id(shipment_id, "id"))
    if shipment["state"] != "PREPARING":
        raise APIError(ERR_INVALID_STATE, "shipment is not PREPARING")

    # PRD 3.7: shipment requires a non-negative deposit and at least one drive.
    if int(shipment["deposit_fee_cents"] or 0) < 0 or int(shipment["drive_count"] or 0) < 1:
        raise APIError(ERR_INVALID_REQUEST,
                       "deposit_fee_cents must be non-negative and drive_count at least one")

    shipment["state"] = "SHIPPED"
    shipment["shipped_at"] = models.fmt_ts(store.now())
    recompute.recompute_shipment(store, shipment)
    account = store.accounts.get(shipment["account_id"])
    if account is not None:
        recompute.recompute_deposit_held(store, account)
        lookup.bump(account)
    lookup.bump(shipment)
    return object_response(models.public(shipment))


@bp.route("/drive-shipments/<shipment_id>/deliver", methods=["POST"])
def deliver(shipment_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    shipment = lookup.shipment(lookup.ensure_id(shipment_id, "id"))
    if shipment["state"] != "SHIPPED":
        raise APIError(ERR_INVALID_STATE, "shipment is not SHIPPED")
    shipment["state"] = "DELIVERED"
    lookup.bump(shipment)
    return object_response(models.public(shipment))


@bp.route("/drive-shipments/<shipment_id>/open-return-window", methods=["POST"])
def open_return_window(shipment_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_SHIPMENT_OWNER)
    shipment = lookup.shipment(lookup.ensure_id(shipment_id, "id"))
    auth.require(caller, auth.R_SHIPMENT_OWNER, owned_account_id=shipment["account_id"])
    if shipment["state"] != "DELIVERED":
        raise APIError(ERR_INVALID_STATE, "shipment is not DELIVERED")
    shipment["state"] = "AWAITING_RETURN"
    lookup.bump(shipment)
    return object_response(models.public(shipment))


@bp.route("/drive-shipments/<shipment_id>/receive-return", methods=["POST"])
def receive_return(shipment_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    shipment = lookup.shipment(lookup.ensure_id(shipment_id, "id"))
    if shipment["state"] not in ("AWAITING_RETURN", "DELINQUENT"):
        raise APIError(ERR_INVALID_STATE, "shipment is not awaiting return")

    # A timely return is the (AWAITING_RETURN, clock <= deadline) edge; past
    # the deadline the caller must target DELINQUENT (PRD 3.7).
    if shipment["state"] == "AWAITING_RETURN":
        deadline = shipment.get("return_deadline_utc")
        if deadline is not None and store.now() > parse_instant(deadline):
            raise APIError(ERR_INVALID_STATE,
                           "the return deadline has elapsed; target DELINQUENT instead")

    shipment["state"] = "RETURNED"
    recompute.recompute_shipment(store, shipment)
    account = store.accounts.get(shipment["account_id"])
    if account is not None:
        recompute.recompute_deposit_held(store, account)
        lookup.bump(account)
    lookup.bump(shipment)
    return object_response(models.public(shipment))


@bp.route("/drive-shipments/<shipment_id>/mark-delinquent", methods=["POST"])
def mark_delinquent(shipment_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    shipment = lookup.shipment(lookup.ensure_id(shipment_id, "id"))
    if shipment["state"] != "AWAITING_RETURN":
        raise APIError(ERR_INVALID_STATE, "shipment is not AWAITING_RETURN")

    deadline = shipment.get("return_deadline_utc")
    if deadline is None or not (store.now() > parse_instant(deadline)):
        raise APIError(ERR_RETURN_WINDOW_OPEN,
                       "the return window is still open")

    shipment["state"] = "DELINQUENT"
    shipment["was_delinquent"] = True     # one-way latch (PRD 3.7)
    recompute.recompute_shipment(store, shipment)
    account = store.accounts.get(shipment["account_id"])
    if account is not None:
        recompute.recompute_deposit_held(store, account)
        lookup.bump(account)
    lookup.bump(shipment)
    return object_response(models.public(shipment))


@bp.route("/drive-shipments/<shipment_id>/close", methods=["POST"])
def close_shipment(shipment_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    shipment = lookup.shipment(lookup.ensure_id(shipment_id, "id"))
    if shipment["state"] != "RETURNED":
        raise APIError(ERR_INVALID_STATE, "shipment is not RETURNED")

    # Cascade hops 2-3 live in this helper (deposit recompute + period close).
    recompute.cascade_close_shipment(store, shipment, bump_shipment=True)
    return object_response(models.public(shipment))
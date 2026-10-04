"""Billing period endpoints (PRD 3.6)."""

from flask import Blueprint, request

import auth
import lookup
import models
import recompute
from errors import APIError, ERR_INVALID_STATE
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import pagination, parse_instant, req_int, req_str

bp = Blueprint("billing", __name__, url_prefix="/backup-provider")


@bp.route("/billing-periods", methods=["POST"])
def open_billing_period():
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    body = request.get_json(silent=True) or {}

    account_id = req_str(body, "account_id")
    account = lookup.account(account_id)
    period_start_utc = parse_instant(req_str(body, "period_start_utc"), "period_start_utc")
    period_end_utc = parse_instant(req_str(body, "period_end_utc"), "period_end_utc")
    restore_active_days = req_int(body, "restore_active_days", required=False, default=0)

    period = models.billing_period(store, account["id"],
                                   models.fmt_ts(period_start_utc),
                                   models.fmt_ts(period_end_utc),
                                   restore_active_days)
    store.periods[period["id"]] = period
    # PRD 3.6: opening recomputes usage_gb_avg and peak_usage_gb.
    recompute.recompute_period_open(store, period)
    return object_response(models.public(period), 201)


@bp.route("/billing-periods", methods=["GET"])
def list_billing_periods():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_PERIOD_READ)
    limit, offset = pagination(request.args)

    account_id = request.args.get("account_id")
    state = request.args.get("state")
    rows = list(store.periods.values())
    if account_id:
        rows = [p for p in rows if p["account_id"] == account_id]
    if state:
        rows = [p for p in rows if p["state"] == state]
    if caller.is_account_owner:
        rows = [p for p in rows if p["account_id"] == caller.user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([models.public(p) for p in page], limit, offset, total)


@bp.route("/billing-periods/<period_id>", methods=["GET"])
def get_billing_period(period_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_PERIOD_READ)
    period = lookup.billing_period(lookup.ensure_id(period_id, "id"))
    auth.require(caller, auth.R_PERIOD_READ, owned_account_id=period["account_id"])
    return object_response(models.public(period))


@bp.route("/billing-periods/<period_id>/close", methods=["POST"])
def close_billing_period(period_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    period = lookup.billing_period(lookup.ensure_id(period_id, "id"))
    if period["state"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, "billing period is not OPEN")

    account = lookup.account(period["account_id"])

    # Settle every charge term, then close; delinquency is a consequence of the
    # inclusive 5000-cent comparison (PRD 3.6).  The account's version advances
    # only when the close itself mutates the account (the DELINQUENT transition
    # or the first-closed-period stamp).
    recompute.recompute_period_close(store, period)
    period["state"] = "CLOSED"
    account_changed = recompute.settle_closed_period(store, account, period)

    lookup.bump(period)
    if account_changed:
        lookup.bump(account)
    return object_response(models.public(period))
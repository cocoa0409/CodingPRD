"""SettlementStatement endpoints: get, list, dispute, resolve, pay."""
from datetime import timedelta

from flask import Blueprint, request

import constants
import store
from errors import (
    err,
    ERR_DISPUTE_WINDOW_EXPIRED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NEGATIVE_SETTLEMENT,
    ERR_NOT_FOUND,
    ERR_STATEMENT_NOT_DISPUTABLE,
    ERR_STATEMENT_NOT_PAYABLE,
)
from helpers import (
    as_int,
    as_str,
    body,
    check_owner,
    dump,
    opt_field,
    paginate,
    req_field,
    require_roles,
    success,
)

bp = Blueprint("settlement_statements", __name__)

ANY_ROLE = constants.ROLES


def get_statement_or_404(stmt_id):
    s = store.db["settlement_statements"].get(stmt_id)
    if s is None:
        raise err(ERR_NOT_FOUND, "No settlement statement with the given id")
    return s


@bp.route("/licensing/settlement-statements/<settlementStatementId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_statement(settlementStatementId):
    return success(dump(get_statement_or_404(settlementStatementId)))


@bp.route("/licensing/settlement-statements", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_statements():
    items = list(store.db["settlement_statements"].values())
    for f in ("pool_period_id", "grower_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [x for x in items if x.get(f) == val]
    page, pagination = paginate(items)
    return success(page, pagination=pagination)


@bp.route("/licensing/settlement-statements/<settlementStatementId>/dispute", methods=["POST"])
@require_roles("GrowerPrincipal")
def dispute_statement(settlementStatementId):
    s = get_statement_or_404(settlementStatementId)
    check_owner(s["grower_id"])
    reason = as_str(req_field(body(), "reason"), "reason")
    # State gate is checked BEFORE the deadline gate (PRD 2.8)
    if s["status"] != "ISSUED":
        raise err(ERR_STATEMENT_NOT_DISPUTABLE, "Statement is not ISSUED")
    if store.clock_now() > s["dispute_deadline"]:
        raise err(ERR_DISPUTE_WINDOW_EXPIRED, "Dispute window has expired")
    s["status"] = "DISPUTED"
    s["dispute_reason"] = reason
    s["dispute_count"] += 1
    store.touch(s)
    return success(dump(s))


@bp.route("/licensing/settlement-statements/<settlementStatementId>/resolve", methods=["POST"])
@require_roles("SettlementOfficer")
def resolve_statement(settlementStatementId):
    s = get_statement_or_404(settlementStatementId)
    b = body()
    resolution = b.get("resolution")
    if resolution not in ("UPHOLD", "ADJUST"):
        raise err(ERR_INVALID_REQUEST, "resolution must be UPHOLD or ADJUST")
    adjustment = opt_field(b, "adjustment_cents", None)
    if resolution == "ADJUST":
        if adjustment is None:
            raise err(ERR_INVALID_REQUEST, "adjustment_cents is required for ADJUST")
        adjustment = as_int(adjustment, "adjustment_cents")
        if adjustment == 0:
            raise err(ERR_INVALID_REQUEST, "adjustment_cents must not be zero")
    if s["status"] != "DISPUTED":
        raise err(ERR_INVALID_STATE, "Statement is not DISPUTED")
    if resolution == "UPHOLD":
        s["status"] = "FINAL"
        s["resolution"] = "UPHOLD"
    else:
        if s["net_cents"] + adjustment < 0:
            raise err(ERR_NEGATIVE_SETTLEMENT, "Adjustment would drive net_cents below zero")
        s["net_cents"] += adjustment
        s["adjustment_total_cents"] += adjustment
        s["status"] = "ISSUED"
        s["resolution"] = "ADJUST"
        s["issued_at"] = store.clock_now()
        s["dispute_deadline"] = s["issued_at"] + timedelta(days=constants.DISPUTE_WINDOW_DAYS)
    store.touch(s)
    return success(dump(s))


@bp.route("/licensing/settlement-statements/<settlementStatementId>/pay", methods=["POST"])
@require_roles("SettlementOfficer")
def pay_statement(settlementStatementId):
    s = get_statement_or_404(settlementStatementId)
    if s["status"] == "PAID":
        raise err(ERR_INVALID_STATE, "Statement is already PAID")
    if s["status"] == "FINAL":
        pass  # a FINAL statement can always be paid
    elif s["status"] == "ISSUED":
        if store.clock_now() <= s["dispute_deadline"]:
            raise err(ERR_STATEMENT_NOT_PAYABLE, "Dispute deadline has not passed")
    else:
        raise err(ERR_STATEMENT_NOT_PAYABLE, "Statement is not payable")
    s["status"] = "PAID"
    s["paid_at"] = store.clock_now()
    store.touch(s)
    # Derived parent state: pool SETTLED -> PAID when its last statement is PAID
    pool = store.db["pool_periods"].get(s["pool_period_id"])
    if pool is not None and pool["status"] == "SETTLED":
        siblings = [
            x for x in store.db["settlement_statements"].values()
            if x["pool_period_id"] == pool["id"]
        ]
        if all(x["status"] == "PAID" for x in siblings):
            pool["status"] = "PAID"
            store.touch(pool)
    return success(dump(s))

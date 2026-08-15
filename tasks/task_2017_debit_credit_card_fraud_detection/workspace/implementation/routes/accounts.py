"""Account endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("accounts", __name__)


@bp.route("/fraudops/accounts", methods=["POST"])
def create_account():
    middleware.require_role("FraudOpsManager")
    body = request.get_json(silent=True) or {}
    account_number = body.get("account_number")
    cardholder_name = body.get("cardholder_name")
    home_country = body.get("home_country")
    if not isinstance(account_number, str) or not account_number:
        raise errors.err_invalid_request("account_number is required")
    if not isinstance(cardholder_name, str) or not cardholder_name:
        raise errors.err_invalid_request("cardholder_name is required")
    if not isinstance(home_country, str) or not home_country:
        raise errors.err_invalid_request("home_country is required")
    for a in db.accounts.values():
        if a["account_number"] == account_number:
            raise errors.err_invalid_request("account_number already exists")
    rec = middleware.stamp_new(
        {
            "account_number": account_number,
            "cardholder_name": cardholder_name,
            "home_country": home_country,
            "account_status": "ACTIVE",
            "credit_balance_cents": 0,
            "open_alert_count": 0,
            "rolling_90d_loss_cents": 0,
            "risk_tier": "LOW",
        }
    )
    db.accounts[rec["id"]] = rec
    return response.success(domain.ser_account(rec), status_code=201)


@bp.route("/fraudops/accounts", methods=["GET"])
def list_accounts():
    middleware.require_role("FraudAnalyst", "FraudOpsManager", "LossAccountant", "RecoverySpecialist")
    args = request.args
    status = args.get("status")
    risk = args.get("risk_tier")
    # Derived fields are time-relative (§2.11: the rolling window "ends at the
    # current logical time"), so refresh them before filtering/serializing.
    for a in list(db.accounts.values()):
        domain._recompute_account(a["id"])
    items = sorted(db.accounts.values(), key=lambda a: (a["created_at"], a["id"]))
    if status:
        items = [a for a in items if a["account_status"] == status]
    if risk:
        items = [a for a in items if a["risk_tier"] == risk]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_account(a) for a in sliced], pagination=pg)


@bp.route("/fraudops/accounts/<aid>", methods=["GET"])
def get_account(aid):
    user_id, role = middleware.require_role(
        "FraudAnalyst", "FraudOpsManager", "LossAccountant", "RecoverySpecialist", "Cardholder"
    )
    a = db.accounts.get(aid)
    if not a:
        raise errors.err_not_found("Account not found")
    if role == "Cardholder" and user_id != aid:
        raise errors.err_not_resource_owner()
    # Refresh time-relative derived fields (§2.11 rolling window) before read.
    domain._recompute_account(aid)
    return response.success(domain.ser_account(a))


@bp.route("/fraudops/accounts/<aid>/suspend", methods=["POST"])
def suspend_account(aid):
    middleware.require_role("FraudOpsManager")
    a = db.accounts.get(aid)
    if not a:
        raise errors.err_not_found("Account not found")
    if a["account_status"] != "ACTIVE":
        raise errors.err_invalid_state("Account is not ACTIVE")
    a["account_status"] = "SUSPENDED"
    middleware.touch(a)
    return response.success(domain.ser_account(a))


@bp.route("/fraudops/accounts/<aid>/reinstate", methods=["POST"])
def reinstate_account(aid):
    middleware.require_role("FraudOpsManager")
    a = db.accounts.get(aid)
    if not a:
        raise errors.err_not_found("Account not found")
    if a["account_status"] != "SUSPENDED":
        raise errors.err_invalid_state("Account is not SUSPENDED")
    a["account_status"] = "ACTIVE"
    middleware.touch(a)
    return response.success(domain.ser_account(a))

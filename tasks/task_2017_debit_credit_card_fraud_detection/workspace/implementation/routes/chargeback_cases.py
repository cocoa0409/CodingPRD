"""ChargebackCase endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("chargeback_cases", __name__)

NON_TERMINAL = {"FILED", "PROVISIONAL_CREDIT_POSTED", "REPRESENTMENT_FILED"}
ACTIVE_CREDIT_STATUSES = {"PROVISIONAL_CREDIT_POSTED", "REPRESENTMENT_FILED", "RESOLVED_WON"}


@bp.route("/fraudops/chargeback-cases", methods=["POST"])
def create_cb():
    middleware.require_role("RecoverySpecialist")
    body = request.get_json(silent=True) or {}
    txn_id = body.get("auth_transaction_id")
    reason_code = body.get("reason_code")
    credit = body.get("provisional_credit_cents")

    if not isinstance(txn_id, str) or not txn_id:
        raise errors.err_invalid_request("auth_transaction_id is required")
    if not isinstance(reason_code, str) or not reason_code:
        raise errors.err_invalid_request("reason_code is required")
    if not isinstance(credit, int) or isinstance(credit, bool) or credit < 0:
        raise errors.err_invalid_request("provisional_credit_cents must be a non-negative integer")

    t = db.auth_transactions.get(txn_id)
    if not t:
        raise errors.err_not_found("AuthTransaction not found")
    if t["decision"] != "APPROVE":
        raise errors.err_txn_not_disputable()
    for c in db.chargeback_cases.values():
        if c["auth_transaction_id"] == txn_id and c["cb_status"] in NON_TERMINAL:
            raise errors.err_chargeback_exists()

    rec = middleware.stamp_new(
        {
            "auth_transaction_id": txn_id,
            "account_id": t["account_id"],
            "reason_code": reason_code,
            "provisional_credit_cents": credit,
            "cb_status": "FILED",
        }
    )
    db.chargeback_cases[rec["id"]] = rec
    return response.success(domain.ser_cb(rec), status_code=201)


@bp.route("/fraudops/chargeback-cases", methods=["GET"])
def list_cb():
    middleware.require_role("RecoverySpecialist", "FraudOpsManager")
    args = request.args
    items = sorted(db.chargeback_cases.values(), key=lambda c: (c["created_at"], c["id"]))
    for key in ("auth_transaction_id", "account_id", "cb_status"):
        v = args.get(key)
        if v:
            items = [c for c in items if c.get(key) == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_cb(c) for c in sliced], pagination=pg)


@bp.route("/fraudops/chargeback-cases/<cid>", methods=["GET"])
def get_cb(cid):
    middleware.require_role("RecoverySpecialist", "FraudOpsManager")
    c = db.chargeback_cases.get(cid)
    if not c:
        raise errors.err_not_found("ChargebackCase not found")
    return response.success(domain.ser_cb(c))


def _txn_active_chargeback_credits(txn_id: str, exclude_cb_id: str | None = None) -> int:
    s = 0
    for c in db.chargeback_cases.values():
        if c["auth_transaction_id"] == txn_id and c["cb_status"] in ACTIVE_CREDIT_STATUSES:
            if exclude_cb_id and c["id"] == exclude_cb_id:
                continue
            s += c["provisional_credit_cents"]
    return s


def _txn_fraud_credits(txn_id: str) -> int:
    s = 0
    for a in db.fraud_alerts.values():
        if a["auth_transaction_id"] == txn_id and a["alert_status"] == "RESOLVED_FRAUD":
            s += a["fraud_credit_cents"]
    return s


@bp.route("/fraudops/chargeback-cases/<cid>/post-provisional-credit", methods=["POST"])
def post_credit(cid):
    middleware.require_role("RecoverySpecialist")
    c = db.chargeback_cases.get(cid)
    if not c:
        raise errors.err_not_found("ChargebackCase not found")
    # state check fires first
    if c["cb_status"] != "FILED":
        raise errors.err_chargeback_invalid_state()
    if c["provisional_credit_cents"] < 1:
        raise errors.err_invalid_request("provisional_credit_cents must be >= 1")
    # fiscal cap
    txn = db.auth_transactions[c["auth_transaction_id"]]
    existing = _txn_active_chargeback_credits(c["auth_transaction_id"]) + _txn_fraud_credits(c["auth_transaction_id"])
    if existing + c["provisional_credit_cents"] > txn["amount_cents"]:
        raise errors.err_duplicate_credit()
    c["cb_status"] = "PROVISIONAL_CREDIT_POSTED"
    middleware.touch(c)
    domain._recompute_account(c["account_id"])
    return response.success(domain.ser_cb(c))


@bp.route("/fraudops/chargeback-cases/<cid>/representment", methods=["POST"])
def representment(cid):
    middleware.require_role("RecoverySpecialist")
    c = db.chargeback_cases.get(cid)
    if not c:
        raise errors.err_not_found("ChargebackCase not found")
    if c["cb_status"] != "PROVISIONAL_CREDIT_POSTED":
        raise errors.err_chargeback_invalid_state()
    c["cb_status"] = "REPRESENTMENT_FILED"
    middleware.touch(c)
    return response.success(domain.ser_cb(c))


@bp.route("/fraudops/chargeback-cases/<cid>/resolve", methods=["POST"])
def resolve_cb(cid):
    middleware.require_role("RecoverySpecialist")
    c = db.chargeback_cases.get(cid)
    if not c:
        raise errors.err_not_found("ChargebackCase not found")
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("WON", "LOST"):
        raise errors.err_invalid_request("outcome must be WON or LOST")

    if outcome == "WON":
        if c["cb_status"] != "REPRESENTMENT_FILED":
            raise errors.err_chargeback_invalid_state()
        c["cb_status"] = "RESOLVED_WON"
    else:  # LOST
        if c["cb_status"] not in ("PROVISIONAL_CREDIT_POSTED", "REPRESENTMENT_FILED"):
            raise errors.err_chargeback_invalid_state()
        c["cb_status"] = "RESOLVED_LOST"
    middleware.touch(c)
    domain._recompute_account(c["account_id"])
    return response.success(domain.ser_cb(c))


@bp.route("/fraudops/chargeback-cases/<cid>/withdraw", methods=["POST"])
def withdraw_cb(cid):
    middleware.require_role("RecoverySpecialist")
    c = db.chargeback_cases.get(cid)
    if not c:
        raise errors.err_not_found("ChargebackCase not found")
    if c["cb_status"] != "FILED":
        raise errors.err_chargeback_invalid_state()
    c["cb_status"] = "WITHDRAWN"
    middleware.touch(c)
    return response.success(domain.ser_cb(c))

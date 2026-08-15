"""LossEntry endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("loss_entries", __name__)

LOSS_NON_TERMINAL = {"ESTIMATED", "BOOKED", "FINALIZED", "PARTIALLY_RECOVERED"}


@bp.route("/fraudops/loss-entries", methods=["POST"])
def create_loss():
    middleware.require_role("LossAccountant")
    body = request.get_json(silent=True) or {}
    account_id = body.get("account_id")
    transaction_ids = body.get("transaction_ids")

    if not isinstance(account_id, str) or not account_id:
        raise errors.err_invalid_request("account_id is required")
    if not isinstance(transaction_ids, list) or not transaction_ids:
        raise errors.err_invalid_request("transaction_ids must be a non-empty array")
    for tid in transaction_ids:
        if not isinstance(tid, str):
            raise errors.err_invalid_request("transaction_ids elements must be strings")

    acct = db.accounts.get(account_id)
    if not acct:
        raise errors.err_not_found("Account not found")
    for tid in transaction_ids:
        if tid not in db.auth_transactions:
            raise errors.err_not_found(f"AuthTransaction {tid} not found")

    # business rule: all txns belong to account and are CONFIRMED_FRAUD
    for tid in transaction_ids:
        t = db.auth_transactions[tid]
        if t["account_id"] != account_id or t["final_disposition"] != "CONFIRMED_FRAUD":
            raise errors.err_loss_txn_not_confirmed()

    # duplicate coverage
    for tid in transaction_ids:
        for l in db.loss_entries.values():
            if l["loss_status"] in LOSS_NON_TERMINAL and tid in l["transaction_ids"]:
                raise errors.err_txn_already_in_loss()

    provisional = domain.compute_provisional(transaction_ids)
    tolerance = domain.compute_tolerance(provisional)

    rec = middleware.stamp_new(
        {
            "account_id": account_id,
            "transaction_ids": list(transaction_ids),
            "provisional_amount_cents": provisional,
            "tolerance_cents": tolerance,
            "final_amount_cents": None,
            "outstanding_cents": 0,
            "written_off_cents": 0,
            "loss_status": "ESTIMATED",
            "booked_by_user_id": None,
            "booked_at": None,
            "finalized_at": None,
        }
    )
    db.loss_entries[rec["id"]] = rec
    return response.success(domain.ser_loss(rec), status_code=201)


@bp.route("/fraudops/loss-entries", methods=["GET"])
def list_losses():
    middleware.require_role("LossAccountant", "RecoverySpecialist", "FraudOpsManager")
    args = request.args
    items = sorted(db.loss_entries.values(), key=lambda l: (l["created_at"], l["id"]))
    for key in ("account_id", "loss_status"):
        v = args.get(key)
        if v:
            items = [l for l in items if l.get(key) == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_loss(l) for l in sliced], pagination=pg)


@bp.route("/fraudops/loss-entries/<lid>", methods=["GET"])
def get_loss(lid):
    middleware.require_role("LossAccountant", "RecoverySpecialist", "FraudOpsManager")
    l = db.loss_entries.get(lid)
    if not l:
        raise errors.err_not_found("LossEntry not found")
    return response.success(domain.ser_loss(l))


@bp.route("/fraudops/loss-entries/<lid>/book", methods=["POST"])
def book_loss(lid):
    user_id, _ = middleware.require_role("LossAccountant")
    l = db.loss_entries.get(lid)
    if not l:
        raise errors.err_not_found("LossEntry not found")
    if l["loss_status"] != "ESTIMATED":
        raise errors.err_invalid_state("Loss is not ESTIMATED")
    l["loss_status"] = "BOOKED"
    l["booked_by_user_id"] = user_id
    l["booked_at"] = db.get_clock_iso()
    middleware.touch(l)
    return response.success(domain.ser_loss(l))


@bp.route("/fraudops/loss-entries/<lid>/finalize", methods=["POST"])
def finalize_loss(lid):
    middleware.require_role("LossAccountant")
    l = db.loss_entries.get(lid)
    if not l:
        raise errors.err_not_found("LossEntry not found")
    body = request.get_json(silent=True) or {}
    final_amount = body.get("final_amount_cents")

    if l["loss_status"] != "BOOKED":
        raise errors.err_invalid_state("Loss is not BOOKED")

    if not isinstance(final_amount, int) or isinstance(final_amount, bool) or final_amount < 0:
        raise errors.err_invalid_request("final_amount_cents must be a non-negative integer")

    # temporal check
    booked_at = db._parse_iso(l["booked_at"])
    if db.get_clock() > booked_at + timedelta(days=30):
        raise errors.err_finalize_window_expired()

    # chargeback pending
    for tid in l["transaction_ids"]:
        for c in db.chargeback_cases.values():
            if c["auth_transaction_id"] == tid and c["cb_status"] in (
                "FILED",
                "PROVISIONAL_CREDIT_POSTED",
                "REPRESENTMENT_FILED",
            ):
                raise errors.err_chargeback_pending()

    # tolerance (inclusive)
    if abs(final_amount - l["provisional_amount_cents"]) > l["tolerance_cents"]:
        raise errors.err_final_amount_tolerance()

    l["final_amount_cents"] = final_amount
    l["finalized_at"] = db.get_clock_iso()
    l["outstanding_cents"] = final_amount
    l["loss_status"] = "FINALIZED"
    middleware.touch(l)
    domain._recompute_account(l["account_id"])
    return response.success(domain.ser_loss(l))


@bp.route("/fraudops/loss-entries/<lid>/write-off", methods=["POST"])
def write_off_loss(lid):
    middleware.require_role("LossAccountant")
    l = db.loss_entries.get(lid)
    if not l:
        raise errors.err_not_found("LossEntry not found")
    if l["loss_status"] not in ("FINALIZED", "PARTIALLY_RECOVERED"):
        raise errors.err_invalid_state("Loss is not FINALIZED or PARTIALLY_RECOVERED")
    if l["outstanding_cents"] <= 0:
        raise errors.err_invalid_state("No outstanding amount remains")
    l["written_off_cents"] = l["outstanding_cents"]
    l["outstanding_cents"] = 0
    l["loss_status"] = "WRITTEN_OFF"
    middleware.touch(l)
    domain._recompute_account(l["account_id"])
    return response.success(domain.ser_loss(l))

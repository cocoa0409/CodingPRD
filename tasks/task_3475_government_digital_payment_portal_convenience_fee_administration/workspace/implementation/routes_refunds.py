"""Refunds (PRD section 3.7): principal-only, initiated and decided by
different AgencyAdmins, approval debits the agency's OPEN batch."""
from flask import Blueprint

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from errors import invalid_state, raise_err
from validate import as_enum, as_positive_int, as_str, body, req_field

bp = Blueprint("refunds", __name__)

REFUNDABLE_STATES = ("CAPTURED", "SETTLED", "RE_PRESENTED")


@bp.route("/portal/refunds", methods=["POST"])
def create_refund():
    uid, _role = caller({"AgencyAdmin"})
    data = body()
    transaction_id = as_str(req_field(data, "transaction_id"), "transaction_id")
    amount = as_positive_int(req_field(data, "amount_cents"), "amount_cents")
    reason = as_str(req_field(data, "reason"), "reason")
    # priority 3: body foreign key
    txn = helpers.get_transaction(transaction_id)
    # priority 5: the transaction must be in a refundable funds state
    if txn["funds_status"] not in REFUNDABLE_STATES:
        invalid_state(
            "Transaction in status %s cannot be refunded" % txn["funds_status"]
        )
    # priority 11: principal-only; never exceeds the remaining refundable
    if amount > helpers.remaining_refundable(txn):
        raise_err(
            "ERR_REFUND_EXCEEDS_REMAINING",
            422,
            "Refund amount exceeds the transaction's remaining refundable "
            "principal",
        )
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "transaction_id": txn["id"],
        "amount_cents": amount,
        "reason": reason,
        "initiated_by_user_id": uid,
        "decided_by_user_id": None,
        "status": "REQUESTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.refunds[rec["id"]] = rec
    return envelope.obj(serialize.refund(rec), 201)


@bp.route("/portal/refunds/<rid>/decide", methods=["POST"])
def decide_refund(rid):
    uid, _role = caller({"AgencyAdmin"})
    rec = helpers.get_refund(rid)
    data = body()
    decision = as_enum(req_field(data, "decision"), "decision", {"APPROVE", "DENY"})
    # priority 5: still REQUESTED
    if rec["status"] != "REQUESTED":
        invalid_state("The refund has already been decided (%s)" % rec["status"])
    # priority 7: segregation of duties — before everything that follows
    if uid == rec["initiated_by_user_id"]:
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The refund decider must differ from the initiator",
        )
    txn = helpers.get_transaction(rec["transaction_id"])
    if decision == "APPROVE":
        # priority 10: an OPEN settlement batch must exist for the agency
        batch = helpers.find_open_batch(txn["agency_id"])
        if batch is None:
            raise_err(
                "ERR_NO_OPEN_BATCH",
                409,
                "Refund approval requires an existing OPEN settlement batch "
                "for the agency",
            )
        # a rejected request must not partially apply: record the decider
        # only once every gate has passed
        rec["decided_by_user_id"] = uid
        rec["status"] = "APPROVED"
        txn["refunded_cents"] += rec["amount_cents"]
        helpers.touch(txn)
        batch["refund_debits_cents"] += rec["amount_cents"]
        helpers.touch(batch)
    else:
        rec["decided_by_user_id"] = uid
        rec["status"] = "DENIED"
    helpers.touch(rec)
    return envelope.obj(serialize.refund(rec))

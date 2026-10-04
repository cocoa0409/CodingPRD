"""Chargeback cases (PRD section 3.7): network intake, agency contest /
accept, platform outcome recording with the evidence-deadline force-LOST
rule. The convenience fee is never clawed back."""
from datetime import timedelta

from flask import Blueprint

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from errors import invalid_state, raise_err
from validate import as_enum, as_str, body, req_field

bp = Blueprint("chargebacks", __name__)

REASON_CODES = {"FRAUD", "DUPLICATE", "SERVICE_NOT_RECEIVED", "CREDIT_NOT_ISSUED"}
FUNDABLE_STATES = ("CAPTURED", "SETTLED", "RE_PRESENTED")
EVIDENCE_WINDOW_DAYS = 10


@bp.route("/portal/chargebacks", methods=["POST"])
def create_chargeback():
    caller({"PlatformAdmin"})
    data = body()
    transaction_id = as_str(req_field(data, "transaction_id"), "transaction_id")
    reason_code = as_enum(req_field(data, "reason_code"), "reason_code", REASON_CODES)
    # priority 3: body foreign key
    txn = helpers.get_transaction(transaction_id)
    # priority 5: at most one live case per transaction
    for c in store.chargebacks.values():
        if c["transaction_id"] == txn["id"] and c["status"] in ("OPENED", "CONTESTED"):
            raise_err(
                "ERR_CHARGEBACK_ALREADY_OPEN",
                409,
                "The transaction already has a live chargeback case",
            )
    # priority 8: CARD only, in a fundable state
    if txn["method"] != "CARD" or txn["funds_status"] not in FUNDABLE_STATES:
        raise_err(
            "ERR_CHARGEBACK_NOT_PERMITTED",
            409,
            "Chargebacks exist only for CARD transactions in CAPTURED, "
            "SETTLED or RE_PRESENTED status",
        )
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "transaction_id": txn["id"],
        "reason_code": reason_code,
        "network_debit_cents": None,
        "opened_at": now,
        "evidence_due_at": clock.add_days(now, EVIDENCE_WINDOW_DAYS),
        "evidence_note": None,
        "status": "OPENED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.chargebacks[rec["id"]] = rec
    return envelope.obj(serialize.chargeback(rec), 201)


def _book_network_debit(case):
    """The financial effects of accepting liability / losing: network debit
    is amount minus refunds at this moment (the fee is never clawed back),
    the transaction records it, and the debit posts into the agency's OPEN
    batch (auto-created for the clock date when none exists)."""
    txn = helpers.get_transaction(case["transaction_id"])
    debit = txn["amount_cents"] - txn["refunded_cents"]
    case["network_debit_cents"] = debit
    txn["charged_back_cents"] = debit
    helpers.touch(txn)
    batch = helpers.ensure_open_batch(txn["agency_id"])
    batch["chargeback_debits_cents"] += debit
    helpers.touch(batch)


@bp.route("/portal/chargebacks/<rid>/contest", methods=["POST"])
def contest(rid):
    caller({"AgencyAdmin"})
    rec = helpers.get_chargeback(rid)
    data = body()
    note = as_str(req_field(data, "evidence_note"), "evidence_note")
    if rec["status"] != "OPENED":
        invalid_state("Only an OPENED case can be contested (status %s)" % rec["status"])
    # priority 9: contest is accepted while the clock is on or before the
    # evidence deadline
    if clock.now() > rec["evidence_due_at"]:
        raise_err(
            "ERR_EVIDENCE_DEADLINE_PASSED",
            409,
            "The evidence deadline has passed",
        )
    rec["status"] = "CONTESTED"
    rec["evidence_note"] = note
    helpers.touch(rec)
    return envelope.obj(serialize.chargeback(rec))


@bp.route("/portal/chargebacks/<rid>/accept", methods=["POST"])
def accept(rid):
    caller({"AgencyAdmin"})
    rec = helpers.get_chargeback(rid)
    if rec["status"] != "OPENED":
        invalid_state("Only an OPENED case can be accepted (status %s)" % rec["status"])
    _book_network_debit(rec)
    rec["status"] = "ACCEPTED"
    helpers.touch(rec)
    return envelope.obj(serialize.chargeback(rec))


@bp.route("/portal/chargebacks/<rid>/record-outcome", methods=["POST"])
def record_outcome(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_chargeback(rid)
    data = body()
    outcome = as_enum(req_field(data, "outcome"), "outcome", {"WON", "LOST"})
    if rec["status"] == "CONTESTED":
        if outcome == "WON":
            # no financial movement; the provisional case closes at zero debit
            rec["status"] = "WON"
        else:
            _book_network_debit(rec)
            rec["status"] = "LOST"
    elif rec["status"] == "OPENED":
        # an OPENED case whose deadline has not passed cannot be
        # outcome-recorded; past the deadline it is force-decided LOST
        if clock.now() <= rec["evidence_due_at"]:
            invalid_state(
                "An OPENED case cannot be outcome-recorded before its "
                "evidence deadline"
            )
        if outcome != "LOST":
            invalid_state("An OPENED case past its deadline is force-decided LOST")
        _book_network_debit(rec)
        rec["status"] = "LOST"
    else:
        invalid_state("Case in status %s accepts no outcome" % rec["status"])
    helpers.touch(rec)
    return envelope.obj(serialize.chargeback(rec))

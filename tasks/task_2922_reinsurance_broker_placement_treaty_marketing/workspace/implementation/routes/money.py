"""Compensation disclosure and the fiduciary premium account (PRD 3.6, 3.8)."""
from flask import Blueprint

import db
import enums
import response
import serialize
import services
import validate
from errors import fail
from middleware import (
    BROKER_ACCOUNTANT,
    CEDENT_UNDERWRITER,
    COMPLIANCE_OFFICER,
    own_cedent,
    require,
)
from routes._common import CEDENT_READ, LEDGER_READ, ordered_filtered, paged, q
from util import dec

bp = Blueprint("money", __name__)

DECISIONS = ("ACKNOWLEDGE", "REJECT")


# ---------------------------------------------------------------------------
# Brokerage disclosures
# ---------------------------------------------------------------------------

@bp.route("/brokerage-disclosures", methods=["GET"])
def list_disclosures():
    require(CEDENT_READ)
    rows = ordered_filtered(db.brokerage_disclosures, [
        ("program_id", q("program_id")),
        ("status", q("status")),
    ])
    return paged(rows, serialize.brokerage_disclosure)


@bp.route("/brokerage-disclosures/<disclosure_id>", methods=["GET"])
def read_disclosure(disclosure_id):
    require(CEDENT_READ)
    row = services.get_disclosure(disclosure_id)
    return response.object_response(serialize.brokerage_disclosure(row), 200)


@bp.route("/brokerage-disclosures/<disclosure_id>/disclose", methods=["POST"])
def disclose(disclosure_id):
    actor = require((BROKER_ACCOUNTANT,))
    disclosure = services.get_disclosure(disclosure_id)
    if disclosure["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_DISCLOSURE_STATE_INVALID",
             "a %s disclosure cannot be released" % disclosure["status"])
    program = services.get_program(disclosure["program_id"])
    if program["placement_status"] not in ("IN_MARKET", "FIRM_ORDER"):
        fail("ERR_PROGRAM_STATE_INVALID",
             "the program must be IN_MARKET or FIRM_ORDER")
    if dec(disclosure["brokerage_pct"]) != dec(program["brokerage_pct"]):
        fail("ERR_DISCLOSURE_PCT_MISMATCH",
             "the disclosed brokerage_pct does not match the program's")

    disclosure["disclosed_by_user_id"] = actor.user_id
    disclosure["acknowledged_by_user_id"] = None
    disclosure["decision_note"] = None
    disclosure["status"] = "DISCLOSED"
    db.touch(disclosure)
    return response.object_response(serialize.brokerage_disclosure(disclosure), 200)


@bp.route("/brokerage-disclosures/<disclosure_id>/decision", methods=["POST"])
def decide_disclosure(disclosure_id):
    actor = require((CEDENT_UNDERWRITER,))
    existing = db.brokerage_disclosures.get(disclosure_id)
    if existing is not None:
        program = db.programs.get(existing["program_id"])
        if program is not None:
            own_cedent(actor, program["cedent_id"])

    shape = validate.Shape()
    decision = shape.enum("decision", DECISIONS)
    decision_note = shape.string("decision_note", min_len=1, max_len=500,
                                 required=False, default=None)

    disclosure = services.get_disclosure(disclosure_id)
    if disclosure["status"] != "DISCLOSED":
        fail("ERR_DISCLOSURE_STATE_INVALID",
             "only a DISCLOSED disclosure may be decided")
    program = services.get_program(disclosure["program_id"])

    disclosure["acknowledged_by_user_id"] = actor.user_id
    disclosure["decision_note"] = decision_note
    if decision == "ACKNOWLEDGE":
        disclosure["status"] = "ACKNOWLEDGED"
        program["disclosure_acknowledged"] = True
    else:
        disclosure["status"] = "REJECTED"
        program["disclosure_acknowledged"] = False
    db.touch(disclosure)
    db.touch(program)
    return response.object_response(serialize.brokerage_disclosure(disclosure), 200)


# ---------------------------------------------------------------------------
# The fiduciary ledger
# ---------------------------------------------------------------------------

@bp.route("/fiduciary-transactions", methods=["GET"])
def list_transactions():
    require(LEDGER_READ)
    rows = ordered_filtered(db.fiduciary_transactions, [
        ("program_id", q("program_id")),
        ("signing_line_id", q("signing_line_id")),
        ("reverses_transaction_id", q("reverses_transaction_id")),
        ("txn_type", q("txn_type")),
        ("status", q("status")),
    ])
    return paged(rows, serialize.fiduciary_transaction)


@bp.route("/fiduciary-transactions/<transaction_id>", methods=["GET"])
def read_transaction(transaction_id):
    require(LEDGER_READ)
    row = services.get_transaction(transaction_id)
    return response.object_response(serialize.fiduciary_transaction(row), 200)


@bp.route("/fiduciary-transactions/<transaction_id>/approve", methods=["POST"])
def approve_transaction(transaction_id):
    actor = require((COMPLIANCE_OFFICER, BROKER_ACCOUNTANT))
    txn = services.get_transaction(transaction_id)
    if txn["status"] != "PENDING":
        fail("ERR_TRANSACTION_STATE_INVALID",
             "only a PENDING movement may be approved")
    if actor.user_id == txn["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the approver may not be the identity that booked the movement")

    txn["approved_by_user_id"] = actor.user_id
    txn["status"] = "APPROVED"
    db.touch(txn)
    program = services.get_program(txn["program_id"])
    services.recompute_cedent_aggregates(program["cedent_id"])
    return response.object_response(serialize.fiduciary_transaction(txn), 200)


@bp.route("/fiduciary-transactions/<transaction_id>/settle", methods=["POST"])
def settle_transaction(transaction_id):
    require((BROKER_ACCOUNTANT,))
    txn = services.get_transaction(transaction_id)
    if txn["status"] != "APPROVED":
        fail("ERR_TRANSACTION_STATE_INVALID",
             "only an APPROVED movement may be settled")
    program = services.get_program(txn["program_id"])
    if txn["txn_type"] in ("REINSURER_REMITTANCE", "REINSTATEMENT_PREMIUM"):
        if program["documentation_status"] not in ("WORDING_AGREED", "EXECUTED"):
            fail("ERR_DOCUMENTATION_NOT_AGREED",
                 "premium out-payments settle only once wording is agreed")
    if txn["txn_type"] in enums.OUTFLOW_TYPES:
        if txn["amount_minor"] > program["fiduciary_holding_minor"]:
            fail("ERR_INSUFFICIENT_FIDUCIARY_BALANCE",
                 "the fiduciary account may not be overdrawn")

    txn["value_date"] = db.now()
    txn["status"] = "SETTLED"
    db.touch(txn)
    if services.recompute_program_balance(program):
        db.touch(program)
    services.recompute_cedent_aggregates(program["cedent_id"])
    return response.object_response(serialize.fiduciary_transaction(txn), 200)


@bp.route("/fiduciary-transactions/<transaction_id>/reverse", methods=["POST"])
def reverse_transaction(transaction_id):
    actor = require((COMPLIANCE_OFFICER,))
    txn = services.get_transaction(transaction_id)
    # A movement may be reversed once and once only.  This is tested ahead of
    # the state gate because a reversed original necessarily leaves SETTLED,
    # which would otherwise make ERR_ALREADY_REVERSED unreachable.
    for other in db.fiduciary_transactions.values():
        if (other["txn_type"] == "REMITTANCE_REVERSAL"
                and other["reverses_transaction_id"] == txn["id"]):
            fail("ERR_ALREADY_REVERSED",
                 "the movement has already been reversed")
    if txn["status"] != "SETTLED" or txn["txn_type"] not in enums.OUTFLOW_TYPES:
        fail("ERR_TRANSACTION_STATE_INVALID",
             "only a SETTLED outflow movement may be reversed")

    program = services.get_program(txn["program_id"])
    txn["status"] = "REVERSED"
    db.touch(txn)
    compensating = services.new_transaction(
        program,
        "REMITTANCE_REVERSAL",
        txn["amount_minor"],
        actor.user_id,
        signing_line_id=txn["signing_line_id"],
        status="SETTLED",
        value_date=db.now(),
        reverses_transaction_id=txn["id"],
    )
    if services.recompute_program_balance(program):
        db.touch(program)
    services.recompute_cedent_aggregates(program["cedent_id"])
    return response.object_response(
        serialize.fiduciary_transaction(compensating), 201)

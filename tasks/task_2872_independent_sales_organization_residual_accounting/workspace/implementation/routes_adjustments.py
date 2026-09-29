"""Statement adjustments: proposal and the review cycle (PRD 3.8)."""
from flask import Blueprint, g, request

from apierrors import fail
from auth import acting_agent, authorize, scope_owned
from calc import lifetime_clawback_cents, recompute_statement
from envelope import apply_filters, list_response, object_response
from serial import adjustment as ser_adjustment
from shapes import as_id, as_int, as_str, body, present
from store import db, new_id, ordered, stamp_new, touch

bp = Blueprint("adjustments", __name__)

KINDS = ("DISPUTE_CREDIT", "MANUAL_DEBIT", "BONUS_CLAWBACK",
         "CLAWBACK_REVERSAL", "VESTED_BUYOUT")
POSITIVE_KINDS = ("DISPUTE_CREDIT", "CLAWBACK_REVERSAL", "VESTED_BUYOUT")
NEGATIVE_KINDS = ("MANUAL_DEBIT", "BONUS_CLAWBACK")
MERCHANT_KINDS = ("BONUS_CLAWBACK", "CLAWBACK_REVERSAL", "DISPUTE_CREDIT")


def _lookup(adjustment_id):
    row = db.adjustments.get(adjustment_id)
    if row is None:
        fail("ERR_ADJUSTMENT_NOT_FOUND", "no statement adjustment with id %s" % adjustment_id)
    return row


def _parent(adjustment):
    return db.statements.get(adjustment["statement_id"])


def _require_parent_open(adjustment):
    statement = _parent(adjustment)
    if statement is not None and statement["lifecycle_state"] not in ("DRAFT", "ISSUED"):
        fail("ERR_STATEMENT_STATE_INVALID",
             "the parent statement is no longer DRAFT or ISSUED")
    return statement


@bp.route("/agent-statements/<statement_id>/adjustments", methods=["POST"])
def propose_adjustment(statement_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    # band 3 -- agent scope precedes request shape, and is evaluated against the
    # statement being corrected whenever that statement exists.
    statement = db.statements.get(statement_id)
    if statement is not None:
        scope_owned(statement["agent_id"])
    payload = body()
    # band 4
    kind = as_str(payload, "kind")
    if kind not in KINDS:
        fail("ERR_INVALID_REQUEST", "kind must be one of %s" % ", ".join(KINDS))
    amount_cents = as_int(payload, "amount_cents")
    reason = as_str(payload, "reason", min_len=1, max_len=300)
    expected_statement_version = as_int(payload, "expected_statement_version")
    source_merchant_id = as_id(payload, "source_merchant_id", required=False)
    # band 6
    if statement is None:
        fail("ERR_STATEMENT_NOT_FOUND", "no agent statement with id %s" % statement_id)
    # band 7
    if source_merchant_id is not None and source_merchant_id not in db.merchants:
        fail("ERR_REFERENCED_MERCHANT_NOT_FOUND",
             "no merchant with id %s" % source_merchant_id)
    # band 8
    if expected_statement_version != statement["version"]:
        fail("ERR_STALE_STATEMENT_VERSION",
             "expected_statement_version %d does not match the statement's current version %d"
             % (expected_statement_version, statement["version"]))
    # band 9
    if statement["lifecycle_state"] not in ("DRAFT", "ISSUED"):
        fail("ERR_STATEMENT_STATE_INVALID",
             "adjustments may only be proposed against a DRAFT or ISSUED statement")
    # band 13 -- sign discipline, then the reversal ceiling
    if amount_cents == 0:
        fail("ERR_ADJUSTMENT_SIGN_INVALID", "amount_cents may never be zero")
    if kind in POSITIVE_KINDS and amount_cents < 0:
        fail("ERR_ADJUSTMENT_SIGN_INVALID",
             "amount_cents must be strictly positive for %s" % kind)
    if kind in NEGATIVE_KINDS and amount_cents > 0:
        fail("ERR_ADJUSTMENT_SIGN_INVALID",
             "amount_cents must be strictly negative for %s" % kind)
    if kind == "CLAWBACK_REVERSAL":
        ceiling = lifetime_clawback_cents(statement["agent_id"])
        if amount_cents > ceiling:
            fail("ERR_CLAWBACK_REVERSAL_EXCEEDS_CLAWBACK",
                 "a clawback reversal may not exceed lifetime_clawback_cents (%d)" % ceiling)
    row = {
        "id": new_id(),
        "statement_id": statement_id,
        "source_merchant_id": source_merchant_id if kind in MERCHANT_KINDS else None,
        "kind": kind,
        "amount_cents": amount_cents,
        "reason": reason,
        "state": "PROPOSED",
        "created_by_user_id": g.user_id,
        "approved_by_user_id": None,
        "info_request_note": None,
    }
    stamp_new(row)
    db.adjustments[row["id"]] = row
    # no money moves at proposal time, but the parent statement's version advances
    touch(statement)
    return object_response(ser_adjustment(row), 201)


@bp.route("/statement-adjustments", methods=["GET"])
def list_adjustments():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    if acting_agent():
        value = request.args.get("agent_id")
        if value is None or value != g.user_id:
            fail("ERR_AGENT_SCOPE_VIOLATION",
                 "an agent must pass agent_id equal to its own id")
    rows = list(db.adjustments.values())
    agent_id = request.args.get("agent_id")
    if agent_id is not None:
        statement_ids = set(r["id"] for r in db.statements.values()
                            if r["agent_id"] == agent_id)
        rows = [r for r in rows if r["statement_id"] in statement_ids]
    rows = apply_filters(
        rows,
        [("statement_id", "statement_id"), ("source_merchant_id", "source_merchant_id"),
         ("kind", "kind"), ("state", "state")])
    return list_response(ordered(rows), ser_adjustment)


@bp.route("/statement-adjustments/<adjustment_id>", methods=["GET"])
def get_adjustment(adjustment_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    return object_response(ser_adjustment(_lookup(adjustment_id)))


@bp.route("/statement-adjustments/<adjustment_id>/review", methods=["POST"])
def review_adjustment(adjustment_id):
    authorize("ResidualController")
    row = _lookup(adjustment_id)
    # band 9 -- the addressed adjustment first, then its parent statement
    if row["state"] != "PROPOSED":
        fail("ERR_ADJUSTMENT_STATE_INVALID", "review is only available from PROPOSED")
    _require_parent_open(row)
    row["state"] = "UNDER_REVIEW"
    touch(row)
    return object_response(ser_adjustment(row))


@bp.route("/statement-adjustments/<adjustment_id>/request-info", methods=["POST"])
def request_info(adjustment_id):
    authorize("ResidualController")
    payload = body()
    # band 4
    info_request_note = as_str(payload, "info_request_note", min_len=1)
    # band 6
    row = _lookup(adjustment_id)
    # band 9
    if row["state"] != "UNDER_REVIEW":
        fail("ERR_ADJUSTMENT_STATE_INVALID",
             "an information request is only available from UNDER_REVIEW")
    row["state"] = "INFO_REQUESTED"
    row["info_request_note"] = info_request_note
    touch(row)
    return object_response(ser_adjustment(row))


@bp.route("/statement-adjustments/<adjustment_id>/resubmit", methods=["POST"])
def resubmit_adjustment(adjustment_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    # band 3 -- scope against the statement being corrected
    row = db.adjustments.get(adjustment_id)
    if row is not None:
        statement = _parent(row)
        if statement is not None:
            scope_owned(statement["agent_id"])
    payload = body()
    # band 4
    reason = as_str(payload, "reason", required=False, min_len=1, max_len=300)
    # band 6
    if row is None:
        fail("ERR_ADJUSTMENT_NOT_FOUND",
             "no statement adjustment with id %s" % adjustment_id)
    # band 9
    if row["state"] != "INFO_REQUESTED":
        fail("ERR_ADJUSTMENT_STATE_INVALID",
             "an answer is only available from INFO_REQUESTED")
    row["state"] = "UNDER_REVIEW"
    row["info_request_note"] = None
    if present(payload, "reason"):
        row["reason"] = reason
    touch(row)
    return object_response(ser_adjustment(row))


@bp.route("/statement-adjustments/<adjustment_id>/approve", methods=["POST"])
def approve_adjustment(adjustment_id):
    authorize("ResidualController")
    row = _lookup(adjustment_id)
    # band 9 -- the state check is evaluated before the duty-segregation check
    if row["state"] != "UNDER_REVIEW":
        fail("ERR_ADJUSTMENT_STATE_INVALID", "approval is only available from UNDER_REVIEW")
    statement = _require_parent_open(row)
    # band 10 -- segregation of duties is about the person, not the role
    if row["created_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "an adjustment may not be approved by the principal that proposed it")
    row["state"] = "APPLIED"
    row["approved_by_user_id"] = g.user_id
    touch(row)
    if statement is not None:
        recompute_statement(statement)
        touch(statement)
    return object_response(ser_adjustment(row))


@bp.route("/statement-adjustments/<adjustment_id>/reject", methods=["POST"])
def reject_adjustment(adjustment_id):
    authorize("ResidualController")
    payload = body()
    # band 4
    reason = as_str(payload, "reason", required=False, min_len=1, max_len=300)
    # band 6
    row = _lookup(adjustment_id)
    # band 9
    if row["state"] != "UNDER_REVIEW":
        fail("ERR_ADJUSTMENT_STATE_INVALID", "refusal is only available from UNDER_REVIEW")
    row["state"] = "REJECTED"
    row["approved_by_user_id"] = g.user_id
    if present(payload, "reason"):
        row["reason"] = reason
    touch(row)
    return object_response(ser_adjustment(row))

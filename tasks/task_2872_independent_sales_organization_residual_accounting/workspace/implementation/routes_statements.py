"""Agent statements: the authoring and settlement dimensions (PRD 3.7, 3.9)."""
from flask import Blueprint

from apierrors import fail
from auth import authorize, scope_list_filter, scope_owned
from calc import (
    advance_recoupment_schedule,
    minimum_fee_reconciliation,
    recompute_statement,
    residual_hold,
    reverse_advance_recoupments,
)
from envelope import apply_filters, list_response, object_response
from serial import statement as ser_statement
from shapes import as_date, as_str, body
from store import MIN_PAYOUT_CENTS, db, ordered, touch

bp = Blueprint("statements", __name__)


def lookup_statement(statement_id):
    row = db.statements.get(statement_id)
    if row is None:
        fail("ERR_STATEMENT_NOT_FOUND", "no agent statement with id %s" % statement_id)
    return row


@bp.route("/agent-statements", methods=["GET"])
def list_statements():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    scope_list_filter("agent_id")
    rows = apply_filters(
        list(db.statements.values()),
        [("agent_id", "agent_id"), ("period_month", "period_month"),
         ("lifecycle_state", "lifecycle_state"),
         ("settlement_state", "settlement_state")])
    return list_response(ordered(rows), ser_statement)


@bp.route("/agent-statements/<statement_id>", methods=["GET"])
def get_statement(statement_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    row = lookup_statement(statement_id)
    scope_owned(row["agent_id"])
    return object_response(ser_statement(row))


@bp.route("/agent-statements/<statement_id>/issue", methods=["POST"])
def issue_statement(statement_id):
    authorize("ResidualController")
    # band 6
    row = lookup_statement(statement_id)
    # band 9
    if row["lifecycle_state"] != "DRAFT":
        fail("ERR_STATEMENT_STATE_INVALID", "a statement may only be issued from DRAFT")
    # band 12 -- the ingestion side of the period must be closed out
    for batch in db.batches.values():
        if batch["period_month"] != row["period_month"]:
            continue
        if batch["state"] not in ("POSTED", "REVERSED"):
            fail("ERR_BATCHES_NOT_POSTED",
                 "every batch for period %s must be POSTED or REVERSED"
                 % row["period_month"])
    row["lifecycle_state"] = "ISSUED"
    row["minimum_true_up_cents"] = minimum_fee_reconciliation(row)
    row["advance_recoupment_cents"] = 0
    recompute_statement(row)
    row["advance_recoupment_cents"] = advance_recoupment_schedule(
        row, row["gross_after_trueup_cents"])
    recompute_statement(row)
    row["issued_at"] = db.now_iso()
    touch(row)
    return object_response(ser_statement(row))


@bp.route("/agent-statements/<statement_id>/recall", methods=["POST"])
def recall_statement(statement_id):
    authorize("ResidualController")
    row = lookup_statement(statement_id)
    # band 9 -- the authoring dimension first, then the settlement dimension
    if row["lifecycle_state"] != "ISSUED":
        fail("ERR_STATEMENT_STATE_INVALID", "a statement may only be recalled from ISSUED")
    if row["settlement_state"] == "SETTLED":
        fail("ERR_SETTLEMENT_STATE_INVALID", "a settled statement may not be recalled")
    reverse_advance_recoupments(row)
    row["lifecycle_state"] = "DRAFT"
    row["minimum_true_up_cents"] = 0
    row["advance_recoupment_cents"] = 0
    row["issued_at"] = None
    recompute_statement(row)
    touch(row)
    return object_response(ser_statement(row))


@bp.route("/agent-statements/<statement_id>/finalize", methods=["POST"])
def finalize_statement(statement_id):
    authorize("ResidualController")
    row = lookup_statement(statement_id)
    if row["lifecycle_state"] != "ISSUED":
        fail("ERR_STATEMENT_STATE_INVALID", "a statement may only be finalized from ISSUED")
    row["lifecycle_state"] = "FINALIZED"
    touch(row)
    return object_response(ser_statement(row))


@bp.route("/agent-statements/<statement_id>/hold", methods=["POST"])
def hold_statement(statement_id):
    authorize("ResidualController")
    payload = body()
    # band 4
    hold_reason = as_str(payload, "hold_reason", min_len=1)
    # band 6
    row = lookup_statement(statement_id)
    # band 9 -- the settlement dimension first, then the authoring dimension
    if row["settlement_state"] != "UNSETTLED":
        fail("ERR_SETTLEMENT_STATE_INVALID", "a hold is only available from UNSETTLED")
    if row["lifecycle_state"] not in ("DRAFT", "ISSUED"):
        fail("ERR_STATEMENT_STATE_INVALID",
             "a FINALIZED statement cannot be newly placed on hold")
    row["settlement_state"] = "HELD"
    row["hold_reason"] = hold_reason
    touch(row)
    return object_response(ser_statement(row))


@bp.route("/agent-statements/<statement_id>/release-hold", methods=["POST"])
def release_hold(statement_id):
    authorize("ResidualController")
    row = lookup_statement(statement_id)
    # band 9
    if row["settlement_state"] != "HELD":
        fail("ERR_SETTLEMENT_STATE_INVALID", "a release is only available from HELD")
    # band 10 -- the agent-level risk flag interlock
    if residual_hold(row["agent_id"]):
        fail("ERR_RESIDUAL_HOLD_ACTIVE",
             "the owning agent's residual_hold flag is still set")
    row["settlement_state"] = "UNSETTLED"
    row["hold_reason"] = None
    touch(row)
    return object_response(ser_statement(row))


@bp.route("/agent-statements/<statement_id>/settle", methods=["POST"])
def settle_statement(statement_id):
    authorize("ResidualController")
    payload = body()
    # band 4
    paid_on = as_date(payload, "paid_on")
    # band 6
    row = lookup_statement(statement_id)
    # band 9 -- settlement dimension, then authoring dimension
    if row["settlement_state"] != "UNSETTLED":
        fail("ERR_SETTLEMENT_STATE_INVALID", "settlement is only available from UNSETTLED")
    if row["lifecycle_state"] not in ("ISSUED", "FINALIZED"):
        fail("ERR_STATEMENT_STATE_INVALID",
             "a DRAFT statement has no true-up or recoupment booked against it")
    # band 10
    if residual_hold(row["agent_id"]):
        fail("ERR_RESIDUAL_HOLD_ACTIVE",
             "the owning agent's residual_hold flag is still set")
    # band 13
    if row["net_payable_cents"] < MIN_PAYOUT_CENTS:
        fail("ERR_BELOW_MIN_PAYOUT",
             "net_payable_cents must be at least %d cents" % MIN_PAYOUT_CENTS)
    row["paid_on"] = paid_on
    row["settlement_state"] = "SETTLED"
    touch(row)
    return object_response(ser_statement(row))

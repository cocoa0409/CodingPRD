"""Read models over the posted ledger: lines, profitability, allocations."""
from flask import Blueprint

from apierrors import fail
from auth import authorize, scope_list_filter, scope_owned
from envelope import apply_filters, list_response, object_response
from serial import allocation as ser_allocation
from serial import line as ser_line
from serial import profitability as ser_profitability
from store import db, ordered

bp = Blueprint("ledger", __name__)


@bp.route("/residual-lines", methods=["GET"])
def list_lines():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    rows = apply_filters(
        list(db.lines.values()),
        [("residual_batch_id", "residual_batch_id"), ("merchant_id", "merchant_id")])
    return list_response(ordered(rows), ser_line)


@bp.route("/residual-lines/<line_id>", methods=["GET"])
def get_line(line_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    row = db.lines.get(line_id)
    if row is None:
        fail("ERR_LINE_NOT_FOUND", "no residual line with id %s" % line_id)
    return object_response(ser_line(row))


@bp.route("/merchant-profitability", methods=["GET"])
def list_profitability():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    rows = apply_filters(
        list(db.profitability.values()),
        [("merchant_id", "merchant_id"), ("residual_batch_id", "residual_batch_id"),
         ("period_month", "period_month")])
    return list_response(ordered(rows), ser_profitability)


@bp.route("/merchant-profitability/<profitability_id>", methods=["GET"])
def get_profitability(profitability_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    row = db.profitability.get(profitability_id)
    if row is None:
        fail("ERR_PROFITABILITY_NOT_FOUND",
             "no merchant profitability row with id %s" % profitability_id)
    return object_response(ser_profitability(row))


@bp.route("/residual-allocations", methods=["GET"])
def list_allocations():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    scope_list_filter("agent_id")
    rows = apply_filters(
        list(db.allocations.values()),
        [("agent_id", "agent_id"), ("merchant_id", "merchant_id"),
         ("statement_id", "statement_id"), ("period_month", "period_month"),
         ("allocation_type", "allocation_type")])
    return list_response(ordered(rows), ser_allocation)


@bp.route("/residual-allocations/<allocation_id>", methods=["GET"])
def get_allocation(allocation_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    row = db.allocations.get(allocation_id)
    if row is None:
        fail("ERR_ALLOCATION_NOT_FOUND", "no residual allocation with id %s" % allocation_id)
    scope_owned(row["agent_id"])
    return object_response(ser_allocation(row))

"""Billing statements: generation, allocation and the monthly close."""

from flask import request

from db import DB
from middleware import guard, require_owner
from response import (ApiError, Err, as_int, as_str, body, created_obj,
                      ensure_known, invalid_state, ok_list, ok_obj, pagination,
                      sorted_by_created, validation_failed)
from services import core


def register(app):
    @app.route("/billing-statements", methods=["POST"])
    def create_statement():
        guard(["CreditAnalyst", "CustomerService"])
        data = body()
        ensure_known(data, ["customer_id", "statement_period", "lines", "payment_cents"],
                     optional=("payment_cents",))
        customer_id = as_str(data, "customer_id")
        period = as_str(data, "statement_period")
        lines = data.get("lines")
        if not isinstance(lines, list):
            raise ApiError(Err.INVALID_REQUEST, "lines must be a list.")
        customer = core.fetch("customers", customer_id, "customer")
        if any(s["customer_id"] == customer_id and s["statement_period"] == period
               for s in DB.all("statements")):
            raise ApiError(Err.INVALID_REQUEST,
                           "A statement for this customer and period already exists.")

        normalised = [_validate_line(line) for line in lines]
        balance = core.statement_rollup(normalised)

        payment = as_int(data, "payment_cents", default=None)
        allocated = {"PROMOTIONAL": 0, "STANDARD_RETAIL": 0, "NEW_ACCOUNT": 0}
        if payment is not None:
            # Priority 25: the payment may not exceed the three bucket balances.
            allocated = core.payment_allocation_waterfall(customer, payment)

        capacity = core.bucket_capacity(customer)
        statement = core.new_row(
            "statements",
            customer_id=customer_id,
            statement_period=period,
            bucket_totals_cents=core.reported_bucket_totals(allocated),
            min_payment_due_cents=core.min_payment_due(allocated, capacity),
            statement_balance_cents=balance,
            statement_status="OPEN",
        )
        statement["lines"] = normalised
        return created_obj(statement)

    @app.route("/billing-statements", methods=["GET"])
    def list_statements():
        guard(["ChainAdmin", "CreditAnalyst", "CustomerService", "Customer"])
        limit, offset = pagination()
        rows = DB.all("statements")
        customer_id = request.args.get("customer_id")
        if customer_id is not None:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        status = request.args.get("statement_status")
        if status is not None:
            rows = [r for r in rows if r["statement_status"] == status]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/billing-statements/<ident>", methods=["GET"])
    def get_statement(ident):
        user_id, role = guard(["ChainAdmin", "CreditAnalyst", "CustomerService", "Customer"])
        statement = core.fetch("statements", ident, "billing statement")
        require_owner(user_id, role, statement)
        return ok_obj(statement)

    @app.route("/billing-statements/<ident>/close", methods=["POST"])
    def close_statement(ident):
        guard(["CustomerService"])
        statement = core.fetch("statements", ident, "billing statement")
        if statement["statement_status"] != "OPEN":
            raise invalid_state("Only an OPEN statement may be closed.")
        if statement["statement_balance_cents"] < 0:
            raise invalid_state("The statement balance is negative.")
        statement["statement_status"] = "CLOSED"
        core.touch(statement)
        return ok_obj(statement)


LINE_STATUSES = ("BILLABLE", "PAID", "DISPUTED")


def _validate_line(line):
    if not isinstance(line, dict):
        raise ApiError(Err.INVALID_REQUEST, "Each line must be an object.")
    for key in line:
        if key not in ("amount_cents", "billable_pct", "line_status"):
            raise ApiError(Err.INVALID_REQUEST, "Unknown line field %s." % key)
    if "amount_cents" not in line or "billable_pct" not in line:
        raise ApiError(Err.INVALID_REQUEST,
                       "A line requires amount_cents and billable_pct.")
    amount = line["amount_cents"]
    pct = line["billable_pct"]
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ApiError(Err.INVALID_REQUEST, "line.amount_cents must be an integer.")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise ApiError(Err.INVALID_REQUEST, "line.billable_pct must be a number.")
    status = line.get("line_status", "BILLABLE")
    if status not in LINE_STATUSES:
        raise validation_failed("line.line_status is outside its constraint set.")
    return {"amount_cents": int(amount), "billable_pct": float(pct), "line_status": status}
"""Payoff ledger entries."""

from flask import request

from db import DB
from middleware import guard
from response import (ApiError, Err, as_enum, as_int, as_str, body, created_obj,
                      ensure_known, ok_list, ok_obj, pagination, sorted_by_created)
from services import core

READ_ROLES = ["ChainAdmin", "CreditAnalyst", "StoreManager", "CustomerService"]


def register(app):
    @app.route("/payoff-ledger-entries", methods=["POST"])
    def append_entry():
        guard(["CustomerService", "CreditAnalyst"])
        data = body()
        ensure_known(data, ["plan_id", "entry_kind", "direction", "amount_cents",
                            "adjustment_cents", "reference_bucket", "expected_plan_version"],
                     optional=("reference_bucket",))
        plan_id = as_str(data, "plan_id")
        plan = core.fetch("promotional_plans", plan_id, "promotional plan")
        expected = as_int(data, "expected_plan_version", required=True)
        if plan["version"] != expected:
            raise ApiError(Err.STALE_VERSION)

        kind = as_enum(data, "entry_kind",
                       ("INSTALLMENT", "LUMPSUM_PAYOFF", "CAPITALIZATION", "TRADE_UP_CREDIT"))
        direction = as_enum(data, "direction", ("INCREASE", "DECREASE"))
        bucket = as_enum(data, "reference_bucket",
                         ("PROMOTIONAL", "CUSTOM_DESIGN", "RETAIL"), required=False)
        amount = as_int(data, "amount_cents", required=True)
        adjustment = as_int(data, "adjustment_cents", required=True)

        entry = core.append_ledger_entry(plan, kind, direction, amount, adjustment, bucket)
        if direction == "DECREASE":
            plan["total_paid_cents"] += amount
        core.touch(plan)
        customer = DB.get("customers", plan["customer_id"])
        if customer is not None:
            customer["outstanding_balance_cents"] = core.outstanding_balance(customer)
            customer["revolving_utilization_bps"] = core.revolving_utilization_bps(customer)
        return created_obj(entry)

    @app.route("/payoff-ledger-entries", methods=["GET"])
    def list_entries():
        guard(READ_ROLES)
        limit, offset = pagination()
        rows = DB.all("ledger")
        plan_id = request.args.get("plan_id")
        if plan_id is not None:
            rows = [r for r in rows if r["plan_id"] == plan_id]
        bucket = request.args.get("reference_bucket")
        if bucket is not None:
            rows = [r for r in rows if r["reference_bucket"] == bucket]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/payoff-ledger-entries/<ident>", methods=["GET"])
    def get_entry(ident):
        guard(READ_ROLES)
        return ok_obj(core.fetch("ledger", ident, "payoff ledger entry"))
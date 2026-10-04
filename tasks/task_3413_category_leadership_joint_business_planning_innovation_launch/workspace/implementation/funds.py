"""TradeFund: read, list (plan_id filter), and per-period accrual postings."""

import re

from flask import Blueprint, request

import calc
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_FINANCE_ANALYST,
    authenticate,
    authorize,
    rb_can_see,
    scope_plan,
)
from envelope import success, success_list
from errors import err
from storage import STORE, by_seq

bp = Blueprint("funds", __name__)

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def get_fund(fund_id):
    return STORE["funds"].get(fund_id)


@bp.get("/jbp/funds/<fund_id>")
def read_fund(fund_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    fund = get_fund(fund_id)
    if fund is not None:
        scope_plan(uid, role, STORE["plans"].get(fund["plan_id"]))
    if fund is None:
        err("ERR_RESOURCE_NOT_FOUND", "fund not found")
    return success(calc.fund_out(fund))


@bp.get("/jbp/funds")
def list_funds():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    items = by_seq(STORE["funds"].values())
    if role == "RetailerBuyer":
        items = [
            f
            for f in items
            if rb_can_see(uid, role, STORE["plans"].get(f["plan_id"]) or {"retailer_id": None})
        ]
    f_plan = request.args.get("plan_id")
    if f_plan is not None:
        items = [f for f in items if f["plan_id"] == f_plan]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([calc.fund_out(f) for f in page], limit, offset, total)


@bp.post("/jbp/funds/<fund_id>/accruals")
def post_accrual(fund_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_FINANCE_ANALYST])
    data = V.body()
    V.check_undeclared(data, {"period", "invoiced_sales_cents"})
    period = V.as_str(V.require(data, "period"), "period")
    if not _PERIOD_RE.match(period):
        err("ERR_VALIDATION", "period must be a YYYY-MM string")
    invoiced = V.as_int(V.require(data, "invoiced_sales_cents"), "invoiced_sales_cents")
    fund = get_fund(fund_id)
    if fund is None:
        err("ERR_RESOURCE_NOT_FOUND", "fund not found")  # 6
    if period in fund["_periods"]:
        err("ERR_DUPLICATE_ACCRUAL_PERIOD", "period already posted to this fund")  # 22
    calc.post_accrual(fund, period, invoiced)
    return success(calc.fund_out(fund), 201)

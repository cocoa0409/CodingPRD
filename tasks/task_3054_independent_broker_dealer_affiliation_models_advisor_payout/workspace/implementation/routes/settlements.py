"""Expense pass-through and advisory revenue split routes."""

import flask

import middleware
from db import advisory_revenue_splits, expense_pass_throughs
from response import ok, ok_list
from services import common
from services import settlements as settlement_service


bp = flask.Blueprint("settlements", __name__)


@bp.post("/expense-pass-throughs")
def create_expense():
    role = middleware.require_role("AdvisorOps", "BranchManager")
    data = common.body()
    middleware.require_advisor_owner(role, common.require_field(data, "advisor_code"))
    return ok(settlement_service.serialize(settlement_service.create_expense(data)), status=201)


@bp.get("/expense-pass-throughs")
def list_expenses():
    middleware.require_role(*middleware.ANY)
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in expense_pass_throughs.values()
            if (args.get("advisor_code") is None or row["advisor_code"] == args.get("advisor_code"))
            and (args.get("payout_period_id") is None
                 or row["payout_period_id"] == args.get("payout_period_id"))
            and (args.get("category") is None or row["category"] == args.get("category"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([settlement_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/expense-pass-throughs/<expense_id>")
def get_expense(expense_id):
    middleware.require_role(*middleware.ANY)
    return ok(settlement_service.serialize(settlement_service.find_expense_or_fail(expense_id)))


@bp.post("/expense-pass-throughs/<expense_id>/state")
def move_expense_state(expense_id):
    middleware.require_role("BranchManager", "AdvisorOps")
    row = settlement_service.find_expense_or_fail(expense_id)
    return ok(settlement_service.serialize(
        settlement_service.move_expense_state(row, common.body())))


# ---------------------------------------------------------------------------
# Advisory revenue splits
# ---------------------------------------------------------------------------

@bp.post("/advisory-splits/levelize")
def levelize():
    role = middleware.require_role("AdvisorOps", "BranchManager")
    data = common.body()
    middleware.require_advisor_owner(role, common.require_field(data, "advisor_code"))
    created = settlement_service.levelize(data)
    return ok([settlement_service.serialize(row) for row in created], response_type="array")


@bp.get("/advisory-splits")
def list_splits():
    middleware.require_role(*middleware.ANY)
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in advisory_revenue_splits.values()
            if (args.get("account_id") is None or row["account_id"] == args.get("account_id"))
            and (args.get("payout_period_id") is None
                 or row["payout_period_id"] == args.get("payout_period_id"))
            and (args.get("status") is None or row["status"] == args.get("status"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([settlement_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/advisory-splits/<split_id>")
def get_split(split_id):
    middleware.require_role(*middleware.ANY)
    return ok(settlement_service.serialize(settlement_service.find_split_or_fail(split_id)))
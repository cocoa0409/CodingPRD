"""Payout period routes."""

import flask

import middleware
from db import expense_pass_throughs, payout_periods
from response import ok, ok_list
from services import common
from services import payout_periods as period_service


bp = flask.Blueprint("payouts", __name__)


@bp.post("/payout-periods")
def create_period():
    middleware.require_role("BranchManager", "PlatformAdmin")
    return ok(period_service.serialize(period_service.create_period(common.body())), status=201)


@bp.get("/payout-periods")
def list_periods():
    middleware.require_role(*middleware.ANY)
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in payout_periods.values()
            if (args.get("branch_code") is None or row["branch_code"] == args.get("branch_code"))
            and (args.get("state") is None or row["state"] == args.get("state"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([period_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/payout-periods/<period_id>")
def get_period(period_id):
    middleware.require_role(*middleware.ANY)
    return ok(period_service.serialize(period_service.find_period_or_fail(period_id)))


@bp.post("/payout-periods/<period_id>/state")
def move_period_state(period_id):
    middleware.require_role("BranchManager", "ComplianceOfficer")
    row = period_service.find_period_or_fail(period_id)
    return ok(period_service.serialize(period_service.move_state(row, common.body())))


@bp.post("/payout-periods/<period_id>/true-up")
def true_up(period_id):
    middleware.require_role("BranchManager", "AdvisorOps")
    row = period_service.find_period_or_fail(period_id)
    return ok(period_service.serialize(period_service.true_up(row, common.body())))


@bp.post("/payout-periods/<period_id>/net-settlement")
def net_settlement(period_id):
    middleware.require_role("BranchManager", "AdvisorOps")
    row = period_service.find_period_or_fail(period_id)
    return ok(period_service.net_settlement(row, common.body()))


@bp.get("/payout-periods/<period_id>/payout-lines")
def list_period_lines(period_id):
    middleware.require_role(*middleware.ANY)
    row = period_service.find_period_or_fail(period_id)
    limit, offset = common.pagination_params()
    rows = period_service.lines_of_period(row["id"])
    page, total = common.page(rows, limit, offset)
    return ok_list([period_service.serialize(item) for item in page], total, limit, offset)


@bp.get("/payout-periods/<period_id>/expense-pass-throughs")
def list_period_expenses(period_id):
    middleware.require_role("BranchManager", "AdvisorOps", "ComplianceOfficer")
    row = period_service.find_period_or_fail(period_id)
    limit, offset = common.pagination_params()
    rows = [item for item in expense_pass_throughs.values()
            if item["payout_period_id"] == row["id"]]
    page, total = common.page(rows, limit, offset)
    return ok_list([period_service.serialize(item) for item in page], total, limit, offset)
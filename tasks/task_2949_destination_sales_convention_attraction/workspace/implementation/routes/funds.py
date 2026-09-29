"""Incentive funds and lodging tax receipts (PRD 2.10, 3.1)."""

from decimal import Decimal

from flask import Blueprint, request

import aggregates
import domain
import queries
import resolve
import serialize
from auth import (BOARD_ANALYST, BUREAU_ADMIN, INCENTIVE_APPROVER,
                  SALES_MANAGER, endpoint)
from response import created, list_response, object_response, pagination
from store import db, ordered
from validation import (body_json, query_enum, query_int, req_instant,
                        req_int, req_money)

bp = Blueprint("funds", __name__)


@bp.route("/incentive-funds", methods=["POST"])
@endpoint(BUREAU_ADMIN)
def create_fund():
    body = body_json()
    fiscal_year = req_int(body, "fiscal_year", minimum=2020)
    budget_amount = req_money(body, "budget_amount", positive=True)

    row = db.new_row()
    row.update({
        "fiscal_year": fiscal_year,
        "budget_amount": budget_amount,
        "lodging_tax_receipts_total": Decimal("0.00"),
        "committed_amount": Decimal("0.00"),
        "disbursed_amount": Decimal("0.00"),
        "uncommitted_amount": budget_amount,
        "posture": "OPEN",
    })
    db.funds[row["id"]] = row
    return created(serialize.fund(row))


@bp.route("/incentive-funds/<row_id>", methods=["GET"])
@endpoint(BUREAU_ADMIN, INCENTIVE_APPROVER, SALES_MANAGER, BOARD_ANALYST)
def get_fund(row_id):
    return object_response(serialize.fund(resolve.fund(row_id)))


@bp.route("/incentive-funds", methods=["GET"])
@endpoint(BUREAU_ADMIN, INCENTIVE_APPROVER, BOARD_ANALYST)
def list_funds():
    fiscal_year = query_int(request.args, "fiscal_year")
    posture = query_enum(request.args, "posture", domain.FUND_POSTURES)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.funds.values()))
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    if posture is not None:
        rows = [r for r in rows if r["posture"] == posture]
    return list_response(rows, serialize.fund, limit, offset)


@bp.route("/incentive-funds/<row_id>/lodging-tax-receipts", methods=["POST"])
@endpoint(BUREAU_ADMIN)
def create_receipt(row_id):
    fund = resolve.fund(row_id)
    body = body_json()
    amount = req_money(body, "amount", positive=True)
    received_at = req_instant(body, "received_at")

    row = db.new_row(versioned=False)
    row.update({
        "fund_id": fund["id"],
        "amount": amount,
        "received_at": received_at,
    })
    db.receipts[row["id"]] = row
    # raises lodging_tax_receipts_total and budget_amount, recomputes the
    # residual, re-derives posture and bumps the fund's version by one
    aggregates.fund_post_receipt(fund, amount)
    return created(serialize.receipt(row))


@bp.route("/incentive-funds/<row_id>/lodging-tax-receipts", methods=["GET"])
@endpoint(BUREAU_ADMIN, BOARD_ANALYST)
def list_receipts(row_id):
    fund = resolve.fund(row_id)
    limit, offset = pagination(request.args)
    rows = queries.receipts_of_fund(fund["id"])
    return list_response(rows, serialize.receipt, limit, offset)


@bp.route("/incentive-funds/<row_id>/incentive-decisions", methods=["GET"])
@endpoint(BUREAU_ADMIN, INCENTIVE_APPROVER, BOARD_ANALYST)
def list_fund_decisions(row_id):
    fund = resolve.fund(row_id)
    verdict = query_enum(request.args, "decision", domain.DECISIONS)
    limit, offset = pagination(request.args)
    rows = queries.decisions_of_fund(fund["id"])
    if verdict is not None:
        rows = [r for r in rows if r["decision"] == verdict]
    return list_response(rows, serialize.decision, limit, offset)

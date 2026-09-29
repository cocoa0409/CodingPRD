"""Investment funds and financial closing (PRD 3.4)."""
from flask import Blueprint, g

import clock
import validators as v
from db import db, new_id
from errors import fail
from middleware import ALL_ROLES, by_created_desc, endpoint, filter_str

bp = Blueprint("funds", __name__)


def load_fund(fund_id):
    fund = db.funds.get(fund_id)
    if fund is None:
        fail("ERR_INVESTMENT_FUND_NOT_FOUND")
    return fund


@bp.route("/nmtc/investment-funds", methods=["POST"])
@endpoint(["TaxCreditInvestor"], mutating=True, status=201)
def create_fund():
    data = v.body()
    legal_name = v.req_str(data, "legal_name", 1, 120)
    equity_contribution_cents = v.req_int(data, "equity_contribution_cents", 0)
    leverage_lender_name = v.req_str(data, "leverage_lender_name", 1, 120)
    leverage_loan_principal_cents = v.req_int(data, "leverage_loan_principal_cents", 0)
    leverage_loan_rate_bps = v.req_int(data, "leverage_loan_rate_bps", 0, 5000)

    now = clock.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "legal_name": legal_name,
        "investor_user_id": g.user_id,
        "equity_contribution_cents": equity_contribution_cents,
        "leverage_lender_name": leverage_lender_name,
        "leverage_loan_principal_cents": leverage_loan_principal_cents,
        "leverage_loan_rate_bps": leverage_loan_rate_bps,
        "equity_received_cents": 0,
        "leverage_received_cents": 0,
        "leverage_loan_outstanding_cents": 0,
        "capital_available_cents": 0,
        "deployed_to_qei_cents": 0,
        "status": "FORMED",
        "closed_at": None,
        "_seq": db.next_seq(),
    }
    db.funds[row["id"]] = row
    return row, 201


@bp.route("/nmtc/investment-funds", methods=["GET"])
@endpoint(ALL_ROLES)
def list_funds():
    rows = list(db.funds.values())
    rows = filter_str(rows, "investor_user_id")
    rows = filter_str(rows, "status")
    return by_created_desc(rows)


@bp.route("/nmtc/investment-funds/<fund_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_fund(fund_id):
    return load_fund(fund_id)


@bp.route("/nmtc/investment-funds/<fund_id>/closing", methods=["POST"])
@endpoint(["TaxCreditInvestor"], mutating=True)
def close_fund(fund_id):
    data = v.body()
    equity_received_cents = v.req_int(data, "equity_received_cents", 0)
    leverage_received_cents = v.req_int(data, "leverage_received_cents", 0)

    fund = load_fund(fund_id)
    if g.user_id != fund["investor_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if fund["status"] != "FORMED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if (equity_received_cents != fund["equity_contribution_cents"]
            or leverage_received_cents != fund["leverage_loan_principal_cents"]):
        fail("ERR_CAPITAL_STACK_SHORTFALL")

    fund["equity_received_cents"] = equity_received_cents
    fund["leverage_received_cents"] = leverage_received_cents
    fund["leverage_loan_outstanding_cents"] = leverage_received_cents
    fund["capital_available_cents"] = (
        equity_received_cents + leverage_received_cents - fund["deployed_to_qei_cents"])
    fund["status"] = "FUNDED"
    fund["closed_at"] = clock.now()
    return fund

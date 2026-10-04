"""MIP ledger listing and MIP servicing events (ANNUAL_BILL / CANCEL)."""
from flask import Blueprint

from auth import authenticate, require_role, check_ownership
from routes_cases import get_case_or_404
from services import mip_entries_of_case, recompute_mip_retained
from store import db, make_entity, bump, public, logical_now
from util import (ApiError, ok_object, paginate, get_body, need_enum, need_int,
                  parse_dt, rhu, months_between)

bp = Blueprint("mip", __name__)

MIP_ACTIVE_CASE_STATES = ("ENDORSED", "IN_DEFAULT", "CLAIM_FILED")
PRE_ANNUAL_RATE_BPS = 55
POST_RATE_LTV_LE_9000_BPS = 50
POST_RATE_LTV_LE_9500_BPS = 55
POST_RATE_LTV_GT_9500_BPS = 80
PRE_CANCEL_BALANCE_BPS = 7800
PRE_CANCEL_MIN_AGE_MONTHS = 60
POST_CANCEL_MIN_AGE_MONTHS = 132
POST_CANCEL_LTV_GATE_BPS = 9000


@bp.get("/mi/loan-cases/<loanCaseId>/mip-ledger-entries")
def list_mip_entries(loanCaseId):
    authenticate()
    get_case_or_404(loanCaseId)
    return paginate(mip_entries_of_case(loanCaseId))


@bp.post("/mi/loan-cases/<loanCaseId>/mip-events")
def mip_event(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["ServicerOfficer"])
    case = get_case_or_404(loanCaseId)
    check_ownership(uid, role, case["lender_id"])
    b = get_body()
    event_type = need_enum(b, "event_type", ("ANNUAL_BILL", "CANCEL"))
    balance = need_int(b, "current_balance_cents", minimum=0)
    # Priority 7: state legality.
    if case["status"] in ("VOIDED", "CLAIM_PAID"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "loan case is %s; no MIP events" % case["status"])
    if case["status"] not in MIP_ACTIVE_CASE_STATES:
        raise ApiError("ERR_INVALID_STATE",
                       "MIP events require an endorsed case, got %s" % case["status"])
    if case["mip_cancelled"]:
        raise ApiError("ERR_INVALID_STATE", "annual MIP is already cancelled")
    if event_type == "ANNUAL_BILL":
        return _annual_bill(case, balance)
    return _cancel(case, balance)


def _annual_bill(case, balance):
    if case["mip_vintage"] == "PRE_CUTOFF":
        rate = PRE_ANNUAL_RATE_BPS
    else:
        ltv = case["ltv_bps"]
        if ltv <= 9000:
            rate = POST_RATE_LTV_LE_9000_BPS
        elif ltv <= 9500:
            rate = POST_RATE_LTV_LE_9500_BPS
        else:
            rate = POST_RATE_LTV_GT_9500_BPS
    amount = rhu(balance * rate, 10000)
    annuals = [e["period_index"] for e in mip_entries_of_case(case["id"])
               if e["entry_type"] == "ANNUAL"]
    period = (max(annuals) if annuals else 0) + 1
    entry = make_entity({
        "loan_case_id": case["id"],
        "entry_type": "ANNUAL",
        "period_index": period,
        "amount_cents": amount,
        "credit_cents": 0,
        "rate_bps": rate,
        "status": "BILLED",
    })
    db.mip_entries[entry["id"]] = entry
    recompute_mip_retained(case)
    return ok_object(public(entry), 200)


def _cancel(case, balance):
    now = logical_now()
    endorsement_dt = parse_dt(case["endorsement_date"])
    age = months_between(endorsement_dt, now)
    if case["mip_vintage"] == "PRE_CUTOFF":
        threshold = rhu(case["appraised_value_cents"] * PRE_CANCEL_BALANCE_BPS, 10000)
        if balance > threshold or age < PRE_CANCEL_MIN_AGE_MONTHS:
            raise ApiError("ERR_MIP_CANCELLATION_INELIGIBLE",
                           "PRE_CUTOFF cancellation requires balance <= 78%% of value "
                           "and endorsement age >= 60 months")
    else:
        if case["ltv_bps"] > POST_CANCEL_LTV_GATE_BPS:
            raise ApiError("ERR_VINTAGE_LIFE_OF_LOAN",
                           "POST_CUTOFF case with LTV > 9000 bps carries life-of-loan MIP")
        if age < POST_CANCEL_MIN_AGE_MONTHS:
            raise ApiError("ERR_MIP_CANCELLATION_INELIGIBLE",
                           "POST_CUTOFF cancellation requires endorsement age >= 132 months")
    period = age // 12 + 1
    months_into = age - 12 * (period - 1)
    unused = 12 - months_into
    current = next(
        (e for e in mip_entries_of_case(case["id"])
         if e["entry_type"] == "ANNUAL" and e["period_index"] == period
         and e["status"] == "BILLED"), None)
    refund = rhu(current["amount_cents"] * unused, 12) if current else 0
    rate = current["rate_bps"] if current else 0
    entry = make_entity({
        "loan_case_id": case["id"],
        "entry_type": "REFUND",
        "period_index": period,
        "amount_cents": -refund,
        "credit_cents": 0,
        "rate_bps": rate,
        "status": "BILLED",
    })
    db.mip_entries[entry["id"]] = entry
    case["mip_cancelled"] = True
    recompute_mip_retained(case)
    bump(case)
    return ok_object(public(entry), 200)

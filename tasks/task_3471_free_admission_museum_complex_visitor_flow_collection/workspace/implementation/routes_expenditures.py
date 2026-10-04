"""Expenditures (PRD 3.7): post directly in POSTED (gated by fund status,
activity permission, and COMMITTED availability), list, read, void."""

from flask import Blueprint

import calc
import constants
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("expenditures", __name__)

EXPENDITURE_READ_ROLES = ["PlatformAdmin", "FinanceOfficer", "CommitteeChair"]


@bp.post("/campus/funds/<fid>/expenditures")
def create_expenditure(fid):
    _uid, role = auth()
    require_role(role, ["FinanceOfficer"])
    fund = get_or_404("funds", fid, "FundAccount")  # (3) path existence
    # (6) the fund must be ACTIVE
    if fund["status"] != "ACTIVE":
        fail("ERR_FUND_FROZEN", "The fund is FROZEN")
    b = util.body()
    # (9) request shape
    amount_cents = util.req_int(b, "amount_cents", minimum=1)
    activity_type = util.req_enum(b, "activity_type", constants.ACTIVITY_TYPES)
    memo = util.req_str(b, "memo")
    # (19) federal/trust activity separation
    if not calc.activity_permitted(fund["fund_type"], activity_type):
        fail(
            "ERR_FUND_ACTIVITY_NOT_PERMITTED",
            f"A {fund['fund_type']} fund may not support {activity_type} activity",
        )
    # (20) the amount must not exceed COMMITTED availability
    if calc.committed_available(fund) < amount_cents:
        fail("ERR_INSUFFICIENT_FUND_AVAILABLE", "Committed availability is insufficient")
    e = db.new_entity(
        {
            "fund_id": fund["id"],
            "review_id": None,
            "amount_cents": amount_cents,
            "activity_type": activity_type,
            "memo": memo,
            "status": "POSTED",
        }
    )
    db.STORE["expenditures"][e["id"]] = e
    return success(serializers.expenditure(e), 201)


@bp.get("/campus/expenditures")
def list_expenditures():
    _uid, role = auth()
    require_role(role, EXPENDITURE_READ_ROLES)
    limit, offset = util.pagination()
    f_fund = util.request.args.get("fund_id")
    f_review = util.request.args.get("review_id")
    rows = []
    for e in db.all_sorted("expenditures"):
        if f_fund is not None and e["fund_id"] != f_fund:
            continue
        if f_review is not None and e["review_id"] != f_review:
            continue
        rows.append(e)
    page = rows[offset : offset + limit]
    return listing([serializers.expenditure(e) for e in page], limit, offset, len(rows))


@bp.get("/campus/expenditures/<eid>")
def get_expenditure(eid):
    _uid, role = auth()
    require_role(role, EXPENDITURE_READ_ROLES)
    e = get_or_404("expenditures", eid, "Expenditure")
    return success(serializers.expenditure(e))


@bp.post("/campus/expenditures/<eid>/void")
def void_expenditure(eid):
    _uid, role = auth()
    require_role(role, ["FinanceOfficer"])
    e = get_or_404("expenditures", eid, "Expenditure")
    if e["status"] != "POSTED":
        fail("ERR_INVALID_STATE", "Only a POSTED expenditure can be voided")
    # Compensating action: VOIDED expenditures no longer count against the
    # fund, so settled and committed availability rise by the amount.
    e["status"] = "VOIDED"
    db.touch(e)
    return success(serializers.expenditure(e))

"""Deduction: retailer-filed claims and FinanceAnalyst resolution, with the
three-hop review-friction cascade into every OPEN review of the fund's plan."""

from flask import Blueprint, request

import calc
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_FINANCE_ANALYST,
    ROLE_RETAILER_BUYER,
    authenticate,
    authorize,
    scope_plan,
)
from constants import DEDUCTION_ACTIONS, DEDUCTION_BUCKETS, DEDUCTION_TERMINAL
from envelope import success, success_list
from errors import err
from funds import get_fund
from storage import STORE, by_seq, new_id, public, stamp_new, touch

bp = Blueprint("deductions", __name__)


@bp.post("/jbp/funds/<fund_id>/deductions")
def create_deduction(fund_id):
    uid, role = authenticate()
    authorize(role, [ROLE_RETAILER_BUYER])
    fund = get_fund(fund_id)
    plan = STORE["plans"].get(fund["plan_id"]) if fund is not None else None
    scope_plan(uid, role, plan)  # 3
    data = V.body()
    V.check_undeclared(data, {"claim_reference", "bucket", "amount_cents"})
    claim_reference = V.as_str(V.require(data, "claim_reference"), "claim_reference")
    bucket = V.as_enum(V.require(data, "bucket"), "bucket", DEDUCTION_BUCKETS)
    amount = V.as_int(V.require(data, "amount_cents"), "amount_cents")
    if amount <= 0:
        err("ERR_VALIDATION", "amount_cents must be > 0")
    if fund is None:
        err("ERR_RESOURCE_NOT_FOUND", "fund not found")  # 6
    # priority 21: claim_reference unique within the fund
    for d in STORE["deductions"].values():
        if d["fund_id"] == fund_id and d["claim_reference"] == claim_reference:
            err("ERR_DUPLICATE_CLAIM", "claim_reference already used within this fund")
    rec = {
        "id": new_id(),
        "fund_id": fund_id,
        "claim_reference": claim_reference,
        "bucket": bucket,
        "amount_cents": amount,
        "status": "RECEIVED",
        "settled_amount_cents": None,
        "short_paid": False,
        "absorbed_by_manufacturer": False,
    }
    stamp_new(rec)
    STORE["deductions"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.get("/jbp/funds/<fund_id>/deductions")
def list_deductions(fund_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    fund = get_fund(fund_id)
    if fund is not None:
        scope_plan(uid, role, STORE["plans"].get(fund["plan_id"]))
    if fund is None:
        err("ERR_RESOURCE_NOT_FOUND", "fund not found")
    items = [d for d in by_seq(STORE["deductions"].values()) if d["fund_id"] == fund_id]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [d for d in items if d["status"] == f_status]
    f_bucket = request.args.get("bucket")
    if f_bucket is not None:
        items = [d for d in items if d["bucket"] == f_bucket]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(d) for d in page], limit, offset, total)


@bp.post("/jbp/deductions/<deduction_id>/resolve")
def resolve_deduction(deduction_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_FINANCE_ANALYST])
    data = V.body()
    V.check_undeclared(data, {"action"})
    action = V.as_enum(V.require(data, "action"), "action", DEDUCTION_ACTIONS)  # 4
    ded = STORE["deductions"].get(deduction_id)
    if ded is None:
        err("ERR_RESOURCE_NOT_FOUND", "deduction not found")  # 6
    if ded["status"] in DEDUCTION_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "deduction is terminal")  # 8
    # priority 7: transition legality per action
    legal = (
        (action == "DISPUTE" and ded["status"] == "RECEIVED")
        or (action == "SETTLE" and ded["status"] in ("RECEIVED", "DISPUTED"))
        or (action in ("REJECT", "WRITE_OFF") and ded["status"] == "DISPUTED")
    )
    if not legal:
        err("ERR_INVALID_STATE", "action not permitted from the deduction's current state")
    fund = get_fund(ded["fund_id"])
    if action == "DISPUTE":
        ded["status"] = "DISPUTED"
    elif action == "SETTLE":
        available = calc.bucket_available(fund, ded["bucket"])
        settled = min(ded["amount_cents"], available)
        ded["settled_amount_cents"] = settled
        ded["short_paid"] = settled < ded["amount_cents"]
        ded["status"] = "SETTLED"
        fund["edlp_settled_cents" if ded["bucket"] == "EDLP" else "event_settled_cents"] += settled
        touch(fund)
    elif action == "REJECT":
        ded["status"] = "REJECTED"  # no fund movement
    else:  # WRITE_OFF
        available = calc.bucket_available(fund, ded["bucket"])
        settled = min(ded["amount_cents"], available)
        ded["settled_amount_cents"] = settled
        ded["short_paid"] = settled < ded["amount_cents"]
        ded["absorbed_by_manufacturer"] = True
        ded["status"] = "WRITTEN_OFF"
        fund["edlp_settled_cents" if ded["bucket"] == "EDLP" else "event_settled_cents"] += settled
        touch(fund)
    touch(ded)
    # hops 2-3: OPEN reviews of the fund's plan recompute friction/risk/posture
    calc.recompute_open_reviews(fund["plan_id"])
    return success(public(ded))

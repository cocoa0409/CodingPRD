"""PenaltyAssessment endpoints."""
from flask import Blueprint, request

from db import store, touch
from errors import err
from middleware import ALL_ROLES, require_roles, body, paginate, sort_default
from response import ok, ok_list
from serializers import ser_assessment
from services import (LATE_REPORT_FEE_CENTS, UNMETERED_PUMPING_FEE_CENTS,
                      APPEAL_WINDOW, compute_overdraft_af, overdraft_penalty_cents,
                      new_assessment)
from util import round3, to_decimal, dp_ok, is_int

bp = Blueprint("penalties", __name__)

REASONS = ("OVERDRAFT", "LATE_REPORT", "UNMETERED_PUMPING")
OUTCOMES = ("UPHELD", "OVERTURNED", "REDUCED")
PAYABLE = ("ASSESSED", "UPHELD", "REDUCED")


@bp.post("/penalty-assessments")
def create_assessment():
    uid, _ = require_roles("EnforcementOfficer")
    b = body()
    acc_id = b.get("account_id")
    if not isinstance(acc_id, str) or not acc_id:
        raise err("ERR_INVALID_REQUEST", "account_id is required")
    reason = b.get("reason")
    if reason not in REASONS:
        raise err("ERR_INVALID_REQUEST", "reason must be one of OVERDRAFT, LATE_REPORT, UNMETERED_PUMPING")
    wy = b.get("water_year")
    if not is_int(wy):
        raise err("ERR_INVALID_REQUEST", "water_year must be an integer")
    od_raw = b.get("overdraft_af")
    od_present = "overdraft_af" in b and od_raw is not None
    od = None
    if reason == "OVERDRAFT":
        if not od_present:
            raise err("ERR_INVALID_REQUEST", "overdraft_af is required for reason OVERDRAFT")
        od = to_decimal(od_raw)
        if od is None or od < 0 or not dp_ok(od, 3):
            raise err("ERR_INVALID_REQUEST", "overdraft_af must be >= 0 with at most 3 decimal places")
        od = round3(od)
    elif od_present:
        raise err("ERR_INVALID_REQUEST", "overdraft_af must be absent for non-OVERDRAFT reasons")
    acct = store.accounts.get(acc_id)
    if acct is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", "No WaterUserAccount with the given id")
    if reason == "OVERDRAFT":
        computed = compute_overdraft_af(acct)
        if od != computed:
            raise err("ERR_OVERDRAFT_AMOUNT_MISMATCH",
                      "overdraft_af does not equal the computed overdraft")
        amount = overdraft_penalty_cents(acct, computed)
    elif reason == "LATE_REPORT":
        amount = LATE_REPORT_FEE_CENTS
    else:
        amount = UNMETERED_PUMPING_FEE_CENTS
    a = new_assessment(acct, reason, wy, od, amount, uid)
    acct["penalty_balance_cents"] += amount
    acct["version"] += 1
    touch(acct)
    return ok(ser_assessment(a), status=201)


@bp.get("/penalty-assessments")
def list_assessments():
    require_roles(*ALL_ROLES)
    items = list(store.assessments.values())
    acc = request.args.get("account_id")
    if acc is not None:
        items = [a for a in items if a["account_id"] == acc]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    rs = request.args.get("reason")
    if rs is not None:
        items = [a for a in items if a["reason"] == rs]
    items = sort_default(items)
    page, pg = paginate(items)
    return ok_list([ser_assessment(a) for a in page], pg)


@bp.get("/penalty-assessments/<assessment_id>")
def get_assessment(assessment_id):
    require_roles(*ALL_ROLES)
    a = store.assessments.get(assessment_id)
    if a is None:
        raise err("ERR_ASSESSMENT_NOT_FOUND", "No PenaltyAssessment with the given id")
    return ok(ser_assessment(a))


@bp.post("/penalty-assessments/<assessment_id>/pay")
def pay_assessment(assessment_id):
    uid, _ = require_roles("WellOwner")
    a = store.assessments.get(assessment_id)
    if a is not None and a["account_id"] != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "WellOwner may only pay their own assessments")
    if a is None:
        raise err("ERR_ASSESSMENT_NOT_FOUND", "No PenaltyAssessment with the given id")
    if a["status"] not in PAYABLE:
        raise err("ERR_INVALID_ASSESSMENT_STATE", "pay requires status ASSESSED, UPHELD, or REDUCED")
    acct = store.accounts[a["account_id"]]
    amount = a["reduced_amount_cents"] if a["status"] == "REDUCED" else a["amount_cents"]
    acct["penalty_balance_cents"] -= amount
    a["paid_amount_cents"] = amount
    a["status"] = "PAID"
    a["version"] += 1
    touch(a)
    acct["version"] += 1
    touch(acct)
    return ok(ser_assessment(a))


@bp.post("/penalty-assessments/<assessment_id>/appeal")
def appeal_assessment(assessment_id):
    uid, _ = require_roles("WellOwner")
    a = store.assessments.get(assessment_id)
    if a is not None and a["account_id"] != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "WellOwner may only appeal their own assessments")
    b = body()
    if not isinstance(b.get("grounds"), str):
        raise err("ERR_INVALID_REQUEST", "grounds is required")
    if a is None:
        raise err("ERR_ASSESSMENT_NOT_FOUND", "No PenaltyAssessment with the given id")
    if a["status"] != "ASSESSED":
        raise err("ERR_INVALID_ASSESSMENT_STATE", "appeal requires status ASSESSED")
    if store.clock > a["created_at"] + APPEAL_WINDOW:
        raise err("ERR_APPEAL_WINDOW_CLOSED", "Appeal filed after created_at + 30 days")
    a["status"] = "APPEALED"
    a["version"] += 1
    touch(a)
    return ok(ser_assessment(a))


@bp.post("/penalty-assessments/<assessment_id>/decide")
def decide_assessment(assessment_id):
    uid, _ = require_roles("AppealsOfficer")
    b = body()
    outcome = b.get("outcome")
    if outcome not in OUTCOMES:
        raise err("ERR_INVALID_REQUEST", "outcome must be one of UPHELD, OVERTURNED, REDUCED")
    red_raw = b.get("reduced_amount_cents")
    red_present = "reduced_amount_cents" in b and red_raw is not None
    reduced = None
    if outcome == "REDUCED":
        if not red_present:
            raise err("ERR_INVALID_REQUEST", "reduced_amount_cents is required for outcome REDUCED")
        if not is_int(red_raw):
            raise err("ERR_INVALID_REQUEST", "reduced_amount_cents must be an integer")
        reduced = red_raw
    elif red_present:
        raise err("ERR_INVALID_REQUEST", "reduced_amount_cents must be absent unless outcome is REDUCED")
    a = store.assessments.get(assessment_id)
    if a is None:
        raise err("ERR_ASSESSMENT_NOT_FOUND", "No PenaltyAssessment with the given id")
    if outcome == "REDUCED" and not (0 < reduced < a["amount_cents"]):
        raise err("ERR_INVALID_REQUEST", "reduced_amount_cents must satisfy 0 < reduced < amount_cents")
    if a["status"] != "APPEALED":
        raise err("ERR_INVALID_ASSESSMENT_STATE", "decide requires status APPEALED")
    if uid == a["assessed_by"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Appeal decider must differ from the assessor")
    a["decided_by"] = uid
    acct = store.accounts[a["account_id"]]
    if outcome == "UPHELD":
        a["status"] = "UPHELD"
        a["version"] += 1
        touch(a)
    elif outcome == "OVERTURNED":
        acct["penalty_balance_cents"] -= a["amount_cents"]
        a["status"] = "OVERTURNED"
        a["version"] += 1
        touch(a)
        acct["version"] += 1
        touch(acct)
    else:  # REDUCED
        acct["penalty_balance_cents"] -= (a["amount_cents"] - reduced)
        a["reduced_amount_cents"] = reduced
        a["status"] = "REDUCED"
        a["version"] += 1
        touch(a)
        acct["version"] += 1
        touch(acct)
    return ok(ser_assessment(a))

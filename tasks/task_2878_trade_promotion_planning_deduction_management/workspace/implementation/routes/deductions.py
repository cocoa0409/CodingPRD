"""Deduction intake, valuation, settlement and the dispute round-trip
(PRD 3.8 / 3.9)."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import services
from calc import ZERO, q2
from db import clock_dt, clock_instant, db, new_row, touch
from errors import ApiError
from response import created_response, object_response
from routes.common import (
    ALL_ROLES,
    ALL_ROLES_WITH_PORTAL,
    PREFIX,
    created_asc,
    get_customer,
    get_deduction,
    get_dispute,
    get_promotion,
    opened_then_created,
    page,
)
from validators import (
    authenticate,
    body_fields,
    get_date,
    get_enum,
    get_int,
    get_money,
    get_string,
    is_portal,
    no_body,
    pagination,
    portal_guard,
    query_enum,
    query_value,
)

bp = Blueprint("deductions", __name__)

DIRECTOR = "TradeMarketingDirector"
ANALYST = "TradeFinanceAnalyst"
SPECIALIST = "DeductionSpecialist"

DEDUCTION_STATUSES = ("RECEIVED", "MATCHED", "VALIDATED", "SETTLED",
                      "DISPUTED", "RECOVERED", "WRITTEN_OFF")
DISPUTE_STATUSES = ("OPEN", "AWAITING_RETAILER", "ESCALATED",
                    "RECOVERED", "WRITTEN_OFF")
REASON_CODES = ("NO_AGREEMENT", "NO_EVIDENCE", "RATE_MISMATCH", "DUPLICATE_CLAIM")
RETAILER_RESPONSES = ("ACCEPT_CHARGEBACK", "PROVIDE_EVIDENCE", "REFUSE")
OPEN_DISPUTE_STATUSES = ("OPEN", "ESCALATED")


def dispute_customer_id(dispute):
    deduction = db.deductions.get(dispute["deduction_id"])
    return deduction["customer_id"] if deduction is not None else None


# --------------------------------------------------------------------------
# intake
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/deductions")
def create_deduction():
    authenticate([SPECIALIST])
    data = body_fields(
        required=["customer_id", "claim_reference", "claimed_amount", "deduction_date"],
        optional=["supersedes_deduction_id"],
    )
    customer_id = get_string(data, "customer_id")
    claim_reference = get_string(data, "claim_reference", min_len=1, max_len=60)
    claimed_amount = get_money(data, "claimed_amount", strictly_positive=True)
    deduction_date = get_date(data, "deduction_date")
    supersedes = get_string(data, "supersedes_deduction_id", required=False)

    # rung 21 - customer_id then supersedes_deduction_id
    customer = get_customer(customer_id)
    if supersedes is not None:
        get_deduction(supersedes)
    # rung 63
    for row in calc.deductions_of_customer(customer_id):
        if row["claim_reference"] == claim_reference:
            raise ApiError("ERR_DUPLICATE_CLAIM_REFERENCE")

    row = new_row()
    row.update({
        "customer_id": customer_id,
        "claim_reference": claim_reference,
        "claimed_amount": claimed_amount,
        "deduction_date": deduction_date,
        "promotion_id": None,
        "status": "RECEIVED",
        "validation_basis": None,
        "entitled_amount": None,
        "validated_amount": None,
        "variance_amount": None,
        "supersedes_deduction_id": supersedes,
        "matched_by_user_id": None,
        "validated_by_user_id": None,
        "settled_at": None,
    })
    db.deductions[row["id"]] = row
    touch(customer)
    return created_response(calc.deduction_out(row))


@bp.get(PREFIX + "/deductions/<deduction_id>")
def read_deduction(deduction_id):
    authenticate(ALL_ROLES_WITH_PORTAL)
    no_body()
    deduction = get_deduction(deduction_id)
    portal_guard(deduction["customer_id"])
    return object_response(calc.deduction_out(deduction))


@bp.get(PREFIX + "/deductions")
def list_deductions():
    authenticate(ALL_ROLES_WITH_PORTAL)
    limit, offset = pagination([
        "customer_id", "promotion_id", "status", "supersedes_deduction_id",
    ])
    customer_id = query_value("customer_id")
    promotion_id = query_value("promotion_id")
    status = query_enum("status", DEDUCTION_STATUSES)
    supersedes = query_value("supersedes_deduction_id")
    if is_portal():
        if customer_id is None:
            customer_id = g.user_id
        else:
            portal_guard(customer_id)
    rows = list(db.deductions.values())
    if customer_id is not None:
        if not is_portal():
            get_customer(customer_id)
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if promotion_id is not None:
        get_promotion(promotion_id)
        rows = [r for r in rows if r["promotion_id"] == promotion_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if supersedes is not None:
        get_deduction(supersedes)
        rows = [r for r in rows if r["supersedes_deduction_id"] == supersedes]
    return page(created_asc(rows), limit, offset, calc.deduction_out)


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/deductions/<deduction_id>/match")
def match_deduction(deduction_id):
    authenticate([SPECIALIST])
    data = body_fields(required=["promotion_id"])
    promotion_id = get_string(data, "promotion_id")
    deduction = get_deduction(deduction_id)
    promo = get_promotion(promotion_id)
    # rung 47
    if deduction["status"] != "RECEIVED":
        raise ApiError("ERR_DEDUCTION_STATE_INVALID")
    # rung 61
    if promo["customer_id"] != deduction["customer_id"]:
        raise ApiError("ERR_DEDUCTION_CUSTOMER_MISMATCH")
    # rung 62
    if promo["lifecycle_status"] not in calc.MATCHABLE_LIFECYCLES:
        raise ApiError("ERR_PROMOTION_NOT_MATCHABLE")
    deduction["status"] = "MATCHED"
    deduction["promotion_id"] = promotion_id
    deduction["matched_by_user_id"] = g.user_id
    touch(deduction)
    return object_response(calc.deduction_out(deduction))


# --------------------------------------------------------------------------
# valuation
# --------------------------------------------------------------------------

def contract_rate(promo):
    total = Decimal("0")
    for tactic in calc.live_tactics(promo["id"]):
        if tactic["tactic_type"] == "TPR" and tactic["rate_per_case"] is not None:
            total += tactic["rate_per_case"]
    return total


def evidence_units(promo):
    total = 0
    for doc in calc.documents_of_promotion(promo["id"]):
        if doc["doc_class"] == "EVIDENCE" and doc["status"] == "VERIFIED":
            total += doc["units_verified"]
    return total


@bp.post(PREFIX + "/deductions/<deduction_id>/validate")
def validate_deduction(deduction_id):
    authenticate([ANALYST])
    data = body_fields(required=["expected_promotion_version"])
    expected = get_int(data, "expected_promotion_version", minimum=0)
    deduction = get_deduction(deduction_id)
    promo = db.promotions.get(deduction["promotion_id"]) \
        if deduction["promotion_id"] else None
    # rung 31 - only meaningful once the claim carries a matched promotion
    if promo is not None and expected != promo["version"]:
        raise ApiError("ERR_STALE_PROMOTION_VERSION")
    # rung 47
    if deduction["status"] != "MATCHED" or promo is None:
        raise ApiError("ERR_DEDUCTION_STATE_INVALID")
    # rung 50
    if promo["approved_by_user_id"] is not None \
            and promo["approved_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    customer = db.customers.get(deduction["customer_id"])
    policy = customer["deduction_validation_policy"] if customer else "EVIDENCE_BASED"
    units = evidence_units(promo)
    balance = calc.promotion_ledger(promo)["accrued_balance"]
    if policy == "EVIDENCE_BASED":
        # rung 86
        if units <= 0:
            raise ApiError("ERR_NO_PERFORMANCE_EVIDENCE")
        entitled = q2(Decimal(units) * contract_rate(promo))
    else:
        # rung 98
        if balance <= ZERO:
            raise ApiError("ERR_ACCRUAL_BALANCE_INSUFFICIENT")
        entitled = q2(balance)

    claimed = deduction["claimed_amount"]
    validated = claimed if claimed < entitled else entitled
    deduction["status"] = "VALIDATED"
    deduction["validation_basis"] = policy
    deduction["entitled_amount"] = q2(entitled)
    deduction["validated_amount"] = q2(validated)
    deduction["variance_amount"] = q2(claimed - validated)
    deduction["validated_by_user_id"] = g.user_id
    touch(deduction)
    touch(promo)
    services.apply_spend_cascade(promo)
    services.recompute_analysis(promo)
    return object_response(calc.deduction_out(deduction))


@bp.post(PREFIX + "/deductions/<deduction_id>/settle")
def settle_deduction(deduction_id):
    authenticate([ANALYST])
    no_body()
    deduction = get_deduction(deduction_id)
    # rung 47
    if deduction["status"] != "VALIDATED":
        raise ApiError("ERR_DEDUCTION_STATE_INVALID")
    customer = db.customers.get(deduction["customer_id"])
    # rung 53
    if customer is not None and customer["trading_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")
    deduction["status"] = "SETTLED"
    deduction["settled_at"] = clock_dt()
    touch(deduction)
    promo = db.promotions.get(deduction["promotion_id"]) \
        if deduction["promotion_id"] else None
    if promo is not None:
        alloc = db.allocations.get(promo["allocation_id"])
        if alloc is not None:
            touch(alloc)
    if customer is not None:
        touch(customer)
    return object_response(calc.deduction_out(deduction))


# --------------------------------------------------------------------------
# disputes
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/deductions/<deduction_id>/dispute")
def open_dispute(deduction_id):
    authenticate([SPECIALIST])
    data = body_fields(required=["reason_code", "disputed_amount"])
    reason_code = get_enum(data, "reason_code", REASON_CODES)
    disputed_amount = get_money(data, "disputed_amount")
    deduction = get_deduction(deduction_id)
    # rung 47
    if deduction["status"] not in ("RECEIVED", "MATCHED", "VALIDATED"):
        raise ApiError("ERR_DEDUCTION_STATE_INVALID")
    # rung 87 - the disputable base narrows once the claim has been valued
    if deduction["status"] == "VALIDATED":
        base = deduction["variance_amount"] or ZERO
    else:
        base = deduction["claimed_amount"]
    if disputed_amount <= ZERO or disputed_amount > base:
        raise ApiError("ERR_DISPUTED_AMOUNT_EXCEEDS_CLAIM")

    deduction["status"] = "DISPUTED"
    touch(deduction)
    row = new_row()
    row.update({
        "deduction_id": deduction_id,
        "reason_code": reason_code,
        "disputed_amount": disputed_amount,
        "opened_at": clock_dt(),
        "opened_by_user_id": g.user_id,
        "status": "OPEN",
        "round_count": 0,
        "retailer_response": None,
        "recovered_amount": None,
        "write_off_amount": None,
        "resolved_by_user_id": None,
        "packet_notes": None,
        "write_off_reason": None,
    })
    db.disputes[row["id"]] = row
    return created_response(calc.dispute_out(row))


@bp.get(PREFIX + "/disputes/<dispute_id>")
def read_dispute(dispute_id):
    authenticate(ALL_ROLES_WITH_PORTAL)
    no_body()
    dispute = get_dispute(dispute_id)
    portal_guard(dispute_customer_id(dispute))
    return object_response(calc.dispute_out(dispute))


@bp.get(PREFIX + "/disputes")
def list_disputes():
    authenticate(ALL_ROLES_WITH_PORTAL)
    limit, offset = pagination(["deduction_id", "status", "reason_code"])
    deduction_id = query_value("deduction_id")
    status = query_enum("status", DISPUTE_STATUSES)
    reason_code = query_enum("reason_code", REASON_CODES)
    rows = list(db.disputes.values())
    if deduction_id is not None:
        deduction = get_deduction(deduction_id)
        portal_guard(deduction["customer_id"])
        rows = [r for r in rows if r["deduction_id"] == deduction_id]
    elif is_portal():
        rows = [r for r in rows if dispute_customer_id(r) == g.user_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reason_code is not None:
        rows = [r for r in rows if r["reason_code"] == reason_code]
    return page(opened_then_created(rows), limit, offset, calc.dispute_out)


@bp.post(PREFIX + "/disputes/<dispute_id>/send-to-retailer")
def send_to_retailer(dispute_id):
    authenticate([SPECIALIST])
    data = body_fields(optional=["packet_notes"])
    notes = get_string(data, "packet_notes", required=False, min_len=1)
    dispute = get_dispute(dispute_id)
    # rung 48
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    # rung 83
    if dispute["round_count"] >= calc.MAX_DISPUTE_ROUNDS:
        raise ApiError("ERR_DISPUTE_ROUND_LIMIT")
    dispute["status"] = "AWAITING_RETAILER"
    dispute["round_count"] += 1
    if notes is not None:
        dispute["packet_notes"] = notes
    touch(dispute)
    return object_response(calc.dispute_out(dispute))


@bp.post(PREFIX + "/disputes/<dispute_id>/retailer-respond")
def retailer_respond(dispute_id):
    authenticate(["CustomerPortalUser"])
    data = body_fields(required=["retailer_response"])
    response = get_enum(data, "retailer_response", RETAILER_RESPONSES)
    dispute = get_dispute(dispute_id)
    # rung 4 - the portal caller must own the disputed deduction
    portal_guard(dispute_customer_id(dispute))
    # rung 48
    if dispute["status"] != "AWAITING_RETAILER":
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    dispute["status"] = "OPEN"
    dispute["retailer_response"] = response
    touch(dispute)
    return object_response(calc.dispute_out(dispute))


@bp.post(PREFIX + "/disputes/<dispute_id>/record-recovery")
def record_recovery(dispute_id):
    authenticate([SPECIALIST])
    data = body_fields(required=["recovered_amount"])
    recovered = get_money(data, "recovered_amount")
    dispute = get_dispute(dispute_id)
    # rung 48
    if dispute["status"] not in OPEN_DISPUTE_STATUSES:
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    # rung 89
    if recovered <= ZERO or recovered > dispute["disputed_amount"]:
        raise ApiError("ERR_RECOVERY_EXCEEDS_OPEN_AMOUNT")
    dispute["status"] = "RECOVERED"
    dispute["recovered_amount"] = recovered
    dispute["resolved_by_user_id"] = g.user_id
    touch(dispute)
    deduction = db.deductions.get(dispute["deduction_id"])
    if deduction is not None:
        deduction["status"] = "RECOVERED"
        touch(deduction)
        promo = db.promotions.get(deduction["promotion_id"]) \
            if deduction["promotion_id"] else None
        if promo is not None:
            services.recompute_analysis(promo)
    return object_response(calc.dispute_out(dispute))


@bp.post(PREFIX + "/disputes/<dispute_id>/write-off")
def write_off(dispute_id):
    authenticate([SPECIALIST, DIRECTOR])
    data = body_fields(required=["write_off_amount"], optional=["write_off_reason"])
    amount = get_money(data, "write_off_amount")
    reason = get_string(data, "write_off_reason", required=False, min_len=1)
    dispute = get_dispute(dispute_id)
    # rung 48
    if dispute["status"] not in OPEN_DISPUTE_STATUSES:
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    # rung 50 - the opener may never approve the write-off
    if dispute["opened_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # rung 51 - a large write-off carries director authority
    if amount >= calc.WRITE_OFF_SELF_APPROVAL_LIMIT and g.user_role != DIRECTOR:
        raise ApiError("ERR_WRITE_OFF_APPROVAL_REQUIRED")
    # rung 88
    if amount <= ZERO or amount > dispute["disputed_amount"]:
        raise ApiError("ERR_WRITE_OFF_EXCEEDS_OPEN_AMOUNT")

    dispute["status"] = "WRITTEN_OFF"
    dispute["write_off_amount"] = amount
    dispute["write_off_reason"] = reason
    dispute["resolved_by_user_id"] = g.user_id
    touch(dispute)
    deduction = db.deductions.get(dispute["deduction_id"])
    if deduction is not None:
        deduction["status"] = "WRITTEN_OFF"
        touch(deduction)
        promo = db.promotions.get(deduction["promotion_id"]) \
            if deduction["promotion_id"] else None
        if promo is not None:
            touch(promo)
            services.apply_spend_cascade(promo)
            services.recompute_analysis(promo)
            alloc = db.allocations.get(promo["allocation_id"])
            if alloc is not None:
                touch(alloc)
    return object_response(calc.dispute_out(dispute))


# --------------------------------------------------------------------------
# aging sweep
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/deduction-aging-runs")
def aging_run():
    authenticate([ANALYST, SPECIALIST])
    no_body()
    result = services.run_aging()
    body = {"run_at": clock_instant()}
    body.update(result)
    return object_response(body)

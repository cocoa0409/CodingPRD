"""Derived figures (PRD 3.1-3.10) and resource serialisation.

Every monetary value is a Decimal in the store and is rounded half up to 2
decimal places; ratios to 4.  Component lines are rounded BEFORE they are
summed (PRD 2.5).
"""

from decimal import Decimal, ROUND_HALF_UP

from db import by_seq, clock_dt, db

CENT = Decimal("0.01")
RATIO = Decimal("0.0001")
THREE = Decimal("0.001")
ZERO = Decimal("0.00")

# PRD 3.3 / scaffold constants
TIER1_CEILING = Decimal("10000.00")
TIER2_CEILING = Decimal("50000.00")
TIER1_RATE = Decimal("0.000")
TIER2_RATE = Decimal("0.020")
TIER3_RATE = Decimal("0.035")
OVERSPEND_WARNING_RATIO = Decimal("0.9000")
OVERSPENT_RATIO = Decimal("1.0000")
ROI_FLOOR = Decimal("1.0000")
SHIP_LEAD_DAYS = 14
TRAILING_BASELINE_WEEKS = 4
POST_PERIOD_WEEKS = 2
AGING_ESCALATION_DAYS = 90
RESTRICTED_ALLOCATION_POINTS = 10
ESCALATED_DISPUTE_POINTS = 5
FINDINGS_ISSUED_POINTS = 10
CREDIT_HOLD_POINTS = 10
SUSPENSION_POINTS = 25
MAX_REVISION_ROUNDS = 2
MAX_DISPUTE_ROUNDS = 2
WRITE_OFF_SELF_APPROVAL_LIMIT = Decimal("500.00")
TPR_CONCURRENCY_CAP = 2
FEATURE_COOLDOWN_DAYS = 7

LIVE_TACTIC_STATUSES = ("PLANNED", "ACTIVE", "COMPLETED")
COMMITTING_LIFECYCLES = ("APPROVED", "LIVE", "ENDED", "ANALYZED")
MATCHABLE_LIFECYCLES = ("APPROVED", "LIVE", "ENDED", "ANALYZED")
OPEN_DEDUCTION_STATUSES = ("RECEIVED", "MATCHED", "VALIDATED", "DISPUTED")


def q2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(RATIO, rounding=ROUND_HALF_UP)


def q3(value):
    return Decimal(value).quantize(THREE, rounding=ROUND_HALF_UP)


def f(value):
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------
# child lookups
# --------------------------------------------------------------------------

def allocations_of_program(program_id):
    return [a for a in db.allocations.values() if a["program_id"] == program_id]


def allocations_of_customer(customer_id):
    return [a for a in db.allocations.values() if a["customer_id"] == customer_id]


def promotions_of_allocation(allocation_id):
    return [p for p in db.promotions.values() if p["allocation_id"] == allocation_id]


def tactics_of_promotion(promotion_id):
    return by_seq([t for t in db.tactics.values() if t["promotion_id"] == promotion_id])


def documents_of_promotion(promotion_id):
    return by_seq([d for d in db.documents.values() if d["promotion_id"] == promotion_id])


def accruals_of_promotion(promotion_id):
    return by_seq([a for a in db.accruals.values() if a["promotion_id"] == promotion_id])


def deductions_of_promotion(promotion_id):
    return [d for d in db.deductions.values() if d["promotion_id"] == promotion_id]


def deductions_of_customer(customer_id):
    return [d for d in db.deductions.values() if d["customer_id"] == customer_id]


def disputes_of_deduction(deduction_id):
    return by_seq([d for d in db.disputes.values() if d["deduction_id"] == deduction_id])


def analysis_of_promotion(promotion_id):
    rows = by_seq([a for a in db.analyses.values() if a["promotion_id"] == promotion_id])
    return rows[0] if rows else None


def audits_of_customer(customer_id):
    return [a for a in db.audits.values() if a["customer_id"] == customer_id]


def live_tactics(promotion_id):
    return [t for t in tactics_of_promotion(promotion_id)
            if t["status"] in LIVE_TACTIC_STATUSES]


# --------------------------------------------------------------------------
# TradeProgram rollup (PRD 3.1)
# --------------------------------------------------------------------------

def program_allocated_amount(program):
    total = ZERO
    for alloc in allocations_of_program(program["id"]):
        total += alloc["planned_amount"]
    return q2(total)


def program_rollup(program):
    allocated = program_allocated_amount(program)
    return allocated, q2(program["total_budget_amount"] - allocated)


# --------------------------------------------------------------------------
# Customer rollups (PRD 3.1) and penalty ledger (PRD 2.10)
# --------------------------------------------------------------------------

def customer_open_deduction_amount(customer):
    total = ZERO
    for ded in deductions_of_customer(customer["id"]):
        if ded["status"] in OPEN_DEDUCTION_STATUSES:
            total += ded["claimed_amount"]
    return q2(total)


def customer_write_off_ytd_amount(customer):
    total = ZERO
    for ded in deductions_of_customer(customer["id"]):
        for dis in disputes_of_deduction(ded["id"]):
            if dis["status"] == "WRITTEN_OFF" and dis["write_off_amount"] is not None:
                total += dis["write_off_amount"]
    return q2(total)


def customer_penalty_points(customer):
    points = 0
    for alloc in allocations_of_customer(customer["id"]):
        if allocation_posture(alloc) == "RESTRICTED":
            points += RESTRICTED_ALLOCATION_POINTS
    for ded in deductions_of_customer(customer["id"]):
        for dis in disputes_of_deduction(ded["id"]):
            if dis["status"] == "ESCALATED":
                points += ESCALATED_DISPUTE_POINTS
    for audit in audits_of_customer(customer["id"]):
        if audit["status"] == "FINDINGS_ISSUED":
            points += FINDINGS_ISSUED_POINTS
    return points


# --------------------------------------------------------------------------
# BudgetAllocation ledger (PRD 3.2)
# --------------------------------------------------------------------------

def allocation_posture(alloc):
    program = db.programs.get(alloc["program_id"])
    if program is not None and program["status"] == "LOCKED":
        return "FROZEN"
    if alloc["overspend_event_count"] >= 1:
        return "RESTRICTED"
    return "OPEN"


def allocation_ledger(alloc):
    committed_amount = ZERO
    committed_units = 0
    accrued_amount = ZERO
    settled_amount = ZERO
    at_risk_amount = ZERO
    for promo in promotions_of_allocation(alloc["id"]):
        pricing = promotion_pricing(promo)
        if promo["lifecycle_status"] in COMMITTING_LIFECYCLES:
            committed_amount += pricing["planned_total_spend"]
            committed_units += pricing["committed_units"]
        ledger = promotion_ledger(promo)
        accrued_amount += ledger["gross_accrued_amount"] - ledger["reversed_accrual_amount"]
        for ded in deductions_of_promotion(promo["id"]):
            if ded["status"] == "SETTLED" and ded["validated_amount"] is not None:
                settled_amount += ded["validated_amount"]
        analysis = analysis_of_promotion(promo["id"])
        if analysis is not None and promotion_performance_flag(promo) == "UNDERPERFORMING":
            at_risk_amount += analysis["net_spend"]
    committed_amount = q2(committed_amount)
    return {
        "committed_amount": committed_amount,
        "committed_units": committed_units,
        "accrued_amount": q2(accrued_amount),
        "settled_amount": q2(settled_amount),
        "at_risk_amount": q2(at_risk_amount),
        "available_amount": q2(alloc["planned_amount"] - committed_amount),
        "unreserved_units": alloc["planned_incremental_units"] - committed_units,
    }


# --------------------------------------------------------------------------
# Promotion pricing (PRD 3.3, four pinned steps)
# --------------------------------------------------------------------------

def tactic_line_planned_spend(tactic):
    if tactic["tactic_type"] == "TPR":
        return q2(Decimal(tactic["planned_units"]) * tactic["rate_per_case"])
    return q2(tactic["fixed_fee"])


def tactic_week_count(tactic):
    return (tactic["window_end"] - tactic["window_start"]).days // 7


def allowance_rate_for(subtotal):
    if subtotal < TIER1_CEILING:
        return TIER1_RATE
    if subtotal < TIER2_CEILING:
        return TIER2_RATE
    return TIER3_RATE


def promotion_pricing(promo):
    subtotal = ZERO
    units = 0
    for tactic in live_tactics(promo["id"]):
        subtotal += tactic_line_planned_spend(tactic)
        units += tactic["planned_units"]
    subtotal = q2(subtotal)
    rate = allowance_rate_for(subtotal)
    allowance = q2(subtotal * rate)
    return {
        "tactic_subtotal_amount": subtotal,
        "allowance_rate": rate,
        "off_invoice_allowance_amount": allowance,
        "planned_total_spend": q2(subtotal + allowance),
        "committed_units": units,
    }


def promotion_commitment_verified(promo):
    required = set()
    for tactic in live_tactics(promo["id"]):
        if tactic["tactic_type"] in ("DISPLAY", "FEATURE"):
            required.add(tactic["tactic_type"])
    covered = set()
    for doc in documents_of_promotion(promo["id"]):
        if doc["doc_class"] == "COMMITMENT" and doc["status"] == "VERIFIED":
            if doc["covers_tactic_type"] == "ALL":
                covered.update(("TPR", "DISPLAY", "FEATURE"))
            else:
                covered.add(doc["covers_tactic_type"])
    return required.issubset(covered)


# --------------------------------------------------------------------------
# Promotion accrual ledger and spend axis (PRD 3.7)
# --------------------------------------------------------------------------

def promotion_ledger(promo):
    gross = ZERO
    reversed_amount = ZERO
    for entry in accruals_of_promotion(promo["id"]):
        if entry["entry_type"] == "ACCRUAL":
            gross += entry["amount"]
        elif entry["entry_type"] == "REVERSAL":
            reversed_amount += entry["amount"]
    validated_total = ZERO
    write_off_total = ZERO
    for ded in deductions_of_promotion(promo["id"]):
        if ded["status"] in ("VALIDATED", "SETTLED") and ded["validated_amount"] is not None:
            validated_total += ded["validated_amount"]
        for dis in disputes_of_deduction(ded["id"]):
            if dis["status"] == "WRITTEN_OFF" and dis["write_off_amount"] is not None:
                write_off_total += dis["write_off_amount"]
    gross = q2(gross)
    reversed_amount = q2(reversed_amount)
    consumed = q2(q2(validated_total) + q2(write_off_total))
    balance = q2(gross - reversed_amount - consumed)
    accrual_view = q2(gross - reversed_amount)
    recognized = accrual_view if accrual_view > consumed else consumed
    return {
        "gross_accrued_amount": gross,
        "reversed_accrual_amount": reversed_amount,
        "consumed_deduction_amount": consumed,
        "accrued_balance": balance,
        "recognized_spend_amount": q2(recognized),
    }


def promotion_spend(promo):
    pricing = promotion_pricing(promo)
    ledger = promotion_ledger(promo)
    planned = pricing["planned_total_spend"]
    if planned == ZERO:
        return q4(0), "WITHIN_BUDGET"
    ratio = q4(ledger["recognized_spend_amount"] / planned)
    if ratio > OVERSPENT_RATIO:
        status = "OVERSPENT"
    elif ratio >= OVERSPEND_WARNING_RATIO:
        status = "OVERSPEND_WARNING"
    else:
        status = "WITHIN_BUDGET"
    return ratio, status


def promotion_performance_flag(promo):
    analysis = analysis_of_promotion(promo["id"])
    if analysis is None or analysis["roi"] is None:
        return "UNRATED"
    if analysis["roi"] < ROI_FLOOR:
        return "UNDERPERFORMING"
    return "ON_TRACK"


# --------------------------------------------------------------------------
# Dispute aging (PRD 3.9)
# --------------------------------------------------------------------------

def dispute_aging_days(dispute):
    elapsed = (clock_dt() - dispute["opened_at"]).total_seconds()
    return int(elapsed // 86400)


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------

def _d(value):
    return value.isoformat() if value is not None else None


def _i(value):
    from db import fmt_instant
    return fmt_instant(value) if value is not None else None


def _common(row, body, versioned=True):
    body["created_at"] = row["created_at"]
    if versioned:
        body["updated_at"] = row["updated_at"]
        body["version"] = row["version"]
    return body


def program_out(row):
    allocated, unallocated = program_rollup(row)
    return _common(row, {
        "id": row["id"],
        "fiscal_year": row["fiscal_year"],
        "name": row["name"],
        "total_budget_amount": f(row["total_budget_amount"]),
        "accrual_method_default": row["accrual_method_default"],
        "status": row["status"],
        "allocated_amount": f(allocated),
        "unallocated_amount": f(unallocated),
    })


def brand_out(row):
    return _common(row, {
        "id": row["id"],
        "program_id": row["program_id"],
        "name": row["name"],
        "list_price_per_case": f(row["list_price_per_case"]),
        "cogs_per_case": f(row["cogs_per_case"]),
        "baseline_units_per_week": row["baseline_units_per_week"],
        "unit_margin": f(row["unit_margin"]),
    })


def customer_out(row):
    return _common(row, {
        "id": row["id"],
        "program_id": row["program_id"],
        "name": row["name"],
        "channel": row["channel"],
        "deduction_validation_policy": row["deduction_validation_policy"],
        "trading_status": row["trading_status"],
        "audit_status": row["audit_status"],
        "compliance_penalty_points": row["compliance_penalty_points"],
        "credit_hold_reason": row["credit_hold_reason"],
        "open_deduction_amount": f(customer_open_deduction_amount(row)),
        "write_off_ytd_amount": f(customer_write_off_ytd_amount(row)),
    })


def allocation_out(row):
    ledger = allocation_ledger(row)
    return _common(row, {
        "id": row["id"],
        "program_id": row["program_id"],
        "customer_id": row["customer_id"],
        "brand_id": row["brand_id"],
        "event_type": row["event_type"],
        "planned_amount": f(row["planned_amount"]),
        "baseline_units": row["baseline_units"],
        "planned_incremental_units": row["planned_incremental_units"],
        "status": row["status"],
        "posture": allocation_posture(row),
        "overspend_event_count": row["overspend_event_count"],
        "committed_amount": f(ledger["committed_amount"]),
        "accrued_amount": f(ledger["accrued_amount"]),
        "settled_amount": f(ledger["settled_amount"]),
        "available_amount": f(ledger["available_amount"]),
        "committed_units": ledger["committed_units"],
        "unreserved_units": ledger["unreserved_units"],
        "at_risk_amount": f(ledger["at_risk_amount"]),
    })


def promotion_out(row):
    pricing = promotion_pricing(row)
    ledger = promotion_ledger(row)
    ratio, spend_status = promotion_spend(row)
    return _common(row, {
        "id": row["id"],
        "allocation_id": row["allocation_id"],
        "customer_id": row["customer_id"],
        "brand_id": row["brand_id"],
        "name": row["name"],
        "window_start": _d(row["window_start"]),
        "window_end": _d(row["window_end"]),
        "accrual_method": row["accrual_method"],
        "lifecycle_status": row["lifecycle_status"],
        "spend_status": spend_status,
        "performance_flag": promotion_performance_flag(row),
        "revision_round": row["revision_round"],
        "tactic_subtotal_amount": f(pricing["tactic_subtotal_amount"]),
        "allowance_rate": f(pricing["allowance_rate"]),
        "off_invoice_allowance_amount": f(pricing["off_invoice_allowance_amount"]),
        "planned_total_spend": f(pricing["planned_total_spend"]),
        "committed_units": pricing["committed_units"],
        "gross_accrued_amount": f(ledger["gross_accrued_amount"]),
        "reversed_accrual_amount": f(ledger["reversed_accrual_amount"]),
        "consumed_deduction_amount": f(ledger["consumed_deduction_amount"]),
        "recognized_spend_amount": f(ledger["recognized_spend_amount"]),
        "accrued_balance": f(ledger["accrued_balance"]),
        "spend_ratio": f(ratio),
        "approved_by_user_id": row["approved_by_user_id"],
        "commitment_verified": promotion_commitment_verified(row),
    })


def tactic_out(row):
    return _common(row, {
        "id": row["id"],
        "promotion_id": row["promotion_id"],
        "tactic_type": row["tactic_type"],
        "rate_per_case": f(row["rate_per_case"]),
        "fixed_fee": f(row["fixed_fee"]),
        "planned_units": row["planned_units"],
        "window_start": _d(row["window_start"]),
        "window_end": _d(row["window_end"]),
        "week_count": tactic_week_count(row),
        "line_planned_spend": f(tactic_line_planned_spend(row)),
        "status": row["status"],
        "effective_from_period": _d(row["effective_from_period"]),
    })


def document_out(row):
    return _common(row, {
        "id": row["id"],
        "promotion_id": row["promotion_id"],
        "doc_class": row["doc_class"],
        "doc_type": row["doc_type"],
        "covers_tactic_type": row["covers_tactic_type"],
        "units_verified": row["units_verified"],
        "received_at": _i(row["received_at"]),
        "status": row["status"],
        "verified_by_user_id": row["verified_by_user_id"],
    })


def fact_out(row):
    return _common(row, {
        "id": row["id"],
        "customer_id": row["customer_id"],
        "brand_id": row["brand_id"],
        "fact_type": row["fact_type"],
        "period_start": _d(row["period_start"]),
        "units": row["units"],
        "source": row["source"],
    }, versioned=False)


def accrual_out(row):
    return _common(row, {
        "id": row["id"],
        "promotion_id": row["promotion_id"],
        "period_start": _d(row["period_start"]),
        "method": row["method"],
        "fact_units": row["fact_units"],
        "entry_type": row["entry_type"],
        "amount": f(row["amount"]),
        "status": row["status"],
        "reverses_entry_id": row["reverses_entry_id"],
        "reversal_reason": row["reversal_reason"],
        "tactic_line_amounts": [
            {"tactic_id": line["tactic_id"], "amount": f(line["amount"])}
            for line in row["tactic_line_amounts"]
        ],
    })


def deduction_out(row):
    return _common(row, {
        "id": row["id"],
        "customer_id": row["customer_id"],
        "claim_reference": row["claim_reference"],
        "claimed_amount": f(row["claimed_amount"]),
        "deduction_date": _d(row["deduction_date"]),
        "promotion_id": row["promotion_id"],
        "status": row["status"],
        "validation_basis": row["validation_basis"],
        "entitled_amount": f(row["entitled_amount"]),
        "validated_amount": f(row["validated_amount"]),
        "variance_amount": f(row["variance_amount"]),
        "supersedes_deduction_id": row["supersedes_deduction_id"],
        "matched_by_user_id": row["matched_by_user_id"],
        "validated_by_user_id": row["validated_by_user_id"],
        "settled_at": _i(row["settled_at"]),
    })


def dispute_out(row):
    return _common(row, {
        "id": row["id"],
        "deduction_id": row["deduction_id"],
        "reason_code": row["reason_code"],
        "disputed_amount": f(row["disputed_amount"]),
        "opened_at": _i(row["opened_at"]),
        "opened_by_user_id": row["opened_by_user_id"],
        "status": row["status"],
        "round_count": row["round_count"],
        "aging_days": dispute_aging_days(row),
        "retailer_response": row["retailer_response"],
        "recovered_amount": f(row["recovered_amount"]),
        "write_off_amount": f(row["write_off_amount"]),
        "resolved_by_user_id": row["resolved_by_user_id"],
    })


def analysis_out(row):
    return _common(row, {
        "id": row["id"],
        "promotion_id": row["promotion_id"],
        "baseline_method": row["baseline_method"],
        "baseline_weekly_units": f(row["baseline_weekly_units"]),
        "promo_consumption_units": row["promo_consumption_units"],
        "baseline_units": f(row["baseline_units"]),
        "lift_units": f(row["lift_units"]),
        "post_period_units": row["post_period_units"],
        "cannibalization_units": f(row["cannibalization_units"]),
        "net_incremental_units": f(row["net_incremental_units"]),
        "incremental_gross_profit": f(row["incremental_gross_profit"]),
        "net_spend": f(row["net_spend"]),
        "roi": f(row["roi"]),
        "data_status": row["data_status"],
        "computed_at": _i(row["computed_at"]),
    })


def audit_out(row):
    return _common(row, {
        "id": row["id"],
        "customer_id": row["customer_id"],
        "scope_start": _d(row["scope_start"]),
        "scope_end": _d(row["scope_end"]),
        "status": row["status"],
        "auditor_user_id": row["auditor_user_id"],
        "findings_count": row["findings_count"],
        "recovery_claim_amount": f(row["recovery_claim_amount"]),
        "issued_at": _i(row["issued_at"]),
    })

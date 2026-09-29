"""Domain calculations, state machines and cascade chains (PRD 1.3 / 1.4 / 2.9)."""
from decimal import Decimal

from core import (ApiError, dec, iso_instant, months_between, parse_instant,
                  rhu_int, round_half_up, shift_months)
from store import db

# --- normative constants --------------------------------------------------
HOEPA_TIER_BOUNDARY_CENTS = 2486600
LARGE_LOAN_CAP_PCT = Decimal("5.00")
SMALL_LOAN_CAP_PCT = Decimal("8.00")
SMALL_LOAN_FLAT_CAP_CENTS = 124300
VARIANCE_ESCALATION_PCT = Decimal("10.00")
VALIDITY_WINDOW_DAYS = 120
REORDER_BUFFER_DAYS = 30
RETIREMENT_AGE_THRESHOLD = 60
BROKERAGE_HAIRCUT = Decimal("0.90")
CHECKING_HAIRCUT = Decimal("1.00")
RETIREMENT_HAIRCUT_UNDER_AGE = Decimal("0.70")
RETIREMENT_HAIRCUT_AT_AGE = Decimal("1.00")
MARKET_RENT_HAIRCUT = Decimal("0.75")
LEASE_RENT_CAP_MULTIPLE = Decimal("1.20")
HIGHER_PRICED_THRESHOLD_FIRST = Decimal("6.500")
HIGHER_PRICED_THRESHOLD_SECOND = Decimal("8.500")

INCLUDED_FEE_CATEGORIES = ("ORIGINATION_POINTS", "AFFILIATE_TITLE", "PMI_UPFRONT",
                           "PREPAYMENT_PENALTY", "LOAN_LEVEL_PRICE_ADJUSTMENT")

SEVERITY_WEIGHT = {"MINOR": 1, "SIGNIFICANT": 3, "MATERIAL": 6}

DOC_TYPE_FOR_PROGRAM = {
    "BANK_STATEMENT_12MO": "BANK_STATEMENT",
    "BANK_STATEMENT_24MO": "BANK_STATEMENT",
    "ASSET_DEPLETION": "ASSET_DEPLETION",
    "DSCR": "DSCR",
    "PROFIT_AND_LOSS": "PROFIT_AND_LOSS",
}


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def program_of(loan_file):
    return db.find("programs", loan_file["program_id"])


def borrower_of(loan_file):
    return db.find("borrowers", loan_file["borrower_id"])


def review_of(loan_file):
    for row in db.rows("reviews"):
        if row["loan_file_id"] == loan_file["id"]:
            return row
    return None


def worksheets_of(loan_file):
    return [w for w in db.rows("worksheets") if w["loan_file_id"] == loan_file["id"]]


def months_of(worksheet):
    return [m for m in db.rows("statement_months") if m["worksheet_id"] == worksheet["id"]]


def fee_items_of(loan_file):
    return [f for f in db.rows("fee_items") if f["loan_file_id"] == loan_file["id"]]


def orders_of(loan_file):
    return [o for o in db.rows("valuation_orders") if o["loan_file_id"] == loan_file["id"]]


def exceptions_of(loan_file):
    return [e for e in db.rows("exceptions") if e["loan_file_id"] == loan_file["id"]]


def audits_of(loan_file):
    return [a for a in db.rows("audits") if a["loan_file_id"] == loan_file["id"]]


def findings_of(audit):
    return [f for f in db.rows("findings") if f["audit_id"] == audit["id"]]


def credit_events_of(borrower_id):
    return [e for e in db.rows("credit_events") if e["borrower_id"] == borrower_id]


def ensure_review(loan_file, tx):
    row = review_of(loan_file)
    if row is not None:
        return row
    row = db.insert("reviews", {
        "loan_file_id": loan_file["id"],
        "primary_review_status": "PRIMARY_NOT_ORDERED",
        "second_valuation_status": ("SECOND_REQUIRED"
                                    if loan_file.get("second_valuation_required")
                                    else "SECOND_NOT_REQUIRED"),
        "primary_value_cents": None,
        "second_value_cents": None,
        "variance_pct": None,
        "reconciled_value_cents": None,
        "escalation_reason": None,
    })
    tx.watch(row)
    return row


# ---------------------------------------------------------------------------
# calculations.pitia_monthly
# ---------------------------------------------------------------------------
def recompute_payment(loan_file):
    rate = dec(loan_file["note_rate_pct"]) / Decimal(100) / Decimal(12)
    principal = dec(loan_file["loan_amount_cents"])
    if loan_file["amortization_type"] == "INTEREST_ONLY":
        pi = rhu_int(principal * rate)
    else:
        term = int(loan_file["term_months"])
        if rate == 0:
            pi = rhu_int(principal / Decimal(term))
        else:
            denom = Decimal(1) - (Decimal(1) + rate) ** (-term)
            pi = rhu_int(principal * rate / denom)
    pitia = (pi + int(loan_file["monthly_taxes_cents"]) + int(loan_file["monthly_insurance_cents"])
             + int(loan_file.get("monthly_hoa_cents") or 0))
    loan_file["pitia_monthly_cents"] = pitia
    recompute_income_derived(loan_file)


def recompute_income_derived(loan_file):
    borrower = borrower_of(loan_file)
    pitia = int(loan_file["pitia_monthly_cents"])
    assets = int(borrower["verified_liquid_assets_cents"])
    if pitia > 0:
        loan_file["documented_reserves_months"] = round_half_up(dec(assets) / dec(pitia), 2)
    else:
        loan_file["documented_reserves_months"] = round_half_up(Decimal(0), 2)
    income = int(loan_file["qualifying_income_monthly_cents"])
    debts = int(borrower["monthly_debt_obligations_cents"])
    loan_file["residual_income_cents"] = income - debts - pitia
    if income == 0:
        loan_file["dti_pct"] = None
    else:
        loan_file["dti_pct"] = round_half_up(dec(debts + pitia) * Decimal(100) / dec(income), 2)
    if loan_file.get("doc_type") == "DSCR":
        recompute_dscr(loan_file)


# ---------------------------------------------------------------------------
# calculations.dscr_ratio
# ---------------------------------------------------------------------------
def recompute_dscr(loan_file):
    if loan_file.get("doc_type") != "DSCR":
        loan_file["dscr_ratio"] = None
        return
    lease = loan_file.get("lease_rent_cents")
    market = loan_file.get("gross_market_rent_cents")
    if lease is not None and loan_file["occupancy"] == "INVESTMENT":
        capped = rhu_int(dec(market or 0) * LEASE_RENT_CAP_MULTIPLE)
        qualifying_rent = min(int(lease), capped)
    else:
        qualifying_rent = rhu_int(dec(market or 0) * MARKET_RENT_HAIRCUT)
    pitia = int(loan_file["pitia_monthly_cents"])
    if pitia <= 0:
        loan_file["dscr_ratio"] = None
        return
    loan_file["dscr_ratio"] = round_half_up(dec(qualifying_rent) / dec(pitia), 4)


# ---------------------------------------------------------------------------
# calculations.ltv_recompute / appraisal_reconciliation step 1
# ---------------------------------------------------------------------------
def ltv_basis(loan_file):
    review = review_of(loan_file)
    basis = None
    if review is not None and review["reconciled_value_cents"] is not None:
        basis = int(review["reconciled_value_cents"])
    if basis is None:
        basis = int(loan_file["property_value_cents"])
    if loan_file["purpose"] == "PURCHASE" and loan_file.get("purchase_price_cents") is not None:
        basis = min(basis, int(loan_file["purchase_price_cents"]))
    return basis


def compute_ltv_only(loan_file):
    basis = ltv_basis(loan_file)
    if basis <= 0:
        loan_file["ltv_pct"] = None
        return
    loan_file["ltv_pct"] = round_half_up(
        dec(loan_file["loan_amount_cents"]) * Decimal(100) / dec(basis), 2)


def retest_second_valuation(loan_file, tx):
    program = program_of(loan_file)
    ltv = loan_file.get("ltv_pct")
    required = False
    if ltv is not None and dec(ltv) > dec(program["second_valuation_ltv_threshold_pct"]):
        required = True
    if int(loan_file["loan_amount_cents"]) >= int(program["second_valuation_loan_amount_threshold_cents"]):
        required = True
    if loan_file["purpose"] == "CASH_OUT_REFI" and loan_file.get("doc_type") == "BANK_STATEMENT":
        required = True
    loan_file["second_valuation_required"] = required
    review = review_of(loan_file)
    if required and review is not None and review["second_valuation_status"] == "SECOND_NOT_REQUIRED":
        tx.watch(review)
        review["second_valuation_status"] = "SECOND_REQUIRED"
    return required


def recompute_ltv(loan_file, tx):
    compute_ltv_only(loan_file)
    retest_second_valuation(loan_file, tx)


# ---------------------------------------------------------------------------
# calculations.credit_event_seasoning
# ---------------------------------------------------------------------------
def compute_seasoning(loan_file):
    program = program_of(loan_file)
    matrix = program.get("seasoning_matrix") or {}
    clock = db.clock
    candidates = [e for e in credit_events_of(loan_file["borrower_id"]) if e.get("documented_flag")]
    if not candidates:
        loan_file["governing_credit_event_id"] = None
        loan_file["seasoning_months_required"] = 0
        loan_file["seasoning_months_elapsed"] = 0
        loan_file["seasoning_satisfied"] = True
        return

    scored = []
    for event in candidates:
        completion = parse_instant(event["completion_date"])
        required = int(matrix.get(event["event_type"], 0))
        elapsed = months_between(completion, clock)
        scored.append((required - elapsed, -completion.timestamp(), event["created_at"],
                       event["_seq"], event, required, elapsed))
    scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    _, _, _, _, governing, required, elapsed = scored[0]
    loan_file["governing_credit_event_id"] = governing["id"]
    loan_file["seasoning_months_required"] = required
    loan_file["seasoning_months_elapsed"] = elapsed
    loan_file["seasoning_satisfied"] = elapsed >= required


# ---------------------------------------------------------------------------
# calculations.overlay_breach_evaluation
# ---------------------------------------------------------------------------
def metric_value(loan_file, rule_metric):
    borrower = borrower_of(loan_file)
    if rule_metric == "MIN_FICO":
        return dec(borrower["fico_score"])
    if rule_metric == "MAX_LTV_PCT":
        value = loan_file.get("ltv_pct")
        return None if value is None else dec(value)
    if rule_metric == "MIN_DSCR":
        value = loan_file.get("dscr_ratio")
        return None if value is None else dec(value)
    if rule_metric == "MAX_DTI_PCT":
        value = loan_file.get("dti_pct")
        return None if value is None else dec(value)
    if rule_metric == "MIN_RESERVES_MONTHS":
        value = loan_file.get("documented_reserves_months")
        return None if value is None else dec(value)
    if rule_metric == "MIN_SEASONING_MONTHS":
        return dec(loan_file.get("seasoning_months_elapsed") or 0)
    if rule_metric == "MAX_LOAN_AMOUNT_CENTS":
        return dec(loan_file["loan_amount_cents"])
    return None


def applicable_overlays(loan_file):
    program = program_of(loan_file)
    rows = []
    for overlay in db.rows("overlays"):
        if overlay["investor_code"] != loan_file["investor_code"]:
            continue
        applies = overlay.get("applies_to_program_code")
        if applies is not None and applies != program["program_code"]:
            continue
        rows.append(overlay)
    rows.sort(key=lambda o: o["overlay_code"])
    return rows


def overlay_satisfied(overlay, value):
    threshold = dec(overlay["threshold_value"])
    if overlay["comparator"] == "GTE":
        return value >= threshold
    return value <= threshold


def void_stale_exceptions(loan_file, tx):
    voided = False
    for request in exceptions_of(loan_file):
        if request["status"] != "APPROVED":
            continue
        overlay = db.find("overlays", request["overlay_id"])
        if overlay is None:
            continue
        live = metric_value(loan_file, overlay["rule_metric"])
        pinned = request.get("pinned_metric_value")
        if live is None or pinned is None or dec(live) != dec(pinned):
            tx.watch(request)
            request["status"] = "VOIDED"
            request["decision_reason"] = "PINNED_METRIC_CHANGED"
            voided = True
    return voided


def overlay_sweep(loan_file, tx):
    """Rebuild overlay_breach_codes / unresolved_overlay_breach_count.

    Returns True when an APPROVED exception was voided by the pinning rule.
    """
    compute_seasoning(loan_file)
    voided = void_stale_exceptions(loan_file, tx)
    codes = []
    breached_overlay_ids = []
    for overlay in applicable_overlays(loan_file):
        value = metric_value(loan_file, overlay["rule_metric"])
        if value is None:
            continue
        if not overlay_satisfied(overlay, value):
            codes.append(overlay["overlay_code"])
            breached_overlay_ids.append(overlay["id"])
    loan_file["overlay_breach_codes"] = codes
    approved_overlay_ids = set(
        r["overlay_id"] for r in exceptions_of(loan_file) if r["status"] == "APPROVED")
    unresolved = sum(1 for oid in breached_overlay_ids if oid not in approved_overlay_ids)
    loan_file["unresolved_overlay_breach_count"] = unresolved
    return voided


def cascade_suspend(loan_file):
    loan_file["status"] = "SUSPENDED"
    loan_file["atr_documentation_status"] = "INCOMPLETE"
    loan_file["safe_harbor_class"] = "NOT_EVALUATED"
    loan_file["securitization_eligible"] = False


def sweep_and_cascade(loan_file, tx, force_suspend=False, value_moved=False,
                      breach_suspend=False):
    """Run the overlay sweep and, where an edge is declared, the suspend cascade.

    The cascade-only UNDERWRITING -> SUSPENDED edge is declared for three
    sources: the appraisal reconciliation chain (breach_suspend / value_moved),
    an ExceptionRequest reaching DENIED (force_suspend) and an APPROVED
    ExceptionRequest being voided by the pinning rule (detected here).
    """
    before = int(loan_file.get("unresolved_overlay_breach_count") or 0)
    voided = overlay_sweep(loan_file, tx)
    after = int(loan_file["unresolved_overlay_breach_count"])
    if loan_file["status"] == "UNDERWRITING":
        if (force_suspend or voided or value_moved
                or (breach_suspend and before == 0 and after > 0)):
            cascade_suspend(loan_file)
    recompute_eligibility(loan_file)


# ---------------------------------------------------------------------------
# calculations.points_and_fees_test
# ---------------------------------------------------------------------------
def classify_fee(item):
    category = item["fee_category"]
    if category in INCLUDED_FEE_CATEGORIES:
        return "INCLUDED"
    if category == "DISCOUNT_POINTS":
        return "EXCLUDED" if item["bona_fide_discount_flag"] else "INCLUDED"
    if category == "THIRD_PARTY_UNAFFILIATED":
        return "INCLUDED" if item["paid_to_affiliate_flag"] else "EXCLUDED"
    return "EXCLUDED"


def points_and_fees_recompute(loan_file, tx, run_test=False):
    """Steps 1-3 always; steps 4-5 on an explicit run or once a verdict exists."""
    items = fee_items_of(loan_file)
    included = []
    for item in items:
        if item["status"] != "ACTIVE":
            continue
        tx.watch(item)
        item["inclusion_in_test"] = classify_fee(item)
        if item["inclusion_in_test"] == "INCLUDED":
            included.append(item)
    total = sum(int(i["amount_cents"]) for i in included)
    financed_prepaid = sum(int(i["amount_cents"]) for i in included
                           if i["prepaid_finance_charge_flag"])
    loan_file["points_and_fees_total_cents"] = total
    loan_file["total_loan_amount_cents"] = int(loan_file["loan_amount_cents"]) - financed_prepaid

    verdict_changed = False
    if run_test or loan_file["points_and_fees_test_result"] != "NOT_TESTED":
        basis = dec(loan_file["total_loan_amount_cents"])
        if loan_file["total_loan_amount_cents"] >= HOEPA_TIER_BOUNDARY_CENTS:
            cap = rhu_int(basis * LARGE_LOAN_CAP_PCT / Decimal(100))
        else:
            cap = min(rhu_int(basis * SMALL_LOAN_CAP_PCT / Decimal(100)),
                      SMALL_LOAN_FLAT_CAP_CENTS)
        loan_file["points_and_fees_cap_cents"] = cap
        previous = loan_file["points_and_fees_test_result"]
        result = "FAIL" if total > cap else "PASS"
        loan_file["points_and_fees_test_result"] = result
        verdict_changed = previous != result
    if verdict_changed:
        loan_file["atr_documentation_status"] = "INCOMPLETE"
        loan_file["safe_harbor_class"] = "NOT_EVALUATED"
    recompute_eligibility(loan_file)


# ---------------------------------------------------------------------------
# calculations.atr_determination
# ---------------------------------------------------------------------------
def atr_determination(loan_file):
    program = program_of(loan_file)
    spread = round_half_up(dec(loan_file["note_rate_pct"]) - dec(loan_file["apor_pct"]), 3)
    loan_file["rate_spread_pct"] = spread
    if program["atr_exempt_flag"] and loan_file["occupancy"] == "INVESTMENT":
        loan_file["atr_documentation_status"] = "EXEMPT"
        loan_file["safe_harbor_class"] = "EXEMPT_BUSINESS_PURPOSE"
        recompute_eligibility(loan_file)
        return
    has_accepted = any(w["status"] == "ACCEPTED" for w in worksheets_of(loan_file))
    complete = (has_accepted
                and loan_file["dti_pct"] is not None
                and loan_file["documented_reserves_months"] is not None
                and loan_file["residual_income_cents"] is not None)
    loan_file["atr_documentation_status"] = "DOCUMENTED" if complete else "INCOMPLETE"
    threshold = (HIGHER_PRICED_THRESHOLD_FIRST if loan_file["lien_position"] == "FIRST"
                 else HIGHER_PRICED_THRESHOLD_SECOND)
    if loan_file["points_and_fees_test_result"] == "FAIL":
        harbor = "HIGH_COST_PROHIBITED"
    elif not complete:
        harbor = "NOT_EVALUATED"
    elif spread > threshold:
        harbor = "HIGHER_PRICED_NO_PRESUMPTION"
    else:
        harbor = "ATR_DOCUMENTED_NO_SAFE_HARBOR"
    loan_file["safe_harbor_class"] = harbor
    recompute_eligibility(loan_file)


def invalidate_determination(loan_file):
    loan_file["atr_documentation_status"] = "INCOMPLETE"
    loan_file["safe_harbor_class"] = "NOT_EVALUATED"


# ---------------------------------------------------------------------------
# calculations.securitization_eligibility
# ---------------------------------------------------------------------------
def recompute_eligibility(loan_file):
    review = review_of(loan_file)
    eligible = (
        loan_file["status"] in ("APPROVED", "CLOSED")
        and loan_file["points_and_fees_test_result"] == "PASS"
        and loan_file["atr_documentation_status"] in ("DOCUMENTED", "EXEMPT")
        and loan_file["safe_harbor_class"] != "HIGH_COST_PROHIBITED"
        and bool(loan_file["seasoning_satisfied"])
        and int(loan_file["unresolved_overlay_breach_count"]) == 0
        and review is not None
        and review["primary_review_status"] == "PRIMARY_CLEARED"
        and review["second_valuation_status"] in ("SECOND_NOT_REQUIRED", "SECOND_RECONCILED")
        and not loan_file["repurchase_flag"]
        and not any(a["grade"] == "C_MATERIAL" for a in audits_of(loan_file))
    )
    loan_file["securitization_eligible"] = bool(eligible)
    return loan_file["securitization_eligible"]


# ---------------------------------------------------------------------------
# calculations.bank_statement_income / asset_depletion_income /
# profit_and_loss_income  (worksheet calculation)
# ---------------------------------------------------------------------------
def included_months(worksheet):
    rows = [m for m in months_of(worksheet) if m["inclusion_status"] == "INCLUDED"]
    rows.sort(key=lambda m: (m["created_at"], m["_seq"]))
    return rows


def calculate_worksheet(worksheet, loan_file, count=True):
    program = program_of(loan_file)
    borrower = borrower_of(loan_file)
    method = worksheet["method"]

    if method != "BANK_STATEMENT":
        worksheet["eligible_deposit_total_cents"] = 0
        worksheet["net_deposit_total_cents"] = 0
        worksheet["included_month_count"] = 0
        worksheet["expense_factor_pct_applied"] = None
    if method != "ASSET_DEPLETION":
        worksheet["eligible_assets_after_haircut_cents"] = 0
        worksheet["depletable_assets_cents"] = 0

    if method == "BANK_STATEMENT":
        months = included_months(worksheet)
        if not months:
            raise ApiError("ERR_NO_INCLUDED_STATEMENT_MONTHS")
        worksheet["included_month_count"] = len(months)
        eligible_total = sum(int(m["eligible_deposit_cents"]) for m in months)
        worksheet["eligible_deposit_total_cents"] = eligible_total
        divisor = dec(program["statement_period_months"])
        worksheet["gross_monthly_income_cents"] = rhu_int(dec(eligible_total) / divisor)
        if worksheet["expense_factor_source"] == "CPA_LETTER":
            factor = dec(worksheet["cpa_expense_factor_pct"])
            worksheet["variant_applied"] = "CPA_LETTER_FACTOR"
        else:
            factor = dec(program["default_expense_factor_pct"])
            worksheet["variant_applied"] = "PROGRAM_DEFAULT_FACTOR"
        worksheet["expense_factor_pct_applied"] = round_half_up(factor, 2)
        net_total = 0
        for month in months:
            net_total += rhu_int(dec(month["eligible_deposit_cents"])
                                 * (Decimal(100) - factor) / Decimal(100))
        worksheet["net_deposit_total_cents"] = net_total
        pre_ownership = rhu_int(dec(net_total) / divisor)
        worksheet["monthly_qualifying_income_cents"] = rhu_int(
            dec(pre_ownership) * dec(borrower["entity_ownership_pct"]) / Decimal(100))
    elif method == "ASSET_DEPLETION":
        age = int(borrower["age_years"])
        retirement_factor = (RETIREMENT_HAIRCUT_AT_AGE if age >= RETIREMENT_AGE_THRESHOLD
                             else RETIREMENT_HAIRCUT_UNDER_AGE)
        checking = rhu_int(dec(worksheet["asset_bucket_checking_cents"]) * CHECKING_HAIRCUT)
        brokerage = rhu_int(dec(worksheet["asset_bucket_brokerage_cents"]) * BROKERAGE_HAIRCUT)
        retirement = rhu_int(dec(worksheet["asset_bucket_retirement_cents"]) * retirement_factor)
        eligible = checking + brokerage + retirement
        worksheet["eligible_assets_after_haircut_cents"] = eligible
        reserves_required = int(program["min_reserves_months"]) * int(loan_file["pitia_monthly_cents"])
        depletable = max(0, eligible - reserves_required)
        worksheet["depletable_assets_cents"] = depletable
        horizon = dec(program["depletion_horizon_months"])
        gross = rhu_int(dec(depletable) / horizon)
        worksheet["gross_monthly_income_cents"] = gross
        worksheet["monthly_qualifying_income_cents"] = gross
        worksheet["variant_applied"] = "ASSET_DEPLETION_STANDARD"
    elif method == "PROFIT_AND_LOSS":
        period = int(worksheet["p_and_l_period_months"])
        if period != int(program["statement_period_months"]):
            raise ApiError("ERR_INVALID_REQUEST",
                           "p_and_l_period_months must equal the program statement_period_months")
        gross = rhu_int(dec(worksheet["p_and_l_net_income_cents"]) / dec(period))
        worksheet["gross_monthly_income_cents"] = gross
        worksheet["monthly_qualifying_income_cents"] = rhu_int(
            dec(gross) * dec(borrower["entity_ownership_pct"]) / Decimal(100))
        worksheet["variant_applied"] = "PL_NET_INCOME"
    else:  # DSCR
        worksheet["gross_monthly_income_cents"] = 0
        worksheet["monthly_qualifying_income_cents"] = 0
        worksheet["variant_applied"] = "DSCR_NO_BORROWER_INCOME"

    if count:
        worksheet["calculation_count"] = int(worksheet["calculation_count"]) + 1
        worksheet["status"] = "CALCULATED"


# ---------------------------------------------------------------------------
# calculations.appraisal_reconciliation (acceptance branch)
# ---------------------------------------------------------------------------
def accept_valuation(order, loan_file, tx):
    review = ensure_review(loan_file, tx)
    tx.watch(review)
    before = review["reconciled_value_cents"]
    kind = order["valuation_type"]
    if kind == "PRIMARY_APPRAISAL":
        review["primary_value_cents"] = order["appraised_value_cents"]
        if review["second_valuation_status"] == "SECOND_NOT_REQUIRED":
            review["reconciled_value_cents"] = review["primary_value_cents"]
            review["primary_review_status"] = "PRIMARY_CLEARED"
    elif kind == "SECOND_APPRAISAL":
        if review["primary_value_cents"] is None:
            raise ApiError("ERR_VALUATION_ORDER_STATE_INVALID",
                           "the primary appraisal value must be published first")
        review["second_value_cents"] = order["appraised_value_cents"]
        low = min(int(review["primary_value_cents"]), int(review["second_value_cents"]))
        high = max(int(review["primary_value_cents"]), int(review["second_value_cents"]))
        if low > 0:
            variance = round_half_up(dec(high - low) * Decimal(100) / dec(low), 2)
        else:
            variance = round_half_up(Decimal(0), 2)
        review["variance_pct"] = variance
        review["second_valuation_status"] = "SECOND_RECONCILED"
        if variance > VARIANCE_ESCALATION_PCT:
            review["reconciled_value_cents"] = low
            review["primary_review_status"] = "PRIMARY_ESCALATED"
            review["escalation_reason"] = "VARIANCE_ABOVE_TOLERANCE"
        else:
            review["reconciled_value_cents"] = review["primary_value_cents"]
            review["primary_review_status"] = "PRIMARY_CLEARED"

    after = review["reconciled_value_cents"]
    if after != before:
        moved = before is not None and after is not None
        invalidate_determination(loan_file)
        recompute_ltv(loan_file, tx)
        sweep_and_cascade(loan_file, tx, value_moved=moved, breach_suspend=True)
    else:
        recompute_eligibility(loan_file)


# ---------------------------------------------------------------------------
# calculations.audit_grade and the post-close cascades
# ---------------------------------------------------------------------------
def pool_recompute(pool):
    members = [f for f in db.rows("loan_files")
               if f.get("pool_id") == pool["id"] and f["status"] == "CLOSED"]
    aggregate = sum(int(f["loan_amount_cents"]) for f in members)
    pool["member_loan_count"] = len(members)
    pool["aggregate_scheduled_balance_cents"] = aggregate
    if aggregate == 0:
        pool["weighted_avg_coupon_pct"] = round_half_up(Decimal(0), 4)
    else:
        weighted = sum(dec(f["loan_amount_cents"]) * dec(f["note_rate_pct"]) for f in members)
        pool["weighted_avg_coupon_pct"] = round_half_up(weighted / dec(aggregate), 4)


def detach_from_pool(loan_file, tx, rebalancing=True):
    pool = db.find("pools", loan_file.get("pool_id"))
    loan_file["pool_id"] = None
    if pool is None:
        return
    tx.bump(pool)
    if rebalancing and pool["status"] == "OPEN":
        pool["status"] = "REBALANCING"
    pool_recompute(pool)


def cascade_material_defect(loan_file, tx):
    tx.watch(loan_file)
    loan_file["repurchase_flag"] = True
    if loan_file["status"] == "CLOSED":
        loan_file["status"] = "AUDIT_DEFECT"
    if loan_file.get("pool_id") is not None:
        detach_from_pool(loan_file, tx)
    recompute_eligibility(loan_file)


def cascade_audit_cleared(audit, loan_file, tx):
    tx.watch(loan_file)
    other_material = any(a["id"] != audit["id"] and a["grade"] == "C_MATERIAL"
                         for a in audits_of(loan_file))
    if loan_file["status"] == "AUDIT_DEFECT" and not other_material:
        loan_file["status"] = "CLOSED"
        loan_file["repurchase_flag"] = False
    recompute_eligibility(loan_file)


def audit_regrade(audit, tx):
    tx.watch(audit)
    findings = findings_of(audit)
    score = sum(SEVERITY_WEIGHT[f["severity"]] for f in findings
                if f["status"] in ("ISSUED", "REBUTTED", "UPHELD"))
    open_count = sum(1 for f in findings if f["status"] in ("ISSUED", "REBUTTED"))
    audit["defect_score"] = score
    audit["open_finding_count"] = open_count
    if score == 0:
        audit["grade"] = "A_CLEAN"
    elif score <= 5:
        audit["grade"] = "B_MINOR"
    else:
        audit["grade"] = "C_MATERIAL"
    loan_file = db.find("loan_files", audit["loan_file_id"])
    if open_count == 0 and audit["status"] in ("FINDINGS_ISSUED", "MATERIAL_DEFECT"):
        if audit["grade"] in ("A_CLEAN", "B_MINOR"):
            audit["status"] = "CLEARED"
            cascade_audit_cleared(audit, loan_file, tx)
        else:
            audit["status"] = "MATERIAL_DEFECT"
            cascade_material_defect(loan_file, tx)
    elif loan_file is not None:
        tx.watch(loan_file)
        recompute_eligibility(loan_file)


# ---------------------------------------------------------------------------
# temporal helpers (validations priority 24, 25, 26, 27)
# ---------------------------------------------------------------------------
def clock_date():
    return db.clock.date()


def expiry_date_of(order):
    effective = parse_instant(order["effective_date"])
    return (effective + _day_delta(VALIDITY_WINDOW_DAYS)).date()


def _day_delta(days):
    from datetime import timedelta
    return timedelta(days=days)


def supporting_valuation(loan_file):
    """The accepted order whose value underpins reconciled_value_cents."""
    review = review_of(loan_file)
    if review is None or review["reconciled_value_cents"] is None:
        return None
    target = int(review["reconciled_value_cents"])
    accepted = [o for o in orders_of(loan_file)
                if o["status"] == "ACCEPTED" and o.get("appraised_value_cents") is not None]
    accepted.sort(key=lambda o: (o["created_at"], o["_seq"]))
    matches = [o for o in accepted if int(o["appraised_value_cents"]) == target]
    for order in matches:
        if order["valuation_type"] == "PRIMARY_APPRAISAL":
            return order
    if matches:
        return matches[0]
    for order in accepted:
        if order["valuation_type"] == "PRIMARY_APPRAISAL":
            return order
    return None


def valuation_expired(order):
    return clock_date() > expiry_date_of(order)


def reorder_too_soon(loan_file, valuation_type):
    prior = [o for o in orders_of(loan_file)
             if o["valuation_type"] == valuation_type and o["status"] != "REJECTED"]
    if not prior:
        return False
    prior.sort(key=lambda o: (o["created_at"], o["_seq"]))
    latest = prior[-1]
    effective = parse_instant(latest["effective_date"]).date()
    days = abs((clock_date() - effective).days)
    return days <= REORDER_BUFFER_DAYS


def statement_period_in_window(program, start, end):
    if end.date() > clock_date():
        return False
    period_months = program.get("statement_period_months")
    if period_months:
        earliest = shift_months(db.clock, -2 * int(period_months)).date()
        if start.date() < earliest:
            return False
    return True


def statement_period_overlaps(worksheet, start, end):
    for month in months_of(worksheet):
        other_start = parse_instant(month["period_start_date"])
        other_end = parse_instant(month["period_end_date"])
        if start < other_end and other_start < end:
            return True
    return False


def computed_authority_tier(overlay):
    severity_tier = 2 if overlay["severity"] == "MATERIAL" else 1
    return max(int(overlay["required_authority_tier"]), severity_tier)


def review_dimensions(loan_file):
    """The two AppraisalReview dimensions, tolerating a not-yet-created review."""
    review = review_of(loan_file)
    if review is not None:
        return review["primary_review_status"], review["second_valuation_status"]
    second = ("SECOND_REQUIRED" if loan_file.get("second_valuation_required")
              else "SECOND_NOT_REQUIRED")
    return "PRIMARY_NOT_ORDERED", second

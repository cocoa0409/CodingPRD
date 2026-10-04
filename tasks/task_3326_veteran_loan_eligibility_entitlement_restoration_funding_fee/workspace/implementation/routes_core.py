"""Routes: veterans, service periods, COEs, entitlement account, loans,
underwriting decisions, close/payoff, funding fee assessments."""
from decimal import Decimal
from flask import Blueprint, request

import common
from common import envelope_ok, paginate, append_audit, stamp_new, touch, new_id, parse_iso
from db import STORE
import errors as E
import middleware as mw
import services as svc
import validate as V

bp = Blueprint("core", __name__)


def veteran_view(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "full_name": v["full_name"],
        "ssn_last4": v["ssn_last4"],
        "service_category": v["service_category"],
        "character_of_discharge": v["character_of_discharge"],
        "receives_disability_compensation": v["receives_disability_compensation"],
        "is_surviving_spouse": v["is_surviving_spouse"],
        "total_qualifying_service_days": v["total_qualifying_service_days"],
        "has_issued_coe": v["has_issued_coe"],
        "charged_loan_count": v["charged_loan_count"],
    }


def service_period_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "veteran_id": p["veteran_id"],
        "branch": p["branch"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "discharge_character": p["discharge_character"],
        "qualifying_days": p["qualifying_days"],
    }


def coe_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "veteran_id": c["veteran_id"],
        "status": c["status"],
        "entitlement_code": c["entitlement_code"],
        "denial_reason": c["denial_reason"],
        "reconsideration_count": c["reconsideration_count"],
        "issued_at": c["issued_at"],
    }


def account_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "veteran_id": a["veteran_id"],
        "basic_entitlement_cents": a["basic_entitlement_cents"],
        "county_limit_cents": a["county_limit_cents"],
        "total_charged_cents": a["total_charged_cents"],
        "total_restored_cents": a["total_restored_cents"],
        "remaining_base_cents": a["remaining_base_cents"],
        "remaining_with_bonus_cents": a["remaining_with_bonus_cents"],
    }


def loan_view(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "veteran_id": l["veteran_id"],
        "coe_id": l["coe_id"],
        "purpose": l["purpose"],
        "property_region": l["property_region"],
        "purchase_price_cents": l["purchase_price_cents"],
        "down_payment_cents": l["down_payment_cents"],
        "loan_amount_cents": l["loan_amount_cents"],
        "interest_rate_percent": float(l["interest_rate_percent"]),
        "rate_type": l["rate_type"],
        "term_months": l["term_months"],
        "originator_user_id": l["originator_user_id"],
        "underwriting_status": l["underwriting_status"],
        "closing_status": l["closing_status"],
        "loan_use": l["loan_use"],
        "entitlement_charged_cents": l["entitlement_charged_cents"],
        "down_payment_pct": float(l["down_payment_pct"]),
        "closing_date": l["closing_date"],
        "first_payment_due_date": l["first_payment_due_date"],
        "payoff_type": l["payoff_type"],
    }


def fee_view(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "loan_id": f["loan_id"],
        "exempt": f["exempt"],
        "fee_rate": float(f["fee_rate"]),
        "assessed_fee_cents": f["assessed_fee_cents"],
        "collected_cents": f["collected_cents"],
        "refunded_cents": f["refunded_cents"],
        "status": f["status"],
    }


def decision_view(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "loan_id": d["loan_id"],
        "decided_by_user_id": d["decided_by_user_id"],
        "gross_monthly_income_cents": d["gross_monthly_income_cents"],
        "new_housing_payment_cents": d["new_housing_payment_cents"],
        "other_obligations_annual_cents": d["other_obligations_annual_cents"],
        "family_size": d["family_size"],
        "region": d["region"],
        "other_obligations_monthly_cents": d["other_obligations_monthly_cents"],
        "residual_income_cents": d["residual_income_cents"],
        "residual_required_cents": d["residual_required_cents"],
        "dti_percent": float(d["dti_percent"]),
        "dti_only_pass": d["dti_only_pass"],
        "outcome": d["outcome"],
    }


# ---------------------------------------------------------------------------
# Veterans
# ---------------------------------------------------------------------------

@bp.post("/va-loans/veterans")
def create_veteran():
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer", "ProgramAdmin"})
    data = V.body_json()
    full_name = V.as_str(data, "full_name")
    ssn_last4 = V.as_str(data, "ssn_last4")
    if len(ssn_last4) != 4 or not ssn_last4.isdigit():
        raise E.validation("ssn_last4 must be exactly four digits")
    service_category = V.as_enum(data, "service_category", svc.SERVICE_CATEGORIES)
    character_of_discharge = V.as_enum(data, "character_of_discharge", svc.DISCHARGE_CHARS)
    receives_disability_compensation = V.as_bool(data, "receives_disability_compensation")
    is_surviving_spouse = V.as_bool(data, "is_surviving_spouse", required=False, default=False)

    vid = new_id()
    veteran = stamp_new({
        "id": vid,
        "full_name": full_name,
        "ssn_last4": ssn_last4,
        "service_category": service_category,
        "character_of_discharge": character_of_discharge,
        "receives_disability_compensation": receives_disability_compensation,
        "is_surviving_spouse": is_surviving_spouse,
        "total_qualifying_service_days": 0,
        "has_issued_coe": False,
        "charged_loan_count": 0,
    })
    STORE.veterans[vid] = veteran

    acct_id = new_id()
    account = stamp_new({
        "id": acct_id,
        "veteran_id": vid,
        "basic_entitlement_cents": svc.BASIC_ENTITLEMENT_CENTS,
        "county_limit_cents": svc.COUNTY_LIMIT_CENTS,
        "total_charged_cents": 0,
        "total_restored_cents": 0,
        "remaining_base_cents": svc.BASIC_ENTITLEMENT_CENTS,
        "remaining_with_bonus_cents": svc.COUNTY_LIMIT_CENTS // 4,
    })
    STORE.entitlement_accounts[acct_id] = account

    append_audit("Veteran", vid, "create", ctx["role"], ctx["user_id"], "veteran registered")
    return envelope_ok(veteran_view(veteran), "object", 201)


@bp.get("/va-loans/veterans/<vid>")
def get_veteran(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Underwriter", "ProgramAdmin"})
    mw.check_veteran_subtree(ctx, vid)
    veteran = mw.get_veteran_or_404(vid)
    svc.refresh_restoration_flags(vid)
    svc.recompute_veteran_totals(veteran)
    return envelope_ok(veteran_view(veteran), "object", 200)


# ---------------------------------------------------------------------------
# Service periods
# ---------------------------------------------------------------------------

@bp.post("/va-loans/veterans/<vid>/service-periods")
def create_service_period(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    veteran = mw.get_veteran_or_404(vid)
    data = V.body_json()
    branch = V.as_enum(data, "branch", svc.BRANCHES)
    start_date = V.as_str(data, "start_date")
    end_date = V.as_str(data, "end_date")
    discharge_character = V.as_enum(data, "discharge_character", svc.DISCHARGE_CHARS)
    try:
        start_dt = parse_iso(start_date)
        end_dt = parse_iso(end_date)
    except Exception:
        raise E.validation("start_date and end_date must be ISO dates")

    # Closed-interval overlap rejection against this veteran's existing periods.
    for p in STORE.service_periods.values():
        if p["veteran_id"] != vid:
            continue
        ex_start = parse_iso(p["start_date"])
        ex_end = parse_iso(p["end_date"])
        if not (end_dt < ex_start or start_dt > ex_end):
            raise E.service_period_overlap()

    if discharge_character in ("HONORABLE", "GENERAL"):
        qualifying_days = (end_dt.date() - start_dt.date()).days + 1
    else:
        qualifying_days = 0

    pid = new_id()
    period = stamp_new({
        "id": pid,
        "veteran_id": vid,
        "branch": branch,
        "start_date": start_date,
        "end_date": end_date,
        "discharge_character": discharge_character,
        "qualifying_days": qualifying_days,
    })
    STORE.service_periods[pid] = period
    svc.recompute_veteran_totals(veteran)
    touch(veteran)
    append_audit("ServicePeriod", pid, "create", ctx["role"], ctx["user_id"], "service period added")
    return envelope_ok(service_period_view(period), "object", 201)


@bp.get("/va-loans/veterans/<vid>/service-periods")
def list_service_periods(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "ProgramAdmin"})
    mw.check_veteran_subtree(ctx, vid)
    mw.get_veteran_or_404(vid)
    items = [p for p in STORE.service_periods.values() if p["veteran_id"] == vid]
    items.sort(key=lambda p: p["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([service_period_view(p) for p in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# COE requests
# ---------------------------------------------------------------------------

@bp.post("/va-loans/veterans/<vid>/coe-requests")
def create_coe_request(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    mw.get_veteran_or_404(vid)
    data = V.body_json()
    entitlement_code = V.as_enum(data, "entitlement_code", svc.ENTITLEMENT_CODES)
    cid = new_id()
    coe = stamp_new({
        "id": cid,
        "veteran_id": vid,
        "status": "REQUESTED",
        "entitlement_code": entitlement_code,
        "denial_reason": None,
        "reconsideration_count": 0,
        "issued_at": None,
    })
    STORE.coes[cid] = coe
    append_audit("CertificateOfEligibility", cid, "create", ctx["role"], ctx["user_id"], "COE requested")
    return envelope_ok(coe_view(coe), "object", 201)


@bp.get("/va-loans/veterans/<vid>/coe-requests")
def list_coe_requests(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "ProgramAdmin"})
    mw.check_veteran_subtree(ctx, vid)
    mw.get_veteran_or_404(vid)
    items = [c for c in STORE.coes.values() if c["veteran_id"] == vid]
    items.sort(key=lambda c: c["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([coe_view(c) for c in page], "array", 200, pagination)


def _issue_gates(coe):
    """Run the three COE issue gates in order. Returns None or raises."""
    veteran = STORE.veterans[coe["veteran_id"]]
    svc.recompute_veteran_totals(veteran)
    if veteran["character_of_discharge"] not in ("HONORABLE", "GENERAL"):
        raise E.discharge_ineligible()
    if not veteran.get("is_surviving_spouse"):
        minimum = 90 if veteran["service_category"] == "REGULAR_MILITARY" else 180
        if veteran["total_qualifying_service_days"] < minimum:
            raise E.insufficient_service()
    data = V.body_json() if request.is_json and request.get_json(silent=True) else {}
    sp_ids = V.opt_field(data, "service_period_ids", []) or []
    if not isinstance(sp_ids, list):
        raise E.validation("service_period_ids must be an array")
    for sp_id in sp_ids:
        period = STORE.service_periods.get(sp_id)
        if period is None or period["veteran_id"] != coe["veteran_id"]:
            raise E.service_period_mismatch()


@bp.post("/va-loans/coe-requests/<cid>/issue")
def issue_coe(cid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"ProgramAdmin"})
    coe = mw.get_coe_or_404(cid)
    if coe["status"] not in ("REQUESTED", "RECONSIDERATION"):
        raise E.invalid_state()
    _issue_gates(coe)
    coe["status"] = "ISSUED"
    coe["denial_reason"] = None
    coe["issued_at"] = common.clock_now_iso_ms()
    touch(coe)
    veteran = STORE.veterans[coe["veteran_id"]]
    svc.recompute_veteran_totals(veteran)
    touch(veteran)
    append_audit("CertificateOfEligibility", cid, "issue", ctx["role"], ctx["user_id"], "COE issued")
    return envelope_ok(coe_view(coe), "object", 200)


@bp.post("/va-loans/coe-requests/<cid>/deny")
def deny_coe(cid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"ProgramAdmin"})
    coe = mw.get_coe_or_404(cid)
    if coe["status"] not in ("REQUESTED", "RECONSIDERATION"):
        raise E.invalid_state()
    veteran = STORE.veterans[coe["veteran_id"]]
    svc.recompute_veteran_totals(veteran)
    if veteran["character_of_discharge"] not in ("HONORABLE", "GENERAL"):
        coe["denial_reason"] = "DISCHARGE_INELIGIBLE"
    else:
        coe["denial_reason"] = "INSUFFICIENT_SERVICE"
    coe["status"] = "DENIED"
    touch(coe)
    svc.cascade_coe_denied(coe["veteran_id"])
    append_audit("CertificateOfEligibility", cid, "deny", ctx["role"], ctx["user_id"], "COE denied")
    return envelope_ok(coe_view(coe), "object", 200)


@bp.post("/va-loans/coe-requests/<cid>/reconsider")
def reconsider_coe(cid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer", "ProgramAdmin"})
    coe = mw.get_coe_or_404(cid)
    if coe["status"] != "DENIED":
        raise E.invalid_state()
    if coe["reconsideration_count"] >= 2:
        raise E.reconsideration_exhausted()
    coe["status"] = "RECONSIDERATION"
    coe["reconsideration_count"] += 1
    coe["denial_reason"] = None
    touch(coe)
    append_audit("CertificateOfEligibility", cid, "reconsider", ctx["role"], ctx["user_id"], "COE reconsideration opened")
    return envelope_ok(coe_view(coe), "object", 200)


# ---------------------------------------------------------------------------
# Entitlement account
# ---------------------------------------------------------------------------

@bp.get("/va-loans/veterans/<vid>/entitlement-account")
def get_entitlement_account(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Underwriter", "ProgramAdmin"})
    mw.check_veteran_subtree(ctx, vid)
    mw.get_veteran_or_404(vid)
    acct = svc.recompute_entitlement_account(vid)
    items = [acct] if acct else []
    return envelope_ok([account_view(a) for a in items], "array", 200)


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------

@bp.post("/va-loans/veterans/<vid>/loans")
def create_loan(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    veteran = mw.get_veteran_or_404(vid)
    data = V.body_json()
    coe_id = V.as_str(data, "coe_id")
    purpose = V.as_enum(data, "purpose", svc.PURPOSES)
    property_region = V.as_enum(data, "property_region", svc.REGIONS)
    purchase_price_cents = V.as_int(data, "purchase_price_cents")
    down_payment_cents = V.as_int(data, "down_payment_cents")
    interest_rate_percent = V.as_number(data, "interest_rate_percent")
    rate_type = V.as_enum(data, "rate_type", svc.RATE_TYPES)
    term_months = V.as_int(data, "term_months", required=False, default=360)

    coe = STORE.coes.get(coe_id)
    if coe is None:
        raise E.not_found("ERR_COE_NOT_FOUND", "certificate of eligibility id does not resolve")
    if coe["veteran_id"] != vid:
        raise E.service_period_mismatch("coe_id does not belong to the path veteran")
    if coe["status"] != "ISSUED":
        raise E.coe_not_issued()
    if down_payment_cents < 0 or down_payment_cents > purchase_price_cents:
        raise E.invalid_down_payment()

    svc.refresh_restoration_flags(vid)
    svc.recompute_veteran_totals(veteran)
    loan_use = "FIRST_USE" if veteran["charged_loan_count"] == 0 else "SUBSEQUENT_USE"
    loan_amount_cents = purchase_price_cents - down_payment_cents
    dp_pct = svc.compute_down_payment_pct(down_payment_cents, purchase_price_cents)

    lid = new_id()
    loan = stamp_new({
        "id": lid,
        "veteran_id": vid,
        "coe_id": coe_id,
        "purpose": purpose,
        "property_region": property_region,
        "purchase_price_cents": purchase_price_cents,
        "down_payment_cents": down_payment_cents,
        "loan_amount_cents": loan_amount_cents,
        "interest_rate_percent": interest_rate_percent,
        "rate_type": rate_type,
        "term_months": term_months,
        "originator_user_id": ctx["user_id"],
        "underwriting_status": "SUBMITTED",
        "closing_status": "NOT_CLOSED",
        "loan_use": loan_use,
        "entitlement_charged_cents": 0,
        "down_payment_pct": dp_pct,
        "closing_date": None,
        "first_payment_due_date": None,
        "payoff_type": None,
        "_charge_fully_restored": False,
    })
    STORE.loans[lid] = loan

    exempt, fee_rate, assessed = svc.compute_funding_fee(
        veteran, loan_use, purpose, down_payment_cents, purchase_price_cents, loan_amount_cents)
    fid = new_id()
    fee = stamp_new({
        "id": fid,
        "loan_id": lid,
        "exempt": exempt,
        "fee_rate": fee_rate,
        "assessed_fee_cents": assessed,
        "collected_cents": 0,
        "refunded_cents": 0,
        "status": "ASSESSED",
    })
    STORE.funding_fee_assessments[fid] = fee

    append_audit("Loan", lid, "create", ctx["role"], ctx["user_id"], "loan created")
    return envelope_ok(loan_view(loan), "object", 201)


@bp.get("/va-loans/veterans/<vid>/loans")
def list_veteran_loans(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Underwriter", "ProgramAdmin"})
    mw.check_veteran_subtree(ctx, vid)
    mw.get_veteran_or_404(vid)
    items = [l for l in STORE.loans.values() if l["veteran_id"] == vid]
    items.sort(key=lambda l: l["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([loan_view(l) for l in page], "array", 200, pagination)


@bp.get("/va-loans/loans/<lid>")
def get_loan(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Underwriter", "ProgramAdmin"})
    loan = mw.get_loan_or_404(lid)
    mw.check_veteran_subtree(ctx, loan["veteran_id"])
    return envelope_ok(loan_view(loan), "object", 200)


@bp.get("/va-loans/loans")
def list_loans():
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer", "Underwriter", "ProgramAdmin"})
    items = list(STORE.loans.values())
    coe_id = request.args.get("coe_id")
    veteran_id = request.args.get("veteran_id")
    if coe_id:
        items = [l for l in items if l["coe_id"] == coe_id]
    if veteran_id:
        items = [l for l in items if l["veteran_id"] == veteran_id]
    items.sort(key=lambda l: l["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([loan_view(l) for l in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Underwriting decisions
# ---------------------------------------------------------------------------

@bp.post("/va-loans/loans/<lid>/underwriting-decisions")
def create_underwriting_decision(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Underwriter"})
    loan = mw.get_loan_or_404(lid)
    if ctx["user_id"] == loan["originator_user_id"]:
        raise E.underwriter_is_originator()
    data = V.body_json()
    gross_monthly_income_cents = V.as_int(data, "gross_monthly_income_cents")
    new_housing_payment_cents = V.as_int(data, "new_housing_payment_cents")
    other_obligations_annual_cents = V.as_list(data, "other_obligations_annual_cents")
    for item in other_obligations_annual_cents:
        if isinstance(item, bool) or not isinstance(item, int):
            raise E.validation("other_obligations_annual_cents items must be integers")
    family_size = V.as_int(data, "family_size")
    region = V.as_enum(data, "region", svc.REGIONS)

    if loan["underwriting_status"] != "SUBMITTED":
        raise E.invalid_state()

    other_monthly = svc.compute_other_obligations_monthly(other_obligations_annual_cents)
    dti_percent = svc.compute_dti_percent(new_housing_payment_cents, other_monthly, gross_monthly_income_cents)
    residual_income_cents = gross_monthly_income_cents - new_housing_payment_cents - other_monthly
    residual_required = svc.residual_required_cents(region, family_size)
    dti_only_pass = dti_percent <= Decimal("41.00")
    outcome = svc.compute_underwriting_outcome(residual_income_cents, residual_required, dti_percent)

    did = new_id()
    decision = stamp_new({
        "id": did,
        "loan_id": lid,
        "decided_by_user_id": ctx["user_id"],
        "gross_monthly_income_cents": gross_monthly_income_cents,
        "new_housing_payment_cents": new_housing_payment_cents,
        "other_obligations_annual_cents": other_obligations_annual_cents,
        "family_size": family_size,
        "region": region,
        "other_obligations_monthly_cents": other_monthly,
        "residual_income_cents": residual_income_cents,
        "residual_required_cents": residual_required,
        "dti_percent": dti_percent,
        "dti_only_pass": dti_only_pass,
        "outcome": outcome,
    })
    STORE.underwriting_decisions[did] = decision

    loan["underwriting_status"] = outcome
    touch(loan)
    if outcome == "DENIED":
        svc.cascade_loan_denied(loan)
    append_audit("Loan", lid, "underwriting_decision", ctx["role"], ctx["user_id"],
                 f"underwriting decision {outcome}")
    return envelope_ok(decision_view(decision), "object", 201)


@bp.get("/va-loans/loans/<lid>/underwriting-decisions")
def list_underwriting_decisions(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer", "Underwriter", "ProgramAdmin"})
    mw.get_loan_or_404(lid)
    items = [d for d in STORE.underwriting_decisions.values() if d["loan_id"] == lid]
    items.sort(key=lambda d: d["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([decision_view(d) for d in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Close / record payoff
# ---------------------------------------------------------------------------

@bp.post("/va-loans/loans/<lid>/close")
def close_loan(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    loan = mw.get_loan_or_404(lid)
    data = V.body_json() if request.is_json else {}
    closing_date = V.as_str(data, "closing_date")
    first_payment_due_date = V.as_str(data, "first_payment_due_date")
    try:
        closing_dt = parse_iso(closing_date)
    except Exception:
        raise E.validation("closing_date must be an ISO date")

    if loan["underwriting_status"] != "APPROVED":
        raise E.loan_not_closable()
    if loan["closing_status"] != "NOT_CLOSED":
        raise E.invalid_state()
    if svc.loan_has_clearance_blockers(lid):
        raise E.repairs_outstanding()
    if not svc.loan_has_value_issued_appraisal_covering(lid, loan["purchase_price_cents"]):
        raise E.loan_not_closable()

    acct = svc.recompute_entitlement_account(loan["veteran_id"])
    remaining_bonus = acct["remaining_with_bonus_cents"] if acct else 0
    loan_amount = loan["loan_amount_cents"]
    if loan_amount > 4 * remaining_bonus:
        required_down = common.round_half_up_int(Decimal(loan_amount - 4 * remaining_bonus) * Decimal("0.25"))
        if loan["down_payment_cents"] < required_down:
            raise E.insufficient_entitlement()

    # CASCADE B link 1: close the loan.
    loan["closing_status"] = "CLOSED"
    loan["closing_date"] = closing_date
    loan["first_payment_due_date"] = first_payment_due_date

    # CASCADE B link 2: entitlement charge + fee collection.
    charge = min(common.round_half_up_int(Decimal(loan_amount) * Decimal("0.25")), remaining_bonus)
    loan["entitlement_charged_cents"] = charge
    for fee in STORE.funding_fee_assessments.values():
        if fee["loan_id"] == lid and fee["status"] == "ASSESSED":
            fee["collected_cents"] = fee["assessed_fee_cents"]
            fee["status"] = "COLLECTED"
            touch(fee)
    touch(loan)

    # CASCADE B link 3: account absorbs the charge.
    if acct is not None:
        acct["total_charged_cents"] += charge
        svc.recompute_entitlement_account(loan["veteran_id"])
        touch(acct)

    # CASCADE B link 4: veteran recompute + occupancy certificate.
    veteran = STORE.veterans[loan["veteran_id"]]
    svc.recompute_veteran_totals(veteran)
    touch(veteran)

    from datetime import timedelta as _td
    move_in_deadline = closing_dt + _td(days=60)
    oid = new_id()
    cert = stamp_new({
        "id": oid,
        "loan_id": lid,
        "certification_date": closing_date,
        "move_in_deadline": common.iso_ms(move_in_deadline),
        "status": "CERTIFIED",
        "exception_type": "NONE",
    })
    STORE.occupancy_certificates[oid] = cert

    append_audit("Loan", lid, "close", ctx["role"], ctx["user_id"], "loan closed")
    return envelope_ok(loan_view(loan), "object", 200)


@bp.post("/va-loans/loans/<lid>/record-payoff")
def record_payoff(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    loan = mw.get_loan_or_404(lid)
    data = V.body_json()
    payoff_type = V.as_enum(data, "payoff_type", svc.PAYOFF_TYPES)
    if loan["closing_status"] != "CLOSED":
        raise E.invalid_state()
    loan["closing_status"] = "PAID_IN_FULL"
    loan["payoff_type"] = payoff_type
    touch(loan)
    veteran = STORE.veterans[loan["veteran_id"]]
    svc.recompute_veteran_totals(veteran)
    touch(veteran)
    append_audit("Loan", lid, "record_payoff", ctx["role"], ctx["user_id"], "loan payoff recorded")
    return envelope_ok(loan_view(loan), "object", 200)


# ---------------------------------------------------------------------------
# Funding fee assessments
# ---------------------------------------------------------------------------

@bp.get("/va-loans/loans/<lid>/funding-fee-assessments")
def list_funding_fee_assessments(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Underwriter", "ProgramAdmin"})
    loan = mw.get_loan_or_404(lid)
    mw.check_veteran_subtree(ctx, loan["veteran_id"])
    items = [f for f in STORE.funding_fee_assessments.values() if f["loan_id"] == lid]
    items.sort(key=lambda f: f["created_at"])
    return envelope_ok([fee_view(f) for f in items], "array", 200)


@bp.post("/va-loans/funding-fee-assessments/<fid>/refund")
def refund_funding_fee(fid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"ProgramAdmin"})
    fee = mw.get_fee_assessment_or_404(fid)
    data = V.body_json()
    disability_evidence = V.as_bool(data, "disability_evidence")
    if fee["status"] != "COLLECTED":
        raise E.fee_not_refundable()
    if not disability_evidence:
        raise E.validation("disability_evidence must be true for a retroactive exemption refund")
    fee["refunded_cents"] = fee["collected_cents"]
    fee["status"] = "REFUNDED"
    fee["exempt"] = True
    touch(fee)
    append_audit("FundingFeeAssessment", fid, "refund", ctx["role"], ctx["user_id"], "funding fee refunded")
    return envelope_ok(fee_view(fee), "object", 200)

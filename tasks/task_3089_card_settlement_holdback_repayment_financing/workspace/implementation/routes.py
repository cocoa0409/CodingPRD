"""All route handlers for the card-settlement holdback financing API."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from core import (
    DB, ApiError, ALL_ROLES, auth,
    clock_now, clock_set, ts_now, new_common, touch,
    success_object, error_body, parse_pagination, paginate,
    err_not_found, err_invalid_request, get_body,
    req_string, opt_string, req_cents, opt_cents, req_state_code, req_number,
    parse_iso8601, parse_date, round_half_up_int, ratio4,
    recompute_merchant_aggregates, compute_offer_amounts, compute_loan_terms,
    compute_disclosure, SCHEDULED_TERM_DAYS,
)

bp = Blueprint("lending", __name__)

MANDATE_STATES = {"CA", "NY", "UT", "VA"}
HOLDBACK_OPTIONS = {Decimal("0.08"), Decimal("0.10"), Decimal("0.14")}
LOAN_TERMINAL = {"REPAID", "CHARGED_OFF"}


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def get_or_404(table, rid):
    e = table.get(rid)
    if e is None:
        raise err_not_found()
    return e


def refresh_offer_expiry(offer):
    if offer["status"] == "OFFERED" and offer["expires_at"] is not None:
        if clock_now() >= parse_iso8601(offer["expires_at"]):
            offer["status"] = "EXPIRED"
            touch(offer)


def refresh_merchant_offers_expiry(merchant_id):
    for o in DB.offers.values():
        if o["merchant_id"] == merchant_id:
            refresh_offer_expiry(o)


def loan_repaid_cascade(loan):
    """Fire the REPAID cascade (PRD 3.5). Assumes loan.remaining_balance_cents == 0."""
    loan["status"] = "REPAID"
    touch(loan)
    merchant = DB.merchants.get(loan["merchant_id"])
    if merchant is not None:
        merchant["active_loan_id"] = None
        merchant["loans_repaid_count"] += 1
        touch(merchant)
        if merchant["status"] == "ELIGIBLE":
            # auto-create renewal offer in DRAFT with recomputed amounts
            recompute_merchant_aggregates(merchant)
            offer = new_common()
            amounts = compute_offer_amounts(merchant)
            offer.update({
                "merchant_id": merchant["id"],
                "status": "DRAFT",
                "trailing_12m_avg_net_cents": amounts["trailing_12m_avg_net_cents"],
                "seasonality_index_at_generation": amounts["seasonality_index_at_generation"],
                "preapproved_standard_cents": amounts["preapproved_standard_cents"],
                "preapproved_conservative_cents": amounts["preapproved_conservative_cents"],
                "preapproved_cents": amounts["preapproved_cents"],
                "issued_at": None,
                "expires_at": None,
                "accepted_principal_cents": None,
                "accepted_holdback_pct": None,
                "accepted_loan_id": None,
                "renewal_count": 0,
                "generated_by": None,
            })
            DB.offers[offer["id"]] = offer
    # open enforcement actions for this loan -> RELEASED
    for action in list(DB.enforcements.values()):
        if action["loan_id"] == loan["id"] and action["status"] in ("DRAFT", "DEMANDED", "ESCALATED"):
            release_enforcement_action(action)


def release_enforcement_action(action):
    action["status"] = "RELEASED"
    touch(action)
    guarantor = DB.guarantors.get(action["guarantor_id"])
    if guarantor is not None and guarantor["status"] != "RELEASED":
        others_open = any(
            a["id"] != action["id"]
            and a["guarantor_id"] == guarantor["id"]
            and a["status"] in ("DRAFT", "DEMANDED", "ESCALATED")
            for a in DB.enforcements.values()
        )
        if not others_open:
            guarantor["status"] = "RELEASED"
            touch(guarantor)


# ===========================================================================
# Clock
# ===========================================================================

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["PlatformAdmin"])
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str):
        raise err_invalid_request("to_iso8601 is required")
    try:
        dt = parse_iso8601(raw)
    except (ValueError, TypeError):
        raise err_invalid_request("to_iso8601 is not a valid ISO 8601 timestamp")
    clock_set(dt)
    return success_object({}, 200)


# ===========================================================================
# Merchants
# ===========================================================================

@bp.route("/lending/merchants", methods=["POST"])
def create_merchant():
    auth(["PlatformAdmin"])
    body = get_body()
    legal_name = req_string(body, "legal_name")
    state_code = req_state_code(body)
    owner_name = req_string(body, "owner_name")
    psa = body.get("processing_started_at")
    if not isinstance(psa, str):
        raise err_invalid_request("processing_started_at is required")
    try:
        parse_iso8601(psa)
    except (ValueError, TypeError):
        raise err_invalid_request("processing_started_at is not a valid ISO 8601 timestamp")
    m = new_common()
    m.update({
        "legal_name": legal_name,
        "state_code": state_code,
        "owner_name": owner_name,
        "processing_started_at": psa,
        "status": "ONBOARDING",
        "lifetime_net_cents": 0,
        "trailing_12m_months_recorded": 0,
        "seasonality_index": 0.0,
        "trailing_30d_net_cents": 0,
        "prior_30d_net_cents": 0,
        "trailing_30d_chargeback_ratio": 0.0,
        "active_loan_id": None,
        "loans_repaid_count": 0,
    })
    DB.merchants[m["id"]] = m
    return success_object(serialize(m), 201)


@bp.route("/lending/merchants/<merchantId>", methods=["GET"])
def get_merchant(merchantId):
    auth(ALL_ROLES)
    m = get_or_404(DB.merchants, merchantId)
    return success_object(serialize(m), 200)


@bp.route("/lending/merchants", methods=["GET"])
def list_merchants():
    auth(ALL_ROLES)
    limit, offset = parse_pagination()
    status = None
    from flask import request as _req
    status = _req.args.get("status")
    rows = [m for m in DB.merchants.values() if status is None or m["status"] == status]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/merchants/<merchantId>/activate", methods=["POST"])
def activate_merchant(merchantId):
    auth(["PlatformAdmin"])
    m = get_or_404(DB.merchants, merchantId)
    if m["status"] != "ONBOARDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Merchant is not ONBOARDING", 409)
    recompute_merchant_aggregates(m)
    # priority 9 (fiscal) before priority 10 (temporal) per PRD 2.7
    if m["lifetime_net_cents"] < 10000000:
        raise ApiError("ERR_MERCHANT_VOLUME_INSUFFICIENT",
                       "lifetime_net_cents below minimum", 409)
    tenure = clock_now() - parse_iso8601(m["processing_started_at"])
    if tenure < timedelta(days=365):
        raise ApiError("ERR_MERCHANT_TENURE_INSUFFICIENT",
                       "Merchant tenure is less than 365 days", 409)
    m["status"] = "ELIGIBLE"
    touch(m)
    return success_object(serialize(m), 200)


@bp.route("/lending/merchants/<merchantId>/reinstate", methods=["POST"])
def reinstate_merchant(merchantId):
    auth(["PlatformAdmin"])
    m = get_or_404(DB.merchants, merchantId)
    if m["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Merchant is not SUSPENDED", 409)
    m["status"] = "ELIGIBLE"
    touch(m)
    return success_object(serialize(m), 200)


# ===========================================================================
# Processing day batches
# ===========================================================================

@bp.route("/lending/merchants/<merchantId>/processing_batches", methods=["POST"])
def create_batch(merchantId):
    auth(["PlatformAdmin", "ServicerAgent"])
    m = get_or_404(DB.merchants, merchantId)
    body = get_body()
    processing_date = body.get("processing_date")
    if isinstance(processing_date, str):
        # uniqueness check (priority 7) runs before body-shape validation (11)
        for b in DB.batches.values():
            if b["merchant_id"] == m["id"] and b["processing_date"] == processing_date:
                raise ApiError("ERR_DUPLICATE_PROCESSING_DATE",
                               "A batch already exists for this merchant and date", 409)
    if not isinstance(processing_date, str):
        raise err_invalid_request("processing_date is required")
    try:
        parse_date(processing_date)
    except (ValueError, TypeError):
        raise err_invalid_request("processing_date must be YYYY-MM-DD")
    gross = req_cents(body, "gross_cents")
    refunds = opt_cents(body, "refunds_cents", 0)
    chargebacks = opt_cents(body, "chargebacks_cents", 0)
    b = new_common()
    b.update({
        "merchant_id": m["id"],
        "processing_date": processing_date,
        "gross_cents": gross,
        "refunds_cents": refunds,
        "chargebacks_cents": chargebacks,
        "net_settled_cents": gross - refunds - chargebacks,
        "status": "OPEN",
    })
    DB.batches[b["id"]] = b
    return success_object(serialize(b), 201)


@bp.route("/lending/processing_batches/<batchId>/finalize", methods=["POST"])
def finalize_batch(batchId):
    auth(["ServicerAgent"])
    b = get_or_404(DB.batches, batchId)
    if b["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Batch is not OPEN", 409)
    b["status"] = "FINALIZED"
    touch(b)
    m = DB.merchants.get(b["merchant_id"])
    if m is not None:
        recompute_merchant_aggregates(m)
        touch(m)
    return success_object(serialize(b), 200)


@bp.route("/lending/processing_batches/<batchId>", methods=["GET"])
def get_batch(batchId):
    auth(ALL_ROLES)
    b = get_or_404(DB.batches, batchId)
    return success_object(serialize(b), 200)


@bp.route("/lending/merchants/<merchantId>/processing_batches", methods=["GET"])
def list_merchant_batches(merchantId):
    auth(ALL_ROLES)
    m = get_or_404(DB.merchants, merchantId)
    limit, offset = parse_pagination()
    from flask import request as _req
    status = _req.args.get("status")
    rows = [b for b in DB.batches.values()
            if b["merchant_id"] == m["id"] and (status is None or b["status"] == status)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


# ===========================================================================
# Loan offers
# ===========================================================================

@bp.route("/lending/merchants/<merchantId>/offers", methods=["POST"])
def create_offer(merchantId):
    uid, _ = auth(["Underwriter"])
    m = get_or_404(DB.merchants, merchantId)
    # state gates (priority 5)
    if m["status"] == "ONBOARDING":
        raise ApiError("ERR_MERCHANT_NOT_ELIGIBLE", "Merchant is not ELIGIBLE", 409)
    if m["status"] == "SUSPENDED":
        raise ApiError("ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED", 409)
    # fiscal gate (priority 9)
    recompute_merchant_aggregates(m)
    if m["trailing_12m_months_recorded"] < 12:
        raise ApiError("ERR_MERCHANT_VOLUME_INSUFFICIENT",
                       "Fewer than 12 trailing months recorded", 409)
    amounts = compute_offer_amounts(m)
    o = new_common()
    o.update({
        "merchant_id": m["id"],
        "status": "DRAFT",
        "trailing_12m_avg_net_cents": amounts["trailing_12m_avg_net_cents"],
        "seasonality_index_at_generation": amounts["seasonality_index_at_generation"],
        "preapproved_standard_cents": amounts["preapproved_standard_cents"],
        "preapproved_conservative_cents": amounts["preapproved_conservative_cents"],
        "preapproved_cents": amounts["preapproved_cents"],
        "issued_at": None,
        "expires_at": None,
        "accepted_principal_cents": None,
        "accepted_holdback_pct": None,
        "accepted_loan_id": None,
        "renewal_count": 0,
        "generated_by": uid,
    })
    DB.offers[o["id"]] = o
    return success_object(serialize(o), 201)


@bp.route("/lending/offers/<offerId>/issue", methods=["POST"])
def issue_offer(offerId):
    auth(["Underwriter"])
    o = get_or_404(DB.offers, offerId)
    refresh_offer_expiry(o)
    if o["status"] not in ("DRAFT", "REUNDERWRITING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Offer is not DRAFT or REUNDERWRITING", 409)
    for other in DB.offers.values():
        if other["id"] != o["id"] and other["merchant_id"] == o["merchant_id"]:
            refresh_offer_expiry(other)
            if other["status"] == "OFFERED":
                raise ApiError("ERR_OFFER_OVERLAP_ACTIVE",
                               "Another offer for this merchant is OFFERED", 409)
    now = clock_now()
    o["status"] = "OFFERED"
    o["issued_at"] = ts_now()
    exp = now + timedelta(days=30)
    o["expires_at"] = exp.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (exp.microsecond // 1000)
    touch(o)
    return success_object(serialize(o), 200)


@bp.route("/lending/offers/<offerId>/withdraw", methods=["POST"])
def withdraw_offer(offerId):
    auth(["Underwriter"])
    o = get_or_404(DB.offers, offerId)
    refresh_offer_expiry(o)
    if o["status"] not in ("DRAFT", "OFFERED", "EXPIRED", "REUNDERWRITING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Offer cannot be withdrawn from its current state", 409)
    o["status"] = "WITHDRAWN"
    touch(o)
    return success_object(serialize(o), 200)


@bp.route("/lending/offers/<offerId>/renew", methods=["POST"])
def renew_offer(offerId):
    auth(["Underwriter"])
    o = get_or_404(DB.offers, offerId)
    refresh_offer_expiry(o)
    if o["status"] != "EXPIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an EXPIRED offer may be renewed", 409)
    m = DB.merchants.get(o["merchant_id"])
    if m is not None:
        recompute_merchant_aggregates(m)
        amounts = compute_offer_amounts(m)
        o["trailing_12m_avg_net_cents"] = amounts["trailing_12m_avg_net_cents"]
        o["seasonality_index_at_generation"] = amounts["seasonality_index_at_generation"]
        o["preapproved_standard_cents"] = amounts["preapproved_standard_cents"]
        o["preapproved_conservative_cents"] = amounts["preapproved_conservative_cents"]
        o["preapproved_cents"] = amounts["preapproved_cents"]
    o["renewal_count"] += 1
    o["status"] = "REUNDERWRITING"
    touch(o)
    return success_object(serialize(o), 200)


@bp.route("/lending/offers/<offerId>/accept", methods=["POST"])
def accept_offer(offerId):
    uid, _ = auth(["MerchantOwner"])
    o = get_or_404(DB.offers, offerId)
    refresh_offer_expiry(o)
    m = DB.merchants.get(o["merchant_id"])
    body = get_body()

    # OCC (priority 4) — merchant must exist to compare version
    if m is None:
        raise err_not_found()
    emv = body.get("expected_merchant_version")
    if emv is not None and emv != m["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_merchant_version does not match merchant version", 412)

    # state checks (priority 5)
    if o["status"] == "OFFERED" and clock_now() >= parse_iso8601(o["expires_at"]):
        raise ApiError("ERR_OFFER_EXPIRED", "Offer acceptance window has closed", 409)
    if o["status"] == "EXPIRED":
        # Acceptance attempted at or after expires_at: PRD 3.2 names
        # ERR_OFFER_EXPIRED, which pre-empts the generic state error.
        raise ApiError("ERR_OFFER_EXPIRED", "Offer acceptance window has closed", 409)
    if o["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Offer is not OFFERED", 409)
    if m["active_loan_id"] is not None:
        raise ApiError("ERR_MERCHANT_HAS_ACTIVE_LOAN",
                       "Merchant already has a non-terminal loan", 409)

    # uniqueness constraint (priority 7): holdback in offered set
    holdback_raw = body.get("accepted_holdback_pct")
    if holdback_raw is not None:
        try:
            holdback_dec = Decimal(str(holdback_raw))
        except Exception:
            holdback_dec = None
        if holdback_dec is None or holdback_dec not in HOLDBACK_OPTIONS:
            raise ApiError("ERR_HOLDBACK_PCT_NOT_OFFERED",
                           "accepted_holdback_pct not in {0.08, 0.10, 0.14}", 409)

    # fiscal (priority 9): principal within pre-approval
    principal_raw = body.get("selected_principal_cents")
    if isinstance(principal_raw, int) and not isinstance(principal_raw, bool):
        if principal_raw > o["preapproved_cents"]:
            raise ApiError("ERR_OFFER_AMOUNT_EXCEEDS_PREAPPROVED",
                           "selected_principal_cents exceeds preapproved_cents", 409)

    # body shape (priority 11)
    if not isinstance(principal_raw, int) or isinstance(principal_raw, bool) or principal_raw < 0:
        raise err_invalid_request("selected_principal_cents must be a non-negative integer")
    if holdback_raw is None or isinstance(holdback_raw, bool) or not isinstance(holdback_raw, (int, float)):
        raise err_invalid_request("accepted_holdback_pct is required")
    guarantor_full_name = req_string(body, "guarantor_full_name")
    guarantor_email = req_string(body, "guarantor_email")
    guarantee_cap_cents = req_cents(body, "guarantee_cap_cents")
    if emv is None or isinstance(emv, bool) or not isinstance(emv, int):
        raise err_invalid_request("expected_merchant_version is required")

    principal = principal_raw
    holdback = Decimal(str(holdback_raw))
    disclosure_required = m["state_code"] in MANDATE_STATES
    fee_rate, fee_cents, total, minimum = compute_loan_terms(principal)

    loan = new_common()
    loan.update({
        "merchant_id": m["id"],
        "offer_id": o["id"],
        "principal_cents": principal,
        "holdback_pct": float(holdback),
        "fee_rate": float(fee_rate),
        "fee_cents": fee_cents,
        "total_repayment_cents": total,
        "per_period_minimum_cents": minimum,
        "remaining_balance_cents": total,
        "paid_to_date_cents": 0,
        "repayment_period_index": 0,
        "consecutive_missed_periods": 0,
        "carried_surplus_cents": 0,
        "cumulative_shortfall_cents": 0,
        "status": "PENDING_DISCLOSURE" if disclosure_required else "PENDING_ACK",
        "disclosure_required": disclosure_required,
        "activated_at": None,
        "servicing_retained": True,
    })
    DB.loans[loan["id"]] = loan

    guarantor = new_common()
    guarantor.update({
        "loan_id": loan["id"],
        "full_name": guarantor_full_name,
        "email": guarantor_email,
        "guarantee_cap_cents": guarantee_cap_cents,
        "status": "LINKED",
        "acknowledged_at": None,
    })
    DB.guarantors[guarantor["id"]] = guarantor

    apr = compute_disclosure(m, fee_rate, holdback, total)
    disclosure = new_common()
    disclosure.update({
        "loan_id": loan["id"],
        "status": "GENERATED",
        "mandate_state": disclosure_required,
        "apr_scheduled": apr["apr_scheduled"],
        "apr_projected": apr["apr_projected"],
        "disclosed_apr_basis": "PROJECTED" if disclosure_required else "SCHEDULED",
        "estimated_term_days": apr["projected_term_days"] if disclosure_required else SCHEDULED_TERM_DAYS,
        "delivered_at": None,
        "acknowledged_at": None,
        "cooling_required": disclosure_required,
    })
    DB.disclosures[disclosure["id"]] = disclosure

    o["status"] = "ACCEPTED"
    o["accepted_principal_cents"] = principal
    o["accepted_holdback_pct"] = float(holdback)
    o["accepted_loan_id"] = loan["id"]
    touch(o)

    m["active_loan_id"] = loan["id"]
    touch(m)

    return success_object(serialize(o), 200)


@bp.route("/lending/offers/<offerId>", methods=["GET"])
def get_offer(offerId):
    auth(ALL_ROLES)
    o = get_or_404(DB.offers, offerId)
    refresh_offer_expiry(o)
    return success_object(serialize(o), 200)


@bp.route("/lending/merchants/<merchantId>/offers", methods=["GET"])
def list_merchant_offers(merchantId):
    auth(ALL_ROLES)
    m = get_or_404(DB.merchants, merchantId)
    limit, offset = parse_pagination()
    from flask import request as _req
    status = _req.args.get("status")
    rows = []
    for o in DB.offers.values():
        if o["merchant_id"] != m["id"]:
            continue
        refresh_offer_expiry(o)
        if status is None or o["status"] == status:
            rows.append(o)
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


# ===========================================================================
# Loans
# ===========================================================================

@bp.route("/lending/loans/<loanId>", methods=["GET"])
def get_loan(loanId):
    auth(ALL_ROLES)
    loan = get_or_404(DB.loans, loanId)
    return success_object(serialize(loan), 200)


@bp.route("/lending/loans", methods=["GET"])
def list_loans():
    auth(ALL_ROLES)
    limit, offset = parse_pagination()
    from flask import request as _req
    merchant_id = _req.args.get("merchant_id")
    offer_id = _req.args.get("offer_id")
    status = _req.args.get("status")
    rows = [l for l in DB.loans.values()
            if (merchant_id is None or l["merchant_id"] == merchant_id)
            and (offer_id is None or l["offer_id"] == offer_id)
            and (status is None or l["status"] == status)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/merchants/<merchantId>/loans", methods=["GET"])
def list_merchant_loans(merchantId):
    auth(ALL_ROLES)
    m = get_or_404(DB.merchants, merchantId)
    limit, offset = parse_pagination()
    from flask import request as _req
    status = _req.args.get("status")
    rows = [l for l in DB.loans.values()
            if l["merchant_id"] == m["id"] and (status is None or l["status"] == status)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/loans/<loanId>/activate", methods=["POST"])
def activate_loan(loanId):
    auth(["ServicerAgent"])
    loan = get_or_404(DB.loans, loanId)
    if loan["status"] not in ("PENDING_DISCLOSURE", "PENDING_ACK"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Loan is not pending activation", 409)
    disclosure = next((d for d in DB.disclosures.values() if d["loan_id"] == loan["id"]), None)
    guarantor = next((g for g in DB.guarantors.values() if g["loan_id"] == loan["id"]), None)
    # disclosure gate (priority 6) before referential guarantor gate (priority 8)
    if loan["status"] == "PENDING_DISCLOSURE":
        if disclosure is None or disclosure["status"] != "ACKNOWLEDGED":
            raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED",
                           "Disclosure statement is not ACKNOWLEDGED", 409)
    else:
        if disclosure is None or disclosure["status"] not in ("DELIVERED", "ACKNOWLEDGED"):
            raise ApiError("ERR_DISCLOSURE_NOT_DELIVERED",
                           "Disclosure statement is not DELIVERED", 409)
    if guarantor is None or guarantor["status"] != "ACTIVE":
        raise ApiError("ERR_GUARANTOR_NOT_ACTIVE", "Guarantor is not ACTIVE", 409)
    loan["status"] = "ACTIVE"
    loan["activated_at"] = ts_now()
    loan["repayment_period_index"] = 0
    touch(loan)
    return success_object(serialize(loan), 200)


@bp.route("/lending/loans/<loanId>/charge_off", methods=["POST"])
def charge_off_loan(loanId):
    auth(["PlatformAdmin"])
    loan = get_or_404(DB.loans, loanId)
    if loan["status"] != "DEFAULTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Loan is not DEFAULTED", 409)
    loan["status"] = "CHARGED_OFF"
    touch(loan)
    m = DB.merchants.get(loan["merchant_id"])
    if m is not None:
        m["active_loan_id"] = None
        touch(m)
    for action in list(DB.enforcements.values()):
        if action["loan_id"] == loan["id"] and action["status"] in ("DRAFT", "DEMANDED", "ESCALATED"):
            release_enforcement_action(action)
    return success_object(serialize(loan), 200)


@bp.route("/lending/loans/<loanId>/evaluate_period", methods=["POST"])
def evaluate_period(loanId):
    auth(["ServicerAgent"])
    loan = get_or_404(DB.loans, loanId)
    if loan["status"] in LOAN_TERMINAL:
        raise ApiError("ERR_LOAN_ALREADY_TERMINAL", "Loan is terminal", 409)
    if loan["status"] not in ("ACTIVE", "DELINQUENT"):
        raise ApiError("ERR_LOAN_NOT_ACTIVE", "Loan is not ACTIVE or DELINQUENT", 409)
    activated = parse_iso8601(loan["activated_at"])
    p = loan["repayment_period_index"]
    period_end = activated + timedelta(days=60 * (p + 1))
    if clock_now() < period_end:
        raise ApiError("ERR_PERIOD_NOT_ELAPSED",
                       "Current 60-day repayment period has not fully elapsed", 409)
    period_start = activated + timedelta(days=60 * p)
    start_date = period_start.date()
    end_date = period_end.date()

    paid_sweeps = 0
    for s in DB.sweeps.values():
        if s["loan_id"] == loan["id"] and s["status"] == "APPLIED":
            d = parse_date(s["swept_date"])
            if start_date <= d < end_date:
                paid_sweeps += s["holdback_cents"]
    paid_catchups = 0
    for c in DB.catchups.values():
        if c["loan_id"] == loan["id"] and c["status"] == "APPLIED" \
                and c["period_index_credited"] == p:
            paid_catchups += c["amount_cents"] - c["_shortfall_applied"]

    effective_paid = paid_sweeps + paid_catchups + loan["carried_surplus_cents"]
    minimum = loan["per_period_minimum_cents"]

    if effective_paid >= minimum:
        loan["carried_surplus_cents"] = effective_paid - minimum
        loan["consecutive_missed_periods"] = 0
        if loan["status"] == "DELINQUENT" and loan["cumulative_shortfall_cents"] == 0:
            loan["status"] = "ACTIVE"
    else:
        loan["consecutive_missed_periods"] += 1
        loan["cumulative_shortfall_cents"] += (minimum - effective_paid)
        loan["carried_surplus_cents"] = 0
        if loan["consecutive_missed_periods"] >= 4:
            loan["status"] = "DEFAULTED"
        elif loan["consecutive_missed_periods"] >= 2 and loan["status"] == "ACTIVE":
            loan["status"] = "DELINQUENT"
    loan["repayment_period_index"] = p + 1
    touch(loan)

    if loan["status"] == "DELINQUENT":
        m = DB.merchants.get(loan["merchant_id"])
        if m is not None and m["status"] == "ELIGIBLE":
            m["status"] = "SUSPENDED"
            touch(m)
    if loan["status"] == "DEFAULTED":
        m = DB.merchants.get(loan["merchant_id"])
        if m is not None and m["status"] == "ELIGIBLE":
            m["status"] = "SUSPENDED"
            touch(m)
        guarantor = next((g for g in DB.guarantors.values() if g["loan_id"] == loan["id"]), None)
        if guarantor is not None:
            action = new_common()
            action.update({
                "loan_id": loan["id"],
                "guarantor_id": guarantor["id"],
                "status": "DRAFT",
                "demanded_at": None,
                "window_end": None,
                "draw_amount_cents": None,
            })
            DB.enforcements[action["id"]] = action
    return success_object(serialize(loan), 200)


# ===========================================================================
# Guarantors
# ===========================================================================

@bp.route("/lending/guarantors/<guarantorId>", methods=["GET"])
def get_guarantor(guarantorId):
    auth(ALL_ROLES)
    g = get_or_404(DB.guarantors, guarantorId)
    return success_object(serialize(g), 200)


@bp.route("/lending/loans/<loanId>/guarantors", methods=["GET"])
def list_loan_guarantors(loanId):
    auth(ALL_ROLES)
    loan = get_or_404(DB.loans, loanId)
    limit, offset = parse_pagination()
    rows = [g for g in DB.guarantors.values() if g["loan_id"] == loan["id"]]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/guarantors/<guarantorId>/acknowledge", methods=["POST"])
def acknowledge_guarantor(guarantorId):
    uid, _ = auth(["GuarantorPrincipal"])
    g = get_or_404(DB.guarantors, guarantorId)
    if g["status"] != "LINKED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Guarantor is not LINKED", 409)
    if uid != g["id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "X-User-ID must equal the guarantor id", 403)
    g["status"] = "ACTIVE"
    g["acknowledged_at"] = ts_now()
    touch(g)
    return success_object(serialize(g), 200)


# ===========================================================================
# Disclosures
# ===========================================================================

@bp.route("/lending/disclosures/<disclosureId>", methods=["GET"])
def get_disclosure(disclosureId):
    auth(ALL_ROLES)
    d = get_or_404(DB.disclosures, disclosureId)
    return success_object(serialize(d), 200)


@bp.route("/lending/loans/<loanId>/disclosures", methods=["GET"])
def list_loan_disclosures(loanId):
    auth(ALL_ROLES)
    loan = get_or_404(DB.loans, loanId)
    limit, offset = parse_pagination()
    rows = [d for d in DB.disclosures.values() if d["loan_id"] == loan["id"]]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/disclosures/<disclosureId>/deliver", methods=["POST"])
def deliver_disclosure(disclosureId):
    auth(["ServicerAgent"])
    d = get_or_404(DB.disclosures, disclosureId)
    if d["status"] != "GENERATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Disclosure is not GENERATED", 409)
    d["status"] = "DELIVERED"
    d["delivered_at"] = ts_now()
    touch(d)
    return success_object(serialize(d), 200)


@bp.route("/lending/disclosures/<disclosureId>/acknowledge", methods=["POST"])
def acknowledge_disclosure(disclosureId):
    uid, _ = auth(["MerchantOwner"])
    d = get_or_404(DB.disclosures, disclosureId)
    if d["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Disclosure is not DELIVERED", 409)
    loan = DB.loans.get(d["loan_id"])
    if loan is not None and uid != loan["merchant_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "X-User-ID must equal the loan's merchant id", 403)
    if d["cooling_required"]:
        delivered = parse_iso8601(d["delivered_at"])
        if clock_now() < delivered + timedelta(hours=24):
            raise ApiError("ERR_DISCLOSURE_COOLING_NOT_ELAPSED",
                           "24-hour cooling period has not elapsed", 409)
    d["status"] = "ACKNOWLEDGED"
    d["acknowledged_at"] = ts_now()
    touch(d)
    return success_object(serialize(d), 200)


# ===========================================================================
# Settlement sweeps
# ===========================================================================

@bp.route("/lending/loans/<loanId>/sweeps", methods=["POST"])
def create_sweep(loanId):
    auth(["ServicerAgent"])
    loan = get_or_404(DB.loans, loanId)
    body = get_body()

    # OCC (priority 4)
    elv = body.get("expected_loan_version")
    if elv is not None and elv != loan["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_loan_version does not match loan version", 412)

    # loan state gate (priority 5)
    if loan["status"] in LOAN_TERMINAL:
        raise ApiError("ERR_LOAN_ALREADY_TERMINAL", "Loan is terminal", 409)
    if loan["status"] not in ("ACTIVE", "DELINQUENT"):
        raise ApiError("ERR_LOAN_NOT_ACTIVE", "Loan is not ACTIVE or DELINQUENT", 409)

    # resolve batch (existence of body-referenced resource)
    batch_id = body.get("batch_id")
    if not isinstance(batch_id, str):
        raise err_invalid_request("batch_id is required")
    batch = DB.batches.get(batch_id)
    if batch is None:
        raise err_not_found()

    # batch ownership: must belong to the loan's merchant
    if batch["merchant_id"] != loan["merchant_id"]:
        raise ApiError("ERR_BATCH_NOT_FINALIZED",
                       "Batch does not belong to the loan's merchant", 409)

    # already-swept vs not-finalized (priority 5)
    if batch["status"] == "SWEPT":
        raise ApiError("ERR_BATCH_ALREADY_SWEPT", "Batch already swept", 409)
    if batch["status"] != "FINALIZED":
        raise ApiError("ERR_BATCH_NOT_FINALIZED", "Batch is not FINALIZED", 409)

    if elv is None or isinstance(elv, bool) or not isinstance(elv, int):
        raise err_invalid_request("expected_loan_version is required")

    # holdback: round per day, then clip (PRD 3.4)
    raw = Decimal(batch["net_settled_cents"]) * Decimal(str(loan["holdback_pct"]))
    daily = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    remaining = loan["remaining_balance_cents"]
    clipped = daily > remaining
    holdback = min(daily, remaining)

    sweep = new_common()
    sweep.update({
        "loan_id": loan["id"],
        "batch_id": batch["id"],
        "holdback_cents": holdback,
        "clipped": clipped,
        "swept_date": batch["processing_date"],
        "status": "APPLIED",
        "reversed_at": None,
    })
    DB.sweeps[sweep["id"]] = sweep

    batch["status"] = "SWEPT"
    touch(batch)

    loan["remaining_balance_cents"] -= holdback
    loan["paid_to_date_cents"] += holdback
    touch(loan)

    if loan["remaining_balance_cents"] == 0:
        loan_repaid_cascade(loan)

    return success_object(serialize(sweep), 201)


@bp.route("/lending/sweeps/<sweepId>", methods=["GET"])
def get_sweep(sweepId):
    auth(ALL_ROLES)
    s = get_or_404(DB.sweeps, sweepId)
    return success_object(serialize(s), 200)


@bp.route("/lending/loans/<loanId>/sweeps", methods=["GET"])
def list_loan_sweeps(loanId):
    auth(ALL_ROLES)
    loan = get_or_404(DB.loans, loanId)
    limit, offset = parse_pagination()
    from flask import request as _req
    status = _req.args.get("status")
    rows = [s for s in DB.sweeps.values()
            if s["loan_id"] == loan["id"] and (status is None or s["status"] == status)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/sweeps", methods=["GET"])
def list_sweeps():
    auth(ALL_ROLES)
    limit, offset = parse_pagination()
    from flask import request as _req
    loan_id = _req.args.get("loan_id")
    batch_id = _req.args.get("batch_id")
    rows = [s for s in DB.sweeps.values()
            if (loan_id is None or s["loan_id"] == loan_id)
            and (batch_id is None or s["batch_id"] == batch_id)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/sweeps/<sweepId>/reverse", methods=["POST"])
def reverse_sweep(sweepId):
    auth(["ServicerAgent"])
    s = get_or_404(DB.sweeps, sweepId)
    loan = DB.loans.get(s["loan_id"])
    if loan is not None and loan["status"] in LOAN_TERMINAL:
        raise ApiError("ERR_LOAN_ALREADY_TERMINAL", "Loan is terminal", 409)
    if s["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Sweep is not APPLIED", 409)
    if loan is not None and loan["status"] not in ("ACTIVE", "DELINQUENT"):
        raise ApiError("ERR_LOAN_NOT_ACTIVE", "Loan is not ACTIVE or DELINQUENT", 409)
    s["status"] = "REVERSED"
    s["reversed_at"] = ts_now()
    touch(s)
    if loan is not None:
        loan["remaining_balance_cents"] += s["holdback_cents"]
        loan["paid_to_date_cents"] -= s["holdback_cents"]
        touch(loan)
    batch = DB.batches.get(s["batch_id"])
    if batch is not None and batch["status"] == "SWEPT":
        batch["status"] = "FINALIZED"
        touch(batch)
    return success_object(serialize(s), 200)


# ===========================================================================
# Catch-up payments
# ===========================================================================

@bp.route("/lending/loans/<loanId>/catch_up_payments", methods=["POST"])
def create_catchup(loanId):
    uid, _ = auth(["MerchantOwner"])
    loan = get_or_404(DB.loans, loanId)
    if uid != loan["merchant_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "X-User-ID must equal the loan's merchant id", 403)
    body = get_body()
    amount = req_cents(body, "amount_cents")
    c = new_common()
    c.update({
        "loan_id": loan["id"],
        "amount_cents": amount,
        "period_index_credited": None,
        "status": "INITIATED",
        "_shortfall_applied": 0,
    })
    DB.catchups[c["id"]] = c
    return success_object(serialize(c), 201)


@bp.route("/lending/catch_up_payments/<paymentId>/settle", methods=["POST"])
def settle_catchup(paymentId):
    auth(["ServicerAgent"])
    c = get_or_404(DB.catchups, paymentId)
    loan = DB.loans.get(c["loan_id"])
    if c["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Catch-up payment is not INITIATED", 409)
    if loan is not None and loan["status"] in LOAN_TERMINAL:
        raise ApiError("ERR_LOAN_ALREADY_TERMINAL", "Loan is terminal", 409)
    if loan is not None and loan["status"] not in ("ACTIVE", "DELINQUENT", "DEFAULTED"):
        raise ApiError("ERR_LOAN_ALREADY_TERMINAL",
                       "Loan is not ACTIVE, DELINQUENT, or DEFAULTED", 409)
    if loan is not None and c["amount_cents"] > loan["remaining_balance_cents"]:
        raise ApiError("ERR_CATCHUP_EXCEEDS_OUTSTANDING",
                       "Catch-up amount exceeds remaining balance", 409)
    if loan is not None:
        # shortfall-first application
        shortfall_applied = min(c["amount_cents"], loan["cumulative_shortfall_cents"])
        c["_shortfall_applied"] = shortfall_applied
        loan["cumulative_shortfall_cents"] -= shortfall_applied
        c["period_index_credited"] = loan["repayment_period_index"]
        loan["remaining_balance_cents"] -= c["amount_cents"]
        loan["paid_to_date_cents"] += c["amount_cents"]
        touch(loan)
    c["status"] = "APPLIED"
    touch(c)
    if loan is not None and loan["remaining_balance_cents"] == 0:
        loan_repaid_cascade(loan)
    return success_object(serialize(c), 200)


@bp.route("/lending/catch_up_payments/<paymentId>/fail", methods=["POST"])
def fail_catchup(paymentId):
    auth(["ServicerAgent"])
    c = get_or_404(DB.catchups, paymentId)
    if c["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Catch-up payment is not INITIATED", 409)
    c["status"] = "FAILED"
    touch(c)
    return success_object(serialize(c), 200)


@bp.route("/lending/catch_up_payments/<paymentId>/reverse", methods=["POST"])
def reverse_catchup(paymentId):
    auth(["ServicerAgent"])
    c = get_or_404(DB.catchups, paymentId)
    loan = DB.loans.get(c["loan_id"])
    if loan is not None and loan["status"] in LOAN_TERMINAL:
        raise ApiError("ERR_LOAN_ALREADY_TERMINAL", "Loan is terminal", 409)
    if c["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Catch-up payment is not APPLIED", 409)
    c["status"] = "REVERSED"
    touch(c)
    if loan is not None:
        loan["remaining_balance_cents"] += c["amount_cents"]
        loan["paid_to_date_cents"] -= c["amount_cents"]
        # unwind shortfall-first attribution
        loan["cumulative_shortfall_cents"] += c["_shortfall_applied"]
        c["_shortfall_applied"] = 0
        touch(loan)
    return success_object(serialize(c), 200)


@bp.route("/lending/catch_up_payments/<paymentId>", methods=["GET"])
def get_catchup(paymentId):
    auth(ALL_ROLES)
    c = get_or_404(DB.catchups, paymentId)
    return success_object(serialize(c), 200)


@bp.route("/lending/loans/<loanId>/catch_up_payments", methods=["GET"])
def list_loan_catchups(loanId):
    auth(ALL_ROLES)
    loan = get_or_404(DB.loans, loanId)
    limit, offset = parse_pagination()
    from flask import request as _req
    status = _req.args.get("status")
    rows = [c for c in DB.catchups.values()
            if c["loan_id"] == loan["id"] and (status is None or c["status"] == status)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


# ===========================================================================
# Enforcement actions
# ===========================================================================

@bp.route("/lending/enforcement_actions/<actionId>/demand", methods=["POST"])
def demand_enforcement(actionId):
    auth(["ServicerAgent"])
    a = get_or_404(DB.enforcements, actionId)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Enforcement action is not DRAFT", 409)
    guarantor = DB.guarantors.get(a["guarantor_id"])
    g_email = guarantor["email"] if guarantor is not None else None
    now = clock_now()
    for other in DB.enforcements.values():
        if other["id"] == a["id"] or other["status"] not in ("DEMANDED", "ESCALATED"):
            continue
        og = DB.guarantors.get(other["guarantor_id"])
        if og is None or og["email"] != g_email:
            continue
        if other["demanded_at"] is not None and other["window_end"] is not None:
            if parse_iso8601(other["demanded_at"]) <= now <= parse_iso8601(other["window_end"]):
                raise ApiError("ERR_ENFORCEMENT_WINDOW_OPEN",
                               "Another open demand exists for this guarantor", 409)
    a["status"] = "DEMANDED"
    a["demanded_at"] = ts_now()
    end = now + timedelta(days=30)
    a["window_end"] = end.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (end.microsecond // 1000)
    touch(a)
    return success_object(serialize(a), 200)


@bp.route("/lending/enforcement_actions/<actionId>/escalate", methods=["POST"])
def escalate_enforcement(actionId):
    auth(["ServicerAgent"])
    a = get_or_404(DB.enforcements, actionId)
    if a["status"] != "DEMANDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Enforcement action is not DEMANDED", 409)
    if clock_now() < parse_iso8601(a["window_end"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Demand window has not yet closed", 409)
    a["status"] = "ESCALATED"
    touch(a)
    return success_object(serialize(a), 200)


@bp.route("/lending/enforcement_actions/<actionId>/draw", methods=["POST"])
def draw_enforcement(actionId):
    auth(["ServicerAgent"])
    a = get_or_404(DB.enforcements, actionId)
    if a["status"] != "ESCALATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Enforcement action is not ESCALATED", 409)
    loan = DB.loans.get(a["loan_id"])
    if loan is None or loan["status"] != "DEFAULTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Loan is not DEFAULTED", 409)
    guarantor = DB.guarantors.get(a["guarantor_id"])
    cap = guarantor["guarantee_cap_cents"] if guarantor is not None else 0
    draw = min(loan["remaining_balance_cents"], cap)
    a["status"] = "DRAWN"
    a["draw_amount_cents"] = draw
    touch(a)
    loan["remaining_balance_cents"] -= draw
    loan["paid_to_date_cents"] += draw
    touch(loan)
    if guarantor is not None and guarantor["status"] == "ACTIVE":
        guarantor["status"] = "ENFORCED"
        touch(guarantor)
    if loan["remaining_balance_cents"] == 0:
        loan_repaid_cascade(loan)
    return success_object(serialize(a), 200)


@bp.route("/lending/enforcement_actions/<actionId>/release", methods=["POST"])
def release_enforcement(actionId):
    auth(["ServicerAgent"])
    a = get_or_404(DB.enforcements, actionId)
    if a["status"] not in ("DRAFT", "DEMANDED", "ESCALATED", "DRAWN"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Enforcement action cannot be released from its current state", 409)
    loan = DB.loans.get(a["loan_id"])
    if loan is None or loan["status"] not in LOAN_TERMINAL:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Loan is not terminal", 409)
    release_enforcement_action(a)
    return success_object(serialize(a), 200)


@bp.route("/lending/enforcement_actions/<actionId>", methods=["GET"])
def get_enforcement(actionId):
    auth(ALL_ROLES)
    a = get_or_404(DB.enforcements, actionId)
    return success_object(serialize(a), 200)


@bp.route("/lending/loans/<loanId>/enforcement_actions", methods=["GET"])
def list_loan_enforcements(loanId):
    auth(ALL_ROLES)
    loan = get_or_404(DB.loans, loanId)
    limit, offset = parse_pagination()
    from flask import request as _req
    status = _req.args.get("status")
    rows = [a for a in DB.enforcements.values()
            if a["loan_id"] == loan["id"] and (status is None or a["status"] == status)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/enforcement_actions", methods=["GET"])
def list_enforcements():
    auth(ALL_ROLES)
    limit, offset = parse_pagination()
    from flask import request as _req
    loan_id = _req.args.get("loan_id")
    guarantor_id = _req.args.get("guarantor_id")
    rows = [a for a in DB.enforcements.values()
            if (loan_id is None or a["loan_id"] == loan_id)
            and (guarantor_id is None or a["guarantor_id"] == guarantor_id)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


# ===========================================================================
# Migration signals
# ===========================================================================

MIGRATION_DROP_THRESHOLD = Decimal("0.60")
CHARGEBACK_SPIKE_RATIO = Decimal("0.03")


@bp.route("/lending/merchants/<merchantId>/migration_signals/evaluate", methods=["POST"])
def evaluate_migration(merchantId):
    auth(["ServicerAgent"])
    m = get_or_404(DB.merchants, merchantId)
    if m["status"] == "SUSPENDED":
        raise ApiError("ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED", 409)
    if m["status"] != "ELIGIBLE":
        raise ApiError("ERR_MERCHANT_NOT_ELIGIBLE", "Merchant is not ELIGIBLE", 409)
    for s in DB.signals.values():
        if s["merchant_id"] == m["id"] and s["status"] in ("DETECTED", "CONFIRMED"):
            raise ApiError("ERR_MIGRATION_SIGNAL_OPEN",
                           "A DETECTED or CONFIRMED signal exists for this merchant", 409)
    recompute_merchant_aggregates(m)
    trailing = m["trailing_30d_net_cents"]
    prior = m["prior_30d_net_cents"]
    if prior == 0:
        drop_ratio = 0.0
    else:
        d = (Decimal(1) - Decimal(trailing) / Decimal(prior)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
        drop_ratio = float(d)
    volume_only = (Decimal(str(drop_ratio)) >= MIGRATION_DROP_THRESHOLD) and trailing > 0
    triggered = volume_only or (Decimal(str(m["trailing_30d_chargeback_ratio"])) > CHARGEBACK_SPIKE_RATIO)
    if not triggered:
        return success_object({
            "triggered": False,
            "volume_only_would_trigger": volume_only,
            "drop_ratio": drop_ratio,
            "merchant_id": m["id"],
        }, 200)
    s = new_common()
    s.update({
        "merchant_id": m["id"],
        "status": "DETECTED",
        "drop_ratio": drop_ratio,
        "volume_only_would_trigger": volume_only,
        "triggered": True,
        "evaluated_at": ts_now(),
    })
    DB.signals[s["id"]] = s
    return success_object(serialize(s), 200)


@bp.route("/lending/migration_signals/<signalId>/confirm", methods=["POST"])
def confirm_signal(signalId):
    auth(["ServicerAgent"])
    s = get_or_404(DB.signals, signalId)
    if s["status"] != "DETECTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Signal is not DETECTED", 409)
    s["status"] = "CONFIRMED"
    touch(s)
    m = DB.merchants.get(s["merchant_id"])
    if m is not None and m["status"] == "ELIGIBLE":
        m["status"] = "SUSPENDED"
        touch(m)
    return success_object(serialize(s), 200)


@bp.route("/lending/migration_signals/<signalId>/dismiss", methods=["POST"])
def dismiss_signal(signalId):
    auth(["ServicerAgent"])
    s = get_or_404(DB.signals, signalId)
    if s["status"] != "DETECTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Signal is not DETECTED", 409)
    s["status"] = "DISMISSED"
    touch(s)
    return success_object(serialize(s), 200)


@bp.route("/lending/migration_signals/<signalId>/clear", methods=["POST"])
def clear_signal(signalId):
    auth(["ServicerAgent"])
    s = get_or_404(DB.signals, signalId)
    if s["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Signal is not CONFIRMED", 409)
    s["status"] = "CLEARED"
    touch(s)
    return success_object(serialize(s), 200)


@bp.route("/lending/migration_signals/<signalId>", methods=["GET"])
def get_signal(signalId):
    auth(ALL_ROLES)
    s = get_or_404(DB.signals, signalId)
    return success_object(serialize(s), 200)


@bp.route("/lending/merchants/<merchantId>/migration_signals", methods=["GET"])
def list_merchant_signals(merchantId):
    auth(ALL_ROLES)
    m = get_or_404(DB.merchants, merchantId)
    limit, offset = parse_pagination()
    from flask import request as _req
    status = _req.args.get("status")
    rows = [s for s in DB.signals.values()
            if s["merchant_id"] == m["id"] and (status is None or s["status"] == status)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


# ===========================================================================
# Funding partner banks
# ===========================================================================

@bp.route("/lending/funding_banks", methods=["POST"])
def create_bank():
    auth(["PlatformAdmin"])
    body = get_body()
    legal_name = req_string(body, "legal_name")
    discount = body.get("purchase_discount_pct")
    if discount is None or isinstance(discount, bool) or not isinstance(discount, (int, float)) or discount < 0:
        raise err_invalid_request("purchase_discount_pct is required")
    b = new_common()
    b.update({
        "legal_name": legal_name,
        "purchase_discount_pct": discount,
        "status": "ACTIVE",
        "committed_exposure_cents": 0,
    })
    DB.banks[b["id"]] = b
    return success_object(serialize(b), 201)


@bp.route("/lending/funding_banks/<bankId>/suspend", methods=["POST"])
def suspend_bank(bankId):
    auth(["PlatformAdmin"])
    b = get_or_404(DB.banks, bankId)
    if b["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Bank is not ACTIVE", 409)
    b["status"] = "SUSPENDED"
    touch(b)
    return success_object(serialize(b), 200)


@bp.route("/lending/funding_banks/<bankId>", methods=["GET"])
def get_bank(bankId):
    auth(ALL_ROLES)
    b = get_or_404(DB.banks, bankId)
    return success_object(serialize(b), 200)


# ===========================================================================
# Loan sales
# ===========================================================================

SALE_RESERVE_PCT = Decimal("0.05")


def quote_price(loan, bank):
    raw = Decimal(loan["remaining_balance_cents"]) * (Decimal(1) - Decimal(str(bank["purchase_discount_pct"])))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.route("/lending/loans/<loanId>/sales/quote", methods=["POST"])
def quote_sale(loanId):
    auth(["BankOfficer"])
    loan = get_or_404(DB.loans, loanId)
    body = get_body()
    bank_id = body.get("bank_id")
    if not isinstance(bank_id, str):
        raise err_invalid_request("bank_id is required")
    bank = DB.banks.get(bank_id)
    if bank is None:
        raise err_not_found()
    if bank["status"] != "ACTIVE":
        raise ApiError("ERR_BANK_INACTIVE", "Bank is SUSPENDED", 409)
    sale = new_common()
    sale.update({
        "loan_id": loan["id"],
        "bank_id": bank["id"],
        "status": "QUOTED",
        "purchase_price_cents": quote_price(loan, bank),
        "reserve_withheld_cents": None,
        "bank_remittance_cents": None,
        "committed_by_user_id": None,
        "settled_by_user_id": None,
    })
    DB.sales[sale["id"]] = sale
    return success_object(serialize(sale), 201)


@bp.route("/lending/sales/<saleId>/commit", methods=["POST"])
def commit_sale(saleId):
    uid, _ = auth(["BankOfficer"])
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Sale is not QUOTED", 409)
    bank = DB.banks.get(sale["bank_id"])
    if bank is None or bank["status"] != "ACTIVE":
        raise ApiError("ERR_BANK_INACTIVE", "Bank is SUSPENDED", 409)
    sale["status"] = "COMMITTED"
    sale["committed_by_user_id"] = uid
    touch(sale)
    bank["committed_exposure_cents"] += sale["purchase_price_cents"]
    touch(bank)
    return success_object(serialize(sale), 200)


@bp.route("/lending/sales/<saleId>/settle", methods=["POST"])
def settle_sale(saleId):
    uid, _ = auth(["BankOfficer"])
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Sale is not COMMITTED", 409)
    loan = DB.loans.get(sale["loan_id"])
    bank = DB.banks.get(sale["bank_id"])
    # SoD (priority 7), loan active (5), bank active (5)
    if sale["committed_by_user_id"] == uid:
        raise ApiError("ERR_SOD_SAME_USER",
                       "Settle must be performed by a different officer than commit", 409)
    if loan is None or loan["status"] != "ACTIVE":
        raise ApiError("ERR_LOAN_NOT_ACTIVE", "Loan is not ACTIVE", 409)
    if bank is None or bank["status"] != "ACTIVE":
        raise ApiError("ERR_BANK_INACTIVE", "Bank is SUSPENDED", 409)
    price = sale["purchase_price_cents"]
    reserve = int((Decimal(price) * SALE_RESERVE_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    sale["reserve_withheld_cents"] = reserve
    sale["bank_remittance_cents"] = price - reserve
    sale["status"] = "SETTLED"
    sale["settled_by_user_id"] = uid
    touch(sale)
    bank["committed_exposure_cents"] -= price
    touch(bank)
    return success_object(serialize(sale), 200)


@bp.route("/lending/sales/<saleId>/fail", methods=["POST"])
def fail_sale(saleId):
    auth(["BankOfficer"])
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Sale is not COMMITTED", 409)
    bank = DB.banks.get(sale["bank_id"])
    sale["status"] = "FAILED"
    touch(sale)
    if bank is not None:
        bank["committed_exposure_cents"] -= sale["purchase_price_cents"]
        touch(bank)
    return success_object(serialize(sale), 200)


@bp.route("/lending/sales/<saleId>/requote", methods=["POST"])
def requote_sale(saleId):
    auth(["BankOfficer"])
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Sale is not FAILED", 409)
    bank = DB.banks.get(sale["bank_id"])
    if bank is None or bank["status"] != "ACTIVE":
        raise ApiError("ERR_BANK_INACTIVE", "Bank is SUSPENDED", 409)
    loan = DB.loans.get(sale["loan_id"])
    if loan is None:
        raise err_not_found()
    sale["purchase_price_cents"] = quote_price(loan, bank)
    sale["status"] = "QUOTED"
    touch(sale)
    return success_object(serialize(sale), 200)


@bp.route("/lending/sales/<saleId>", methods=["GET"])
def get_sale(saleId):
    auth(ALL_ROLES)
    sale = get_or_404(DB.sales, saleId)
    return success_object(serialize(sale), 200)


@bp.route("/lending/loans/<loanId>/sales", methods=["GET"])
def list_loan_sales(loanId):
    auth(ALL_ROLES)
    loan = get_or_404(DB.loans, loanId)
    limit, offset = parse_pagination()
    from flask import request as _req
    status = _req.args.get("status")
    rows = [s for s in DB.sales.values()
            if s["loan_id"] == loan["id"] and (status is None or s["status"] == status)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)


@bp.route("/lending/sales", methods=["GET"])
def list_sales():
    auth(ALL_ROLES)
    limit, offset = parse_pagination()
    from flask import request as _req
    loan_id = _req.args.get("loan_id")
    bank_id = _req.args.get("bank_id")
    rows = [s for s in DB.sales.values()
            if (loan_id is None or s["loan_id"] == loan_id)
            and (bank_id is None or s["bank_id"] == bank_id)]
    rows.sort(key=lambda e: e["created_at"])
    return paginate([serialize(r) for r in rows], limit, offset)

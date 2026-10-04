"""Routes: billing profiles, invoices, payments, close-month."""
import calendar
from datetime import timedelta
from flask import Blueprint, request
from core import (DB, CLOCK, ok, paginate, err, new_record, touch, authenticate,
                  require_role, check_ownership, parse_date)
from services import (serialize, lazy_invoice, profile_for_account, issue_invoice,
                      escalate_threshold, ad_account)

bp = Blueprint("billing", __name__)


def get_profile_or_404(profile_id):
    p = DB.billing_profiles.get(profile_id)
    if p is None:
        err("ERR_NOT_FOUND", "BillingProfile not found")
    return p


def get_invoice_or_404(invoice_id):
    i = DB.invoices.get(invoice_id)
    if i is None:
        err("ERR_NOT_FOUND", "Invoice not found")
    return i


@bp.post("/advertiser-accounts/<account_id>/billing-profile")
def create_billing_profile(account_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    check_ownership(caller, account["id"])
    body = request.get_json(silent=True) or {}
    pmt = body.get("payment_method_type")
    currency = body.get("currency_code", "USD")
    if pmt not in ("CARD", "INVOICING"):
        err("ERR_VALIDATION", "payment_method_type must be CARD or INVOICING")
    if not isinstance(currency, str):
        err("ERR_VALIDATION", "currency_code must be a string")
    if profile_for_account(account["id"]) is not None:
        err("ERR_BILLING_PROFILE_EXISTS", "Account already has a billing profile")
    profile = new_record({
        "account_id": account["id"],
        "payment_method_type": pmt,
        "currency_code": currency,
        "billing_threshold_cents": 50000,
        "unbilled_cost_cents": 0,
        "pending_credit_cents": 0,
        "outstanding_balance_cents": 0,
        "last_closed_month": None,
        "_last_invoice_end": None,
    })
    DB.billing_profiles[profile["id"]] = profile
    return ok(serialize("billing_profile", profile), 201)


@bp.get("/advertiser-accounts/<account_id>/billing-profile")
def get_account_billing_profile(account_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "BillingAdmin")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    check_ownership(caller, account["id"])
    p = profile_for_account(account["id"])
    data = [] if p is None else [serialize("billing_profile", p)]
    return ok(data, 200)


@bp.get("/billing-profiles/<profile_id>")
def get_billing_profile(profile_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "BillingAdmin")
    p = get_profile_or_404(profile_id)
    check_ownership(caller, p["account_id"])
    return ok(serialize("billing_profile", p), 200)


@bp.get("/billing-profiles/<profile_id>/invoices")
def list_invoices(profile_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "BillingAdmin")
    p = get_profile_or_404(profile_id)
    check_ownership(caller, p["account_id"])
    items = [i for i in DB.invoices.values() if i["billing_profile_id"] == p["id"]]
    items.sort(key=lambda i: (i["created_at"], i.get("_seq", 0), i["id"]))
    for i in items:
        lazy_invoice(i)
    page, meta = paginate(items)
    return ok([serialize("invoice", i) for i in page], 200, meta)


@bp.post("/invoices/<invoice_id>/payments")
def pay_invoice(invoice_id):
    caller = authenticate()
    require_role(caller, "BillingAdmin")
    inv = get_invoice_or_404(invoice_id)
    lazy_invoice(inv)
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        err("ERR_VALIDATION", "amount_cents must be an integer")
    if inv["status"] == "PAID":
        err("ERR_INVOICE_NOT_PAYABLE", "Invoice already PAID")
    remaining = inv["amount_cents"] - inv["paid_cents"]
    if amount <= 0 or amount > remaining:
        err("ERR_OVERPAYMENT", "Payment must be positive and not exceed remaining balance")
    inv["paid_cents"] += amount
    if inv["paid_cents"] >= inv["amount_cents"]:
        inv["status"] = "PAID"
        if inv["kind"] == "THRESHOLD":
            p = DB.billing_profiles.get(inv["billing_profile_id"])
            if p is not None:
                escalate_threshold(p)
                touch(p)
    else:
        inv["status"] = "PARTIALLY_PAID"
    touch(inv)
    return ok(serialize("invoice", inv), 200)


@bp.post("/billing-profiles/<profile_id>/close-month")
def close_month(profile_id):
    caller = authenticate()
    require_role(caller, "BillingAdmin")
    p = get_profile_or_404(profile_id)
    body = request.get_json(silent=True) or {}
    month = body.get("month")
    if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
        err("ERR_VALIDATION", "month must be YYYY-MM")
    try:
        y, m = int(month[:4]), int(month[5:7])
        if m < 1 or m > 12:
            raise ValueError
    except ValueError:
        err("ERR_VALIDATION", "month must be YYYY-MM")
    # month must be fully past: last day of month < current logical date
    days_in_month = calendar.monthrange(y, m)[1]
    from datetime import date as _date
    last_day = _date(y, m, days_in_month)
    today = CLOCK.today()
    if last_day >= today:
        err("ERR_MONTH_NOT_CLOSABLE", "Month is not fully past")
    if p["last_closed_month"] is not None and month <= p["last_closed_month"]:
        err("ERR_MONTH_NOT_CLOSABLE", "Month not strictly after last_closed_month")

    account_id = p["account_id"]
    total_overdelivery = 0
    for campaign in list(DB.campaigns.values()):
        if campaign["account_id"] != account_id:
            continue
        # per-day budgets in effect at end of day d, from budget history
        hist = campaign.get("_budget_history") or []
        # sort by date asc
        hist_sorted = sorted(hist, key=lambda e: e[0])
        per_day_sum = 0
        for day_num in range(1, days_in_month + 1):
            day_s = f"{month}-{day_num:02d}"
            effective = campaign["daily_budget_cents"]
            for d, b in hist_sorted:
                if d <= day_s:
                    effective = b
                else:
                    break
            per_day_sum += effective
        cap_final = (per_day_sum * 304) // (10 * days_in_month)
        month_served = sum(
            d["served_cents"] for d in DB.daily_spend_records.values()
            if d["campaign_id"] == campaign["id"] and d["spend_date"].startswith(month))
        credit = max(0, month_served - cap_final)
        campaign["overdelivery_credit_cents"] = campaign.get("overdelivery_credit_cents", 0) + credit
        campaign["last_closed_month_cap_cents"] = cap_final
        campaign["last_closed_month_credit_cents"] = credit
        touch(campaign)
        total_overdelivery += credit
    account = DB.accounts.get(account_id)
    if account is not None:
        account["lifetime_overdelivery_credit_cents"] = \
            account.get("lifetime_overdelivery_credit_cents", 0) + total_overdelivery
        touch(account)
    # issue MONTHLY invoice when amount > 0 (pending credits applied first inside)
    invoice_id = None
    if p["unbilled_cost_cents"] > 0 or total_overdelivery > 0:
        inv = issue_invoice(p, "MONTHLY", p["unbilled_cost_cents"],
                            overdelivery_credit=total_overdelivery)
        if inv is not None:
            invoice_id = inv["id"]
        p["unbilled_cost_cents"] = 0
    p["last_closed_month"] = month
    touch(p)
    return ok({
        "closed_month": month,
        "invoice_id": invoice_id,
        "total_overdelivery_credit_cents": total_overdelivery,
    }, 200)

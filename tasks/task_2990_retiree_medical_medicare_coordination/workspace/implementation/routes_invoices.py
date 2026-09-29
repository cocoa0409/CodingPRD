"""PremiumInvoice endpoints: the ten-step assembly, payments and the
delinquency unwind (PRD 3.8)."""

from flask import Blueprint, request

import calc
import errors
from auth import (ALL_ROLES, ROLE_BILLING_CLERK, ROLE_RETIREE, require_caller,
                  require_ownership)
from domain import (body_reference, get_enrollment, get_invoice,
                   invoices_of_enrollment, open_account_for,
                   outstanding_balance)
from envelope import object_response, paginate
from errors import fail
from store import base_record, db, order_asc, touch
from validate import read_body, require_interval

bp = Blueprint("invoices", __name__)

INVOICE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "PAID", "PAST_DUE",
                    "WRITTEN_OFF")
PAYABLE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "PAST_DUE")


@bp.post("/retiree-benefits/premium-invoices")
def create_invoice():
    require_caller((ROLE_BILLING_CLERK,))
    body = read_body()
    enrollment = body_reference(body, "enrollment_id", get_enrollment)

    enrollment_id = body.string("enrollment_id")
    period_start = body.instant("billing_period_start")
    period_end = body.instant("billing_period_end")
    require_interval(period_start, period_end,
                     "billing_period_start", "billing_period_end")

    plan_year = db.plan_years.get(enrollment["plan_year_id"])
    if plan_year is None or plan_year["status"] != "OPEN":
        fail(errors.ERR_PLAN_YEAR_NOT_OPEN)

    for existing in invoices_of_enrollment(enrollment_id):
        if existing["status"] == "WRITTEN_OFF":
            continue
        if calc.billing_periods_collide(period_start, period_end,
                                        existing["billing_period_start"],
                                        existing["billing_period_end"]):
            fail(errors.ERR_BILLING_PERIOD_OVERLAP)

    option = db.plan_options[enrollment["plan_option_id"]]
    retiree = db.retirees[enrollment["retiree_id"]]
    account = open_account_for(enrollment["retiree_id"],
                             enrollment["plan_year_id"])
    available = account["available_balance_cents"] if account is not None else 0

    waterfall = calc.premium_waterfall(option, retiree, available)
    due_date = calc.plus_days(period_start, calc.PREMIUM_DUE_DAYS)
    past_due_at = calc.plus_days(due_date, plan_year["premium_grace_period_days"])

    record = base_record()
    record.update({
        "enrollment_id": enrollment_id,
        "billing_period_start": period_start,
        "billing_period_end": period_end,
        "base_premium_cents": waterfall["base_premium_cents"],
        "admin_fee_cents": waterfall["admin_fee_cents"],
        "gross_premium_cents": waterfall["gross_premium_cents"],
        "employer_subsidy_bps": waterfall["employer_subsidy_bps"],
        "employer_subsidy_cents": waterfall["employer_subsidy_cents"],
        "retiree_share_cents": waterfall["retiree_share_cents"],
        "hra_applied_cents": waterfall["hra_applied_cents"],
        "net_due_cents": waterfall["net_due_cents"],
        "paid_cents": 0,
        "due_date": due_date,
        "past_due_at": past_due_at,
        "status": "PAID" if waterfall["net_due_cents"] == 0 else "ISSUED",
    })
    db.invoices[record["id"]] = record

    applied = waterfall["hra_applied_cents"]
    if applied > 0 and account is not None:
        account["available_balance_cents"] -= applied
        account["premium_offset_cents"] += applied
        touch(account)

    return object_response(record, 201)


@bp.get("/retiree-benefits/premium-invoices/<invoice_id>")
def read_invoice(invoice_id):
    require_caller(ALL_ROLES)
    return object_response(get_invoice(invoice_id))


@bp.get("/retiree-benefits/premium-invoices")
def list_invoices():
    require_caller(ALL_ROLES)
    rows = list(db.invoices.values())
    for field in ("enrollment_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginate(order_asc(rows))


@bp.post("/retiree-benefits/premium-invoices/<invoice_id>/payments")
def post_payment(invoice_id):
    caller = require_caller((ROLE_RETIREE, ROLE_BILLING_CLERK))
    invoice = get_invoice(invoice_id)
    enrollment = db.enrollments[invoice["enrollment_id"]]
    require_ownership(caller, enrollment["retiree_id"])
    body = read_body()
    amount_cents = body.cents("amount_cents")

    if invoice["status"] not in PAYABLE_STATUSES:
        fail(errors.ERR_INVOICE_ALREADY_SETTLED)

    if amount_cents > outstanding_balance(invoice):
        fail(errors.ERR_PAYMENT_EXCEEDS_BALANCE)

    was_past_due = invoice["status"] == "PAST_DUE"
    invoice["paid_cents"] += amount_cents
    fully_paid = invoice["paid_cents"] >= invoice["net_due_cents"]
    invoice["status"] = "PAID" if fully_paid else "PARTIALLY_PAID"
    touch(invoice)

    if was_past_due and fully_paid:
        _unwind_delinquency(enrollment)

    return object_response(invoice)


def _unwind_delinquency(enrollment):
    enrollment["consecutive_unpaid_periods"] = max(
        0, enrollment["consecutive_unpaid_periods"] - 1)

    remaining_past_due = any(
        i["status"] == "PAST_DUE"
        for i in invoices_of_enrollment(enrollment["id"]))

    if enrollment["consecutive_unpaid_periods"] == 0 and not remaining_past_due:
        if enrollment["billing_status"] == "DELINQUENT":
            enrollment["billing_status"] = "CURRENT"
        enrollment["delinquency_first_unpaid_period_start"] = None
        if enrollment["coverage_status"] == "SUSPENDED":
            enrollment["coverage_status"] = "ACTIVE"

    touch(enrollment)

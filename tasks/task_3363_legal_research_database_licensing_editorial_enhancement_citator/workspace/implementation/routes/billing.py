"""Invoice routes (PRD 3.6): generation with totals and cost recovery,
list/read, and the billing lifecycle transitions."""

from datetime import timedelta

from flask import Blueprint, request

from constants import INVOICE_STATUSES, INVOICE_TARGET_STATUSES, NET_TERMS_DAYS
from db import fmt_dt, stamp_new, store, touch
from errors import raise_err
from middleware import require_roles
from response import list_response, ok_object
from serializers import serialize_invoice
from services.billing import compute_invoice_fields, eval_auto_resume
from util import get_body, opt_enum_query, req_date, req_enum, req_str

bp = Blueprint("billing", __name__)

INVOICE_READERS = ("BillingAdmin", "LicensingManager", "FirmAdmin")


@bp.post("/legal-research/invoices/generate")
@require_roles("BillingAdmin")
def generate_invoice():
    body = get_body()
    subscription_id = req_str(body, "subscription_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if not (period_start < period_end):
        raise_err("ERR_INVALID_REQUEST", "period_start must be earlier than period_end")

    subscription = store.subscriptions.get(subscription_id)
    if subscription is None:
        raise_err("ERR_SUBSCRIPTION_NOT_FOUND", "subscription %s does not exist" % subscription_id)

    # Invoice generation is blocked by ANY non-VOID invoice whose window
    # overlaps — even a DRAFT blocks here (contrast with the usage-event rule).
    for inv in store.invoices.values():
        if inv["subscription_id"] != subscription_id or inv["status"] == "VOID":
            continue
        if period_start < inv["_period_end"] and inv["_period_start"] < period_end:
            raise_err("ERR_INVOICE_PERIOD_CLOSED", "window overlaps an existing invoice")

    fields = compute_invoice_fields(subscription, period_start, period_end)

    invoice = stamp_new({
        "subscription_id": subscription_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "_period_start": period_start,
        "_period_end": period_end,
        "billing_model": fields["billing_model"],
        "base_fee_cents": fields["base_fee_cents"],
        "search_count": fields["search_count"],
        "doc_view_count": fields["doc_view_count"],
        "overage_search_units": fields["overage_search_units"],
        "overage_view_units": fields["overage_view_units"],
        "overage_fee_cents": fields["overage_fee_cents"],
        "total_cents": fields["total_cents"],
        "cost_recovery_allocation": fields["cost_recovery_allocation"],
        "status": "DRAFT",
        "issued_at": None,
        "due_at": None,
        "_due_dt": None,
    })
    store.invoices[invoice["id"]] = invoice
    return ok_object(serialize_invoice(invoice), 201)


@bp.get("/legal-research/invoices")
@require_roles(*INVOICE_READERS)
def list_invoices():
    f_subscription = request.args.get("subscription_id")
    f_status = opt_enum_query("status", INVOICE_STATUSES)

    rows = list(store.invoices.values())
    if f_subscription is not None:
        rows = [i for i in rows if i["subscription_id"] == f_subscription]
    if f_status is not None:
        rows = [i for i in rows if i["status"] == f_status]
    return list_response(rows, serialize_invoice)


@bp.get("/legal-research/invoices/<invoice_id>")
@require_roles(*INVOICE_READERS)
def get_invoice(invoice_id):
    invoice = store.invoices.get(invoice_id)
    if invoice is None:
        raise_err("ERR_INVOICE_NOT_FOUND", "invoice %s does not exist" % invoice_id)
    return ok_object(serialize_invoice(invoice))


@bp.post("/legal-research/invoices/<invoice_id>/transition")
@require_roles("BillingAdmin")
def transition_invoice(invoice_id):
    body = get_body()
    target = req_enum(body, "target_status", INVOICE_TARGET_STATUSES)

    invoice = store.invoices.get(invoice_id)
    if invoice is None:
        raise_err("ERR_INVOICE_NOT_FOUND", "invoice %s does not exist" % invoice_id)
    current = invoice["status"]

    if target == "ISSUED":
        if current != "DRAFT":
            raise_err("ERR_INVALID_STATE", "invoice %s cannot be issued from %s" % (invoice_id, current))
        issued_at = store.clock
        due_at = issued_at + timedelta(days=NET_TERMS_DAYS)
        invoice["issued_at"] = fmt_dt(issued_at)
        invoice["due_at"] = fmt_dt(due_at)
        invoice["_due_dt"] = due_at
    elif target == "PAID":
        if current not in ("ISSUED", "OVERDUE"):
            raise_err("ERR_INVALID_STATE", "invoice %s cannot be paid from %s" % (invoice_id, current))
    else:  # VOID
        if current not in ("DRAFT", "ISSUED", "OVERDUE"):
            raise_err("ERR_INVALID_STATE", "invoice %s cannot be voided from %s" % (invoice_id, current))

    invoice["status"] = target
    touch(invoice)

    # Settlement in either direction triggers the auto-resume evaluation.
    if target in ("PAID", "VOID"):
        eval_auto_resume(invoice["subscription_id"])

    return ok_object(serialize_invoice(invoice), 200)

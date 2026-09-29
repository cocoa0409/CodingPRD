"""The rent-invoice lifecycle (PRD section 3.9, final paragraphs).

Rent never touches the option-payment ledger: paying an invoice leaves both
total_paid_cents and total_option_paid_cents alone.
"""

from flask import Blueprint

import access
import calc
import cascades
import serializers as ser
import validation as v
from auth import LANDOWNER, PAYMENT_ADMINISTRATOR, PORTFOLIO_MANAGER, require
from envelope import ok, ok_list
from errors import (
    ERR_INVALID_STATE,
    ERR_LANDOWNER_PAYMENT_HOLD,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    fail,
)
from store import db, now, ordered, touch
from util import add_days

bp = Blueprint("invoices", __name__, url_prefix="/land-origination")

READERS = (PORTFOLIO_MANAGER, PAYMENT_ADMINISTRATOR, LANDOWNER)


def _owner_of(invoice_row):
    lease = db.leases.get(invoice_row["lease_agreement_id"])
    return lease["landowner_id"] if lease is not None else None


@bp.get("/rent-invoices/<invoice_id>")
@require(*READERS)
def get_invoice(invoice_id):
    row = access.invoice(invoice_id)
    access.own_invoice(row)
    return ok(ser.invoice(row))


@bp.get("/rent-invoices")
@require(*READERS)
def list_invoices():
    limit, offset = v.pagination()
    rows = ordered(db.invoices.values())
    rows = access.scope_rows(rows, _owner_of)
    rows = v.apply_filters(rows, [
        ("lease_agreement_id", v.query_str("lease_agreement_id")),
        ("period_year", v.query_int("period_year")),
        ("rent_variant", v.query_str("rent_variant")),
        ("status", v.query_str("status")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.invoice, page), limit, offset, total)


@bp.post("/rent-invoices/<invoice_id>/issue")
@require(PAYMENT_ADMINISTRATOR)
def issue_invoice(invoice_id):
    row = access.invoice(invoice_id)
    if row["status"] != "DRAFT":
        fail(ERR_INVALID_STATE)

    issued_at = now()
    row["status"] = "ISSUED"
    row["issued_at"] = issued_at
    row["due_at"] = add_days(issued_at, calc.INVOICE_NET_DAYS)
    touch(row)
    return ok(ser.invoice(row))


def _has_overdue_issued(lease):
    clock = now()
    for other in cascades.lease_invoices(lease["id"]):
        if other["status"] == "ISSUED" and other["due_at"] is not None \
                and other["due_at"] <= clock:
            return True
    return False


@bp.post("/rent-invoices/<invoice_id>/pay")
@require(PAYMENT_ADMINISTRATOR)
def pay_invoice(invoice_id):
    row = access.invoice(invoice_id)
    body = v.json_body()
    amount = v.req_int(body, "paid_amount_cents", lo=0)
    lease = db.leases.get(row["lease_agreement_id"])
    owner = db.landowners.get(lease["landowner_id"]) if lease else None

    if row["status"] != "ISSUED":
        fail(ERR_INVALID_STATE)
    if owner is not None and owner["payment_hold"]:
        fail(ERR_LANDOWNER_PAYMENT_HOLD)
    if amount != int(row["gross_rent_cents"]):
        fail(ERR_PAYMENT_AMOUNT_MISMATCH)

    row["status"] = "PAID"
    row["paid_at"] = now()
    row["paid_amount_cents"] = amount
    touch(row)

    if lease is not None:
        before_year = int(lease["last_paid_invoice_year"])
        before_status = lease["rent_status"]
        cascades.recompute_last_paid_invoice_year(lease)
        if before_status == "PENDING_FIRST_RENT":
            lease["rent_status"] = "CURRENT"
        elif before_status == "DELINQUENT" and not _has_overdue_issued(lease):
            # The cycle only closes once nothing else is past due.
            lease["rent_status"] = "CURRENT"
        if int(lease["last_paid_invoice_year"]) != before_year \
                or lease["rent_status"] != before_status:
            touch(lease)
    return ok(ser.invoice(row))


@bp.post("/rent-invoices/<invoice_id>/void")
@require(PAYMENT_ADMINISTRATOR)
def void_invoice(invoice_id):
    row = access.invoice(invoice_id)
    body = v.json_body()
    reason = v.req_str(body, "void_reason", min_len=1)

    if row["status"] not in ("DRAFT", "ISSUED"):
        fail(ERR_INVALID_STATE)

    row["status"] = "VOID"
    row["void_reason"] = reason
    touch(row)
    return ok(ser.invoice(row))

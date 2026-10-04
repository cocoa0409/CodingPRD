"""Placement-fee invoicing and partner receivables (PRD 3.7)."""

from flask import Blueprint

import db
import middleware
import response
import validators
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_PARTNER_CREDIT_LIMIT,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ApiError,
)
from routes.common import must_get, must_get_body, require_version
from services import partner_svc

PARTNER_CREDIT_CEILING_CENTS = 750000
TERMINAL_STATUSES = ("PAID", "VOID")

bp = Blueprint("invoices", __name__)


@bp.post("/invoices")
def create_invoice():
    middleware.require(("ProgramStaff",))
    data = validators.body()

    raw_partner_id = data.get("partner_id")
    if not isinstance(raw_partner_id, str) or not raw_partner_id.strip():
        validators.fail("field 'partner_id' is required")
    partner = must_get_body("partners", raw_partner_id.strip(), "partner_id")

    raw_placement_id = data.get("placement_id")
    if not isinstance(raw_placement_id, str) or not raw_placement_id.strip():
        validators.fail("field 'placement_id' is required")
    placement = must_get_body("placements", raw_placement_id.strip(), "placement_id")

    due_date = validators.as_dt(data, "due_date")
    expected_version = validators.as_int(data, "expected_partner_version")

    total_amount_cents = int(placement.get("placement_fee_cents") or 0)
    if int(partner["outstanding_balance_cents"]) + total_amount_cents > PARTNER_CREDIT_CEILING_CENTS:
        raise ApiError(
            ERR_PARTNER_CREDIT_LIMIT,
            "the partner's outstanding balance plus this invoice exceeds the %d cent ceiling"
            % PARTNER_CREDIT_CEILING_CENTS,
            402,
        )

    require_version(expected_version, partner["version"], "partner")

    row = db.make_row(
        partner_id=partner["id"],
        placement_id=placement["id"],
        total_amount_cents=total_amount_cents,
        amount_paid_cents=0,
        due_date=due_date,
        paid_on=None,
        status="ISSUED",
    )
    db.insert("invoices", row)

    partner_svc.apply_derived(partner)
    db.touch(partner)
    return response.success(row, status=201)


@bp.get("/invoices")
def list_invoices():
    middleware.require(("ProgramStaff", "Partner"))
    partner_id = validators.request_arg("partner_id")
    placement_id = validators.request_arg("placement_id")
    status = validators.request_arg("status")

    rows = db.all_rows("invoices")
    if partner_id:
        rows = [i for i in rows if i["partner_id"] == partner_id]
    if placement_id:
        rows = [i for i in rows if i["placement_id"] == placement_id]
    if status:
        rows = [i for i in rows if i["status"] == status]
    return response.list_response(rows, key=response.by_created_at)


@bp.get("/invoices/<invoice_id>")
def read_invoice(invoice_id):
    middleware.require(("ProgramStaff", "Partner"))
    invoice = must_get("invoices", invoice_id, "invoice")
    partner_svc.refresh_partner(db.get("partners", invoice["partner_id"]))
    return response.success(invoice)


@bp.post("/invoices/<invoice_id>/payments")
def pay_invoice(invoice_id):
    middleware.require(("ProgramStaff",))
    invoice = must_get("invoices", invoice_id, "invoice")
    data = validators.body()
    amount_paid_cents = validators.as_int(data, "amount_paid_cents")
    paid_on = validators.as_dt(data, "paid_on")

    if invoice["status"] in TERMINAL_STATUSES:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "invoice %s is already %s" % (invoice_id, invoice["status"]),
            409,
        )

    if int(amount_paid_cents) != int(invoice["total_amount_cents"]):
        raise ApiError(
            ERR_PAYMENT_AMOUNT_MISMATCH,
            "amount_paid_cents must equal the invoice total %d" % invoice["total_amount_cents"],
            422,
        )

    invoice["status"] = "PAID"
    invoice["amount_paid_cents"] = int(amount_paid_cents)
    invoice["paid_on"] = paid_on
    db.touch(invoice)

    partner = db.get("partners", invoice["partner_id"])
    partner_svc.apply_derived(partner)
    db.touch(partner)
    return response.success(invoice)


@bp.post("/invoices/<invoice_id>/voids")
def void_invoice(invoice_id):
    middleware.require(("ProgramStaff",))
    invoice = must_get("invoices", invoice_id, "invoice")

    if invoice["status"] in TERMINAL_STATUSES:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "invoice %s is already %s" % (invoice_id, invoice["status"]),
            409,
        )

    invoice["status"] = "VOID"
    db.touch(invoice)

    partner = db.get("partners", invoice["partner_id"])
    partner_svc.apply_derived(partner)
    db.touch(partner)
    return response.success(invoice)

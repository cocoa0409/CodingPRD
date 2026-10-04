"""PremiumInvoice: list, pay (exact amount; delinquency cure re-check)."""
from __future__ import annotations

from authn import (ROLE_BENEFICIARY, ROLE_BENEFIT_ADMINISTRATOR,
                   ROLE_FIELD_OFFICER, authenticate, authorize,
                   check_ownership)
from db import find, find_one, get, public, sort_entities, touch
from envelope import success_list, success_object
from errors import fail
from validate import body_json, pagination_args, paginate, req_int


def list_invoices(beneficiary_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_BENEFIT_ADMINISTRATOR,
                     ROLE_FIELD_OFFICER])
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("invoices",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def pay_invoice(invoice_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY])
    body = body_json()
    amount = req_int(body, "amount_cents", minimum=0)
    inv = get("invoices", invoice_id)
    if not inv:
        fail("ERR_INVOICE_NOT_FOUND", "No invoice with that id")
    check_ownership(role, uid, inv["beneficiary_id"])
    # Guards in pinned order: payable state, then exact-amount (always last)
    if inv["status"] not in ("ISSUED", "PAST_DUE"):
        fail("ERR_INVOICE_NOT_PAYABLE",
             "Invoice is PAID, CANCELLED, or WRITTEN_OFF")
    if amount != inv["outstanding_cents"]:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH",
             "Payment must equal outstanding_cents exactly")
    inv["status"] = "PAID"
    inv["paid_cents"] = amount
    inv["applied_cents"] = amount
    inv["outstanding_cents"] = 0
    touch(inv)
    # Cure re-check: no PAST_DUE invoices remain -> DELINQUENT -> DIRECT_BILL
    ent = None
    if inv.get("_enrollment_id"):
        ent = get("enrollments", inv["_enrollment_id"])
    if ent is None:
        ent = find_one("enrollments",
                       lambda e: e["beneficiary_id"] == inv["beneficiary_id"]
                       and e["part"] == inv["part"]
                       and e["enrollment_status"] in ("PENDING", "ACTIVE"))
    if ent and ent["collection_status"] == "DELINQUENT":
        remaining = find_one(
            "invoices",
            lambda i: i.get("_enrollment_id") == ent["id"]
            and i["status"] == "PAST_DUE")
        if not remaining:
            ent["collection_status"] = "DIRECT_BILL"
            touch(ent)
    return success_object(public(inv))


def register(app):
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/invoices",
                     "list_invoices", list_invoices, methods=["GET"])
    app.add_url_rule("/medicare/invoices/<invoice_id>/pay", "pay_invoice",
                     pay_invoice, methods=["POST"])

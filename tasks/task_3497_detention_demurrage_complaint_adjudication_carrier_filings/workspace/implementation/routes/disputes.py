"""InvoiceDispute: open on an ISSUED invoice, list, respond within the 30-day
window; a late response is a forced waiver (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint

import store
from auth import require_roles, any_role
from clock import CLOCK
from envelope import ok_object, ok_list, paginate
from errors import (
    fail,
    ERR_INVOICE_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE_ACCESS,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_DISPUTABLE,
    ERR_DISPUTE_NOT_PENDING,
    ERR_REDUCED_AMOUNT_NOT_LOWER,
    ERR_JUSTIFICATION_REQUIRED,
)
from serialization import ser_dispute
from services import cascades
from store import touch
from util import body, req_enum, is_int
from constants import (
    DISPUTE_RESPONSE_WINDOW_DAYS,
    SCORE_PENALTY_LATE_DISPUTE_RESPONSE,
)

bp = Blueprint("disputes", __name__)

DISPUTE_REASONS = (
    "LATE_ISSUANCE",
    "INCORRECT_PARTY",
    "MISSING_ELEMENTS",
    "CHARGE_EXCEEDS_PUBLISHED",
    "OTHER",
)
RESOLUTIONS = ("WAIVE", "REDUCE", "DENY")


@bp.post("/fmc/invoices/<invoiceId>/disputes")
def open_dispute(invoiceId):
    uid, _role = require_roles("ShipperRep")
    inv = store.invoices.get(invoiceId)
    if inv is None:
        fail(ERR_INVOICE_NOT_FOUND, "invoice not found: %s" % invoiceId)
    if uid != inv["billed_party_shipper_id"]:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "only the billed party may dispute the invoice")
    b = body()
    dispute_reason = req_enum(b, "dispute_reason", DISPUTE_REASONS)
    if inv["invoice_status"] != "ISSUED":
        fail(ERR_INVOICE_NOT_DISPUTABLE,
             "dispute filing requires the invoice to be ISSUED")
    now = CLOCK.now()
    rec = store.base_record()
    rec.update(
        invoice_id=invoiceId,
        dispute_reason=dispute_reason,
        filed_at=now,
        response_due_at=now + timedelta(days=DISPUTE_RESPONSE_WINDOW_DAYS),
        responded_at=None,
        requested_resolution=None,
        resolution="PENDING",
        response_was_late=False,
        resolved_amount_cents=None,
    )
    store.disputes[rec["id"]] = rec
    inv["invoice_status"] = "DISPUTED"
    touch(inv)
    return ok_object(ser_dispute(rec), 201)


@bp.get("/fmc/invoices/<invoiceId>/disputes")
def list_disputes(invoiceId):
    any_role()
    if invoiceId not in store.invoices:
        fail(ERR_INVOICE_NOT_FOUND, "invoice not found: %s" % invoiceId)
    recs = [d for d in store.disputes.values() if d["invoice_id"] == invoiceId]
    page, limit, offset, total = paginate(recs)
    return ok_list([ser_dispute(d) for d in page], limit, offset, total)


@bp.post("/fmc/invoice-disputes/<disputeId>/respond")
def respond_dispute(disputeId):
    uid, _role = require_roles("CarrierRep")
    d = store.disputes.get(disputeId)
    if d is None:
        fail(ERR_DISPUTE_NOT_FOUND, "invoice dispute not found: %s" % disputeId)
    inv = store.invoices[d["invoice_id"]]
    if uid != inv["carrier_id"]:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "only the invoicing carrier may respond to the dispute")
    b = body()
    resolution = req_enum(b, "resolution", RESOLUTIONS)
    reduced_amount_cents = b.get("reduced_amount_cents")
    if reduced_amount_cents is not None and (
        not is_int(reduced_amount_cents) or reduced_amount_cents < 0
    ):
        fail(ERR_INVALID_REQUEST,
             "reduced_amount_cents must be a non-negative integer")
    denial_justification = b.get("denial_justification")
    if denial_justification is not None and not isinstance(denial_justification, str):
        fail(ERR_INVALID_REQUEST, "denial_justification must be a string")
    if d["resolution"] != "PENDING":
        fail(ERR_DISPUTE_NOT_PENDING, "respond requires the dispute to be PENDING")

    now = CLOCK.now()
    d["responded_at"] = now
    d["requested_resolution"] = resolution

    if now > d["response_due_at"]:
        # A late response loses the right to choose: forced waiver, invoice
        # voided, 25-point compliance deduction (which may suspend the carrier).
        d["resolution"] = "UPHELD_WAIVED"
        d["response_was_late"] = True
        d["resolved_amount_cents"] = 0
        inv["invoice_status"] = "VOIDED"
        touch(inv)
        carrier = store.carriers[inv["carrier_id"]]
        cascades.apply_score_event(carrier, -SCORE_PENALTY_LATE_DISPUTE_RESPONSE)
        touch(d)
        return ok_object(ser_dispute(d))

    if resolution == "WAIVE":
        d["resolution"] = "UPHELD_WAIVED"
        d["resolved_amount_cents"] = 0
        inv["invoice_status"] = "VOIDED"
        touch(inv)
    elif resolution == "REDUCE":
        if reduced_amount_cents is None or reduced_amount_cents >= inv["amount_cents"]:
            fail(ERR_REDUCED_AMOUNT_NOT_LOWER,
                 "a timely REDUCE must carry a reduced_amount_cents strictly "
                 "lower than the invoice's current amount_cents")
        d["resolution"] = "UPHELD_REDUCED"
        d["resolved_amount_cents"] = reduced_amount_cents
        inv["amount_cents"] = reduced_amount_cents
        inv["invoice_status"] = "ISSUED"
        touch(inv)
    else:  # DENY
        if denial_justification is None:
            fail(ERR_JUSTIFICATION_REQUIRED,
                 "a DENY response must carry a denial_justification")
        d["resolution"] = "DENIED"
        d["resolved_amount_cents"] = inv["amount_cents"]
        inv["invoice_status"] = "ISSUED"
        touch(inv)
    touch(d)
    return ok_object(ser_dispute(d))

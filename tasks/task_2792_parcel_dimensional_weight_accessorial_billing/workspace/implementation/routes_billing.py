"""The billing sweep, invoice lifecycle and billing adjustments
(PRD 3.6, 3.7, 3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import domain
import pricing
import serializers as ser
import validators as v
from auth import (ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER,
                  authorize, caller_id, enforce_named_shipper,
                  enforce_shipper_scope, is_shipper_user)
from errors import ApiError
from response import pagination_params, paginate, success
from store import (db, iso, new_record, now, parse_instant, sorted_records,
                   touch)

bp = Blueprint("billing", __name__)

INVOICE_STATUSES = ("OPEN", "ISSUED", "ADJUSTED", "SETTLED", "VOID")
ADJUSTMENT_REASONS = ("WEIGHT_CORRECTION", "ACCESSORIAL_CORRECTION",
                      "DISPUTE_CREDIT", "GUARANTEE_REFUND", "MANUAL")
ADJUSTMENT_STATUSES = ("PROPOSED", "APPLIED", "REJECTED")

SWEEPABLE_MEASUREMENT = ("PENDING_SCAN", "SCANNED", "VERIFIED")
SWEEPABLE_MOVEMENT = ("DELIVERED", "UNDELIVERABLE", "REFUSED")
ADJUSTABLE_INVOICE_STATES = ("ISSUED", "ADJUSTED")


def invoice_of_line(line):
    return db.invoices.get(line["invoice_id"])


def shipper_of_line(line):
    invoice = invoice_of_line(line)
    return invoice["shipper_id"] if invoice else None


# --------------------------------------------------------------------------
# the billing sweep (PRD 3.6)
# --------------------------------------------------------------------------

@bp.route("/invoices", methods=["POST"])
@authorize(ROLE_BILLING_OPS)
def create_invoice():
    body = v.get_body()

    shipper = domain.shipper_or_404(v.peek_str(body, "shipper_id"))

    named = []
    if isinstance(body.get("include_shipment_ids"), list):
        for raw in body["include_shipment_ids"]:
            shipment = domain.shipment_or_404(raw if isinstance(raw, str) else None)
            if shipment["shipper_id"] != shipper["id"]:
                raise ApiError("ERR_SHIPMENT_NOT_FOUND",
                               "The named shipment does not belong to this shipper.")
            named.append(shipment)

    period_start = v.req_date(body, "period_start")
    period_end = v.req_date(body, "period_end")
    v.opt_str_list(body, "include_shipment_ids")

    if period_end < period_start:
        raise ApiError("ERR_INVALID_PERIOD",
                       "period_end must be on or after period_start.")

    for shipment in named:
        if shipment["billing_status"] != "UNBILLED":
            raise ApiError("ERR_SHIPMENT_ALREADY_BILLED",
                           "The named shipment already sits on a non-void invoice.")
    for shipment in named:
        if shipment["measurement_status"] == "TOLERANCE_FLAGGED":
            raise ApiError("ERR_SCAN_TOLERANCE_UNRESOLVED",
                           "The named shipment's scanner verdict is unresolved.")

    selection = {}
    for shipment in domain.shipments_of_shipper(shipper["id"]):
        if shipment["billing_status"] != "UNBILLED":
            continue
        if shipment["measurement_status"] not in SWEEPABLE_MEASUREMENT:
            continue
        if shipment["movement_status"] not in SWEEPABLE_MOVEMENT:
            continue
        if not (period_start <= shipment["pickup_date"] <= period_end):
            continue
        selection[shipment["id"]] = shipment
    for shipment in named:
        selection[shipment["id"]] = shipment

    if not selection:
        raise ApiError("ERR_NO_BILLABLE_SHIPMENTS",
                       "No shipment of this shipper is billable for the period.")

    ordered = sorted(selection.values(),
                     key=lambda s: (s["pickup_date"], s["created_at"], s["_seq"]))

    # Price every candidate before any record is written so a data error leaves
    # no partial invoice behind.
    for shipment in ordered:
        pricing.price_shipment(shipment)

    invoice = new_record()
    invoice.update({
        "shipper_id": shipper["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "transportation_subtotal_cents": 0,
        "accessorial_subtotal_cents": 0,
        "gross_charges_cents": 0,
        "tier_discount_bps": 0,
        "tier_discount_cents": 0,
        "issued_at": None,
        "dispute_deadline_utc": None,
        "payment_reference": None,
    })
    db.invoices[invoice["id"]] = invoice

    for shipment in ordered:
        pricing.create_line(invoice, shipment)
        shipment["billing_status"] = "BILLED"
        touch(shipment)

    pricing.recompute_invoice(invoice)
    return success(ser.invoice(invoice), 201)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def read_invoice(invoice_id):
    invoice = domain.invoice_or_404(invoice_id)
    enforce_shipper_scope(invoice["shipper_id"])
    return success(ser.invoice(invoice))


@bp.route("/invoices", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def list_invoices():
    shipper_id = request.args.get("shipper_id")
    enforce_named_shipper(shipper_id)
    limit, offset = pagination_params()

    rows = sorted_records(list(db.invoices.values()))
    if is_shipper_user():
        rows = [r for r in rows if r["shipper_id"] == caller_id()]
    if shipper_id is not None:
        rows = [r for r in rows if r["shipper_id"] == shipper_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.invoice, limit, offset)


@bp.route("/invoices/<invoice_id>/issue", methods=["POST"])
@authorize(ROLE_BILLING_OPS)
def issue_invoice(invoice_id):
    invoice = domain.invoice_or_404(invoice_id)
    line_count = len(domain.lines_of_invoice(invoice["id"]))
    if invoice["status"] != "OPEN" or line_count < 1:
        raise ApiError("ERR_INVOICE_NOT_IN_STATE",
                       "Only an OPEN invoice carrying at least one line may be issued.")

    issued_at = now()
    invoice["issued_at"] = iso(issued_at)
    invoice["dispute_deadline_utc"] = iso(
        issued_at + timedelta(days=calc.DISPUTE_WINDOW_DAYS))
    pricing.recompute_invoice(invoice)
    invoice["status"] = "ISSUED"
    touch(invoice)
    return success(ser.invoice(invoice))


@bp.route("/invoices/<invoice_id>/settle", methods=["POST"])
@authorize(ROLE_BILLING_OPS)
def settle_invoice(invoice_id):
    invoice = domain.invoice_or_404(invoice_id)
    body = v.get_body()
    payment_reference = v.req_string(body, "payment_reference")

    if (invoice["status"] not in ADJUSTABLE_INVOICE_STATES
            or domain.invoice_pending_count(invoice["id"]) != 0):
        raise ApiError("ERR_INVOICE_NOT_IN_STATE",
                       "Only an ISSUED or ADJUSTED invoice with no PROPOSED "
                       "adjustment may be settled.")

    invoice["payment_reference"] = payment_reference
    invoice["status"] = "SETTLED"
    touch(invoice)
    return success(ser.invoice(invoice))


@bp.route("/invoices/<invoice_id>/void", methods=["POST"])
@authorize(ROLE_BILLING_OPS)
def void_invoice(invoice_id):
    invoice = domain.invoice_or_404(invoice_id)
    if invoice["status"] not in ("OPEN", "ISSUED", "ADJUSTED"):
        raise ApiError("ERR_INVOICE_NOT_IN_STATE",
                       "Only an OPEN, ISSUED or ADJUSTED invoice may be voided.")

    lines = domain.lines_of_invoice(invoice["id"])

    invoice["status"] = "VOID"
    touch(invoice)

    for line in lines:
        line["voided"] = True
        touch(line)

        shipment = db.shipments.get(line["shipment_id"])
        if shipment is not None and shipment["billing_status"] in ("BILLED", "ADJUSTED"):
            shipment["billing_status"] = "UNBILLED"
            touch(shipment)

        for adjustment in domain.adjustments_of_line(line["id"]):
            if adjustment["status"] == "PROPOSED":
                reject_adjustment_record(adjustment, None)

    return success(ser.invoice(invoice))


# --------------------------------------------------------------------------
# invoice lines
# --------------------------------------------------------------------------

@bp.route("/invoice-lines/<line_id>", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def read_invoice_line(line_id):
    line = domain.line_or_404(line_id)
    enforce_shipper_scope(shipper_of_line(line))
    return success(ser.invoice_line(line))


@bp.route("/invoice-lines", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def list_invoice_lines():
    limit, offset = pagination_params()
    rows = sorted_records(list(db.invoice_lines.values()))
    if is_shipper_user():
        rows = [r for r in rows if shipper_of_line(r) == caller_id()]
    invoice_id = request.args.get("invoice_id")
    shipment_id = request.args.get("shipment_id")
    if invoice_id is not None:
        rows = [r for r in rows if r["invoice_id"] == invoice_id]
    if shipment_id is not None:
        rows = [r for r in rows if r["shipment_id"] == shipment_id]
    return paginate(rows, ser.invoice_line, limit, offset)


# --------------------------------------------------------------------------
# billing adjustments (PRD 3.8)
# --------------------------------------------------------------------------

def create_adjustment(line, reason, delta_cents, created_by_user_id,
                      note=None, status="PROPOSED", dispute_id=None,
                      guarantee_claim_id=None, applied_at=None,
                      applied_by_user_id=None):
    record = new_record()
    record.update({
        "invoice_line_id": line["id"],
        "dispute_id": dispute_id,
        "guarantee_claim_id": guarantee_claim_id,
        "reason": reason,
        "delta_cents": delta_cents,
        "status": status,
        "created_by_user_id": created_by_user_id,
        "applied_by_user_id": applied_by_user_id,
        "note": note,
        "applied_at": applied_at,
    })
    db.billing_adjustments[record["id"]] = record
    return record


def reject_adjustment_record(adjustment, note):
    """Shared by operator rejection and the void cascade (PRD 3.7 hop 4)."""
    adjustment["status"] = "REJECTED"
    if note is not None:
        adjustment["note"] = note
    touch(adjustment)

    claim_id = adjustment["guarantee_claim_id"]
    if claim_id is not None:
        claim = db.guarantee_claims.get(claim_id)
        if claim is not None and claim["status"] == "APPROVED":
            claim["status"] = "DENIED"
            claim["refund_cents"] = 0
            touch(claim)
    return adjustment


@bp.route("/billing-adjustments", methods=["POST"])
@authorize(ROLE_BILLING_OPS)
def propose_adjustment():
    body = v.get_body()
    line = domain.line_or_404(v.peek_str(body, "invoice_line_id"))

    reason = v.req_enum(body, "reason", ADJUSTMENT_REASONS)
    delta_cents = v.req_int(body, "delta_cents")
    expected_invoice_version = v.req_int(body, "expected_invoice_version")
    note = v.opt_string(body, "note")
    if delta_cents == 0:
        v.bad("Field 'delta_cents' must not be 0.")

    invoice = invoice_of_line(line)
    if expected_invoice_version != invoice["version"]:
        raise ApiError("ERR_STALE_INVOICE_VERSION",
                       "expected_invoice_version does not match the invoice's "
                       "current version.")

    if invoice["status"] not in ADJUSTABLE_INVOICE_STATES:
        raise ApiError("ERR_INVOICE_NOT_ADJUSTABLE",
                       "Only an ISSUED or ADJUSTED invoice admits adjustments.")

    if delta_cents < 0:
        if -delta_cents > domain.line_total_cents(line):
            raise ApiError("ERR_ADJUSTMENT_EXCEEDS_LINE",
                           "A credit may not exceed the line's current total.")
        if domain.invoice_net_amount(invoice) + delta_cents < 0:
            raise ApiError("ERR_CREDIT_EXCEEDS_INVOICE_NET",
                           "A credit may not push the invoice net below zero.")

    adjustment = create_adjustment(line, reason, delta_cents, caller_id(), note)
    touch(invoice)
    return success(ser.billing_adjustment(adjustment), 201)


def apply_adjustment_record(adjustment, applier_user_id):
    """The four-hop application cascade (PRD 3.8)."""
    line = db.invoice_lines[adjustment["invoice_line_id"]]
    invoice = invoice_of_line(line)

    adjustment["status"] = "APPLIED"
    adjustment["applied_by_user_id"] = applier_user_id
    adjustment["applied_at"] = iso(now())
    touch(adjustment)

    touch(line)

    invoice["status"] = "ADJUSTED"
    touch(invoice)

    shipment = db.shipments.get(line["shipment_id"])
    if shipment is not None and shipment["billing_status"] == "BILLED":
        shipment["billing_status"] = "ADJUSTED"
        touch(shipment)
    elif shipment is not None:
        touch(shipment)

    claim_id = adjustment["guarantee_claim_id"]
    if claim_id is not None:
        claim = db.guarantee_claims.get(claim_id)
        if claim is not None and claim["status"] == "APPROVED":
            claim["status"] = "REFUNDED"
            claim["refund_cents"] = -adjustment["delta_cents"]
            touch(claim)
    return adjustment


@bp.route("/billing-adjustments/<adjustment_id>/apply", methods=["POST"])
@authorize(ROLE_BILLING_OPS)
def apply_adjustment(adjustment_id):
    adjustment = domain.adjustment_or_404(adjustment_id)
    line = db.invoice_lines[adjustment["invoice_line_id"]]
    invoice = invoice_of_line(line)

    if invoice["status"] not in ADJUSTABLE_INVOICE_STATES:
        raise ApiError("ERR_INVOICE_NOT_ADJUSTABLE",
                       "Only an ISSUED or ADJUSTED invoice admits adjustments.")
    if adjustment["status"] != "PROPOSED":
        raise ApiError("ERR_ADJUSTMENT_NOT_PENDING",
                       "The adjustment has already been applied or rejected.")
    if caller_id() == adjustment["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The operator who proposed an adjustment may not apply it.")
    if adjustment["delta_cents"] < 0:
        if domain.invoice_net_amount(invoice) + adjustment["delta_cents"] < 0:
            raise ApiError("ERR_CREDIT_EXCEEDS_INVOICE_NET",
                           "A credit may not push the invoice net below zero.")

    apply_adjustment_record(adjustment, caller_id())
    return success(ser.billing_adjustment(adjustment))


@bp.route("/billing-adjustments/<adjustment_id>/reject", methods=["POST"])
@authorize(ROLE_BILLING_OPS)
def reject_adjustment(adjustment_id):
    adjustment = domain.adjustment_or_404(adjustment_id)
    body = v.get_body()
    note = v.opt_string(body, "note")

    if adjustment["status"] != "PROPOSED":
        raise ApiError("ERR_ADJUSTMENT_NOT_PENDING",
                       "Only a PROPOSED adjustment may be rejected.")

    reject_adjustment_record(adjustment, note)
    line = db.invoice_lines[adjustment["invoice_line_id"]]
    invoice = invoice_of_line(line)
    if invoice is not None:
        touch(invoice)
    return success(ser.billing_adjustment(adjustment))


@bp.route("/billing-adjustments/<adjustment_id>", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def read_adjustment(adjustment_id):
    adjustment = domain.adjustment_or_404(adjustment_id)
    line = db.invoice_lines.get(adjustment["invoice_line_id"])
    if line is not None:
        enforce_shipper_scope(shipper_of_line(line))
    return success(ser.billing_adjustment(adjustment))


@bp.route("/billing-adjustments", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def list_adjustments():
    limit, offset = pagination_params()
    rows = sorted_records(list(db.billing_adjustments.values()))
    if is_shipper_user():
        rows = [r for r in rows
                if shipper_of_line(db.invoice_lines[r["invoice_line_id"]]) == caller_id()]
    for key in ("invoice_line_id", "dispute_id", "guarantee_claim_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, ser.billing_adjustment, limit, offset)

"""Outsourcing: engagements, the vendor cooldown and contractor invoices (PRD 3.8)."""

from flask import Blueprint, request

from calc import committed_basis_cents, vendor_cooldown_conflict
from envelope import created, success
from errors import ApiError
from guards import (
    ALL_ROLES,
    ROLE_DEVELOPER,
    ROLE_PUBLISHER_FINANCE,
    agreement_of_engagement,
    agreement_of_invoice,
    agreement_of_milestone,
    begin,
    body,
    find_engagement,
    find_invoice,
    find_milestone,
    require_party,
    visible,
)
from ledger import invoices_of_engagement
from listing import matches, paged
from money import apply_bps
from serializers import engagement as ser_engagement
from serializers import invoice as ser_invoice
from store import db, fmt_date, lock, new_id, now_iso, ordered, stamp_new, touch
from validation import Field, paging

bp = Blueprint("contractors", __name__)

INVOICE_TOLERANCE_BPS = 12500

ENGAGEMENT_FIELDS = (
    Field("milestone_id", "string", required=True),
    Field("vendor_code", "string", required=True, min_len=2, max_len=40, pattern=r"^[A-Z0-9-]+$"),
    Field("scope_summary", "string", required=True, min_len=1, max_len=300, non_blank=True),
    Field("committed_cents", "int", required=True, min=1),
    Field("start_date", "date", required=True),
    Field("end_date", "date", required=True),
)

INVOICE_FIELDS = (
    Field("engagement_id", "string", required=True),
    Field("invoice_number", "string", required=True, min_len=1, max_len=40),
    Field("amount_cents", "int", required=True, min=1),
    Field("period_end_date", "date", required=True),
    Field("description", "string"),
)

INVOICE_DECIDE_FIELDS = (
    Field("decision", "enum", required=True, values=("APPROVE", "REJECT")),
    Field("rejection_reason", "string"),
)

REASON_FIELDS = (Field("reason", "string"),)

OPEN_FOR_OUTSOURCING = ("DEFINED", "IN_DEVELOPMENT", "CURE_PENDING")


@bp.post("/contractor-engagements")
def create_engagement():
    actor = begin([ROLE_DEVELOPER])
    _, data = body(ENGAGEMENT_FIELDS)
    with lock:
        # Rule 19: engagement creation resolves milestone_id.
        milestone = find_milestone(data["milestone_id"])
        agreement = agreement_of_milestone(milestone)
        require_party(actor, agreement)
        # Rule 23.
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        # Rule 32: the state rule outranks the budget cap at rule 60.
        if milestone["status"] not in OPEN_FOR_OUTSOURCING:
            raise ApiError("ERR_MILESTONE_NOT_OPEN_FOR_OUTSOURCING")
        start = data["start_date"]
        end = data["end_date"]
        # Rule 55: the end may equal but never precede the start.
        if end < start:
            raise ApiError("ERR_INVALID_DATE_RANGE")
        studio_id = agreement["studio_id"]
        # Rule 56: the vendor cooldown, evaluated before the budget.
        if vendor_cooldown_conflict(studio_id, data["vendor_code"], start, end):
            raise ApiError("ERR_VENDOR_COOLDOWN_CONFLICT")
        # Rule 60: the committed basis plus this commitment must fit the budget.
        if (
            committed_basis_cents(milestone) + data["committed_cents"]
            > milestone["contractor_budget_cents"]
        ):
            raise ApiError("ERR_CONTRACTOR_BUDGET_EXCEEDED")

        row = {
            "id": new_id(),
            "milestone_id": milestone["id"],
            "studio_id": studio_id,
            "vendor_code": data["vendor_code"],
            "scope_summary": data["scope_summary"],
            "committed_cents": data["committed_cents"],
            "start_date": fmt_date(start),
            "end_date": fmt_date(end),
            "status": "PROPOSED" if milestone["status"] == "DEFINED" else "ACTIVE",
            "approved_invoice_total_cents": 0,
        }
        stamp_new(row)
        db.engagements[row["id"]] = row
        return created(ser_engagement(row))


@bp.get("/contractor-engagements/<eid>")
def read_engagement(eid):
    actor = begin(ALL_ROLES)
    with lock:
        engagement = find_engagement(eid)
        require_party(actor, agreement_of_engagement(engagement))
        return success(ser_engagement(engagement))


@bp.get("/contractor-engagements")
def list_engagements():
    actor = begin(ALL_ROLES)
    with lock:
        rows = [
            row for row in ordered(db.engagements.values())
            if matches(row, request.args, ("milestone_id", "studio_id", "vendor_code", "status"))
        ]
        rows = visible(actor, rows, agreement_of_engagement)
        return paged(rows, request.args, ser_engagement)


@bp.post("/contractor-engagements/<eid>/complete")
def complete_engagement(eid):
    actor = begin([ROLE_DEVELOPER])
    with lock:
        engagement = find_engagement(eid)
        require_party(actor, agreement_of_engagement(engagement))
        # Rule 39 then rule 65.
        if engagement["status"] != "ACTIVE":
            raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")
        if any(i["status"] == "SUBMITTED" for i in invoices_of_engagement(engagement)):
            raise ApiError("ERR_ENGAGEMENT_HAS_OPEN_INVOICES")
        engagement["status"] = "COMPLETED"
        touch(engagement)
        return success(ser_engagement(engagement))


@bp.post("/contractor-engagements/<eid>/cancel")
def cancel_engagement(eid):
    actor = begin([ROLE_DEVELOPER])
    body(REASON_FIELDS)
    with lock:
        engagement = find_engagement(eid)
        require_party(actor, agreement_of_engagement(engagement))
        # Rule 39 then rule 66.
        if engagement["status"] not in ("PROPOSED", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")
        if engagement["approved_invoice_total_cents"] > 0:
            raise ApiError("ERR_ENGAGEMENT_HAS_APPROVED_INVOICES")
        engagement["status"] = "CANCELLED"
        touch(engagement)
        for invoice in invoices_of_engagement(engagement):
            if invoice["status"] == "SUBMITTED":
                invoice["status"] = "VOIDED"
                touch(invoice)
        return success(ser_engagement(engagement))


@bp.post("/contractor-invoices")
def create_invoice():
    actor = begin([ROLE_DEVELOPER])
    _, data = body(INVOICE_FIELDS)
    with lock:
        # Rule 19: invoice creation resolves engagement_id.
        engagement = find_engagement(data["engagement_id"])
        agreement = agreement_of_engagement(engagement)
        require_party(actor, agreement)
        # Rule 23.
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        # Rule 38: only an ACTIVE or COMPLETED engagement may be invoiced.
        if engagement["status"] not in ("ACTIVE", "COMPLETED"):
            raise ApiError("ERR_ENGAGEMENT_NOT_INVOICEABLE")
        # Rule 41: the number is reserved by every sibling invoice, voided ones included.
        for sibling in invoices_of_engagement(engagement):
            if sibling["invoice_number"] == data["invoice_number"]:
                raise ApiError("ERR_INVOICE_NUMBER_TAKEN")

        row = {
            "id": new_id(),
            "engagement_id": engagement["id"],
            "invoice_number": data["invoice_number"],
            "amount_cents": data["amount_cents"],
            "period_end_date": fmt_date(data["period_end_date"]),
            "description": data.get("description"),
            "status": "SUBMITTED",
            "rejection_reason": None,
            "decided_at": None,
        }
        stamp_new(row)
        db.invoices[row["id"]] = row
        return created(ser_invoice(row))


@bp.get("/contractor-invoices/<iid>")
def read_invoice(iid):
    actor = begin(ALL_ROLES)
    with lock:
        invoice = find_invoice(iid)
        require_party(actor, agreement_of_invoice(invoice))
        return success(ser_invoice(invoice))


@bp.get("/contractor-engagements/<eid>/invoices")
def list_engagement_invoices(eid):
    actor = begin(ALL_ROLES)
    paging(request.args)
    with lock:
        engagement = find_engagement(eid)
        require_party(actor, agreement_of_engagement(engagement))
        rows = [
            row for row in invoices_of_engagement(engagement)
            if matches(row, request.args, ("status",))
        ]
        return paged(rows, request.args, ser_invoice)


@bp.post("/contractor-invoices/<iid>/decide")
def decide_invoice(iid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    _, data = body(INVOICE_DECIDE_FIELDS)
    decision = data["decision"]
    reason = data.get("rejection_reason")
    # A rejection must carry its reason; that is a structural defect (rule 6).
    if decision == "REJECT" and (reason is None or reason.strip() == ""):
        raise ApiError(
            "ERR_INVALID_REQUEST", "rejection_reason is required when decision is REJECT."
        )
    with lock:
        invoice = find_invoice(iid)
        engagement = find_engagement(invoice["engagement_id"])
        agreement = agreement_of_engagement(engagement)
        require_party(actor, agreement)
        # Rule 23.
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        # Rule 38 outranks rule 40, and on a decision it binds approvals only:
        # "rejecting is always available while the invoice is still SUBMITTED".
        # An approval needs an ACTIVE engagement -- not merely COMPLETED -- whose
        # milestone is not CANCELLED.
        if decision == "APPROVE":
            milestone = db.milestones.get(engagement["milestone_id"])
            if engagement["status"] != "ACTIVE" or (
                milestone is not None and milestone["status"] == "CANCELLED"
            ):
                raise ApiError("ERR_ENGAGEMENT_NOT_INVOICEABLE")
        # Rule 40.
        if invoice["status"] != "SUBMITTED":
            raise ApiError("ERR_INVOICE_NOT_SUBMITTED")

        if decision == "APPROVE":
            # Rule 61: approvals may overrun the commitment by the tolerance only.
            ceiling = apply_bps(engagement["committed_cents"], INVOICE_TOLERANCE_BPS)
            if engagement["approved_invoice_total_cents"] + invoice["amount_cents"] > ceiling:
                raise ApiError("ERR_INVOICE_EXCEEDS_ENGAGEMENT")
            invoice["status"] = "APPROVED"
            engagement["approved_invoice_total_cents"] += invoice["amount_cents"]
            touch(engagement)
        else:
            invoice["status"] = "REJECTED"
            invoice["rejection_reason"] = reason
        invoice["decided_at"] = now_iso()
        touch(invoice)
        return success(ser_invoice(invoice))

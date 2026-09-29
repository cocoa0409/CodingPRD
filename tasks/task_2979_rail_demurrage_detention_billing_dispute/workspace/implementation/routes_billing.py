"""Invoicing, closing and the average-agreement programme (PRD §3.7)."""

from flask import Blueprint, request

import guards
import schema
from auth import (ROLE_ADJUDICATOR, ROLE_BILLING, ROLE_CUSTOMER, ROLE_REGULATOR,
                  authenticate, require_owner)
from cascade import (apply_agreement_credit, rebuild_agreement_days,
                     reverse_agreement_credit)
from clockcal import add_days, date_of, eod
from derive import (agreement_json, invoice_json, invoice_status,
                    live_charges_of_invoice)
from envelope import listing, ok
from errors import fail
from store import base_record, db, touch

bp = Blueprint("billing", __name__)

DISPUTE_WINDOW_CALENDAR_DAYS = 30
DEFAULT_CREDIT_CAP_RATIO = 0.30


# --------------------------------------------------------------------------
# opening an invoice, which is also the attachment operation
# --------------------------------------------------------------------------

@bp.post("/invoices")
def create_invoice():
    authenticate(ROLE_BILLING)
    data = schema.body()
    with db.lock:
        # Band 7: the single body reference.
        raw_customer = schema.opt_ref(data, "customer_id")
        if raw_customer is not None:
            guards.customer(raw_customer)

        # Band 8.
        customer_id = schema.req_ref(data, "customer_id")
        start = schema.req_instant(data, "billing_period_start")
        end = schema.req_instant(data, "billing_period_end")

        # Band 20: an inverted period reports the cluster-window code.
        if start > end:
            fail("ERR_INVALID_CLUSTER_WINDOW",
                 "billing_period_start must not be after billing_period_end.")

        rec = base_record("invoice")
        rec.update({
            "customer_id": customer_id,
            "billing_period_start": start,
            "billing_period_end": end,
            "agreement_credit_cents": 0,
            "dispute_deadline_at": None,
            "status_base": "DRAFT",
        })
        db.invoices[rec["id"]] = rec

        # Attach every eligible final line.  The cycle keeps its movement
        # dimension; only the money dimension moves.
        for charge in db.ordered("charges"):
            if charge["status"] != "FINAL" or charge["invoice_id"] is not None:
                continue
            cycle = db.cycles.get(charge["placement_cycle_id"])
            if cycle is None or cycle["customer_id"] != customer_id:
                continue
            released = cycle.get("released_at")
            if released is None or released < start or released > end:
                continue
            charge["invoice_id"] = rec["id"]
            cycle["billing_status"] = "INVOICED"
        return ok(invoice_json(rec), 201)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    actor = authenticate(ROLE_CUSTOMER, ROLE_ADJUDICATOR, ROLE_REGULATOR,
                         ROLE_BILLING)
    with db.lock:
        rec = guards.invoice(iid)
        require_owner(actor, rec["customer_id"])
        return ok(invoice_json(rec))


@bp.get("/invoices")
def list_invoices():
    actor = authenticate(ROLE_CUSTOMER, ROLE_BILLING)
    with db.lock:
        rows = db.ordered("invoices")
        customer_id = request.args.get("customer_id")
        if customer_id is not None:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        status = request.args.get("status")
        if status is not None:
            # The filter runs against the compound derived status, not the
            # stored base.
            rows = [r for r in rows if invoice_status(r) == status]
        if actor.is_customer:
            rows = [r for r in rows if r["customer_id"] == actor.user_id]
        return listing(rows, invoice_json)


# --------------------------------------------------------------------------
# issuing is one-way, because the deadline is derived from the clock
# --------------------------------------------------------------------------

@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    authenticate(ROLE_BILLING)
    with db.lock:
        rec = guards.invoice(iid)
        if rec["status_base"] != "DRAFT":
            fail("ERR_INVOICE_INVALID_STATE", "Only a DRAFT invoice can be issued.")
        if not live_charges_of_invoice(rec["id"]):
            fail("ERR_INVOICE_NO_CHARGES",
                 "An invoice with no live charge line cannot be issued.")

        rec["status_base"] = "ISSUED"
        # The rollup itself is a read-side derivation; issuing's own work is the
        # agreement credit and the dispute window.
        apply_agreement_credit(rec)
        rec["dispute_deadline_at"] = eod(
            add_days(date_of(db.now()), DISPUTE_WINDOW_CALENDAR_DAYS))
        touch(rec)
        return ok(invoice_json(rec))


@bp.post("/invoices/<iid>/close")
def close_invoice(iid):
    authenticate(ROLE_BILLING)
    with db.lock:
        rec = guards.invoice(iid)
        status = invoice_status(rec)
        if status not in ("ISSUED", "ADJUSTED"):
            # DRAFT, PARTIALLY_DISPUTED and CLOSED all report the same code.
            fail("ERR_INVOICE_INVALID_STATE",
                 "Only an ISSUED or ADJUSTED invoice can be closed.")

        rec["status_base"] = "CLOSED"
        for charge in live_charges_of_invoice(rec["id"]):
            cycle = db.cycles.get(charge["placement_cycle_id"])
            if cycle is not None:
                cycle["billing_status"] = "SETTLED"
        for dispute in db.disputes.values():
            # An ESCALATED dispute is deliberately left alone: only a DECIDED
            # one is swept, so a closed invoice may still carry an escalation.
            if dispute["invoice_id"] == rec["id"] and dispute["status"] == "DECIDED":
                dispute["status"] = "CLOSED"
        touch(rec)
        return ok(invoice_json(rec))


# --------------------------------------------------------------------------
# average agreements
# --------------------------------------------------------------------------

@bp.post("/average-agreements")
def create_agreement():
    authenticate(ROLE_BILLING)
    data = schema.body()
    with db.lock:
        raw_customer = schema.opt_ref(data, "customer_id")
        if raw_customer is not None:
            guards.customer(raw_customer)

        customer_id = schema.req_ref(data, "customer_id")
        month = schema.req_str(data, "agreement_month", None, None,
                              schema.AGREEMENT_MONTH_RE)
        ratio = schema.opt_number(data, "credit_cap_ratio",
                                  DEFAULT_CREDIT_CAP_RATIO, 0, 1,
                                  lo_exclusive=True, max_decimals=2)

        # Band 22: a RECONCILED or FORFEITED month does not block a new one.
        for other in db.agreements.values():
            if (other["customer_id"] == customer_id
                    and other["agreement_month"] == month
                    and other["status"] == "OPEN"):
                fail("ERR_DUPLICATE_AGREEMENT_MONTH",
                     "This consignee already holds an OPEN agreement for %s."
                     % month)

        rec = base_record("agreement")
        rec.update({
            "customer_id": customer_id,
            "agreement_month": month,
            "credit_cap_ratio": ratio,
            "credit_days_earned": 0,
            "debit_days_incurred": 0,
            "net_days": 0,
            "agreement_credit_cents": 0,
            "status": "OPEN",
        })
        db.agreements[rec["id"]] = rec
        return ok(agreement_json(rec), 201)


@bp.post("/average-agreements/<aid>/reconcile")
def reconcile_agreement(aid):
    authenticate(ROLE_BILLING)
    with db.lock:
        rec = guards.agreement(aid)
        if rec["status"] != "OPEN":
            fail("ERR_AGREEMENT_INVALID_STATE",
                 "Only an OPEN agreement can be reconciled.")

        rebuild_agreement_days(rec)
        if rec["net_days"] >= 0:
            # The credit landed at issue time is honoured as it stands.
            rec["status"] = "RECONCILED"
        else:
            rec["status"] = "FORFEITED"
            reverse_agreement_credit(rec)
        touch(rec)
        return ok(agreement_json(rec))

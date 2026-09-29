"""Cascades shared by more than one endpoint (PRD 3.5, 3.7, 3.8)."""
import calc
from db import db
from money import ZERO2, ZERO4, q2


def release_payable(consultant_invoice):
    """PRD 3.5: either route raises the subcontract's released_to_date and
    increments both the payable's version and the subcontract's version by 1.
    When released_to_date reaches or passes committed_amount the subcontract
    moves EXECUTED -> CLOSED, which lowers the phase's consultant_committed_open."""
    consultant_invoice["payment_status"] = "RELEASED"
    calc.touch(consultant_invoice)
    sub = calc.subcontract_of(consultant_invoice)
    if sub is None:
        return
    calc.touch(sub)
    if sub["status"] == "EXECUTED" and \
            calc.subcontract_released_to_date(sub) >= sub["committed_amount"]:
        sub["status"] = "CLOSED"
        calc.touch(sub)
        phase = db.phases.get(sub["phase_id"])
        if phase is not None:
            calc.touch(phase)


def release_payables_of_invoice(invoice):
    """PRD 3.5: when the client invoice carrying the payable reaches PAID, or
    reaches WRITTEN_OFF, every payable on it whose approval_status is APPROVED,
    whose payment_status is WITHHELD and whose billing_status is
    BILLED_TO_CLIENT moves to RELEASED."""
    rows = [c for c in db.consultant_invoices.values()
            if c["client_invoice_id"] == invoice["id"]
            and c["approval_status"] == "APPROVED"
            and c["payment_status"] == "WITHHELD"
            and c["billing_status"] == "BILLED_TO_CLIENT"]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for c in rows:
        release_payable(c)


def apply_sweep(invoice, labor, expenses, payables):
    """PRD 3.7: every swept time entry moves to BILLED with its
    billed_invoice_id set, every swept expense moves to BILLED, every swept
    payable moves to BILLED_TO_CLIENT. Rows already attached to this same
    invoice (the revise path) stay attached and are not re-stamped."""
    for e in labor:
        if e["billed_invoice_id"] != invoice["id"]:
            e["status"] = "BILLED"
            e["billed_invoice_id"] = invoice["id"]
            calc.touch(e)
    for x in expenses:
        if x["billed_invoice_id"] != invoice["id"]:
            x["billing_status"] = "BILLED"
            x["billed_invoice_id"] = invoice["id"]
            calc.touch(x)
    for c in payables:
        if c["client_invoice_id"] != invoice["id"]:
            c["billing_status"] = "BILLED_TO_CLIENT"
            c["client_invoice_id"] = invoice["id"]
            calc.touch(c)


def sweep_totals(labor, expenses, payables):
    labor_billed = ZERO2
    for e in labor:
        labor_billed += e["billable_amount"]
    expense_billed = ZERO2
    for x in expenses:
        expense_billed += x["billable_amount"]
    consultant_billed = ZERO2
    for c in payables:
        consultant_billed += c["billable_amount"]
    labor_billed = q2(labor_billed)
    expense_billed = q2(expense_billed)
    consultant_billed = q2(consultant_billed)
    gross = q2(labor_billed + consultant_billed + expense_billed)
    return labor_billed, expense_billed, consultant_billed, gross


def write_invoice_figures(invoice, client, labor, expenses, payables):
    """The pinned order of PRD 3.7: tier on pre-discount gross, then discount,
    then retainage on the post-discount base, then net_due."""
    labor_billed, expense_billed, consultant_billed, gross = sweep_totals(labor, expenses, payables)
    pct, discount, retainage, net_due = calc.invoice_money_figures(gross, client)
    invoice["labor_billed"] = labor_billed
    invoice["expense_billed"] = expense_billed
    invoice["consultant_billed"] = consultant_billed
    invoice["gross_billed"] = gross
    invoice["volume_discount_pct"] = pct
    invoice["discount_amount"] = discount
    invoice["retainage_amount"] = retainage
    invoice["net_due"] = net_due
    invoice["swept_labor_count"] = len(labor)
    invoice["swept_expense_count"] = len(expenses)
    invoice["swept_consultant_count"] = len(payables)
    invoice["backup_missing_count"] = len([c for c in payables if not c["backup_attached"]])


def detach_invoice(invoice):
    """PRD 3.7 void: every attached time entry moves BILLED -> APPROVED, every
    attached expense BILLED -> UNBILLED, every attached payable
    BILLED_TO_CLIENT -> UNBILLED (the last only while still WITHHELD), each with
    its invoice link cleared."""
    entries = [e for e in db.time_entries.values() if e["billed_invoice_id"] == invoice["id"]]
    entries.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for e in entries:
        e["status"] = "APPROVED"
        e["billed_invoice_id"] = None
        calc.touch(e)
    expenses = [x for x in db.expenses.values() if x["billed_invoice_id"] == invoice["id"]]
    expenses.sort(key=lambda x: (x["created_at"], x["_seq"]))
    for x in expenses:
        x["billing_status"] = "UNBILLED"
        x["billed_invoice_id"] = None
        calc.touch(x)
    payables = [c for c in db.consultant_invoices.values()
                if c["client_invoice_id"] == invoice["id"] and c["payment_status"] == "WITHHELD"]
    payables.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for c in payables:
        c["billing_status"] = "UNBILLED"
        c["client_invoice_id"] = None
        calc.touch(c)


def write_off_labor(write_off):
    """PRD 3.8: every time entry named in allocated_time_entry_ids moves
    APPROVED -> WRITTEN_OFF, each such entry's version incrementing by 1."""
    for entry_id in write_off["allocated_time_entry_ids"]:
        entry = db.time_entries.get(entry_id)
        if entry is None or entry["status"] != "APPROVED":
            continue
        entry["status"] = "WRITTEN_OFF"
        calc.touch(entry)

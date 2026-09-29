"""Shared services: the identity ladder rungs, lookups, customer scoping,
live aggregates, the ledger and every cross-entity cascade of PRD 3.

Version discipline (PRD 2.4): every named transition / cascade / recomputation
that actually changes a row refreshes that row's updated_at and increments its
version by exactly 1. Rows whose values do not change are not touched.
"""

from decimal import Decimal

from flask import request

from calc import (BILLING_CYCLE_DAYS, CREW_TRAVEL_BUFFER_MINUTES, DELIVERY_FEE_CENTS,
                  NET_TERMS_DAYS, ceil_div, invoice_rollup, round_half_up)
from errors import NOT_FOUND, fail
from store import store
from validation import iso_ms, plus_days, plus_seconds

ALL_ROLES = ("PlatformAdmin", "AccountManager", "CustomerContact",
             "DispatchCoordinator", "MunicipalLiaison", "YardAuditor")

KIND_OF_COLLECTION = {
    "municipalities": "municipality",
    "accounts": "account",
    "jobsites": "jobsite",
    "products": "product",
    "crews": "crew",
    "quotes": "quote",
    "permits": "permit",
    "contracts": "contract",
    "work_orders": "work_order",
    "invoices": "invoice",
    "reconciliations": "reconciliation",
}


class Identity(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == "CustomerContact"


# ---------------------------------------------------------------------------
# Rungs 1 and 2
# ---------------------------------------------------------------------------

def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must both be present and non-empty.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role '%s' may not call this endpoint." % role)
    return Identity(user_id, role)


# ---------------------------------------------------------------------------
# Rungs 4 and 5
# ---------------------------------------------------------------------------

def lookup(collection, row_id):
    row = store.collection(collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(NOT_FOUND[KIND_OF_COLLECTION[collection]],
             "No %s resolves the supplied identifier." % KIND_OF_COLLECTION[collection])
    return row


def product_by_code(code):
    for row in store.sorted_rows("products"):
        if row["code"] == code:
            return row
    fail("ERR_PRODUCT_NOT_FOUND", "No product carries code '%s'." % code)


def find_product_by_code(code):
    for row in store.sorted_rows("products"):
        if row["code"] == code:
            return row
    return None


# ---------------------------------------------------------------------------
# Rung 6 — customer account scoping
# ---------------------------------------------------------------------------

def account_of_jobsite(jobsite):
    return jobsite["customer_account_id"]


def account_of_quote(quote):
    return lookup("jobsites", quote["jobsite_id"])["customer_account_id"]


def account_of_permit(permit):
    return lookup("jobsites", permit["jobsite_id"])["customer_account_id"]


def account_of_contract(contract):
    return contract["customer_account_id"]


def account_of_work_order(work_order):
    return lookup("contracts", work_order["contract_id"])["customer_account_id"]


def account_of_invoice(invoice):
    return lookup("contracts", invoice["contract_id"])["customer_account_id"]


def account_of_reconciliation(recon):
    return lookup("contracts", recon["contract_id"])["customer_account_id"]


def enforce_scope(identity, account_id):
    """A CustomerContact may only touch rows resolving to its own account."""
    if identity.is_customer and identity.user_id != account_id:
        fail("ERR_ACCOUNT_SCOPE_VIOLATION",
             "This resource belongs to a different customer account.")


# ---------------------------------------------------------------------------
# Live aggregates
# ---------------------------------------------------------------------------

def municipality_of_jobsite(jobsite):
    return lookup("municipalities", jobsite["municipality_id"])


def municipality_of_permit(permit):
    return municipality_of_jobsite(lookup("jobsites", permit["jobsite_id"]))


def committed_closure_linear_feet(municipality_id):
    """PRD 3.1: SUBMITTED/APPROVED permits whose half-open window holds the clock."""
    clock = store.clock
    total = 0
    for permit in store.sorted_rows("permits"):
        if permit["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        jobsite = store.jobsites.get(permit["jobsite_id"])
        if jobsite is None or jobsite["municipality_id"] != municipality_id:
            continue
        if permit["closure_start_utc"] <= clock < permit["closure_end_utc"]:
            total += permit["closure_linear_feet"]
    return total


def windows_intersect(a_start, a_end, b_start, b_end):
    """PRD 2.6: half-open windows intersect iff each starts before the other ends."""
    return a_start < b_end and b_start < a_end


def contract_invoices(contract_id):
    return [row for row in store.sorted_rows("invoices") if row["contract_id"] == contract_id]


def account_invoices(account_id):
    rows = []
    for invoice in store.sorted_rows("invoices"):
        contract = store.contracts.get(invoice["contract_id"])
        if contract is not None and contract["customer_account_id"] == account_id:
            rows.append(invoice)
    return rows


def open_amount(invoice):
    return invoice["total_cents"] - invoice["amount_paid_cents"]


def account_open_balance(account_id):
    """W4: sum of the open amount over ISSUED and PARTIALLY_PAID invoices."""
    return sum(open_amount(inv) for inv in account_invoices(account_id)
               if inv["status"] in ("ISSUED", "PARTIALLY_PAID"))


def recompute_account(account, credited_delta=0):
    """W4/W5 inside the disturbing request; W6 adds to lifetime_credited_cents."""
    new_balance = account_open_balance(account["id"])
    new_credited = account["lifetime_credited_cents"] + credited_delta
    new_hold = new_balance > account["credit_limit_cents"]
    if (new_balance != account["open_balance_cents"]
            or new_credited != account["lifetime_credited_cents"]
            or new_hold != account["credit_hold_flag"]):
        account["open_balance_cents"] = new_balance
        account["lifetime_credited_cents"] = new_credited
        account["credit_hold_flag"] = new_hold
        store.touch(account)
    return account


def account_of(contract):
    return lookup("accounts", contract["customer_account_id"])


# ---------------------------------------------------------------------------
# Fleet buckets (PRD 2.10) — units move, they are never created or destroyed
# ---------------------------------------------------------------------------

def move_fleet(product, source, target, count):
    if count <= 0 or source == target:
        return
    product[source] -= count
    product[target] += count
    store.touch(product)


def panel_commitment(contract):
    """The first entry of fleet_commitments is always the panel entry (PRD 3.3)."""
    commitments = contract["fleet_commitments"]
    return commitments[0] if commitments else None


def addon_commitments(contract):
    return contract["fleet_commitments"][1:]


def addon_unit_total(contract):
    return sum(entry["unit_count"] for entry in addon_commitments(contract))


def contract_panel_product(contract):
    entry = panel_commitment(contract)
    return product_by_code(entry["product_code"])


def contract_quote(contract):
    return lookup("quotes", contract["quote_id"])


def contract_jurisdiction(contract):
    return municipality_of_jobsite(lookup("jobsites", contract["jobsite_id"]))


def panels_for_feet(linear_feet, panel_product):
    return ceil_div(linear_feet, panel_product["panel_length_ft"])


# ---------------------------------------------------------------------------
# The money dimension (PRD 3.8)
# ---------------------------------------------------------------------------

def past_due_open_cents(contract_id):
    """Open amount over the contract's invoices already due at the clock."""
    clock = store.clock
    total = 0
    for invoice in contract_invoices(contract_id):
        if invoice["status"] in ("ISSUED", "PARTIALLY_PAID") and invoice["due_at_utc"] <= clock:
            total += open_amount(invoice)
    return total


def has_overdue_invoice(contract_id):
    clock = store.clock
    for invoice in contract_invoices(contract_id):
        if invoice["status"] in ("ISSUED", "PARTIALLY_PAID") and invoice["due_at_utc"] <= clock:
            return True
    return False


def has_open_invoice(contract_id):
    for invoice in contract_invoices(contract_id):
        if invoice["status"] in ("ISSUED", "PARTIALLY_PAID"):
            return True
    return False


def all_invoices_settled(contract_id):
    invoices = contract_invoices(contract_id)
    if not invoices:
        return False
    return all(inv["status"] in ("PAID", "VOID") for inv in invoices)


def set_billing_status(contract, new_status):
    if contract["billing_status"] != new_status:
        contract["billing_status"] = new_status
        store.touch(contract)


def reevaluate_past_due(contract):
    """CURRENT -> PAST_DUE, evaluated at the start of a billing run and on a payment."""
    if contract["billing_status"] == "CURRENT" and has_overdue_invoice(contract["id"]):
        set_billing_status(contract, "PAST_DUE")


def reevaluate_billing_on_payment(contract):
    if contract["billing_status"] in ("CURRENT", "PAST_DUE") and all_invoices_settled(contract["id"]):
        set_billing_status(contract, "SETTLED")
        return
    if contract["billing_status"] == "CURRENT":
        if has_overdue_invoice(contract["id"]):
            set_billing_status(contract, "PAST_DUE")
        return
    if contract["billing_status"] == "PAST_DUE":
        if not has_overdue_invoice(contract["id"]) and has_open_invoice(contract["id"]):
            set_billing_status(contract, "CURRENT")


def reevaluate_billing_on_void(contract):
    if contract["billing_status"] in ("CURRENT", "PAST_DUE") and all_invoices_settled(contract["id"]):
        set_billing_status(contract, "SETTLED")


def billing_status_on_issuance(contract):
    """NOT_BILLED -> CURRENT on the first invoice; SETTLED -> CURRENT on a re-open."""
    status = contract["billing_status"]
    if status == "NOT_BILLED":
        set_billing_status(contract, "CURRENT")
    elif status == "SETTLED" and contract["lifecycle_status"] != "CLOSED":
        set_billing_status(contract, "CURRENT")


def new_line(line_type, amount_cents, product_code=None, quantity=1):
    return {
        "line_type": line_type,
        "product_code": product_code,
        "quantity": quantity,
        "amount_cents": amount_cents,
    }


def issue_invoice(contract, invoice_kind, lines, actor_user_id,
                  period_start=None, period_end=None, billable_days=0,
                  billing_status_at_start=None):
    """PRD 3.8 issuance: rollup, then the money dimension, then the account."""
    jurisdiction = contract_jurisdiction(contract)
    if billing_status_at_start is None:
        billing_status_at_start = contract["billing_status"]
    apply_late_fee = (billing_status_at_start == "PAST_DUE" and invoice_kind == "PERIODIC")
    past_due_open = past_due_open_cents(contract["id"]) if apply_late_fee else 0
    subtotal, tax, late_fee, total = invoice_rollup(
        lines, jurisdiction["rental_tax_rate_bp"], past_due_open, apply_late_fee)

    clock = store.clock
    invoice = store.new_row("invoices")
    invoice.update({
        "contract_id": contract["id"],
        "invoice_kind": invoice_kind,
        "period_start_utc": period_start,
        "period_end_utc": period_end,
        "billable_days": billable_days if invoice_kind == "PERIODIC" else 0,
        "lines": lines,
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "late_fee_cents": late_fee,
        "total_cents": total,
        "amount_paid_cents": 0,
        "status": "ISSUED",
        "issued_at_utc": clock,
        "due_at_utc": plus_days(clock, NET_TERMS_DAYS),
        "issued_by_user_id": actor_user_id,
        "void_reason_code": None,
    })
    store.invoices[invoice["id"]] = invoice

    billing_status_on_issuance(contract)
    recompute_account(account_of(contract))
    return invoice


def allocate_payment(account, amount_cents):
    """PRD 3.8 waterfall: oldest due first, no proportional spreading."""
    open_invoices = [inv for inv in account_invoices(account["id"])
                     if inv["status"] in ("ISSUED", "PARTIALLY_PAID")]
    open_invoices.sort(key=lambda inv: (inv["due_at_utc"], inv["created_at"], inv["id"]))
    total_open = sum(open_amount(inv) for inv in open_invoices)
    if amount_cents > total_open:
        fail("ERR_PAYMENT_EXCEEDS_BALANCE",
             "The payment exceeds the account's total open invoice amount.")
    remaining = amount_cents
    touched = []
    for invoice in open_invoices:
        if remaining <= 0:
            break
        absorbed = min(remaining, open_amount(invoice))
        if absorbed <= 0:
            continue
        invoice["amount_paid_cents"] += absorbed
        remaining -= absorbed
        invoice["status"] = ("PAID" if invoice["amount_paid_cents"] >= invoice["total_cents"]
                            else "PARTIALLY_PAID")
        store.touch(invoice)
        touched.append(invoice)
    return touched


# ---------------------------------------------------------------------------
# Cross-entity cascades (PRD 3.6, 3.7, 3.9)
# ---------------------------------------------------------------------------

def contract_work_orders(contract_id):
    return [row for row in store.sorted_rows("work_orders") if row["contract_id"] == contract_id]


def recompute_deployed_linear_feet(contract):
    """Sum of completed footage over the contract's COMPLETED/PARTIAL installs."""
    total = 0
    for order in contract_work_orders(contract["id"]):
        if order["work_order_type"] == "DELIVERY_INSTALL" and order["status"] in ("COMPLETED", "PARTIAL"):
            total += order["completed_linear_feet"]
    return total


def contract_permit_fee_cents(contract):
    """The permit coordination fee frozen into the contract's one-time total."""
    return contract["one_time_cents"] - contract["install_labor_cents"] - DELIVERY_FEE_CENTS


def mobilize_contract(contract, actor_user_id):
    """PRD 3.6: PENDING_MOBILIZATION -> ACTIVE with its invoice and fleet hops."""
    if contract["lifecycle_status"] != "PENDING_MOBILIZATION":
        return None
    contract["lifecycle_status"] = "ACTIVE"
    contract["billing_anchor_utc"] = store.clock
    contract["deployed_linear_feet"] = recompute_deployed_linear_feet(contract)
    contract["addons_deployed"] = True
    store.touch(contract)
    for entry in addon_commitments(contract):
        product = product_by_code(entry["product_code"])
        move_fleet(product, "available_count", "deployed_count", entry["unit_count"])
    lines = [new_line("INSTALL_LABOR", contract["install_labor_cents"]),
             new_line("DELIVERY", DELIVERY_FEE_CENTS)]
    permit_fee = contract_permit_fee_cents(contract)
    if permit_fee != 0:
        lines.append(new_line("PERMIT_HANDLING", permit_fee))
    return issue_invoice(contract, "MOBILIZATION", lines, actor_user_id)


def open_reconciliation(contract, work_order):
    """PRD 3.7: the yard's expectation, snapshotted at demobilization."""
    panel_product = contract_panel_product(contract)
    snapshot = [{
        "product_code": panel_product["code"],
        "unit_count": panels_for_feet(contract["deployed_linear_feet"], panel_product),
    }]
    if contract["addons_deployed"]:
        for entry in addon_commitments(contract):
            snapshot.append({"product_code": entry["product_code"],
                             "unit_count": entry["unit_count"]})
    recon = store.new_row("reconciliations")
    recon.update({
        "contract_id": contract["id"],
        "work_order_id": work_order["id"],
        "deployed_snapshot": snapshot,
        "unit_returns": [],
        "theft_police_report_number": None,
        "assessment_variant": None,
        "loss_charge_cents": 0,
        "damage_charge_cents": 0,
        "status": "OPEN",
        "finalized_by_user_id": None,
        "auditor_note": None,
    })
    store.reconciliations[recon["id"]] = recon
    return recon


def close_approved_permits(jobsite_id):
    """PRD 3.4: an approved permit is retired by the fence coming down."""
    closed = []
    for permit in store.sorted_rows("permits"):
        if permit["jobsite_id"] == jobsite_id and permit["status"] == "APPROVED":
            permit["status"] = "CLOSED"
            store.touch(permit)
            closed.append(permit)
    return closed


def demobilize_contract(contract, work_order):
    """PRD 3.6: ACTIVE -> DEMOBILIZING, opening the reconciliation and closing permits."""
    contract["lifecycle_status"] = "DEMOBILIZING"
    store.touch(contract)
    recon = open_reconciliation(contract, work_order)
    close_approved_permits(contract["jobsite_id"])
    return recon


def contract_reconciliation(contract_id):
    for recon in store.sorted_rows("reconciliations"):
        if recon["contract_id"] == contract_id:
            return recon
    return None


def maybe_close_contract(contract):
    """PRD 3.9: the one edge that reads both parallel dimensions at once."""
    if contract["lifecycle_status"] != "DEMOBILIZING":
        return False
    if contract["billing_status"] != "SETTLED":
        return False
    recon = contract_reconciliation(contract["id"])
    if recon is None or recon["status"] != "FINALIZED":
        return False
    contract["lifecycle_status"] = "CLOSED"
    store.touch(contract)
    return True


def release_reservation(work_order):
    """Compensating release: reserved units go back to the yard."""
    for entry in work_order["reserved_unit_counts"]:
        product = product_by_code(entry["product_code"])
        move_fleet(product, "reserved_count", "available_count", entry["unit_count"])
    work_order["reserved_unit_counts"] = []


def crew_committed_end(work_order):
    """A crew is blocked until 90 minutes after the visit's scheduled end."""
    return plus_seconds(work_order["scheduled_end_utc"], CREW_TRAVEL_BUFFER_MINUTES * 60)


def crew_scheduled_orders(crew_id, exclude_id=None):
    rows = []
    for order in store.sorted_rows("work_orders"):
        if order["status"] != "SCHEDULED" or order["crew_id"] != crew_id:
            continue
        if exclude_id is not None and order["id"] == exclude_id:
            continue
        rows.append(order)
    return rows


# ---------------------------------------------------------------------------
# List filters (PRD 2.3) — an unresolvable identifier filter is a not-found
# ---------------------------------------------------------------------------

def filter_fk(args, name, collection):
    if name not in args:
        return None
    row = lookup(collection, args.get(name))
    return row


def next_billing_floor(contract_id):
    """period_start must be at or after the newest PERIODIC invoice's period_end."""
    newest = None
    for invoice in contract_invoices(contract_id):
        if invoice["invoice_kind"] != "PERIODIC" or invoice["period_end_utc"] is None:
            continue
        if newest is None or invoice["_seq"] > newest["_seq"]:
            newest = invoice
    return None if newest is None else newest["period_end_utc"]

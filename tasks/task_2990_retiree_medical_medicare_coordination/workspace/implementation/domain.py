"""Shared lookups and the cascades that more than one endpoint drives."""

import calc
import errors
from errors import fail
from store import db, now, order_asc, touch

CLAIM_HELD_STATUSES = ("SUBMITTED", "PENDING_SUBSTANTIATION", "APPROVED")


# --- existence resolution (ladder steps 3-11) -------------------------------
def _resolve(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        fail(error_id)
    return row


def get_plan_year(pk):
    return _resolve(db.plan_years, pk, errors.ERR_PLAN_YEAR_NOT_FOUND)


def get_retiree(pk):
    return _resolve(db.retirees, pk, errors.ERR_RETIREE_NOT_FOUND)


def get_plan_option(pk):
    return _resolve(db.plan_options, pk, errors.ERR_PLAN_OPTION_NOT_FOUND)


def get_determination(pk):
    return _resolve(db.determinations, pk, errors.ERR_DETERMINATION_NOT_FOUND)


def get_election_event(pk):
    return _resolve(db.election_events, pk, errors.ERR_ELECTION_EVENT_NOT_FOUND)


def get_enrollment(pk):
    return _resolve(db.enrollments, pk, errors.ERR_ENROLLMENT_NOT_FOUND)


def get_hra_account(pk):
    return _resolve(db.hra_accounts, pk, errors.ERR_HRA_ACCOUNT_NOT_FOUND)


def get_claim(pk):
    return _resolve(db.claims, pk, errors.ERR_CLAIM_NOT_FOUND)


def get_invoice(pk):
    return _resolve(db.invoices, pk, errors.ERR_INVOICE_NOT_FOUND)


def body_reference(body, field, getter):
    """Resolve a body-carried foreign key.  A field that is absent or carries the
    wrong JSON type is left for the shape ladder (step 12) to report; a
    well-formed identifier that names nothing is a 404 here."""
    if not body.present(field):
        return None
    raw = body.value(field)
    if not isinstance(raw, str):
        return None
    return getter(raw)


# --- determination lookups --------------------------------------------------
def certified_determination(retiree_id, plan_year_id):
    rows = [d for d in db.determinations.values()
            if d["retiree_id"] == retiree_id
            and d["plan_year_id"] == plan_year_id
            and d["status"] == "CERTIFIED"]
    if not rows:
        return None
    return order_asc(rows)[-1]


def require_certified_eligible(retiree_id, plan_year_id):
    """Ladder steps 29 then 30, in that order."""
    determination = certified_determination(retiree_id, plan_year_id)
    if determination is None:
        fail(errors.ERR_DETERMINATION_NOT_CERTIFIED)
    if determination["outcome"] != "ELIGIBLE":
        fail(errors.ERR_NOT_ELIGIBLE_FOR_RETIREE_MEDICAL)
    return determination


# --- Medicare secondary payer -----------------------------------------------
def apply_msp(enrollment, retiree):
    """Write payer_order and msp_basis_code; returns True when either moved."""
    payer_order, basis = calc.msp_determination(retiree, now())
    changed = (enrollment.get("payer_order") != payer_order
               or enrollment.get("msp_basis_code") != basis)
    enrollment["payer_order"] = payer_order
    enrollment["msp_basis_code"] = basis
    return changed


def enrollments_of_retiree(retiree_id):
    return order_asc([e for e in db.enrollments.values()
                      if e["retiree_id"] == retiree_id])


def active_enrollments_of_retiree(retiree_id):
    return [e for e in enrollments_of_retiree(retiree_id)
            if e["coverage_status"] in calc.ACTIVE_COVERAGE_STATUSES]


# --- reimbursement account cascades -----------------------------------------
def open_account_for(retiree_id, plan_year_id, statuses=("OPEN",)):
    rows = [a for a in db.hra_accounts.values()
            if a["retiree_id"] == retiree_id
            and a["plan_year_id"] == plan_year_id
            and a["status"] in statuses]
    if not rows:
        return None
    return order_asc(rows)[0]


def claims_of_account(hra_account_id):
    return order_asc([c for c in db.claims.values()
                      if c["hra_account_id"] == hra_account_id])


def deny_held_claims(account):
    """Shed unfinished work: every held claim is denied and its hold released.
    The account's own version is advanced by the caller."""
    for claim in claims_of_account(account["id"]):
        if claim["status"] not in CLAIM_HELD_STATUSES:
            continue
        held = claim["eligible_cents"]
        account["pending_hold_cents"] -= held
        account["available_balance_cents"] += held
        claim["status"] = "DENIED"
        claim["denial_reason_code"] = "ACCOUNT_NOT_OPEN"
        touch(claim)


def freeze_account_for(retiree_id, plan_year_id):
    """Lapse cascade hop five, and hop six chained from it."""
    account = open_account_for(retiree_id, plan_year_id)
    if account is None:
        return None
    account["status"] = "FROZEN"
    deny_held_claims(account)
    touch(account)
    return account


# --- invoices ---------------------------------------------------------------
def invoices_of_enrollment(enrollment_id):
    return order_asc([i for i in db.invoices.values()
                      if i["enrollment_id"] == enrollment_id])


def write_off_invoices(enrollment_id, statuses):
    for invoice in invoices_of_enrollment(enrollment_id):
        if invoice["status"] in statuses:
            invoice["status"] = "WRITTEN_OFF"
            touch(invoice)


def outstanding_balance(invoice):
    return invoice["net_due_cents"] - invoice["paid_cents"]


# --- headcount conservation -------------------------------------------------
def adjust_enrolled_count(plan_option_id, delta):
    option = db.plan_options.get(plan_option_id)
    if option is None:
        return None
    option["enrolled_count"] += delta
    touch(option)
    return option


def terminate_coverage(enrollment, reason):
    """The compensating move for the increment an approval made."""
    enrollment["coverage_status"] = "TERMINATED"
    enrollment["coverage_end_date"] = now()
    enrollment["termination_reason"] = reason

"""Invoices: list, get, issue, pay, void."""
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope, active_grant
from errors import (ok, ok_list, invoice_not_payable, invalid_state, not_found,
                    needs_primary_admin, ApiError)
from helpers import (get_or_404, paginate, sort_by_created, filter_items,
                     company_subscription)
import serializers

bp = Blueprint("invoices", __name__, url_prefix="/api/companies/<company_id>")


def _get_invoice(company_id, iid):
    get_or_404("ClientCompany", company_id)
    inv = get_or_404("Invoice", iid)
    if inv["company_id"] != company_id:
        not_found("Invoice not in company")
    return inv


def _settle_bubble(sub):
    """After an invoice becomes PAID: PAST_DUE -> ACTIVE if no other unpaid;
    REACTIVATED -> ACTIVE on first successful payment."""
    others_unpaid = any(
        i["invoice_status"] in ("ISSUED", "PAST_DUE")
        for i in db.TABLES["Invoice"].values()
        if i["subscription_id"] == sub["id"])
    if sub["lifecycle_status"] == "PAST_DUE" and not others_unpaid:
        sub["lifecycle_status"] = "ACTIVE"
        sub["billing_status"] = "CURRENT"
        db.touch(sub)
    elif sub["lifecycle_status"] == "REACTIVATED":
        sub["lifecycle_status"] = "ACTIVE"
        db.touch(sub)


@bp.get("/invoices")
def list_invoices(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [i for i in db.TABLES["Invoice"].values() if i["company_id"] == company_id]
    items = filter_items(items, [("invoice_status", "invoice_status"),
                                 ("subscription_id", "subscription_id")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_invoice(i) for i in page], limit, offset, total)


@bp.get("/invoices/<iid>")
def get_invoice(company_id, iid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    inv = _get_invoice(company_id, iid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_invoice(inv))


@bp.post("/invoices/<iid>/issue")
def issue_invoice(company_id, iid):
    require_role(["PlatformAdmin"])
    inv = _get_invoice(company_id, iid)
    sub = db.TABLES["Subscription"].get(inv["subscription_id"])
    if inv["invoice_status"] == "ISSUED":
        # Idempotent re-issue: lines were snapshotted at issue time; return
        # the already-issued invoice.  (The activation flow issues the first
        # invoice through this same endpoint, so a second issue call on it
        # must not error.)
        return ok(serializers.serialize_invoice(inv))
    if inv["invoice_status"] != "DRAFT":
        # PRD: "to issue one that is not DRAFT — is rejected with
        # ERR_INVOICE_NOT_PAYABLE".
        invoice_not_payable()
    if sub is None or sub["lifecycle_status"] not in ("ACTIVE", "PAST_DUE", "REACTIVATED"):
        invalid_state("Subscription not issuable")
    company = db.TABLES["ClientCompany"].get(company_id)
    lines = services.compute_invoice_lines(
        company, sub, db.parse_iso(inv["period_start"]), db.parse_iso(inv["period_end"]))
    inv.update(lines)
    inv["invoice_status"] = "ISSUED"
    db.touch(inv)
    if sub is not None:
        # The next billing date is this invoice's period end.
        nxt = db.parse_iso(inv["period_end"])
        cur = db.parse_iso(sub["next_billing_at"]) if sub.get("next_billing_at") else None
        if cur is None or nxt > cur:
            sub["next_billing_at"] = db.fmt(nxt)
            db.touch(sub)
    return ok(serializers.serialize_invoice(inv))


@bp.post("/invoices/<iid>/pay")
def pay_invoice(company_id, iid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    inv = _get_invoice(company_id, iid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        if identity.get("permission_level") != "PRIMARY_ADMIN":
            needs_primary_admin()
    else:
        active_grant(identity, company_id, ("FULL_BOOKKEEPING",))
    if inv["invoice_status"] != "ISSUED":
        # PRD verbatim: "Attempting to pay an invoice that is not ISSUED ... is
        # rejected with ERR_INVOICE_NOT_PAYABLE."
        invoice_not_payable()
    inv["invoice_status"] = "PAID"
    db.touch(inv)
    sub = db.TABLES["Subscription"].get(inv["subscription_id"])
    if sub is not None:
        sub["payment_method_on_file"] = True
        _settle_bubble(sub)
    return ok(serializers.serialize_invoice(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(company_id, iid):
    require_role(["PlatformAdmin"])
    inv = _get_invoice(company_id, iid)
    if inv["invoice_status"] not in ("DRAFT", "ISSUED"):
        invoice_not_payable()
    inv["invoice_status"] = "VOID"
    db.touch(inv)
    return ok(serializers.serialize_invoice(inv))

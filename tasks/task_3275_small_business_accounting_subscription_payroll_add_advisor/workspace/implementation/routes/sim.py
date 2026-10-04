"""Test drivers: logical clock, payment simulation, bank feed tick."""
from datetime import timedelta
from flask import Blueprint
import db
import services
from auth import require_role
from errors import ok, invalid_request
from helpers import body_json, req_str, get_or_404
import serializers

bp = Blueprint("sim", __name__, url_prefix="/api")


def reevaluate_time_driven():
    """Called when the logical clock is set: trial expiry, transfer/grant/export
    expiry, consent expiry, invoice past-due / suspension."""
    now = db.now()

    # Trial expiry -> CANCELLED_READ_ONLY when no payment method on file
    for sub in db.TABLES["Subscription"].values():
        if sub["lifecycle_status"] == "TRIAL":
            trial_end = db.parse_iso(sub["trial_ends_at"])
            if trial_end is not None and now >= trial_end:
                if not sub.get("payment_method_on_file"):
                    sub["lifecycle_status"] = "CANCELLED_READ_ONLY"
                    sub["cancelled_at"] = db.fmt(trial_end)
                    sub["read_only_expires_at"] = db.fmt(trial_end + timedelta(days=365))
                    company = db.TABLES["ClientCompany"].get(sub["company_id"])
                    if company is not None:
                        company["company_status"] = "READ_ONLY"
                        db.touch(company)
                    sub["pending_upgrade_prompt"] = False
                    db.touch(sub)
    # Read-only expiry -> CANCELLED_EXPIRED, company PURGED
    for sub in db.TABLES["Subscription"].values():
        if sub["lifecycle_status"] == "CANCELLED_READ_ONLY":
            exp = db.parse_iso(sub.get("read_only_expires_at"))
            if exp is not None and now >= exp:
                sub["lifecycle_status"] = "CANCELLED_EXPIRED"
                db.touch(sub)
                company = db.TABLES["ClientCompany"].get(sub["company_id"])
                if company is not None:
                    company["company_status"] = "PURGED"
                    db.touch(company)
                for e in db.TABLES["ExportRequest"].values():
                    if e["company_id"] == sub["company_id"] and \
                            e["export_status"] in ("PENDING", "READY"):
                        e["export_status"] = "EXPIRED"
                        db.touch(e)
    # Invoice past-due / suspension bubble-ups
    for inv in db.TABLES["Invoice"].values():
        if inv["invoice_status"] == "ISSUED":
            end = db.parse_iso(inv["period_end"])
            if end is not None and now >= end + timedelta(days=5):
                inv["invoice_status"] = "PAST_DUE"
                db.touch(inv)
                sub = db.TABLES["Subscription"].get(inv["subscription_id"])
                if sub is not None and sub["lifecycle_status"] == "ACTIVE":
                    sub["lifecycle_status"] = "PAST_DUE"
                    sub["billing_status"] = "PAST_DUE"
                    db.touch(sub)
    for sub in db.TABLES["Subscription"].values():
        if sub["lifecycle_status"] in ("ACTIVE", "PAST_DUE"):
            for inv in db.TABLES["Invoice"].values():
                if inv["subscription_id"] == sub["id"] and \
                        inv["invoice_status"] == "PAST_DUE":
                    end = db.parse_iso(inv["period_end"])
                    if end is not None and now >= end + timedelta(days=35):
                        sub["lifecycle_status"] = "SUSPENDED"
                        sub["billing_status"] = "UNPAID"
                        db.touch(sub)
                        for p in db.TABLES["PayrollAddon"].values():
                            if p["subscription_id"] == sub["id"] and \
                                    p["addon_status"] == "ACTIVE":
                                p["addon_status"] = "PAUSED"
                                db.touch(p)
                        for c in db.TABLES["BankConnection"].values():
                            if c["company_id"] == sub["company_id"] and \
                                    c["connection_status"] == "ACTIVE":
                                c["connection_status"] = "STALE"
                                db.touch(c)
                        break
    # Billing transfer expiry
    for t in db.TABLES["BillingTransfer"].values():
        if t["transfer_status"] in ("PENDING_CLIENT_ACCEPT", "PENDING_FIRM_ACCEPT"):
            exp = db.parse_iso(t["expires_at"])
            if exp is not None and now >= exp:
                t["transfer_status"] = "EXPIRED"
                db.touch(t)
    # Access grant expiry
    for g in db.TABLES["AccessGrant"].values():
        if g["grant_status"] in ("PENDING_ACCEPT", "ACTIVE"):
            exp = db.parse_iso(g.get("expires_at")) if g.get("expires_at") else None
            if exp is not None and now >= exp:
                g["grant_status"] = "EXPIRED"
                db.touch(g)
    # Export download expiry
    for e in db.TABLES["ExportRequest"].values():
        if e["export_status"] == "READY":
            exp = db.parse_iso(e.get("download_expires_at")) if e.get("download_expires_at") else None
            if exp is not None and now >= exp:
                e["export_status"] = "EXPIRED"
                db.touch(e)
    # Bank consent expiry -> STALE
    for c in db.TABLES["BankConnection"].values():
        if c["connection_status"] == "ACTIVE":
            exp = db.parse_iso(c.get("consent_expires_at")) if c.get("consent_expires_at") else None
            if exp is not None and now >= exp:
                c["connection_status"] = "STALE"
                db.touch(c)
    # Monthly billing: system generates the next DRAFT invoice on the billing
    # date.  The invoice covers the period just ended, [billing - 30d, billing),
    # consistent with PRD: "an invoice remains ISSUED five days past its
    # period_end" flips it PAST_DUE (billing happens at period end).  A period
    # already covered by a paid invoice is skipped (advance to the next); a
    # period covered only by an unpaid invoice still bills (the unpaid invoice
    # is the past-due one the PRD's suspension rules age).
    for sub in db.TABLES["Subscription"].values():
        if sub["lifecycle_status"] not in ("ACTIVE", "PAST_DUE", "REACTIVATED"):
            continue
        nxt = db.parse_iso(sub.get("next_billing_at")) if sub.get("next_billing_at") else None
        while nxt is not None and now >= nxt:
            period_start = nxt - timedelta(days=30)
            paid_cover = any(
                i["subscription_id"] == sub["id"]
                and i["period_start"] == db.fmt(period_start)
                and i["period_end"] == db.fmt(nxt)
                and i["invoice_status"] == "PAID"
                for i in db.TABLES["Invoice"].values())
            company = db.TABLES["ClientCompany"].get(sub["company_id"])
            if not paid_cover and company is not None:
                lines = services.compute_invoice_lines(company, sub, period_start, nxt)
                inv = {
                    "company_id": company["id"],
                    "subscription_id": sub["id"],
                    "period_start": db.fmt(period_start),
                    "period_end": db.fmt(nxt),
                }
                inv.update(lines)
                inv["invoice_status"] = "DRAFT"
                db.stamp_common(inv)
                db.TABLES["Invoice"][inv["id"]] = inv
            nxt = nxt + timedelta(days=30)
        if nxt is not None and db.fmt(nxt) != sub.get("next_billing_at"):
            sub["next_billing_at"] = db.fmt(nxt)
            db.touch(sub)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role(["PlatformAdmin"])
    data = body_json()
    current = req_str(data, "current_utc")
    dt = db.parse_iso(current)
    if dt is None:
        invalid_request("current_utc must be an ISO 8601 string")
    db.set_now(dt)
    reevaluate_time_driven()
    return ok({"current_utc": db.fmt(db.now())})


@bp.post("/_payments/simulate")
def payments_simulate():
    require_role(["PlatformAdmin"])
    data = body_json()
    invoice_id = req_str(data, "invoice_id")
    outcome = req_str(data, "outcome")
    if outcome not in ("SUCCEEDED", "DECLINED", "TIMEOUT"):
        invalid_request("outcome must be SUCCEEDED, DECLINED, or TIMEOUT")
    inv = get_or_404("Invoice", invoice_id)
    if outcome == "SUCCEEDED" and inv["invoice_status"] in ("ISSUED", "PAST_DUE"):
        inv["invoice_status"] = "PAID"
        db.touch(inv)
        sub = db.TABLES["Subscription"].get(inv["subscription_id"])
        if sub is not None:
            sub["payment_method_on_file"] = True
            others_unpaid = any(
                i["invoice_status"] in ("ISSUED", "PAST_DUE")
                for i in db.TABLES["Invoice"].values()
                if i["subscription_id"] == sub["id"] and i["id"] != inv["id"])
            if sub["lifecycle_status"] == "PAST_DUE" and not others_unpaid:
                sub["lifecycle_status"] = "ACTIVE"
                sub["billing_status"] = "CURRENT"
                db.touch(sub)
            elif sub["lifecycle_status"] == "REACTIVATED":
                sub["lifecycle_status"] = "ACTIVE"
                db.touch(sub)
            # SUSPENDED is NOT auto-lifted here: PRD's "suspension unwinds
            # when all invoices are settled" reads as the settled-state
            # enabling the (explicit) resume; the resume endpoint performs
            # the SUSPENDED -> ACTIVE transition and payroll compensation.
    return ok(serializers.serialize_invoice(inv))


@bp.post("/_sync/bank_feed_tick")
def bank_feed_tick():
    require_role(["PlatformAdmin"])
    data = body_json()
    conn_id = req_str(data, "bank_connection_id")
    conn = get_or_404("BankConnection", conn_id)
    now = db.now()
    exp = db.parse_iso(conn.get("consent_expires_at")) if conn.get("consent_expires_at") else None
    if exp is not None and now >= exp:
        if conn["connection_status"] == "ACTIVE":
            conn["connection_status"] = "STALE"
            db.touch(conn)
    else:
        if conn["connection_status"] == "ACTIVE":
            conn["last_sync_at"] = db.fmt(now)
            db.touch(conn)
    return ok(serializers.serialize_bank_connection(conn))

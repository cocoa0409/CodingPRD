"""Invoice endpoints (PRD 3.9)."""
from flask import Blueprint

import calc
import store
import validation as v
from auth import (OFFICER, PRO_ADMIN, REGULATOR, endpoint, must, new_row,
                  require_pro_owner, touch)
from envelope import ok_entity, ok_list
from errors import fail
from routes.common import enum_filter, listing, str_filter

bp = Blueprint("invoices", __name__)


def producer_of(report):
    registration = store.get("registrations", report["registration_id"])
    return store.get("producers", registration["producer_id"])


@bp.post("/epr/invoices")
@endpoint([PRO_ADMIN])
def create_invoice():
    body = v.body()
    report_id = v.req_str(body, "packaging_report_id")
    membership_id = v.req_str(body, "membership_id")
    report = must("reports", report_id)
    membership = must("memberships", membership_id)
    require_pro_owner(membership["pro_id"])
    if report["fee_status"] != "FINAL":
        fail("ERR_INVALID_STATE", "Only a finally assessed report may be invoiced.")
    if membership["registration_id"] != report["registration_id"]:
        fail("ERR_MEMBERSHIP_REGISTRATION_MISMATCH")
    schedule = store.get("fee_schedules", membership["fee_schedule_id"])
    subtotal = int(report["fee_subtotal_cents"])
    bps, admin_cents, total = calc.admin_fee(subtotal, schedule)
    row = new_row(
        "invoices",
        {
            "packaging_report_id": report["id"],
            "membership_id": membership["id"],
            "fee_subtotal_cents": subtotal,
            "admin_fee_bps_applied": bps,
            "admin_fee_cents": admin_cents,
            "total_cents": total,
            "status": "ISSUED",
            "void_reason": None,
        },
    )
    report["fee_status"] = "INVOICED"
    touch(report)
    calc.recompute_producer_balance(producer_of(report))
    return ok_entity(row, 201)


@bp.get("/epr/invoices/<iid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def get_invoice(iid):
    return ok_entity(must("invoices", iid))


@bp.get("/epr/invoices")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def list_invoices():
    report_id = str_filter("packaging_report_id")
    membership_id = str_filter("membership_id")
    status = enum_filter("status", v.INVOICE_STATUSES)
    rows = store.values("invoices")
    if report_id is not None:
        rows = [r for r in rows if r["packaging_report_id"] == report_id]
    if membership_id is not None:
        rows = [r for r in rows if r["membership_id"] == membership_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/invoices/<iid>/void")
@endpoint([PRO_ADMIN])
def void_invoice(iid):
    body = v.body()
    reason = v.req_str(body, "void_reason")
    invoice = must("invoices", iid)
    membership = store.get("memberships", invoice["membership_id"])
    require_pro_owner(membership["pro_id"])
    if invoice["status"] != "ISSUED":
        fail("ERR_INVOICE_NOT_ISSUED")
    invoice["status"] = "VOID"
    invoice["void_reason"] = reason
    touch(invoice)
    report = store.get("reports", invoice["packaging_report_id"])
    if report["fee_status"] == "INVOICED":
        report["fee_status"] = "FINAL"
    touch(report)
    calc.recompute_producer_balance(producer_of(report))
    return ok_entity(invoice)

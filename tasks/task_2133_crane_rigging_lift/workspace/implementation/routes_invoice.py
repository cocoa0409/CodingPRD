"""Invoicing and the receivable ledger."""
from flask import Blueprint

import cascades
import derive
from core import fail, ordered, respond_list, respond_object, store, touch
from guards import Body, auth, body, fk, must_exist, pagination, paginate, q_enum, q_str

bp = Blueprint("invoices", __name__)

BILLING_MODES = ["HOURLY", "LUMP_SUM"]
INVOICE_STATUSES = ["DRAFT", "ISSUED", "DISPUTED", "PAID", "VOIDED"]


@bp.post("/invoices")
def create_invoice():
    auth(["BillingClerk"])
    b = Body(body())
    lift_plan_id = b.string("lift_plan_id")
    billing_mode = b.enum("billing_mode", BILLING_MODES)
    expected_version = b.integer("expected_lift_plan_version")
    on_site_hours = b.number("on_site_hours", required=False, default=0, minimum=0)
    travel_hours = b.number("travel_hours", required=False, default=0, minimum=0)
    travel_miles = b.number("travel_miles", required=False, default=0, minimum=0)
    lump_sum_cents = b.integer("lump_sum_cents", required=False, default=0, minimum=0)
    plan = fk("lift_plans", lift_plan_id)

    if expected_version != plan["version"]:
        fail("ERR_STALE_PLAN_VERSION",
             "expected_lift_plan_version does not match the plan's current version.")

    if billing_mode == "LUMP_SUM" and lump_sum_cents <= 0:
        fail("ERR_LUMP_SUM_REQUIRED", "A lump-sum invoice needs a positive agreed price.")

    for prior in ordered(store.invoices):
        if prior["lift_plan_id"] == plan["id"] and prior["status"] == "DRAFT":
            prior["status"] = "VOIDED"
            touch(prior)

    inv = cascades.build_invoice(plan, billing_mode, on_site_hours, travel_hours, travel_miles,
                                 lump_sum_cents)
    touch(plan)
    return respond_object(derive.invoice_json(inv), 201)


@bp.get("/invoices/<iid>")
def read_invoice(iid):
    user_id, role = auth(["Dispatcher", "LiftDirector", "BillingClerk", "Customer"])
    inv = must_exist("invoices", iid)
    if role == "Customer" and inv["customer_id"] != user_id:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION", "A customer may only read its own invoices.")
    return respond_object(derive.invoice_json(inv))


@bp.get("/invoices")
def list_invoices():
    auth(["Dispatcher", "LiftDirector", "BillingClerk"])
    limit, offset = pagination()
    lift_plan_id = q_str("lift_plan_id")
    customer_id = q_str("customer_id")
    status = q_enum("status", INVOICE_STATUSES)
    rows = ordered(store.invoices)
    if lift_plan_id:
        rows = [r for r in rows if r["lift_plan_id"] == lift_plan_id]
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = paginate(rows, limit, offset, derive.invoice_json)
    return respond_list(items, limit, offset, total)


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    auth(["BillingClerk"])
    inv = must_exist("invoices", iid)
    if inv["status"] not in ("DRAFT", "DISPUTED"):
        fail("ERR_INVALID_INVOICE_STATE", "Only a draft or disputed invoice may be issued.")
    customer = store.customers.get(inv["customer_id"])
    if customer is not None and customer["credit_hold"]:
        fail("ERR_CUSTOMER_CREDIT_HOLD", "The owning account is on credit hold.")
    inv["status"] = "ISSUED"
    touch(inv)
    return respond_object(derive.invoice_json(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    auth(["BillingClerk"])
    inv = must_exist("invoices", iid)
    b = Body(body())
    b.string("reason")
    if inv["status"] not in ("DRAFT", "ISSUED", "DISPUTED"):
        fail("ERR_INVALID_INVOICE_STATE", "That invoice can no longer be voided.")
    inv["status"] = "VOIDED"
    touch(inv)
    return respond_object(derive.invoice_json(inv))


@bp.post("/invoices/<iid>/dispute")
def dispute_invoice(iid):
    user_id, _role = auth(["Customer"])
    inv = must_exist("invoices", iid)
    b = Body(body())
    b.string("dispute_reason", allow_empty=True)
    if inv["customer_id"] != user_id:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION", "A customer may only dispute its own invoices.")
    if inv["status"] != "ISSUED":
        fail("ERR_INVALID_INVOICE_STATE", "Only an ISSUED invoice may be disputed.")
    inv["status"] = "DISPUTED"
    touch(inv)
    return respond_object(derive.invoice_json(inv))


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    auth(["BillingClerk"])
    inv = must_exist("invoices", iid)
    if inv["status"] not in ("ISSUED", "DISPUTED"):
        fail("ERR_INVALID_INVOICE_STATE", "Only an issued or disputed invoice may be paid.")
    inv["status"] = "PAID"
    touch(inv)
    return respond_object(derive.invoice_json(inv))

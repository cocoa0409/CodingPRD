"""TuitionInvoice routes."""
from flask import Blueprint, request
from store import store, stamp
from middleware import auth, json_body, require_fields, pagination_params, require_student_owner
from response import success_obj, success_list
from errors import (
    not_found, invalid_request, raise_err, ERR_INVOICE_ALREADY_SETTLED, ERR_INVOICE_OVERPAYMENT,
)
from services import issue_invoice, recompute_invoice

bp = Blueprint("invoices", __name__)

TERMINAL = ("PAID", "REFUNDED", "TRANSFERRED", "VOID")


def _get(iid):
    inv = store.invoices.get(iid)
    if not inv:
        not_found("invoice not found")
    return inv


@bp.post("/tuition-invoices")
def create_invoice():
    auth(["FinanceOfficer", "Registrar"])
    body = json_body()
    require_fields(body, ["student_id", "enrollment_id", "base_amount_cents"])
    if body["student_id"] not in store.students:
        not_found("student not found")
    if body["enrollment_id"] not in store.enrollments:
        not_found("enrollment not found")
    amt = body["base_amount_cents"]
    if not isinstance(amt, int) or isinstance(amt, bool) or amt < 0:
        invalid_request("base_amount_cents must be a non-negative integer")
    inv = issue_invoice(body["student_id"], body["enrollment_id"], amt)
    return success_obj(inv, 201)


@bp.get("/tuition-invoices")
def list_invoices():
    auth(["FinanceOfficer", "Registrar", "Student"])
    limit, offset = pagination_params()
    items = list(store.invoices.values())
    for f in ("student_id", "enrollment_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/tuition-invoices/<iid>")
def get_invoice(iid):
    user_id, role = auth(["FinanceOfficer", "Registrar", "Student"])
    inv = _get(iid)
    if role == "Student":
        require_student_owner(user_id, role, inv["student_id"])
    return success_obj(inv)


@bp.post("/tuition-invoices/<iid>/pay")
def pay(iid):
    user_id, role = auth(["Student", "FinanceOfficer"])
    inv = _get(iid)
    if role == "Student":
        require_student_owner(user_id, role, inv["student_id"])
    if inv["status"] in TERMINAL:
        raise_err(ERR_INVOICE_ALREADY_SETTLED, "invoice is in a terminal state")
    body = json_body()
    require_fields(body, ["amount_cents"])
    amt = body["amount_cents"]
    if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
        invalid_request("amount_cents must be a positive integer")
    if amt > inv["amount_due_cents"]:
        raise_err(ERR_INVOICE_OVERPAYMENT, "payment exceeds amount due")
    inv["paid_cents"] += amt
    recompute_invoice(inv)
    if inv["amount_due_cents"] == 0:
        inv["status"] = "PAID"
    else:
        inv["status"] = "PARTIALLY_PAID"
    stamp(inv)
    return success_obj(inv)

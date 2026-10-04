"""Invoice routes: billing run, manual create, get, list, issue, pay, cancel,
write-off; invoice line reads."""
from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request, err_forbidden
from helpers import new_record, touch, paginate, sort_by_created, recompute_trust, reevaluate, first_of_month, valid_month
from clock import now, fmt, parse
import views

bp = Blueprint("invoices", __name__)

LINE_KINDS = ("DESK_FEE", "OVERHEAD_SHARE", "TECH_SUBSCRIPTION", "MARKETING",
              "PRORATED_DESK_FEE", "ADVANCE_RECOVERY")


def get_office_or_404(office_id):
    o = db["offices"].get(office_id)
    if not o:
        raise err_not_found("Office not found")
    return o


def get_invoice_or_404(iid):
    inv = db["invoices"].get(iid)
    if not inv:
        raise err_not_found("Invoice not found")
    return inv


def _add_line(invoice_id, kind, label, amount):
    ln = new_record()
    ln.update({
        "invoice_id": invoice_id,
        "line_kind": kind,
        "period_label": label,
        "amount_cents": amount,
        "applied_at_closing_cents": 0,
    })
    db["invoice_lines"][ln["id"]] = ln
    return ln


def _accepted_assignment_covering_month(agent_id, billing_month):
    ms = first_of_month(billing_month)
    for fa in db["fee_assignments"].values():
        if fa["agent_id"] != agent_id or fa["status"] != "ACCEPTED":
            continue
        ef, et = parse(fa["effective_from"]), parse(fa["effective_to"])
        if ef is not None and et is not None and ef <= ms < et:
            s = db["fee_schedules"].get(fa["fee_schedule_id"])
            if s:
                return fa, s
    return None, None


def _maybe_lift_suspension(office):
    if office and office["status"] == "SUSPENDED":
        still = any(
            inv for inv in db["invoices"].values()
            if inv["office_id"] == office["id"] and inv["status"] == "COLLECTIONS"
        )
        if not still:
            office["status"] = "ACTIVE"
            touch(office)


@bp.route("/offices/<officeId>/generate-invoices", methods=["POST"])
def generate_invoices(officeId):
    require_roles("ManagingBroker")
    o = get_office_or_404(officeId)
    body = request.get_json(silent=True) or {}
    billing_month = body.get("billing_month")
    if not valid_month(billing_month):
        raise err_invalid_request("billing_month must be YYYY-MM")
    result = []
    agents = [a for a in db["agents"].values()
              if a["office_id"] == o["id"] and a["status"] == "ACTIVE"]
    agents = sort_by_created(agents)
    for a in agents:
        # idempotent per (agent, billing_month)
        existing = next(
            (inv for inv in db["invoices"].values()
             if inv["agent_id"] == a["id"] and inv["billing_month"] == billing_month
             and inv["origin"] == "AUTO_RUN"),
            None,
        )
        if existing:
            result.append(existing)
            continue
        fa, schedule = _accepted_assignment_covering_month(a["id"], billing_month)
        if not schedule:
            continue
        inv = new_record()
        due = first_of_month(billing_month) + timedelta(days=7)
        inv.update({
            "office_id": o["id"],
            "agent_id": a["id"],
            "billing_month": billing_month,
            "origin": "AUTO_RUN",
            "amount_due_cents": 0,
            "due_date": fmt(due),
            "amount_paid_cents": 0,
            "status": "ISSUED",
        })
        db["invoices"][inv["id"]] = inv
        total = 0
        for kind, label, amount in (
            ("DESK_FEE", f"{billing_month} desk fee", schedule["desk_fee_cents"]),
            ("TECH_SUBSCRIPTION", f"{billing_month} tech subscription",
             schedule["tech_subscription_monthly_cents"]),
            ("MARKETING", f"{billing_month} marketing", schedule["marketing_monthly_cents"]),
        ):
            _add_line(inv["id"], kind, label, amount)
            total += amount
        inv["amount_due_cents"] = total
        result.append(inv)
    recompute_trust(o)
    items = [views.invoice_view(inv) for inv in result]
    return ok_list(items, len(items), 10, 0)


@bp.route("/invoices", methods=["POST"])
def create_manual_invoice():
    require_roles("ManagingBroker")
    body = request.get_json(silent=True) or {}
    office_id = body.get("office_id")
    agent_id = body.get("agent_id")
    billing_month = body.get("billing_month")
    lines = body.get("lines")
    office = db["offices"].get(office_id) if isinstance(office_id, str) else None
    if not office:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "office_id does not resolve")
    agent = db["agents"].get(agent_id) if isinstance(agent_id, str) else None
    if not agent:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "agent_id does not resolve")
    if not valid_month(billing_month):
        raise err_invalid_request("billing_month must be YYYY-MM")
    if not isinstance(lines, list) or not lines:
        raise err_invalid_request("lines must be a non-empty array")
    parsed = []
    for l in lines:
        if not isinstance(l, dict):
            raise err_invalid_request("each line must be an object")
        kind = l.get("line_kind")
        amount = l.get("amount_cents")
        label = l.get("period_label") or billing_month
        if kind not in LINE_KINDS:
            raise err_invalid_request("invalid line_kind")
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise err_invalid_request("amount_cents must be an integer")
        parsed.append((kind, label, amount))
    rec = new_record()
    created = parse(rec["created_at"])
    due = created + timedelta(days=7)
    rec.update({
        "office_id": office["id"],
        "agent_id": agent["id"],
        "billing_month": billing_month,
        "origin": "MANUAL",
        "amount_due_cents": sum(p[2] for p in parsed),
        "due_date": fmt(due),
        "amount_paid_cents": 0,
        "status": "DRAFT",
    })
    db["invoices"][rec["id"]] = rec
    for kind, label, amount in parsed:
        _add_line(rec["id"], kind, label, amount)
    return ok(views.invoice_view(rec), 201)


@bp.route("/invoices/<invoiceId>", methods=["GET"])
def get_invoice(invoiceId):
    require_roles(*ALL_ROLES)
    reevaluate()
    inv = get_invoice_or_404(invoiceId)
    return ok(views.invoice_view(inv))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    require_roles(*ALL_ROLES)
    reevaluate()
    items = list(db["invoices"].values())
    args = request.args
    if args.get("office_id") is not None:
        items = [i for i in items if i["office_id"] == args.get("office_id")]
    if args.get("agent_id") is not None:
        items = [i for i in items if i["agent_id"] == args.get("agent_id")]
    if args.get("invoice_id") is not None:
        items = [i for i in items if i["id"] == args.get("invoice_id")]
    if args.get("status") is not None:
        items = [i for i in items if i["status"] == args.get("status")]
    if args.get("billing_month") is not None:
        items = [i for i in items if i["billing_month"] == args.get("billing_month")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.invoice_view(i) for i in page], total, limit, offset)


@bp.route("/invoices/<invoiceId>/issue", methods=["POST"])
def issue_invoice(invoiceId):
    require_roles("ManagingBroker")
    inv = get_invoice_or_404(invoiceId)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is not DRAFT")
    inv["status"] = "ISSUED"
    touch(inv)
    office = db["offices"].get(inv["office_id"])
    if office:
        recompute_trust(office)
    return ok(views.invoice_view(inv))


@bp.route("/invoices/<invoiceId>/pay", methods=["POST"])
def pay_invoice(invoiceId):
    uid, _role = require_roles("Agent")
    reevaluate()
    inv = get_invoice_or_404(invoiceId)
    if uid != inv["agent_id"]:
        raise err_forbidden("Agents may only pay their own invoices")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE", "COLLECTIONS"):
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is not payable in its state")
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise err_invalid_request("amount_cents must be a positive integer")
    remaining = inv["amount_due_cents"] - inv["amount_paid_cents"]
    if amount > remaining:
        raise ApiError("ERR_OVERPAYMENT", 422, "Payment exceeds the remaining balance")
    inv["amount_paid_cents"] += amount
    if inv["amount_paid_cents"] >= inv["amount_due_cents"]:
        inv["status"] = "PAID"
    elif inv["status"] in ("ISSUED", "OVERDUE"):
        inv["status"] = "PARTIALLY_PAID"
    # COLLECTIONS partial payments stay COLLECTIONS
    touch(inv)
    office = db["offices"].get(inv["office_id"])
    if office:
        recompute_trust(office)
        _maybe_lift_suspension(office)
    return ok(views.invoice_view(inv))


@bp.route("/invoices/<invoiceId>/cancel", methods=["POST"])
def cancel_invoice(invoiceId):
    require_roles("ManagingBroker")
    inv = get_invoice_or_404(invoiceId)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is not DRAFT")
    inv["status"] = "CANCELLED"
    touch(inv)
    return ok(views.invoice_view(inv))


@bp.route("/invoices/<invoiceId>/write-off", methods=["POST"])
def write_off_invoice(invoiceId):
    require_roles("BrokerOfRecord")
    reevaluate()
    inv = get_invoice_or_404(invoiceId)
    if inv["status"] != "COLLECTIONS":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is not COLLECTIONS")
    due = parse(inv["due_date"])
    if now() < due + timedelta(days=90):
        raise ApiError("ERR_WRITE_OFF_TOO_EARLY", 409,
                       "Invoice is not yet 90 days past due_date")
    unpaid = inv["amount_due_cents"] - inv["amount_paid_cents"]
    inv["status"] = "WRITTEN_OFF"
    touch(inv)
    office = db["offices"].get(inv["office_id"])
    if office:
        recompute_trust(office)  # WRITTEN_OFF drops out of the trust base
        _maybe_lift_suspension(office)
    return ok(views.invoice_view(inv))


# ---------------------------------------------------------------------------
# Invoice lines
# ---------------------------------------------------------------------------

@bp.route("/invoice-lines/<lineId>", methods=["GET"])
def get_invoice_line(lineId):
    require_roles(*ALL_ROLES)
    l = db["invoice_lines"].get(lineId)
    if not l:
        raise err_not_found("InvoiceLine not found")
    return ok(views.invoice_line_view(l))


@bp.route("/invoices/<invoiceId>/lines", methods=["GET"])
def list_invoice_lines(invoiceId):
    require_roles(*ALL_ROLES)
    get_invoice_or_404(invoiceId)
    items = [l for l in db["invoice_lines"].values() if l["invoice_id"] == invoiceId]
    if request.args.get("invoice_id") is not None:
        items = [l for l in items if l["invoice_id"] == request.args.get("invoice_id")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.invoice_line_view(l) for l in page], total, limit, offset)


@bp.route("/invoice-lines", methods=["GET"])
def list_all_invoice_lines():
    require_roles(*ALL_ROLES)
    items = list(db["invoice_lines"].values())
    args = request.args
    if args.get("invoice_id") is not None:
        items = [l for l in items if l["invoice_id"] == args.get("invoice_id")]
    if args.get("line_kind") is not None:
        items = [l for l in items if l["line_kind"] == args.get("line_kind")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.invoice_line_view(l) for l in page], total, limit, offset)

"""Agent routes: onboard, get, list, terminate, complete-termination, advances."""
from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request, err_forbidden
from helpers import new_record, touch, paginate, sort_by_created, recompute_trust, month_of, first_of_month, valid_month
from clock import now, fmt, parse
from calculations import departure_proration
import views

bp = Blueprint("agents", __name__)


def get_agent_or_404(agent_id):
    a = db["agents"].get(agent_id)
    if not a:
        raise err_not_found("Agent not found")
    return a


def get_office_or_404(office_id):
    o = db["offices"].get(office_id)
    if not o:
        raise err_not_found("Office not found")
    return o


def _post_entry(office_id, transaction_id, kind, amount, status):
    rec = new_record()
    rec.update({
        "office_id": office_id,
        "transaction_id": transaction_id,
        "entry_kind": kind,
        "amount_cents": amount,
        "entry_month": month_of(now()),
        "status": status,
    })
    db["entries"][rec["id"]] = rec
    return rec


@bp.route("/offices/<officeId>/agents", methods=["POST"])
def onboard_agent(officeId):
    require_roles("ManagingBroker")
    o = get_office_or_404(officeId)
    body = request.get_json(silent=True) or {}
    full_name = body.get("full_name")
    email = body.get("email")
    license_number = body.get("license_number")
    if not isinstance(full_name, str) or not full_name:
        raise err_invalid_request("full_name is required")
    if not isinstance(email, str) or not email:
        raise err_invalid_request("email is required")
    if not isinstance(license_number, str) or not license_number:
        raise err_invalid_request("license_number is required")
    if o["status"] != "ACTIVE":
        raise ApiError("ERR_OFFICE_SUSPENDED", 409, "Office is not ACTIVE")
    for a in db["agents"].values():
        if a["license_number"] == license_number:
            raise ApiError("ERR_DUPLICATE_LICENSE", 409, "license_number already registered")
    rec = new_record()
    rec.update({
        "office_id": o["id"],
        "full_name": full_name,
        "email": email,
        "license_number": license_number,
        "status": "PENDING_ONBOARDING",
        "onboarded_at": None,
        "termination_requested_at": None,
        "terminated_at": None,
        "supervision_cadence_days": 30,
        "unearned_advance_balance_cents": 0,
    })
    db["agents"][rec["id"]] = rec
    return ok(views.agent_view(rec), 201)


@bp.route("/agents/<agentId>", methods=["GET"])
def get_agent(agentId):
    require_roles(*ALL_ROLES)
    a = get_agent_or_404(agentId)
    return ok(views.agent_view(a))


@bp.route("/agents", methods=["GET"])
def list_agents():
    require_roles("FranchiseeOwner", "BrokerOfRecord", "ManagingBroker",
                  "TrustAccountant", "ComplianceAuditor", "PlatformAdmin")
    items = list(db["agents"].values())
    args = request.args
    if args.get("office_id") is not None:
        items = [a for a in items if a["office_id"] == args.get("office_id")]
    if args.get("agent_id") is not None:
        items = [a for a in items if a["id"] == args.get("agent_id")]
    if args.get("status") is not None:
        items = [a for a in items if a["status"] == args.get("status")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.agent_view(a) for a in page], total, limit, offset)


@bp.route("/agents/<agentId>/terminate", methods=["POST"])
def terminate_agent(agentId):
    uid, _role = require_roles("Agent")
    a = get_agent_or_404(agentId)
    if uid != a["id"]:
        raise err_forbidden("Agents may only terminate themselves")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Agent is not ACTIVE")
    n = now()
    a["status"] = "TERMINATION_PENDING"
    a["termination_requested_at"] = fmt(n)
    a["supervision_cadence_days"] = 7
    touch(a)
    # cascade: spawn DEPARTURE_HOLD entries for open invoice lines
    for inv in db["invoices"].values():
        if inv["agent_id"] != a["id"] or inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
            continue
        for line in db["invoice_lines"].values():
            if line["invoice_id"] != inv["id"]:
                continue
            remaining = line["amount_cents"] - line.get("applied_at_closing_cents", 0)
            if remaining > 0:
                _post_entry(inv["office_id"], None, "DEPARTURE_HOLD", remaining, "DEPARTURE_HOLD")
    office = db["offices"].get(a["office_id"])
    if office:
        recompute_trust(office)
    return ok(views.agent_view(a))


def _accepted_schedule_for(agent, at_dt):
    """The ACCEPTED FeeAssignment whose window contains at_dt, plus its schedule."""
    for fa in db["fee_assignments"].values():
        if fa["agent_id"] != agent["id"] or fa["status"] != "ACCEPTED":
            continue
        ef, et = parse(fa["effective_from"]), parse(fa["effective_to"])
        if ef is not None and et is not None and ef <= at_dt < et:
            s = db["fee_schedules"].get(fa["fee_schedule_id"])
            if s:
                return fa, s
    return None, None


@bp.route("/agents/<agentId>/complete-termination", methods=["POST"])
def complete_termination(agentId):
    require_roles("ManagingBroker")
    a = get_agent_or_404(agentId)
    if a["status"] != "TERMINATION_PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Agent is not TERMINATION_PENDING")
    req_at = parse(a["termination_requested_at"])
    n = now()
    if n < req_at + timedelta(days=14):
        raise ApiError("ERR_TERMINATION_WINDOW_OPEN", 409, "14-day notice window still open")
    a["status"] = "TERMINATED"
    a["terminated_at"] = fmt(n)
    touch(a)
    office = db["offices"].get(a["office_id"])
    if office:
        office["active_agent_count"] = sum(
            1 for x in db["agents"].values()
            if x["office_id"] == office["id"] and x["status"] == "ACTIVE"
        )

    # Departure invoice
    _fa, schedule = _accepted_schedule_for(a, req_at)
    desk_fee = schedule["desk_fee_cents"] if schedule else 0
    day_of_month = req_at.day
    owed, refund = departure_proration(desk_fee, day_of_month)
    advance_balance = a.get("unearned_advance_balance_cents", 0)

    # refund variant applies if the full month's desk fee was already invoiced and PAID
    period_month = req_at.strftime("%Y-%m")
    full_paid = False
    for inv in db["invoices"].values():
        if inv["agent_id"] != a["id"] or inv["billing_month"] != period_month:
            continue
        if inv["status"] != "PAID":
            continue
        for line in db["invoice_lines"].values():
            if line["invoice_id"] == inv["id"] and line["line_kind"] == "DESK_FEE" \
                    and line["amount_cents"] >= desk_fee:
                full_paid = True
                break
        if full_paid:
            break

    lines = []
    if full_paid:
        if refund > 0:
            lines.append(("PRORATED_DESK_FEE", f"{period_month} desk fee refund", -refund))
    else:
        if owed > 0:
            lines.append(("PRORATED_DESK_FEE", f"{period_month} prorated desk fee", owed))
    if advance_balance > 0:
        lines.append(("ADVANCE_RECOVERY", f"{period_month} advance recovery", advance_balance))

    inv = new_record()
    due = n + timedelta(days=14)
    total = sum(l[2] for l in lines)
    inv.update({
        "office_id": a["office_id"],
        "agent_id": a["id"],
        "billing_month": period_month,
        "origin": "DEPARTURE",
        "amount_due_cents": total,
        "due_date": fmt(due),
        "amount_paid_cents": 0,
        "status": "ISSUED",
    })
    db["invoices"][inv["id"]] = inv
    for kind, label, amount in lines:
        ln = new_record()
        ln.update({
            "invoice_id": inv["id"],
            "line_kind": kind,
            "period_label": label,
            "amount_cents": amount,
            "applied_at_closing_cents": 0,
        })
        db["invoice_lines"][ln["id"]] = ln

    # settle the advance balance at exit
    a["unearned_advance_balance_cents"] = 0

    # resolve departure holds
    holds = [e for e in db["entries"].values()
             if e["office_id"] == a["office_id"] and e["status"] == "DEPARTURE_HOLD"]
    if total <= 0:
        for e in holds:
            e["entry_kind"] = "DEPARTURE_RELEASE"
            e["status"] = "DISBURSED"
            touch(e)
    if office:
        recompute_trust(office)
    return ok(views.agent_view(a))


@bp.route("/agents/<agentId>/advance-commission", methods=["POST"])
def advance_commission(agentId):
    require_roles("ManagingBroker")
    a = get_agent_or_404(agentId)
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise err_invalid_request("amount_cents must be a positive integer")
    a["unearned_advance_balance_cents"] = a.get("unearned_advance_balance_cents", 0) + amount
    touch(a)
    rec = _post_entry(a["office_id"], None, "ADVANCE", amount, "DISBURSED")
    office = db["offices"].get(a["office_id"])
    if office:
        recompute_trust(office)
    return ok(views.entry_view(rec), 201)


@bp.route("/agents/<agentId>/return-advance", methods=["POST"])
def return_advance(agentId):
    uid, _role = require_roles("Agent")
    a = get_agent_or_404(agentId)
    if uid != a["id"]:
        raise err_forbidden("Agents may only return their own advances")
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise err_invalid_request("amount_cents must be a positive integer")
    balance = a.get("unearned_advance_balance_cents", 0)
    if amount > balance:
        raise ApiError("ERR_OVERPAYMENT", 422, "Return exceeds unearned advance balance")
    a["unearned_advance_balance_cents"] = balance - amount
    touch(a)
    rec = _post_entry(a["office_id"], None, "ADVANCE_RETURN", amount, "DISBURSED")
    office = db["offices"].get(a["office_id"])
    if office:
        recompute_trust(office)
    return ok(views.entry_view(rec), 201)

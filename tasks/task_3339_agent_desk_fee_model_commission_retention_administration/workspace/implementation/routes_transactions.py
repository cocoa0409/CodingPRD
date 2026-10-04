"""Transaction routes: create, get, list, request-close, close (closing cascade),
mark-fell-through, relist, recontract."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request
from helpers import new_record, touch, paginate, sort_by_created, recompute_trust, month_of
from clock import now, fmt, parse
from calculations import closing_statement
import views

bp = Blueprint("transactions", __name__)


def get_txn_or_404(tid):
    t = db["transactions"].get(tid)
    if not t:
        raise err_not_found("Transaction not found")
    return t


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


def _post_closing_line(txn_id, line_type, agent_id, amount, applied_invoice_line_id, variant):
    rec = new_record()
    rec.update({
        "transaction_id": txn_id,
        "line_type": line_type,
        "agent_id": agent_id,
        "amount_cents": amount,
        "applied_invoice_line_id": applied_invoice_line_id,
        "variant": variant,
        "status": "FINAL",
    })
    db["closing_lines"][rec["id"]] = rec
    return rec


def _active_referral_for(selling_agent_id, office_id):
    for r in db["referrals"].values():
        if r["status"] == "ACTIVE" and r["agent_id"] == selling_agent_id \
                and r["receiving_office_id"] == office_id:
            return r
    return None


def _accepted_schedule_for(agent_id, at_dt):
    for fa in db["fee_assignments"].values():
        if fa["agent_id"] != agent_id or fa["status"] != "ACCEPTED":
            continue
        ef, et = parse(fa["effective_from"]), parse(fa["effective_to"])
        if ef is not None and et is not None and ef <= at_dt < et:
            s = db["fee_schedules"].get(fa["fee_schedule_id"])
            if s:
                return s
    return None


def _advance_offset_waterfall(agent, offset):
    """Apply offset against the agent's open invoice lines, oldest first by created_at.
    Bucket 1: ADVANCE_RECOVERY / PRORATED_DESK_FEE / DESK_FEE lines.
    Bucket 2: TECH_SUBSCRIPTION then MARKETING lines.
    Returns list of (invoice_line, applied_amount)."""
    if offset <= 0:
        return []
    open_statuses = ("ISSUED", "PARTIALLY_PAID", "OVERDUE")
    open_invoice_ids = {
        inv["id"] for inv in db["invoices"].values()
        if inv["agent_id"] == agent["id"] and inv["status"] in open_statuses
    }
    lines = [
        l for l in db["invoice_lines"].values()
        if l["invoice_id"] in open_invoice_ids
        and l.get("applied_at_closing_cents", 0) < l["amount_cents"]
    ]
    b1_kinds = ("ADVANCE_RECOVERY", "PRORATED_DESK_FEE", "DESK_FEE")
    bucket1 = sorted(
        (l for l in lines if l["line_kind"] in b1_kinds),
        key=lambda l: (l.get("created_at") or "", l["id"]),
    )
    bucket2 = sorted(
        (l for l in lines if l["line_kind"] == "TECH_SUBSCRIPTION"),
        key=lambda l: (l.get("created_at") or "", l["id"]),
    ) + sorted(
        (l for l in lines if l["line_kind"] == "MARKETING"),
        key=lambda l: (l.get("created_at") or "", l["id"]),
    )
    applied = []
    remaining = offset
    for line in bucket1 + bucket2:
        if remaining <= 0:
            break
        avail = line["amount_cents"] - line.get("applied_at_closing_cents", 0)
        take = min(avail, remaining)
        if take > 0:
            line["applied_at_closing_cents"] = line.get("applied_at_closing_cents", 0) + take
            touch(line)
            applied.append((line, take))
            remaining -= take
    return applied


@bp.route("/offices/<officeId>/transactions", methods=["POST"])
def create_transaction(officeId):
    require_roles("ManagingBroker")
    get_office_or_404(officeId)
    body = request.get_json(silent=True) or {}
    listing_agent_id = body.get("listing_agent_id")
    selling_agent_id = body.get("selling_agent_id")
    offer_id = body.get("offer_id")
    sale_price = body.get("sale_price_cents")
    gci = body.get("gross_commission_cents")
    if not isinstance(listing_agent_id, str) or listing_agent_id not in db["agents"]:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "listing_agent_id does not resolve")
    if not isinstance(selling_agent_id, str) or selling_agent_id not in db["agents"]:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "selling_agent_id does not resolve")
    if not isinstance(offer_id, str) or offer_id not in db["offers"]:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "offer_id does not resolve")
    if not isinstance(sale_price, int) or isinstance(sale_price, bool) or sale_price <= 0:
        raise err_invalid_request("sale_price_cents must be a positive integer")
    if not isinstance(gci, int) or isinstance(gci, bool) or gci <= 0:
        raise err_invalid_request("gross_commission_cents must be a positive integer")
    rec = new_record()
    rec.update({
        "office_id": officeId,
        "listing_agent_id": listing_agent_id,
        "selling_agent_id": selling_agent_id,
        "offer_id": offer_id,
        "sale_price_cents": sale_price,
        "gross_commission_cents": gci,
        "status": "LISTED",
        "closed_at": None,
        "request_close_at": None,
    })
    db["transactions"][rec["id"]] = rec
    return ok(views.transaction_view(rec), 201)


@bp.route("/transactions/<transactionId>", methods=["GET"])
def get_transaction(transactionId):
    require_roles(*ALL_ROLES)
    t = get_txn_or_404(transactionId)
    return ok(views.transaction_view(t))


@bp.route("/transactions", methods=["GET"])
def list_transactions():
    require_roles("FranchiseeOwner", "BrokerOfRecord", "ManagingBroker",
                  "TrustAccountant", "ComplianceAuditor", "PlatformAdmin")
    items = list(db["transactions"].values())
    args = request.args
    if args.get("office_id") is not None:
        items = [t for t in items if t["office_id"] == args.get("office_id")]
    if args.get("status") is not None:
        items = [t for t in items if t["status"] == args.get("status")]
    if args.get("selling_agent_id") is not None:
        items = [t for t in items if t["selling_agent_id"] == args.get("selling_agent_id")]
    if args.get("listing_agent_id") is not None:
        items = [t for t in items if t["listing_agent_id"] == args.get("listing_agent_id")]
    if args.get("offer_id") is not None:
        items = [t for t in items if t["offer_id"] == args.get("offer_id")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.transaction_view(t) for t in page], total, limit, offset)


@bp.route("/transactions/<transactionId>/request-close", methods=["POST"])
def request_close(transactionId):
    require_roles("Agent")
    t = get_txn_or_404(transactionId)
    if t["status"] != "UNDER_CONTRACT":
        raise ApiError("ERR_INVALID_STATE", 409, "Transaction is not UNDER_CONTRACT")
    approved = any(
        c for c in db["cdas"].values()
        if c["transaction_id"] == t["id"] and c["status"] == "APPROVED"
    )
    if not approved:
        raise ApiError("ERR_CDA_NOT_APPROVED", 409, "No APPROVED CDA on the transaction")
    listing_agent = db["agents"].get(t["listing_agent_id"])
    if not listing_agent or listing_agent["status"] != "ACTIVE":
        raise ApiError("ERR_AGENT_NOT_ACTIVE", 409, "Listing agent is not ACTIVE")
    t["status"] = "PENDING_CLOSE"
    t["request_close_at"] = fmt(now())
    touch(t)
    return ok(views.transaction_view(t))


@bp.route("/transactions/<transactionId>/close", methods=["POST"])
def close_transaction(transactionId):
    require_roles("ManagingBroker")
    t = get_txn_or_404(transactionId)
    if t["status"] != "PENDING_CLOSE":
        raise ApiError("ERR_INVALID_STATE", 409, "Transaction is not PENDING_CLOSE")
    n = now()
    req_at = parse(t.get("request_close_at")) if t.get("request_close_at") else None
    if req_at is not None and n < req_at:
        raise ApiError("ERR_TEMPORAL_GATE", 409, "Close before request-close timestamp")

    selling = db["agents"].get(t["selling_agent_id"])
    if not selling:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "selling agent missing")
    schedule = _accepted_schedule_for(t["selling_agent_id"], n)
    if not schedule:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422,
                       "No ACCEPTED fee assignment in force for the selling agent")

    former = selling["status"] in ("TERMINATION_PENDING", "TERMINATED")
    variant = "FORMER_AGENT" if former else "STANDARD"

    referral = _active_referral_for(t["selling_agent_id"], t["office_id"])
    referral_bps = referral["referral_fee_bps"] if referral else schedule["referral_fee_bps"]

    figures = closing_statement(t, schedule, referral_bps,
                                selling.get("unearned_advance_balance_cents", 0))
    if former:
        figures["overhead_share"] = 0
        figures["office_split"] = (figures["net_gci"] - figures["agent_retention"])

    t["status"] = "CLOSED"
    t["closed_at"] = fmt(n)
    touch(t)

    agent_id = t["selling_agent_id"]
    # Closing statement lines — signed so they sum to zero. Convention:
    # the GCI line is negative (cash into escrow) and the distribution
    # lines are positive (obligations owed out), matching §3.8's reconcile
    # arithmetic where leaving cash reduces the trust by the entry amount.
    _post_closing_line(t["id"], "GCI", agent_id, -figures["gross"], None, variant)
    _post_closing_line(t["id"], "REFERRAL_FEE", None, figures["referral_fee"], None, variant)
    _post_closing_line(t["id"], "AGENT_RETENTION", agent_id, figures["agent_retention"], None, variant)
    _post_closing_line(t["id"], "OVERHEAD_SHARE", agent_id, figures["overhead_share"], None, variant)
    _post_closing_line(t["id"], "OFFICE_SPLIT", None, figures["office_split"], None, variant)

    # advance recovery offset waterfall
    offset = figures["advance_offset"]
    applied = _advance_offset_waterfall(selling, offset)
    selling["unearned_advance_balance_cents"] = max(
        0, selling.get("unearned_advance_balance_cents", 0) - offset)
    touch(selling)
    first_applied_id = applied[0][0]["id"] if applied else None
    _post_closing_line(t["id"], "ADVANCE_RECOVERY", agent_id, offset, first_applied_id, variant)

    office = db["offices"].get(t["office_id"])

    # Cascade hop 1: GCI receipt into escrow
    _post_entry(t["office_id"], t["id"], "GCI_RECEIPT", figures["gross"], "ESCROW_HELD")
    # Hop 2: split
    disb_status = "DEPARTURE_HOLD" if former else "AGENT_PAYABLE"
    disb_kind = "AGENT_DISBURSEMENT"
    _post_entry(t["office_id"], t["id"], disb_kind, figures["agent_disbursed"], disb_status)
    _post_entry(t["office_id"], t["id"], "OFFICE_FEE_ACCRUAL",
                figures["office_split"] + figures["overhead_share"], "OFFICE_FEE_ACCRUED")
    if offset > 0:
        _post_entry(t["office_id"], t["id"], "OFFICE_FEE_ACCRUAL", offset, "OFFICE_FEE_ACCRUED")
    # Hop 3: referral payout
    if referral and figures["referral_fee"] > 0:
        _post_entry(t["office_id"], t["id"], "REFERRAL_PAYOUT", figures["referral_fee"],
                    "REFERRAL_PAYABLE")
        referral["status"] = "FULFILLED"
        referral["fulfilled_transaction_id"] = t["id"]
        touch(referral)
    elif referral:
        referral["status"] = "FULFILLED"
        referral["fulfilled_transaction_id"] = t["id"]
        touch(referral)

    if office:
        recompute_trust(office)
    return ok(views.transaction_view(t))


@bp.route("/transactions/<transactionId>/mark-fell-through", methods=["POST"])
def mark_fell_through(transactionId):
    require_roles("Agent")
    t = get_txn_or_404(transactionId)
    if t["status"] not in ("UNDER_CONTRACT", "PENDING_CLOSE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Transaction cannot fall through from its state")
    t["status"] = "FELL_THROUGH"
    touch(t)
    for c in db["cdas"].values():
        if c["transaction_id"] == t["id"] and c["status"] == "IN_REVIEW":
            c["status"] = "SUPERSEDED"
            touch(c)
    return ok(views.transaction_view(t))


@bp.route("/transactions/<transactionId>/relist", methods=["POST"])
def relist(transactionId):
    require_roles("Agent")
    t = get_txn_or_404(transactionId)
    if t["status"] != "FELL_THROUGH":
        raise ApiError("ERR_INVALID_STATE", 409, "Transaction is not FELL_THROUGH")
    t["status"] = "RELISTED"
    touch(t)
    return ok(views.transaction_view(t))


@bp.route("/transactions/<transactionId>/recontract", methods=["POST"])
def recontract(transactionId):
    require_roles("Agent")
    t = get_txn_or_404(transactionId)
    if t["status"] != "RELISTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Transaction is not RELISTED")
    t["status"] = "UNDER_CONTRACT"
    touch(t)
    return ok(views.transaction_view(t))

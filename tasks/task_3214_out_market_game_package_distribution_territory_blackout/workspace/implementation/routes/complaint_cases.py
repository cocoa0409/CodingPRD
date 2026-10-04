"""Complaint cases: file, list, get, resolve, escalate, deescalate."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    err_not_owner, err_already_terminal, err_invalid_state,
    err_complaint_window, err_complaint_not_refundable, err_refund_not_available,
)
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import (
    new_resource, touch, get_or_404, weekly_value_cents, append_payment,
)
from validate import body_json, req_string, req_enum

bp = Blueprint("complaint_cases", __name__)


def _check_owner(auth, account_id):
    user_id, role = auth
    if role in ("Subscriber", "VenueManager") and user_id != account_id:
        raise err_not_owner()


@bp.post("/complaint-cases")
@require_roles("Subscriber", "VenueManager")
def create_complaint(auth):
    body = body_json()
    account_id = req_string(body, "account_id")
    subscription_id = req_string(body, "subscription_id")
    game_id = req_string(body, "game_id")
    category = req_enum(body, "category", {"BLACKOUT_DISPUTE", "BILLING", "QUALITY"})
    detail = req_string(body, "detail")
    account = get_or_404(db.accounts, account_id)
    get_or_404(db.subscriptions, subscription_id)
    get_or_404(db.games, game_id)
    _check_owner(auth, account["id"])

    case = new_resource()
    case.update({
        "account_id": account["id"],
        "subscription_id": subscription_id,
        "game_id": game_id,
        "category": category,
        "detail": detail,
        "status": "OPEN",
        "refund_amount_cents": 0,
        "resolution_note": None,
    })
    db.complaint_cases[case["id"]] = case
    return success(case, status=201)


@bp.get("/complaint-cases")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def list_complaints(auth):
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    subscription_id = request.args.get("subscription_id")
    game_id = request.args.get("game_id")
    status = request.args.get("status")
    category = request.args.get("category")
    items = sorted(db.complaint_cases.values(), key=lambda r: r["created_at"])
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if subscription_id is not None:
        items = [c for c in items if c["subscription_id"] == subscription_id]
    if game_id is not None:
        items = [c for c in items if c["game_id"] == game_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if category is not None:
        items = [c for c in items if c["category"] == category]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/complaint-cases/<cid>")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor", "Subscriber")
def get_complaint(cid, auth):
    case = get_or_404(db.complaint_cases, cid)
    return success(case)


@bp.post("/complaint-cases/<cid>/resolve")
@require_roles("SupportAgent")
def resolve_complaint(cid, auth):
    case = get_or_404(db.complaint_cases, cid)
    if case["status"] in ("APPROVED_REFUND", "DENIED"):
        raise err_already_terminal()
    if case["status"] != "OPEN":
        raise err_invalid_state()
    body = body_json()
    decision = req_enum(body, "decision", {"APPROVE", "DENY"})
    note = req_string(body, "note")

    if decision == "DENY":
        case["status"] = "DENIED"
        case["resolution_note"] = note
        touch(case)
        return success(case)

    # APPROVE path — guards in §2.8 order.
    sub = get_or_404(db.subscriptions, case["subscription_id"])
    season = db.seasons.get(sub["season_id"])
    # Priority 16: grace window
    grace_days = season["grace_days"] if season else 0
    from db import parse_iso
    purchased_at = parse_iso(sub["created_at"])
    now = db.clock.now()
    if now - purchased_at > timedelta(days=grace_days):
        raise err_complaint_window()
    # Priority 17: category gate
    if case["category"] != "BLACKOUT_DISPUTE":
        raise err_complaint_not_refundable()
    # Priority 18: refund floor
    if sub["status"] == "CANCELLED":
        raise err_refund_not_available()
    weekly = weekly_value_cents(sub, season)
    refund = min(weekly, sub["paid_amount_cents"])
    if refund <= 0 or refund > sub["paid_amount_cents"]:
        raise err_refund_not_available()

    case["status"] = "APPROVED_REFUND"
    case["refund_amount_cents"] = refund
    case["resolution_note"] = note
    touch(case)
    append_payment(sub, "REFUND", refund, reason=note)
    sub["paid_amount_cents"] -= refund
    touch(sub)
    return success(case)


@bp.post("/complaint-cases/<cid>/escalate")
@require_roles("SupportAgent")
def escalate_complaint(cid, auth):
    case = get_or_404(db.complaint_cases, cid)
    if case["status"] in ("APPROVED_REFUND", "DENIED"):
        raise err_already_terminal()
    if case["status"] != "OPEN":
        raise err_invalid_state()
    case["status"] = "ESCALATED"
    touch(case)
    return success(case)


@bp.post("/complaint-cases/<cid>/deescalate")
@require_roles("SupportAgent")
def deescalate_complaint(cid, auth):
    case = get_or_404(db.complaint_cases, cid)
    if case["status"] in ("APPROVED_REFUND", "DENIED"):
        raise err_already_terminal()
    if case["status"] != "ESCALATED":
        raise err_invalid_state()
    case["status"] = "OPEN"
    touch(case)
    return success(case)

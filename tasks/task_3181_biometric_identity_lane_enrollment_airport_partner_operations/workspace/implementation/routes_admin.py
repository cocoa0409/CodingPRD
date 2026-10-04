"""Test-driving endpoints: logical clock, fraud watchlist, billing simulator,
admin member overrides."""
from flask import Blueprint

from db import store, fmt_dt, _parse_dt
from errors import ApiError
from middleware import require_roles, body, require_field
from models import touch
from response import success
from serializers import present
import services

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("OpsAdmin")
def set_clock():
    data = body()
    to_iso8601 = require_field(data, "to_iso8601")
    try:
        new_clock = _parse_dt(to_iso8601)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be an ISO 8601 datetime")
    old_date = store.clock.date()
    store.clock = new_clock
    if new_clock.date() != old_date:
        services.run_daily_sweep()
        store._last_sweep_date = new_clock.date()
    return success({"current_utc": fmt_dt(store.clock)}, status_code=200)


@bp.post("/_fraud/watchlist")
@require_roles("OpsAdmin")
def fraud_watchlist():
    data = body()
    document_number = require_field(data, "document_number")
    date_of_birth = require_field(data, "date_of_birth")
    action = require_field(data, "action")
    action_norm = str(action).strip().lower()
    if action_norm not in ("add", "remove"):
        raise ApiError("ERR_VALIDATION", 400, "action must be 'add' or 'remove'")
    pair = (str(document_number), str(date_of_birth))
    if action_norm == "add":
        store.watchlist.add(pair)
        watchlisted = True
    else:
        store.watchlist.discard(pair)
        watchlisted = False
    return success({"watchlisted": watchlisted}, status_code=200)


@bp.post("/_billing/record-payment")
@require_roles("OpsAdmin")
def record_payment():
    data = body()
    invoice_id = require_field(data, "invoice_id")
    outcome = require_field(data, "outcome")
    if outcome not in ("SUCCEEDED", "FAILED"):
        raise ApiError("ERR_VALIDATION", 400, "outcome must be SUCCEEDED or FAILED")
    inv = store.subscription_invoices.get(invoice_id)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", 404, "Invoice not found")
    if inv["status"] != "DUE":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is not DUE")
    sub = store.subscriptions.get(inv["subscription_id"])
    if outcome == "SUCCEEDED":
        inv["status"] = "PAID"
        touch(inv)
        if sub is not None:
            from datetime import timedelta
            if sub.get("current_period_end"):
                sub["current_period_end"] = fmt_dt(
                    _parse_dt(sub["current_period_end"]) + timedelta(days=30)
                )
            if sub["status"] == "PAST_DUE":
                sub["status"] = "ACTIVE"
                sub["past_due_since"] = None
                if sub.get("pending_plan"):
                    sub["plan"] = sub["pending_plan"]
                    sub["pending_plan"] = None
                    services._apply_plan_now(sub)
            touch(sub)
    else:  # FAILED
        inv["attempt_count"] = inv.get("attempt_count", 0) + 1
        touch(inv)
        if sub is not None and sub["status"] == "ACTIVE":
            sub["status"] = "PAST_DUE"
            sub["past_due_since"] = fmt_dt(store.now())
            touch(sub)
    return success(present(inv), status_code=200)


@bp.post("/_admin/members/<mid>/suspend")
@require_roles("OpsAdmin")
def admin_suspend_member(mid):
    member = store.members.get(mid)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Member is not ACTIVE")
    member["status"] = "SUSPENDED"
    touch(member)
    services.reject_draft_enrollments(member)
    return success(present(member), status_code=200)


@bp.post("/_admin/members/<mid>/terminate")
@require_roles("OpsAdmin")
def admin_terminate_member(mid):
    member = store.members.get(mid)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    if member["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Member is not SUSPENDED")
    confirmed = any(
        d for d in store.identity_disputes.values()
        if d["member_id"] == mid and d["status"] == "RESOLVED_CONFIRMED"
    )
    if not confirmed:
        raise ApiError("ERR_DISPUTE_NOT_CONFIRMED", 409,
                       "Admin termination requires a RESOLVED_CONFIRMED dispute on file")
    services.cascade_member_termination(member, actor=store_now_actor())
    return success(present(member), status_code=200)


def store_now_actor():
    from flask import request
    return getattr(request, "user_id", "system")

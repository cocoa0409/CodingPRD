"""Subscription routes."""
from flask import Blueprint, request

from db import db
from errors import err_validation, err_not_found, err_invalid_state, err_forbidden
from middleware import require_roles, check_self_or_admin
from response import ok_object, ok_list, init_common, touch, parse_pagination, parse_iso_dt
from serializers import subscription_view
from services import lazy_lapse_subscription

bp = Blueprint("subscriptions", __name__)


def _get_athlete_or_404(aid):
    a = db.athletes.get(aid)
    if not a:
        raise err_not_found("Athlete not found")
    return a


@bp.post("/v1/athletes/<aid>/subscriptions")
def create_subscription(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    _get_athlete_or_404(aid)
    check_self_or_admin(user_id, role, aid)
    body = request.get_json(silent=True) or {}
    plan = body.get("plan")
    started_at = body.get("started_at")
    expires_at = body.get("expires_at")
    if plan not in ("SUMMIT_MONTHLY", "SUMMIT_ANNUAL"):
        raise err_validation("plan must be SUMMIT_MONTHLY or SUMMIT_ANNUAL")
    sd = parse_iso_dt(started_at)
    ed = parse_iso_dt(expires_at)
    if sd is None or ed is None:
        raise err_validation("started_at and expires_at must be ISO8601 UTC")
    if not ed > sd:
        raise err_validation("expires_at must be strictly after started_at")
    # at most one ACTIVE per athlete
    for s in db.subscriptions.values():
        if s["athlete_id"] == aid:
            lazy_lapse_subscription(s)
            if s["status"] == "ACTIVE":
                raise err_invalid_state("athlete already holds an ACTIVE subscription")
    sub = init_common({
        "athlete_id": aid,
        "plan": plan,
        "started_at": started_at,
        "expires_at": expires_at,
        "status": "ACTIVE",
        "cancel_reason": None,
    })
    db.subscriptions[sub["id"]] = sub
    return ok_object(subscription_view(sub), 201)


@bp.get("/v1/athletes/<aid>/subscriptions")
def list_subscriptions(aid):
    require_roles("Athlete", "PlatformAdmin")
    _get_athlete_or_404(aid)
    status_f = request.args.get("status")
    items = []
    for s in db.subscriptions.values():
        if s["athlete_id"] != aid:
            continue
        lazy_lapse_subscription(s)
        if status_f and s["status"] != status_f:
            continue
        items.append(s)
    items.sort(key=lambda s: s["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([subscription_view(s) for s in items], limit, offset)


@bp.get("/v1/subscriptions/<sid>")
def get_subscription(sid):
    require_roles("Athlete", "PlatformAdmin")
    s = db.subscriptions.get(sid)
    if not s:
        raise err_not_found("Subscription not found")
    lazy_lapse_subscription(s)
    return ok_object(subscription_view(s))


@bp.post("/v1/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    s = db.subscriptions.get(sid)
    if not s:
        raise err_not_found("Subscription not found")
    if role == "Athlete" and user_id != s["athlete_id"]:
        raise err_forbidden("Only the owner may cancel")
    if s["status"] != "ACTIVE":
        raise err_invalid_state("Subscription is not ACTIVE")
    body = request.get_json(silent=True) or {}
    reason = body.get("cancel_reason")
    s["status"] = "CANCELLED"
    s["cancel_reason"] = reason
    touch(s)
    return ok_object(subscription_view(s))

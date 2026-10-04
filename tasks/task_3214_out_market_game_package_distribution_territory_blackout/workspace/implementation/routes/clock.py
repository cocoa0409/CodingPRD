"""Clock and payment simulation routes (test-driving surface)."""
from flask import Blueprint

from db import db, parse_iso, format_iso
from errors import err_invalid_request, err_already_terminal, err_invalid_state
from middleware import require_roles
from response import success
from services import (
    get_or_404, run_auto_transitions, append_payment, entitlement_fanout,
    touch,
)
from validate import body_json, req_string, req_enum

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock(auth):
    body = body_json()
    if body is None or not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    current_utc = body.get("current_utc")
    dt = parse_iso(current_utc)
    if dt is None:
        raise err_invalid_request("current_utc must be an ISO 8601 UTC datetime")
    db.clock.set(dt)
    run_auto_transitions()
    return success({"current_utc": format_iso(dt)})


@bp.post("/_payments/simulate")
@require_roles("PlatformAdmin")
def simulate_payment(auth):
    body = body_json()
    subscription_id = req_string(body, "subscription_id")
    outcome = req_enum(body, "outcome", {"SUCCEEDED", "FAILED"})
    sub = get_or_404(db.subscriptions, subscription_id)
    if sub["status"] != "PENDING_PAYMENT":
        raise err_invalid_state("Subscription is not pending payment")
    if outcome == "SUCCEEDED":
        sub["status"] = "ACTIVE"
        sub["paid_amount_cents"] = sub["paid_amount_cents"] + sub["price_charged_cents"]
        sub["entitlement_state"] = "ENABLED"
        touch(sub)
        append_payment(sub, "CHARGE", sub["price_charged_cents"])
        entitlement_fanout(sub)
    else:  # FAILED
        sub["status"] = "CANCELLED"
        sub["entitlement_state"] = "REVOKED"
        sub["cancelled_at"] = db.clock.now_iso()
        touch(sub)
    return success(sub)

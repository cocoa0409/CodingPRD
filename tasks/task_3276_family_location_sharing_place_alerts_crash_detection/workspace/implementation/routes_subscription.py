"""Subscription lifecycle, fiscal endpoints, and compliance holds."""
from flask import Blueprint, request
from db import db, touch, new_entity, now
from errors import (ApiError, err_not_found, err_invalid_request,
                    ERR_STALE_VERSION, ERR_INVALID_STATE,
                    ERR_ASSISTANCE_UNITS_EXHAUSTED, ERR_NO_IDENTITY_CREDIT)
from middleware import (get_actor, require_roles, require_circle_member,
                        require_circle_owner, require_circle_admin,
                        require_not_restricted, circle_posture)
from response import success, created, list_response, pagination_params
from serializers import ser, ser_many
import calculations as calc
from services import (append_subscription_event, recompute_posture,
                      on_circle_frozen, members_of_circle,
                      recompute_member_interval)
from routes_circles import _get_circle_or_404

bp = Blueprint("subscription", __name__)

TIERS = {"FREE", "PLUS", "PROTECT"}


@bp.route("/api/circles/<circle_id>/subscription/change-tier", methods=["POST"])
def change_tier(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    circle = _get_circle_or_404(circle_id)
    require_circle_owner(actor, circle)
    body = request.get_json(silent=True) or {}
    to_tier = body.get("to_tier")
    if to_tier not in TIERS:
        raise err_invalid_request("to_tier must be one of FREE, PLUS, PROTECT")
    expected = body.get("expected_circle_version")
    if expected is None:
        raise err_invalid_request("expected_circle_version is required")
    if expected != circle["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale circle version")
    from_tier = circle["subscription_tier"]
    circle["subscription_tier"] = to_tier
    circle["history_retention_days"] = calc.TIER_RETENTION_DAYS[to_tier]
    if to_tier == "PROTECT" and from_tier != "PROTECT":
        circle["identity_protection_credits"] = 1
    elif from_tier == "PROTECT" and to_tier != "PROTECT":
        circle["identity_protection_credits"] = 0
    append_subscription_event(circle, "TIER_CHANGE", from_tier=from_tier,
                              to_tier=to_tier)
    touch(circle)
    recompute_posture(circle)
    # Tier change re-triggers sample interval recompute for all members
    for m in members_of_circle(circle["id"]):
        recompute_member_interval(m, circle)
    return success(ser(circle))


@bp.route("/api/circles/<circle_id>/subscription/reactivate", methods=["POST"])
def reactivate(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    circle = _get_circle_or_404(circle_id)
    require_circle_owner(actor, circle)
    if circle["subscription_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only SUSPENDED circles reactivate")
    circle["subscription_status"] = "ACTIVE"
    append_subscription_event(circle, "REACTIVATED")
    touch(circle)
    recompute_posture(circle)
    return success(ser(circle))


@bp.route("/api/circles/<circle_id>/subscription/simulate-payment-failed",
          methods=["POST"])
def simulate_payment_failed(circle_id):
    actor = get_actor()
    require_roles(actor, {"System"})
    circle = _get_circle_or_404(circle_id)
    circle["subscription_status"] = "PAST_DUE"
    append_subscription_event(circle, "PAYMENT_FAILED")
    touch(circle)
    recompute_posture(circle)
    return success(ser(circle))


@bp.route("/api/circles/<circle_id>/subscription/simulate-suspend", methods=["POST"])
def simulate_suspend(circle_id):
    actor = get_actor()
    require_roles(actor, {"System"})
    circle = _get_circle_or_404(circle_id)
    circle["subscription_status"] = "SUSPENDED"
    append_subscription_event(circle, "SUSPENDED")
    touch(circle)
    posture = recompute_posture(circle)
    if posture == "FROZEN":
        on_circle_frozen(circle)
    return success(ser(circle))


# ---------------------------------------------------------------------------
# Subscription events
# ---------------------------------------------------------------------------

@bp.route("/api/circles/<circle_id>/subscription-events", methods=["GET"])
def list_subscription_events(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "System"})
    circle = _get_circle_or_404(circle_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin"})
    items = [e for e in db.subscription_events.values()
             if e["circle_id"] == circle["id"]]
    kind = request.args.get("event_kind")
    if kind:
        items = [e for e in items if e["event_kind"] == kind]
    items.sort(key=lambda e: e["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/subscription-events/<event_id>", methods=["GET"])
def get_subscription_event(event_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "System"})
    ev = db.subscription_events.get(event_id)
    if ev is None:
        raise err_not_found("Subscription event not found")
    if not actor.is_system:
        circle = db.circles.get(ev["circle_id"])
        require_circle_member(actor, circle, {"Owner", "Admin"})
    return success(ser(ev))


@bp.route("/api/subscription-events", methods=["GET"])
def list_subscription_events_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.subscription_events.values())
    circle_id = request.args.get("circle_id")
    kind = request.args.get("event_kind")
    if circle_id:
        items = [e for e in items if e["circle_id"] == circle_id]
    if kind:
        items = [e for e in items if e["event_kind"] == kind]
    items.sort(key=lambda e: e["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


# ---------------------------------------------------------------------------
# Roadside assistance & identity protection
# ---------------------------------------------------------------------------

@bp.route("/api/circles/<circle_id>/roadside-assistance", methods=["POST"])
def consume_assistance(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin"})
    circle = _get_circle_or_404(circle_id)
    require_circle_admin(actor, circle)
    from middleware import require_not_frozen
    require_not_frozen(circle)
    require_not_restricted(circle)
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not reason or not isinstance(reason, str):
        raise err_invalid_request("reason is required")
    tier = circle["subscription_tier"]
    balance = circle["assistance_units_balance"]
    if tier == "PROTECT":
        if balance <= -1:
            raise ApiError(ERR_ASSISTANCE_UNITS_EXHAUSTED, 402,
                           "assistance units exhausted")
    else:
        if balance <= 0:
            raise ApiError(ERR_ASSISTANCE_UNITS_EXHAUSTED, 402,
                           "assistance units exhausted")
    circle["assistance_units_balance"] = balance - 1
    touch(circle)
    ev = append_subscription_event(circle, "ASSISTANCE_CONSUME", units_delta=-1)
    return created(ser(ev))


@bp.route("/api/circles/<circle_id>/identity-protection/consume", methods=["POST"])
def consume_identity_credit(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    circle = _get_circle_or_404(circle_id)
    require_circle_owner(actor, circle)
    from middleware import require_not_frozen
    require_not_frozen(circle)
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not reason or not isinstance(reason, str):
        raise err_invalid_request("reason is required")
    if circle["identity_protection_credits"] <= 0:
        raise ApiError(ERR_NO_IDENTITY_CREDIT, 402, "No identity protection credit")
    circle["identity_protection_credits"] -= 1
    touch(circle)
    ev = append_subscription_event(circle, "IDENTITY_CREDIT_CONSUME", units_delta=-1)
    return created(ser(ev))


# ---------------------------------------------------------------------------
# Compliance holds
# ---------------------------------------------------------------------------

HOLD_KINDS = {"DATA_SHARING_DISCLOSURE", "MONETIZATION_OPT_OUT_SWEEP",
              "MINOR_PRIVACY_AUDIT"}


@bp.route("/api/circles/<circle_id>/compliance-holds", methods=["POST"])
def open_hold(circle_id):
    actor = get_actor()
    require_roles(actor, {"System"})
    circle = _get_circle_or_404(circle_id)
    body = request.get_json(silent=True) or {}
    kind = body.get("hold_kind")
    if kind not in HOLD_KINDS:
        raise err_invalid_request("hold_kind invalid")
    reason = body.get("opened_reason") or "manual"
    hold = new_entity(
        circle_id=circle["id"],
        hold_kind=kind,
        hold_status="OPEN",
        opened_reason=reason,
        resolved_by_member_id=None,
    )
    db.compliance_holds[hold["id"]] = hold
    touch(circle)
    recompute_posture(circle)
    return created(ser(hold))


@bp.route("/api/circles/<circle_id>/compliance-holds", methods=["GET"])
def list_holds(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "System"})
    circle = _get_circle_or_404(circle_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin"})
    items = [h for h in db.compliance_holds.values() if h["circle_id"] == circle["id"]]
    status = request.args.get("hold_status")
    if status:
        items = [h for h in items if h["hold_status"] == status]
    items.sort(key=lambda h: h["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/circles/<circle_id>/compliance-holds/<hold_id>/resolve",
          methods=["POST"])
def resolve_hold(circle_id, hold_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    circle = _get_circle_or_404(circle_id)
    hold = db.compliance_holds.get(hold_id)
    if hold is None or hold["circle_id"] != circle["id"]:
        raise err_not_found("Compliance hold not found")
    require_circle_owner(actor, circle)
    if hold["hold_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Hold not OPEN")
    hold["hold_status"] = "RESOLVED"
    hold["resolved_by_member_id"] = actor.user_id
    touch(hold)
    touch(circle)
    recompute_posture(circle)
    return success(ser(hold))


@bp.route("/api/compliance-holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "System"})
    hold = db.compliance_holds.get(hold_id)
    if hold is None:
        raise err_not_found("Compliance hold not found")
    if not actor.is_system:
        circle = db.circles.get(hold["circle_id"])
        require_circle_member(actor, circle, {"Owner", "Admin"})
    return success(ser(hold))


@bp.route("/api/compliance-holds", methods=["GET"])
def list_holds_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.compliance_holds.values())
    circle_id = request.args.get("circle_id")
    resolved_by = request.args.get("resolved_by_member_id")
    if circle_id:
        items = [h for h in items if h["circle_id"] == circle_id]
    if resolved_by:
        items = [h for h in items if h.get("resolved_by_member_id") == resolved_by]
    items.sort(key=lambda h: h["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)

"""Circle and member routes."""
from flask import Blueprint, request
from db import db, now, touch, new_entity, parse_dt
from errors import (ApiError, err_unauthenticated, err_forbidden, err_not_found,
                    err_invalid_request, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
                    ERR_ROLE_INCOMPATIBLE, ERR_INVALID_STATE)
from middleware import (get_actor, require_roles, require_circle_member,
                        require_circle_admin, require_circle_owner,
                        require_not_frozen, circle_posture)
from response import success, created, list_response, pagination_params
from serializers import ser, ser_many
import calculations as calc
from services import (recompute_posture, on_circle_frozen, members_of_circle,
                      recompute_member_interval, append_subscription_event)

bp = Blueprint("circles", __name__)

TIERS = {"FREE", "PLUS", "PROTECT"}


def _get_circle_or_404(circle_id):
    circle = db.circles.get(circle_id)
    if circle is None:
        raise err_not_found("Circle not found")
    return circle


def _get_member_or_404(circle, member_id):
    member = db.members.get(member_id)
    if member is None or member["circle_id"] != circle["id"]:
        raise err_not_found("Member not found")
    return member


@bp.route("/api/circles", methods=["POST"])
def create_circle():
    actor = get_actor()
    # Only the Owner role may create a circle (the creating user becomes OWNER).
    if actor.role != "Owner":
        raise err_forbidden()
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    tier = body.get("subscription_tier")
    anchor = body.get("billing_anchor_day")
    owner_name = body.get("owner_display_name")
    owner_birthdate_raw = body.get("owner_birthdate")
    if not name or not isinstance(name, str):
        raise err_invalid_request("name is required")
    if tier not in TIERS:
        raise err_invalid_request("subscription_tier must be one of FREE, PLUS, PROTECT")
    if not isinstance(anchor, int) or isinstance(anchor, bool) or not (1 <= anchor <= 28):
        raise err_invalid_request("billing_anchor_day must be an integer in 1..28")
    if not owner_name:
        raise err_invalid_request("owner_display_name is required")
    owner_birthdate = parse_dt(owner_birthdate_raw)
    if owner_birthdate is None:
        raise err_invalid_request("owner_birthdate must be an ISO-8601 date")

    circle = new_entity(
        name=name,
        owner_member_id=None,
        subscription_tier=tier,
        subscription_status="TRIALING",
        billing_anchor_day=anchor,
        circle_posture="OPEN",
        assistance_units_balance=calc.TIER_UNITS[tier],
        identity_protection_credits=calc.TIER_IDENTITY_CREDITS[tier],
        history_retention_days=calc.TIER_RETENTION_DAYS[tier],
    )
    db.circles[circle["id"]] = circle
    owner = new_entity(
        circle_id=circle["id"],
        display_name=owner_name,
        birthdate=owner_birthdate,
        role="OWNER",
        age_years=calc.age_years(owner_birthdate, now()),
        consent_state="GRANTED",
        privacy_mode="PRECISE",
        sampling_profile="BALANCED",
        effective_sample_interval_seconds=calc.effective_sample_interval(
            "BALANCED", "UNKNOWN", 100, tier),
        current_battery_pct=100,
        last_known_fix_id=None,
        tension_flag=False,
        monetization_opt_in=False,
    )
    db.members[owner["id"]] = owner
    circle["owner_member_id"] = owner["id"]
    from services import append_consent_record
    append_consent_record(owner, owner["id"], "FULL", "GRANT",
                          monetization_opt_in=False)
    append_subscription_event(circle, "TIER_CHANGE", from_tier=None, to_tier=tier)
    return created(ser(circle))


@bp.route("/api/circles", methods=["GET"])
def list_circles():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.circles.values())
    status = request.args.get("subscription_status")
    tier = request.args.get("subscription_tier")
    owner_id = request.args.get("owner_member_id")
    if status:
        items = [c for c in items if c["subscription_status"] == status]
    if tier:
        items = [c for c in items if c["subscription_tier"] == tier]
    if owner_id:
        items = [c for c in items if c["owner_member_id"] == owner_id]
    for c in items:
        c["circle_posture"] = circle_posture(c)
    items.sort(key=lambda c: c["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/circles/<circle_id>", methods=["GET"])
def get_circle(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    circle["circle_posture"] = circle_posture(circle)
    return success(ser(circle))


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@bp.route("/api/circles/<circle_id>/members", methods=["POST"])
def invite_member(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin"})
    circle = _get_circle_or_404(circle_id)
    require_circle_admin(actor, circle)
    require_not_frozen(circle)
    body = request.get_json(silent=True) or {}
    name = body.get("display_name")
    birthdate = parse_dt(body.get("birthdate"))
    if not name:
        raise err_invalid_request("display_name is required")
    if birthdate is None:
        raise err_invalid_request("birthdate must be an ISO-8601 date")
    age = calc.age_years(birthdate, now())
    role = "MINOR" if age < 16 else "MEMBER"
    member = new_entity(
        circle_id=circle["id"],
        display_name=name,
        birthdate=birthdate,
        role=role,
        age_years=age,
        consent_state="PENDING",
        privacy_mode="PRECISE",
        sampling_profile="BALANCED",
        effective_sample_interval_seconds=calc.effective_sample_interval(
            "BALANCED", "UNKNOWN", 100, circle["subscription_tier"]),
        current_battery_pct=100,
        last_known_fix_id=None,
        tension_flag=False,
        monetization_opt_in=False,
    )
    db.members[member["id"]] = member
    touch(circle)
    return created(ser(member))


@bp.route("/api/circles/<circle_id>/members", methods=["GET"])
def list_members(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    items = members_of_circle(circle["id"])
    role = request.args.get("role")
    consent = request.args.get("consent_state")
    if role:
        items = [m for m in items if m["role"] == role]
    if consent:
        items = [m for m in items if m["consent_state"] == consent]
    for m in items:
        m["age_years"] = calc.age_years(m["birthdate"], now())
    items.sort(key=lambda m: m["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/circles/<circle_id>/members/<member_id>", methods=["GET"])
def get_member_nested(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    member["age_years"] = calc.age_years(member["birthdate"], now())
    return success(ser(member))


@bp.route("/api/members/<member_id>", methods=["GET"])
def get_member_top(member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    member = db.members.get(member_id)
    if member is None:
        raise err_not_found("Member not found")
    if not actor.is_system:
        circle = db.circles.get(member["circle_id"])
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    member["age_years"] = calc.age_years(member["birthdate"], now())
    return success(ser(member))


@bp.route("/api/members", methods=["GET"])
def list_members_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.members.values())
    circle_id = request.args.get("circle_id")
    fix_id = request.args.get("last_known_fix_id")
    role = request.args.get("role")
    consent = request.args.get("consent_state")
    if circle_id:
        items = [m for m in items if m["circle_id"] == circle_id]
    if fix_id:
        items = [m for m in items if m.get("last_known_fix_id") == fix_id]
    if role:
        items = [m for m in items if m["role"] == role]
    if consent:
        items = [m for m in items if m["consent_state"] == consent]
    for m in items:
        m["age_years"] = calc.age_years(m["birthdate"], now())
    items.sort(key=lambda m: m["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/circles/<circle_id>/members/<member_id>/promote", methods=["POST"])
def promote_member(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    require_circle_owner(actor, circle)
    require_not_frozen(circle)
    if member["role"] == "MINOR":
        raise ApiError(ERR_ROLE_INCOMPATIBLE, 409, "Cannot promote a MINOR to ADMIN")
    if member["role"] != "MEMBER":
        raise ApiError(ERR_INVALID_STATE, 409, "Only MEMBER can be promoted to ADMIN")
    if member["consent_state"] != "GRANTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Promotion requires consent GRANTED")
    member["role"] = "ADMIN"
    touch(member)
    return success(ser(member))


@bp.route("/api/circles/<circle_id>/members/<member_id>/demote", methods=["POST"])
def demote_member(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    require_circle_owner(actor, circle)
    require_not_frozen(circle)
    if member["role"] != "ADMIN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only ADMIN can be demoted")
    member["role"] = "MEMBER"
    touch(member)
    return success(ser(member))


@bp.route("/api/circles/<circle_id>/transfer-ownership", methods=["POST"])
def transfer_ownership(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    circle = _get_circle_or_404(circle_id)
    require_circle_owner(actor, circle)
    require_not_frozen(circle)
    body = request.get_json(silent=True) or {}
    target_id = body.get("target_member_id")
    if not target_id:
        raise err_invalid_request("target_member_id is required")
    target = _get_member_or_404(circle, target_id)
    if target["role"] == "MINOR":
        raise ApiError(ERR_ROLE_INCOMPATIBLE, 409, "Cannot transfer ownership to a MINOR")
    if target["consent_state"] != "GRANTED":
        raise ApiError(ERR_ROLE_INCOMPATIBLE, 409,
                       "Target consent_state must be GRANTED")
    prior = db.members.get(circle["owner_member_id"])
    if prior is not None and prior["id"] != target["id"]:
        prior["role"] = "ADMIN"
        touch(prior)
    target["role"] = "OWNER"
    touch(target)
    circle["owner_member_id"] = target["id"]
    touch(circle)
    circle["circle_posture"] = circle_posture(circle)
    return success(ser(circle))

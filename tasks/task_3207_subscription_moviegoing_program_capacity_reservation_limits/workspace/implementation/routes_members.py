from datetime import timedelta

from flask import request

from core import (
    STORE, now, fmt_dt, fmt_date, parse_dt, get_auth, require_role,
    check_member_identity, parse_body, get_pagination, paginate, lookup,
    envelope_ok, ApiError, err_not_found, err_invalid_state, err_invalid_request,
    err_forbidden, stamp_new, touch, TIERS,
)
import engine


# ================= Serializers =================

def serialize_member(m):
    return engine.member_view(m)


def serialize_plan(p):
    return dict(p)


def serialize_subscription(sub):
    engine.sync_pause_cycle(sub)
    return engine.subscription_view(sub)


def serialize_bucket(b):
    return engine.bucket_view(b)


# ================= Clock =================

def set_clock():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    body = parse_body(request, {"to_iso8601": ("dt", True, None)})
    engine.advance_clock(body["to_iso8601"])
    return envelope_ok({"current_utc": fmt_dt(now())}, "object", 200)


# ================= Members =================

def create_member():
    user_id, role = get_auth(request)
    require_role(role, "MemberServices")
    body = parse_body(request, {
        "email": ("str", True, None),
        "full_name": ("str", True, None),
    })
    member = {
        "email": body["email"],
        "full_name": body["full_name"],
        "status": "REGISTERED",
        "suspended_until": None,
    }
    stamp_new(member)
    STORE["members"][member["id"]] = member
    return envelope_ok(serialize_member(member), "object", 201)


def get_member(member_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices", "Member", "ProgramAdmin")
    member = lookup("members", member_id)
    check_member_identity(user_id, role, member["id"])
    return envelope_ok(serialize_member(member), "object", 200)


def list_members():
    user_id, role = get_auth(request)
    require_role(role, "MemberServices", "ProgramAdmin")
    limit, offset = get_pagination(request)
    status = request.args.get("status")
    items = list(STORE["members"].values())
    if status is not None:
        items = [m for m in items if m["status"] == status]
    views = [serialize_member(m) for m in items]
    page, meta = paginate(views, limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def activate_member(member_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices")
    member = lookup("members", member_id)
    if member["status"] != "REGISTERED":
        raise err_invalid_state("Only a REGISTERED member can be activated")
    member["status"] = "ACTIVE"
    touch(member)
    return envelope_ok(serialize_member(member), "object", 200)


def unsuspend_member_route(member_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices")
    member = lookup("members", member_id)
    if member["status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED member can be unsuspended")
    engine.unsuspend_member(member)
    return envelope_ok(serialize_member(member), "object", 200)


def close_member(member_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices")
    member = lookup("members", member_id)
    if member["status"] not in ("REGISTERED", "ACTIVE", "SUSPENDED"):
        raise err_invalid_state("Member is already CLOSED")
    for sub in STORE["subscriptions"].values():
        if sub["member_id"] == member_id and sub["status"] in ("ACTIVE", "PAUSED"):
            raise err_invalid_state("Member holds an ACTIVE or PAUSED subscription")
    member["status"] = "CLOSED"
    member["suspended_until"] = None
    touch(member)
    return envelope_ok(serialize_member(member), "object", 200)


def list_member_strikes(member_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices", "Member", "ProgramAdmin")
    member = lookup("members", member_id)
    check_member_identity(user_id, role, member["id"])
    limit, offset = get_pagination(request)
    engine.expire_strikes_for_member(member_id)
    status = request.args.get("status")
    items = [s for s in STORE["strikes"].values() if s["member_id"] == member_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items, limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_member_ledger(member_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices", "Member", "ProgramAdmin")
    member = lookup("members", member_id)
    check_member_identity(user_id, role, member["id"])
    limit, offset = get_pagination(request)
    kind = request.args.get("kind")
    items = [e for e in STORE["ledger"].values() if e["member_id"] == member_id]
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    page, meta = paginate(items, limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def create_loyalty_adjustment(member_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices")
    member = lookup("members", member_id)
    body = parse_body(request, {
        "points": ("int", True, None),
        "note": ("str", False, None),
    })
    entry = engine.append_ledger(member["id"], "ADJUST", body["points"],
                                 source_id=None, note=body.get("note"))
    return envelope_ok(entry, "object", 201)


# ================= Subscription plans =================

def create_plan():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    body = parse_body(request, {
        "code": ("str", True, None),
        "tier": ("str", True, TIERS),
        "monthly_fee_cents": ("int", True, None),
        "weekly_reservation_quota": ("int", True, None),
        "max_rollover_credits": ("int", True, None),
        "premium_format_allowed": ("bool", True, None),
        "max_future_reservations": ("int", True, None),
        "loyalty_points_multiplier_pct": ("int", True, None),
        "concession_discount_pct": ("int", True, None),
    })
    plan = dict(body)
    plan["status"] = "DRAFT"
    stamp_new(plan)
    STORE["plans"][plan["id"]] = plan
    return envelope_ok(serialize_plan(plan), "object", 201)


def get_plan(plan_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices", "Member")
    plan = lookup("plans", plan_id)
    return envelope_ok(serialize_plan(plan), "object", 200)


def publish_plan(plan_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    plan = lookup("plans", plan_id)
    if plan["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT plan can be published")
    plan["status"] = "PUBLISHED"
    touch(plan)
    return envelope_ok(serialize_plan(plan), "object", 200)


def retire_plan(plan_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    plan = lookup("plans", plan_id)
    if plan["status"] != "PUBLISHED":
        raise err_invalid_state("Only a PUBLISHED plan can be retired")
    plan["status"] = "RETIRED"
    touch(plan)
    return envelope_ok(serialize_plan(plan), "object", 200)


def list_plan_subscriptions(plan_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices")
    plan = lookup("plans", plan_id)
    limit, offset = get_pagination(request)
    status = request.args.get("status")
    items = [s for s in STORE["subscriptions"].values() if s["plan_id"] == plan_id]
    views = [serialize_subscription(s) for s in items]
    if status is not None:
        views = [v for v in views if v["status"] == status]
    page, meta = paginate(views, limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


# ================= Subscriptions =================

def enroll(member_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices")
    member = lookup("members", member_id)
    check_member_identity(user_id, role, member["id"])
    body = parse_body(request, {"plan_id": ("str", True, None)})
    plan = lookup("plans", body["plan_id"])
    # Priority 7: member-level gate
    if member["status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "SUSPENDED members may not enroll")
    if member["status"] == "CLOSED":
        raise err_invalid_state("CLOSED members may not enroll")
    # Priority 8: rejoin lock
    n = now()
    locks = [parse_dt(s["rejoin_locked_until"]) for s in STORE["subscriptions"].values()
             if s["member_id"] == member_id and s["status"] == "CANCELLED"
             and s.get("rejoin_locked_until")]
    if locks and max(locks) > n:
        raise ApiError("ERR_REJOIN_LOCKED", 409,
                       "Rejoin waiting period has not elapsed")
    # Priority 17: plan enrollability
    if plan["status"] != "PUBLISHED":
        raise ApiError("ERR_PLAN_NOT_ENROLLABLE", 422, "Plan is not PUBLISHED")
    sub = {
        "member_id": member["id"],
        "plan_id": plan["id"],
        "status": "ACTIVE",
        "cycle_anchor_date": fmt_date(n.date()),
        "pause_count_in_cycle": 0,
        "paused_at": None,
        "pause_resume_at": None,
        "cancelled_at": None,
        "rejoin_locked_until": None,
    }
    stamp_new(sub)
    sub["_pause_cycle_index"] = engine.current_cycle_index(sub)
    STORE["subscriptions"][sub["id"]] = sub
    # Fresh-enrollment bucket for week 0
    engine.ensure_buckets_up_to(sub, 0)
    return envelope_ok(serialize_subscription(sub), "object", 201)


def get_subscription(subscription_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "ProgramAdmin")
    sub = lookup("subscriptions", subscription_id)
    check_member_identity(user_id, role, sub["member_id"])
    return envelope_ok(serialize_subscription(sub), "object", 200)


def list_member_subscriptions(member_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "ProgramAdmin")
    member = lookup("members", member_id)
    check_member_identity(user_id, role, member["id"])
    limit, offset = get_pagination(request)
    status = request.args.get("status")
    items = [s for s in STORE["subscriptions"].values() if s["member_id"] == member_id]
    views = [serialize_subscription(s) for s in items]
    if status is not None:
        views = [v for v in views if v["status"] == status]
    page, meta = paginate(views, limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_subscriptions():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices")
    limit, offset = get_pagination(request)
    member_id = request.args.get("member_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    items = list(STORE["subscriptions"].values())
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if plan_id is not None:
        items = [s for s in items if s["plan_id"] == plan_id]
    views = [serialize_subscription(s) for s in items]
    if status is not None:
        views = [v for v in views if v["status"] == status]
    page, meta = paginate(views, limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def pause_subscription(subscription_id):
    user_id, role = get_auth(request)
    require_role(role, "Member")
    sub = lookup("subscriptions", subscription_id)
    check_member_identity(user_id, role, sub["member_id"])
    body = parse_body(request, {"pause_days": ("int", True, None)})
    # Priority 5: state
    if sub["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE subscription can be paused")
    # Member-level gate
    member = STORE["members"].get(sub["member_id"])
    if member is not None and member["status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "SUSPENDED members may not pause")
    # pause_days range per PRD 3.3 -> ERR_INVALID_REQUEST
    if body["pause_days"] < 7 or body["pause_days"] > 30:
        raise err_invalid_request("pause_days must be between 7 and 30 inclusive")
    # Priority 15: pause policy
    engine.sync_pause_cycle(sub)
    if sub["pause_count_in_cycle"] >= 1:
        raise ApiError("ERR_PAUSE_LIMIT_REACHED", 422,
                       "Pause already consumed in the current billing cycle")
    n = now()
    sub["status"] = "PAUSED"
    sub["paused_at"] = fmt_dt(n)
    sub["pause_resume_at"] = fmt_dt(n + timedelta(days=body["pause_days"]))
    sub["pause_count_in_cycle"] += 1
    touch(sub)
    return envelope_ok(serialize_subscription(sub), "object", 200)


def resume_subscription_route(subscription_id):
    user_id, role = get_auth(request)
    require_role(role, "Member")
    sub = lookup("subscriptions", subscription_id)
    check_member_identity(user_id, role, sub["member_id"])
    if sub["status"] != "PAUSED":
        raise err_invalid_state("Only a PAUSED subscription can be resumed")
    member = STORE["members"].get(sub["member_id"])
    if member is not None and member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409,
                       "Manual resume requires the member account to be ACTIVE")
    engine.resume_subscription(sub)
    return envelope_ok(serialize_subscription(sub), "object", 200)


def cancel_subscription_route(subscription_id):
    user_id, role = get_auth(request)
    require_role(role, "Member")
    sub = lookup("subscriptions", subscription_id)
    check_member_identity(user_id, role, sub["member_id"])
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise err_invalid_state("Only an ACTIVE or PAUSED subscription can be cancelled")
    engine.cancel_subscription(sub)
    return envelope_ok(serialize_subscription(sub), "object", 200)


def change_plan(subscription_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices")
    sub = lookup("subscriptions", subscription_id)
    check_member_identity(user_id, role, sub["member_id"])
    body = parse_body(request, {
        "new_plan_id": ("str", True, None),
        "expected_subscription_version": ("int", True, None),
    })
    new_plan = lookup("plans", body["new_plan_id"])
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise err_invalid_state("Plan change requires an ACTIVE or PAUSED subscription")
    # Priority 6: OCC
    if body["expected_subscription_version"] != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_subscription_version does not match the current version")
    sub["plan_id"] = new_plan["id"]
    touch(sub)
    return envelope_ok(serialize_subscription(sub), "object", 200)


# ================= Credit buckets =================

def list_subscription_buckets(subscription_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "ProgramAdmin")
    sub = lookup("subscriptions", subscription_id)
    check_member_identity(user_id, role, sub["member_id"])
    # Lazy week-rollover creation
    if sub["status"] in ("ACTIVE", "PAUSED"):
        engine.ensure_buckets_up_to(sub, engine.week_index_at(sub, now()))
    limit, offset = get_pagination(request)
    week_index = request.args.get("week_index")
    items = [b for b in STORE["buckets"].values() if b["subscription_id"] == subscription_id]
    if week_index is not None:
        try:
            wi = int(week_index)
        except (ValueError, TypeError):
            raise err_invalid_request("week_index must be an integer")
        items = [b for b in items if b["week_index"] == wi]
    views = [serialize_bucket(b) for b in items]
    page, meta = paginate(views, limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def get_bucket(bucket_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "ProgramAdmin")
    bucket = lookup("buckets", bucket_id)
    sub = STORE["subscriptions"].get(bucket["subscription_id"])
    if role == "Member" and (sub is None or sub["member_id"] != user_id):
        raise err_forbidden("Member may only act on their own resources")
    return envelope_ok(serialize_bucket(bucket), "object", 200)


def list_buckets():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices")
    limit, offset = get_pagination(request)
    subscription_id = request.args.get("subscription_id")
    posture = request.args.get("posture")
    items = list(STORE["buckets"].values())
    if subscription_id is not None:
        items = [b for b in items if b["subscription_id"] == subscription_id]
    views = [serialize_bucket(b) for b in items]
    if posture is not None:
        views = [v for v in views if v["posture"] == posture]
    page, meta = paginate(views, limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)

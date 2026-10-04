"""Subscriptions, partner discounts, family groups, invoices."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, fmt_dt, _parse_dt
from errors import ApiError
from middleware import require_roles, body, require_field, pagination_params, paginate
from models import new_entity, touch
from response import success
from serializers import present, present_list
import services

bp = Blueprint("subscriptions", __name__)


def _sorted(collection):
    return sorted(collection, key=lambda e: (e["created_at"], e["id"]))


# ---------------- subscriptions ----------------

@bp.post("/subscriptions")
@require_roles("Member")
def create_subscription():
    data = body()
    member_id = require_field(data, "member_id")
    plan = require_field(data, "plan")
    billing_cycle_day = require_field(data, "billing_cycle_day")
    member = services.get_member(member_id)
    if request.user_role == "Member" and request.user_id != member_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only create their own subscription")
    if plan not in ("INDIVIDUAL", "FAMILY"):
        raise ApiError("ERR_VALIDATION", 400, "plan must be INDIVIDUAL or FAMILY")
    if not isinstance(billing_cycle_day, int) or not (1 <= billing_cycle_day <= 28):
        raise ApiError("ERR_VALIDATION", 400, "billing_cycle_day must be within 1..28")
    for s in store.subscriptions.values():
        if s["member_id"] == member_id and s["status"] in ("ACTIVE", "PAST_DUE"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Member already has an ACTIVE or PAST_DUE subscription")
    sub = new_entity()
    sub.update({
        "member_id": member_id,
        "plan": plan,
        "price_cents": services.subscription_price_cents(plan, None),
        "billing_cycle_day": billing_cycle_day,
        "partner_discount_id": None,
        "status": "ACTIVE",
        "current_period_start": None,
        "current_period_end": None,
        "pending_plan": None,
        "past_due_since": None,
    })
    store.subscriptions[sub["id"]] = sub
    member["subscription_id"] = sub["id"]
    touch(member)
    if member["status"] == "ACTIVE":
        # member already enrolled: activate the subscription immediately
        now = store.now()
        sub["current_period_start"] = fmt_dt(now)
        sub["current_period_end"] = fmt_dt(now + timedelta(days=30))
        sub["updated_at"] = fmt_dt(now)
    if plan == "FAMILY":
        services.create_family_group(sub)
    return success(present(sub), status_code=201)


@bp.get("/subscriptions")
@require_roles("OpsAdmin", "Member")
def list_subscriptions():
    limit, offset = pagination_params()
    items = _sorted(store.subscriptions.values())
    mid = request.args.get("member_id")
    did = request.args.get("partner_discount_id")
    if mid is not None:
        items = [s for s in items if s["member_id"] == mid]
    if did is not None:
        items = [s for s in items if s.get("partner_discount_id") == did]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/subscriptions/<sid>")
@require_roles("OpsAdmin", "Member")
def get_subscription(sid):
    s = store.subscriptions.get(sid)
    if s is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    return success(present(s))


@bp.post("/subscriptions/<sid>/attach-discount")
@require_roles("Member")
def attach_discount(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    if request.user_role == "Member" and request.user_id != sub["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only manage their own subscription")
    data = body()
    code = require_field(data, "discount_code")
    discount = None
    for d in store.partner_discounts.values():
        if d["code"] == code:
            discount = d
            break
    if discount is None:
        raise ApiError("ERR_DISCOUNT_NOT_FOUND", 404, "Discount code not found")
    if discount["status"] != "ACTIVE":
        if discount["status"] == "EXHAUSTED":
            raise ApiError("ERR_DISCOUNT_EXHAUSTED", 422, "Discount is exhausted")
        raise ApiError("ERR_INVALID_STATE", 409, "Discount is not ACTIVE")
    if store.now() >= _parse_dt(discount["expires_at"]):
        raise ApiError("ERR_DISCOUNT_EXPIRED", 422, "Discount has expired")
    if discount["redemptions_used"] >= discount["max_redemptions"]:
        raise ApiError("ERR_DISCOUNT_EXHAUSTED", 422, "Discount is exhausted")
    discount["redemptions_used"] += 1
    if discount["redemptions_used"] >= discount["max_redemptions"]:
        discount["status"] = "EXHAUSTED"
    touch(discount)
    sub["partner_discount_id"] = discount["id"]
    sub["price_cents"] = services.subscription_price_cents(sub["plan"], discount)
    touch(sub)
    return success(present(sub))


@bp.post("/subscriptions/<sid>/detach-discount")
@require_roles("Member")
def detach_discount(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    if request.user_role == "Member" and request.user_id != sub["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only manage their own subscription")
    sub["partner_discount_id"] = None
    sub["price_cents"] = services.subscription_price_cents(sub["plan"], None)
    touch(sub)
    return success(present(sub))


@bp.post("/subscriptions/<sid>/change-plan")
@require_roles("Member")
def change_plan(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    if request.user_role == "Member" and request.user_id != sub["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only manage their own subscription")
    data = body()
    new_plan = require_field(data, "new_plan")
    expected_version = require_field(data, "expected_subscription_version")
    if new_plan not in ("INDIVIDUAL", "FAMILY"):
        raise ApiError("ERR_VALIDATION", 400, "new_plan must be INDIVIDUAL or FAMILY")
    if not isinstance(expected_version, int):
        raise ApiError("ERR_VALIDATION", 400, "expected_subscription_version must be an integer")
    if sub["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is CANCELLED")
    if expected_version != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale subscription version")
    if new_plan == sub["plan"]:
        raise ApiError("ERR_VALIDATION", 400, "new_plan equals current plan")
    if new_plan == "INDIVIDUAL":
        # FAMILY -> INDIVIDUAL: immediate, no refund; dissolve family group
        sub["plan"] = "INDIVIDUAL"
        sub["pending_plan"] = None
        group = services.find_family_group_for_subscription(sub["id"])
        if group is not None:
            services.dissolve_family_group(group)
        discount = None
        if sub.get("partner_discount_id"):
            discount = store.partner_discounts.get(sub["partner_discount_id"])
        sub["price_cents"] = services.subscription_price_cents("INDIVIDUAL", discount)
    else:
        # INDIVIDUAL -> FAMILY: deferred to next renewal
        sub["pending_plan"] = "FAMILY"
    touch(sub)
    return success(present(sub))


@bp.post("/subscriptions/<sid>/cancel")
@require_roles("Member")
def cancel_subscription(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    if request.user_role == "Member" and request.user_id != sub["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only cancel their own subscription")
    if sub["status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE or PAST_DUE")
    member = store.members.get(sub["member_id"])
    if member is None or member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Member is not ACTIVE")
    services.cancel_subscription(sub, actor=request.user_id)
    return success(present(sub))


@bp.post("/subscriptions/<sid>/invoices/run-cycle")
@require_roles("OpsAdmin")
def run_invoice_cycle(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    if sub["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is CANCELLED")
    amount = services.invoice_amount_cents(sub)
    period_start = sub.get("current_period_start")
    period_end = sub.get("current_period_end")
    inv = new_entity()
    inv.update({
        "subscription_id": sub["id"],
        "period_start": period_start,
        "period_end": period_end,
        "amount_cents": amount,
        "status": "DUE",
        "attempt_count": 0,
        "due_at": period_end,
    })
    store.subscription_invoices[inv["id"]] = inv
    return success(present(inv), status_code=201)


@bp.get("/subscriptions/<sid>/invoices")
@require_roles("OpsAdmin", "Member")
def list_invoices(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    limit, offset = pagination_params()
    items = [i for i in _sorted(store.subscription_invoices.values())
             if i["subscription_id"] == sid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/subscription-invoices/<iid>")
@require_roles("OpsAdmin", "Member")
def get_invoice(iid):
    inv = store.subscription_invoices.get(iid)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", 404, "Invoice not found")
    return success(present(inv))


# ---------------- family groups ----------------

@bp.get("/family-groups")
@require_roles("OpsAdmin", "Member")
def list_family_groups():
    limit, offset = pagination_params()
    items = _sorted(store.family_groups.values())
    psid = request.args.get("primary_subscription_id")
    if psid is not None:
        items = [g for g in items if g["primary_subscription_id"] == psid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/family-groups/<gid>")
@require_roles("OpsAdmin", "Member")
def get_family_group(gid):
    g = store.family_groups.get(gid)
    if g is None:
        raise ApiError("ERR_FAMILY_GROUP_NOT_FOUND", 404, "Family group not found")
    return success(present(g))


@bp.post("/family-groups/<gid>/members")
@require_roles("Member")
def add_family_member(gid):
    g = store.family_groups.get(gid)
    if g is None:
        raise ApiError("ERR_FAMILY_GROUP_NOT_FOUND", 404, "Family group not found")
    data = body()
    member_id = require_field(data, "member_id")
    member = services.get_member(member_id)
    # primary ownership: caller must be the group's primary member
    sub = store.subscriptions.get(g["primary_subscription_id"])
    if request.user_role == "Member":
        if sub is None or request.user_id != sub["member_id"]:
            raise ApiError("ERR_UNAUTHORIZED", 403,
                           "Only the primary member may manage the family group")
    if g["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Family group is not ACTIVE")
    if g["slots_used"] >= g["slots_total"]:
        raise ApiError("ERR_FAMILY_FULL", 422, "Family group is full")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Member is not ACTIVE")
    if member.get("family_group_id"):
        raise ApiError("ERR_VALIDATION", 400, "Member already belongs to a family group")
    member["family_group_id"] = g["id"]
    touch(member)
    g["slots_used"] += 1
    touch(g)
    return success(present(g), status_code=201)


@bp.delete("/family-groups/<gid>/members/<member_id>")
@require_roles("Member")
def remove_family_member(gid, member_id):
    g = store.family_groups.get(gid)
    if g is None:
        raise ApiError("ERR_FAMILY_GROUP_NOT_FOUND", 404, "Family group not found")
    member = store.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    sub = store.subscriptions.get(g["primary_subscription_id"])
    if request.user_role == "Member":
        if sub is None or request.user_id != sub["member_id"]:
            raise ApiError("ERR_UNAUTHORIZED", 403,
                           "Only the primary member may manage the family group")
    if sub is not None and member_id == sub["member_id"]:
        raise ApiError("ERR_VALIDATION", 400, "Cannot detach the primary member")
    if member.get("family_group_id") != g["id"]:
        raise ApiError("ERR_VALIDATION", 400, "Member is not attached to this group")
    member["family_group_id"] = None
    touch(member)
    g["slots_used"] = max(0, g["slots_used"] - 1)
    touch(g)
    return success(present(g))


# ---------------- partner discounts ----------------

@bp.post("/partner-discounts")
@require_roles("PartnerManager")
def create_discount():
    data = body()
    airport_id = require_field(data, "airport_id")
    code = require_field(data, "code")
    percent_off = require_field(data, "percent_off")
    max_redemptions = require_field(data, "max_redemptions")
    expires_at = require_field(data, "expires_at")
    if store.airports.get(airport_id) is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    for d in store.partner_discounts.values():
        if d["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "Discount code already in use")
    if not isinstance(percent_off, int) or not (1 <= percent_off <= 100):
        raise ApiError("ERR_VALIDATION", 400, "percent_off must be within 1..100")
    if not isinstance(max_redemptions, int) or max_redemptions < 1:
        raise ApiError("ERR_VALIDATION", 400, "max_redemptions must be >= 1")
    try:
        exp = _parse_dt(expires_at)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "expires_at must be an ISO datetime")
    d = new_entity()
    d.update({
        "airport_id": airport_id,
        "code": code,
        "percent_off": percent_off,
        "max_redemptions": max_redemptions,
        "redemptions_used": 0,
        "status": "ACTIVE",
        "expires_at": fmt_dt(exp),
    })
    store.partner_discounts[d["id"]] = d
    return success(present(d), status_code=201)


@bp.get("/partner-discounts")
@require_roles("OpsAdmin", "PartnerManager", "Member")
def list_discounts():
    limit, offset = pagination_params()
    items = _sorted(store.partner_discounts.values())
    ap = request.args.get("airport_id")
    if ap is not None:
        items = [d for d in items if d["airport_id"] == ap]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/partner-discounts/<did>")
@require_roles("OpsAdmin", "PartnerManager", "Member")
def get_discount(did):
    d = store.partner_discounts.get(did)
    if d is None:
        raise ApiError("ERR_DISCOUNT_NOT_FOUND", 404, "Discount not found")
    return success(present(d))


@bp.post("/partner-discounts/<did>/suspend")
@require_roles("PartnerManager")
def suspend_discount(did):
    d = store.partner_discounts.get(did)
    if d is None:
        raise ApiError("ERR_DISCOUNT_NOT_FOUND", 404, "Discount not found")
    if d["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Discount is not ACTIVE")
    d["status"] = "SUSPENDED"
    touch(d)
    return success(present(d))

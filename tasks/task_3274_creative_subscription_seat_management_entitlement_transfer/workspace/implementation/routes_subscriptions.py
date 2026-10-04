"""Subscriptions, Seats, Entitlements routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_invalid_request,
    err_not_found,
    err_reference_not_found,
    err_invalid_state,
    err_stale_version,
    err_org_frozen,
    err_seat_capacity,
    err_reseller_suspended,
    err_subscription_not_active,
    err_user_not_active,
    err_cross_org,
    err_duplicate_plan_seat,
    err_reclaim_grace,
    err_device_limit,
    err_identity_mismatch,
)
from helpers import (
    make_record,
    touch,
    require_fields,
    require_int,
    compute_monthly_charge,
    default_product_version,
    refresh_org,
    subscription_settle,
    finalize_reclaim,
    entitlements_of_seat,
    suspend_entitlement,
    resume_entitlement,
)
from middleware import get_identity, require_role, resolve_identity, require_org_scope
from response import (
    success_object,
    success_list,
    paginate,
    now_dt,
    now_iso,
    add_hours,
    iso_no_frac,
    parse_iso,
)

bp = Blueprint("subscriptions", __name__)


def _org_of_subscription(sub):
    return sub["org_id"]


# ---------------- subscriptions ----------------

@bp.post("/licensing/subscriptions")
def create_subscription():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["org_id", "plan_id", "seats_purchased"])
    if payload["org_id"] not in db["organizations"]:
        raise err_reference_not_found("org_id does not exist")
    plan = db["plans"].get(payload["plan_id"])
    if plan is None:
        raise err_reference_not_found("plan_id does not exist")
    reseller_id = payload.get("reseller_id")
    if reseller_id is not None and reseller_id not in db["resellers"]:
        raise err_reference_not_found("reseller_id does not exist")
    seats = require_int(payload, "seats_purchased", minimum=1)
    if plan["seat_limit"] != -1 and seats > plan["seat_limit"]:
        raise err_seat_capacity("seats_purchased exceeds plan seat_limit")
    rec = make_record({
        "org_id": payload["org_id"],
        "plan_id": payload["plan_id"],
        "reseller_id": reseller_id,
        "status": "PENDING_PAYMENT",
        "seats_purchased": seats,
        "seats_assigned": 0,
        "commitment_start": None,
        "commitment_months": 0,
        "months_elapsed": 0,
        "monthly_charge_cents": 0,
    })
    db["subscriptions"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/subscriptions")
def list_subscriptions():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    items = list(db["subscriptions"].values())
    if identity.role == "OrgAdmin" and identity.admin:
        items = [s for s in items if s["org_id"] == identity.admin["org_id"]]
    for key in ("org_id", "plan_id", "reseller_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [s for s in items if str(s.get(key)) == v]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/subscriptions/<sid>")
def get_subscription(sid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    sub = db["subscriptions"].get(sid)
    if sub is None:
        raise err_not_found("Subscription not found")
    require_org_scope(identity, sub["org_id"])
    return success_object(sub)


@bp.post("/licensing/subscriptions/<sid>/activate")
def activate_subscription(sid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    sub = db["subscriptions"].get(sid)
    if sub is None:
        raise err_not_found("Subscription not found")
    if sub["status"] != "PENDING_PAYMENT":
        raise err_invalid_state("Subscription is not PENDING_PAYMENT")
    org = db["organizations"].get(sub["org_id"])
    if org is None or org["status"] != "ACTIVE":
        raise err_invalid_state("Organization is not ACTIVE")
    if org["compliance_posture"] == "FROZEN":
        raise err_org_frozen()
    plan = db["plans"].get(sub["plan_id"])
    if sub["seats_purchased"] < 1:
        raise err_seat_capacity()
    if plan and plan["seat_limit"] != -1 and sub["seats_purchased"] > plan["seat_limit"]:
        raise err_seat_capacity("seats_purchased exceeds plan seat_limit")
    if sub.get("reseller_id"):
        reseller = db["resellers"].get(sub["reseller_id"])
        if reseller is None or reseller["status"] != "ACTIVE":
            raise err_reseller_suspended()
    sub["status"] = "ACTIVE"
    sub["commitment_start"] = now_iso()
    sub["commitment_months"] = 1 if plan["billing_model"] == "MONTHLY" else 12
    sub["months_elapsed"] = 0
    sub["monthly_charge_cents"] = compute_monthly_charge(sub)
    touch(sub)
    # mint seats per seats_purchased
    for _ in range(sub["seats_purchased"]):
        seat = make_record({
            "subscription_id": sub["id"],
            "end_user_id": None,
            "status": "UNASSIGNED",
            "assigned_at": None,
            "pending_reclaim_not_before": None,
        })
        db["seats"][seat["id"]] = seat
    refresh_org(sub["org_id"])
    return success_object(sub)


@bp.post("/licensing/subscriptions/<sid>/settle")
def settle_subscription(sid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    sub = db["subscriptions"].get(sid)
    if sub is None:
        raise err_not_found("Subscription not found")
    if sub["status"] != "PAST_DUE":
        raise err_invalid_state("Subscription is not PAST_DUE")
    org = db["organizations"].get(sub["org_id"])
    if org is None or org["status"] != "ACTIVE":
        raise err_invalid_state("Organization is not ACTIVE")
    subscription_settle(sub)
    return success_object(sub)


# ---------------- seats ----------------

@bp.post("/licensing/seats")
def create_seat():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["subscription_id", "expected_subscription_version"])
    sub = db["subscriptions"].get(payload["subscription_id"])
    if sub is None:
        raise err_reference_not_found("subscription_id does not exist")
    expected = payload["expected_subscription_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_subscription_version must be an integer")
    if expected != sub["version"]:
        raise err_stale_version()
    seat = make_record({
        "subscription_id": sub["id"],
        "end_user_id": None,
        "status": "UNASSIGNED",
        "assigned_at": None,
        "pending_reclaim_not_before": None,
    })
    db["seats"][seat["id"]] = seat
    touch(sub)
    refresh_org(sub["org_id"])
    return success_object(seat, 201)


@bp.get("/licensing/seats")
def list_seats():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    items = list(db["seats"].values())
    if identity.role == "OrgAdmin" and identity.admin:
        org_id = identity.admin["org_id"]
        sub_org = {s["id"]: s["org_id"] for s in db["subscriptions"].values()}
        items = [s for s in items if sub_org.get(s["subscription_id"]) == org_id]
    for key in ("subscription_id", "end_user_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [s for s in items if str(s.get(key)) == v]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/seats/<sid>")
def get_seat(sid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    seat = db["seats"].get(sid)
    if seat is None:
        raise err_not_found("Seat not found")
    sub = db["subscriptions"].get(seat["subscription_id"])
    require_org_scope(identity, sub["org_id"] if sub else None)
    out = {k: v for k, v in seat.items() if not k.startswith("_")}
    return success_object(out)


def _check_duplicate_plan_seat(sub, end_user_id, exclude_seat_id=None):
    """No other ASSIGNED/TRANSFERRING seat under the same plan in this org for this user."""
    plan_id = sub["plan_id"]
    org_id = sub["org_id"]
    for s in db["subscriptions"].values():
        if s["org_id"] != org_id or s["plan_id"] != plan_id:
            continue
        for seat in db["seats"].values():
            if seat["subscription_id"] != s["id"]:
                continue
            if exclude_seat_id and seat["id"] == exclude_seat_id:
                continue
            if seat["status"] in ("ASSIGNED", "TRANSFERRING") and seat["end_user_id"] == end_user_id:
                raise err_duplicate_plan_seat()


@bp.post("/licensing/seats/<sid>/assign")
def assign_seat(sid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    seat = db["seats"].get(sid)
    if seat is None:
        raise err_not_found("Seat not found")
    sub = db["subscriptions"].get(seat["subscription_id"])
    require_org_scope(identity, sub["org_id"])
    payload = request.get_json(silent=True)
    require_fields(payload, ["end_user_id"])
    user = db["end_users"].get(payload["end_user_id"])
    if user is None:
        raise err_reference_not_found("end_user_id does not exist")
    if seat["status"] not in ("UNASSIGNED", "RECLAIMED"):
        raise err_invalid_state("Seat is not assignable")
    if sub["status"] != "ACTIVE":
        raise err_subscription_not_active()
    org = db["organizations"].get(sub["org_id"])
    if org and org["compliance_posture"] == "FROZEN":
        raise err_org_frozen()
    if user["org_id"] != sub["org_id"]:
        raise err_cross_org()
    if user["status"] != "ACTIVE":
        raise err_user_not_active()
    if sub["seats_assigned"] >= sub["seats_purchased"]:
        raise err_seat_capacity()
    _check_duplicate_plan_seat(sub, user["id"])
    plan = db["plans"][sub["plan_id"]]
    pv = default_product_version(plan["id"])
    seat["status"] = "ASSIGNED"
    seat["end_user_id"] = user["id"]
    seat["assigned_at"] = now_iso()
    touch(seat)
    sub["seats_assigned"] += 1
    touch(sub)
    ent = make_record({
        "seat_id": seat["id"],
        "device_id": None,
        "status": "PENDING_ACTIVATION",
        "product_version_id": pv["id"],
        "storage_granted_gb": plan["storage_gb_per_seat"],
    })
    db["entitlements"][ent["id"]] = ent
    refresh_org(sub["org_id"])
    out = {k: v for k, v in seat.items() if not k.startswith("_")}
    return success_object(out)


@bp.post("/licensing/seats/<sid>/reclaim")
def reclaim_seat(sid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    seat = db["seats"].get(sid)
    if seat is None:
        raise err_not_found("Seat not found")
    sub = db["subscriptions"].get(seat["subscription_id"])
    require_org_scope(identity, sub["org_id"])
    if seat["status"] != "ASSIGNED":
        raise err_invalid_state("Seat is not ASSIGNED")
    if sub["status"] not in ("ACTIVE", "PAST_DUE"):
        raise err_subscription_not_active("Subscription must be ACTIVE or PAST_DUE")
    seat["status"] = "PENDING_RECLAIM"
    seat["pending_reclaim_not_before"] = iso_no_frac(add_hours(now_dt(), 24))
    touch(seat)
    for ent in entitlements_of_seat(sid):
        suspend_entitlement(ent)
    out = {k: v for k, v in seat.items() if not k.startswith("_")}
    return success_object(out)


@bp.post("/licensing/seats/<sid>/reclaim/cancel")
def cancel_reclaim(sid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    seat = db["seats"].get(sid)
    if seat is None:
        raise err_not_found("Seat not found")
    sub = db["subscriptions"].get(seat["subscription_id"])
    require_org_scope(identity, sub["org_id"])
    if seat["status"] != "PENDING_RECLAIM":
        raise err_invalid_state("Seat is not PENDING_RECLAIM")
    if seat["pending_reclaim_not_before"] and now_dt() >= parse_iso(seat["pending_reclaim_not_before"]):
        raise err_invalid_state("Grace period already lapsed")
    seat["status"] = "ASSIGNED"
    seat["pending_reclaim_not_before"] = None
    seat.pop("_deactivation_initiated", None)
    touch(seat)
    for ent in entitlements_of_seat(sid):
        resume_entitlement(ent)
    out = {k: v for k, v in seat.items() if not k.startswith("_")}
    return success_object(out)


@bp.post("/licensing/seats/<sid>/reclaim/finalize")
def finalize_reclaim_endpoint(sid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    seat = db["seats"].get(sid)
    if seat is None:
        raise err_not_found("Seat not found")
    sub = db["subscriptions"].get(seat["subscription_id"])
    require_org_scope(identity, sub["org_id"])
    if seat["status"] != "PENDING_RECLAIM":
        raise err_invalid_state("Seat is not PENDING_RECLAIM")
    if seat["pending_reclaim_not_before"] and now_dt() < parse_iso(seat["pending_reclaim_not_before"]):
        raise err_reclaim_grace()
    finalize_reclaim(seat)
    out = {k: v for k, v in seat.items() if not k.startswith("_")}
    return success_object(out)


# ---------------- entitlements ----------------

@bp.get("/licensing/entitlements")
def list_entitlements():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "EndUser"])
    resolve_identity(identity)
    items = list(db["entitlements"].values())
    if identity.role == "EndUser":
        my_seats = {s["id"] for s in db["seats"].values() if s["end_user_id"] == identity.user_id}
        items = [e for e in items if e["seat_id"] in my_seats]
    elif identity.role == "OrgAdmin" and identity.admin:
        org_id = identity.admin["org_id"]
        sub_org = {s["id"]: s["org_id"] for s in db["subscriptions"].values()}
        seat_sub = {s["id"]: s["subscription_id"] for s in db["seats"].values()}
        items = [e for e in items if sub_org.get(seat_sub.get(e["seat_id"])) == org_id]
    for key in ("seat_id", "device_id", "status", "product_version_id"):
        v = request.args.get(key)
        if v is not None:
            items = [e for e in items if str(e.get(key)) == v]
    items.sort(key=lambda e: e["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/entitlements/<eid>")
def get_entitlement(eid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "EndUser"])
    resolve_identity(identity)
    ent = db["entitlements"].get(eid)
    if ent is None:
        raise err_not_found("Entitlement not found")
    seat = db["seats"].get(ent["seat_id"])
    sub = db["subscriptions"].get(seat["subscription_id"]) if seat else None
    if identity.role == "EndUser":
        if not seat or seat["end_user_id"] != identity.user_id:
            raise err_identity_mismatch("Entitlement does not belong to caller")
    elif identity.role == "OrgAdmin":
        require_org_scope(identity, sub["org_id"] if sub else None)
    return success_object(ent)


@bp.post("/licensing/entitlements/<eid>/activate")
def activate_entitlement(eid):
    identity = get_identity()
    require_role(identity, ["EndUser"])
    resolve_identity(identity)
    ent = db["entitlements"].get(eid)
    if ent is None:
        raise err_not_found("Entitlement not found")
    payload = request.get_json(silent=True)
    require_fields(payload, ["device_id"])
    device = db["devices"].get(payload["device_id"])
    if device is None:
        raise err_reference_not_found("device_id does not exist")
    seat = db["seats"].get(ent["seat_id"])
    if seat is None or seat["end_user_id"] != identity.user_id:
        raise err_identity_mismatch("Caller is not the seat's current assignee")
    if ent["status"] != "PENDING_ACTIVATION":
        raise err_invalid_state("Entitlement is not PENDING_ACTIVATION")
    if seat["status"] != "ASSIGNED":
        raise err_invalid_state("Seat is not ASSIGNED")
    sub = db["subscriptions"].get(seat["subscription_id"])
    if sub is None or sub["status"] != "ACTIVE":
        raise err_subscription_not_active()
    if device["end_user_id"] != identity.user_id:
        raise err_identity_mismatch("Device does not belong to caller")
    if device["status"] != "ACTIVE":
        raise err_invalid_state("Device is not ACTIVE")
    plan = db["plans"][sub["plan_id"]]
    active_device_ents = [
        e for e in db["entitlements"].values()
        if e["seat_id"] == seat["id"] and e["status"] == "ACTIVE" and e.get("device_id")
    ]
    if len(active_device_ents) >= plan["max_devices_per_seat"]:
        raise err_device_limit()
    pv = db["product_versions"].get(ent["product_version_id"])
    if pv and pv.get("forced_upgrade_deadline"):
        if now_dt() >= parse_iso(pv["forced_upgrade_deadline"]):
            latest = default_product_version(plan["id"])
            ent["product_version_id"] = latest["id"]
    ent["status"] = "ACTIVE"
    ent["device_id"] = device["id"]
    touch(ent)
    return success_object(ent)

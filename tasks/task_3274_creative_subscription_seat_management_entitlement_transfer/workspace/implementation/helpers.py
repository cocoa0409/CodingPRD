"""Shared helpers: record creation, derived computations, system sweeps."""

import math
import uuid
from datetime import timezone

from db import db, clock
from errors import err_invalid_request, err_no_available_version
from response import (
    iso_no_frac,
    now_dt,
    now_iso,
    parse_iso,
    add_hours,
    add_months,
    months_elapsed_between,
)

RESELLER_DISCOUNT = {"CERTIFIED": 5, "GOLD": 10, "PLATINUM": 15}
TIER_PRIORITY = {"PLATINUM": 3, "GOLD": 2, "CERTIFIED": 1}


def new_id():
    return str(uuid.uuid4())


def make_record(fields):
    now = now_iso()
    rec = dict(fields)
    rec.setdefault("id", new_id())
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def require_fields(payload, field_names):
    if payload is None or not isinstance(payload, dict):
        raise err_invalid_request("Request body must be a JSON object")
    for f in field_names:
        if f not in payload or payload[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")
    return payload


def require_int(payload, name, minimum=None, allow_negative_one=False):
    v = payload.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {name} must be an integer")
    if allow_negative_one and v == -1:
        return v
    if minimum is not None and v < minimum:
        raise err_invalid_request(f"Field {name} must be >= {minimum}")
    return v


def require_enum(payload, name, allowed):
    v = payload.get(name)
    if v not in allowed:
        raise err_invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---------------- derived computations ----------------

def default_product_version(plan_id):
    """Latest AVAILABLE ProductVersion of the plan: release_date DESC, created_at ASC."""
    candidates = [
        v for v in db["product_versions"].values()
        if v["plan_id"] == plan_id and v["availability"] == "AVAILABLE"
    ]
    if not candidates:
        raise err_no_available_version()
    candidates.sort(key=lambda v: v["created_at"])
    candidates.sort(key=lambda v: parse_iso(v["release_date"]), reverse=True)
    return candidates[0]


def compute_org_storage_pool(org_id):
    total = 0
    for sub in db["subscriptions"].values():
        if sub["org_id"] != org_id:
            continue
        if sub["status"] == "ACTIVE":
            plan = db["plans"].get(sub["plan_id"])
            if plan:
                total += sub["seats_assigned"] * plan["storage_gb_per_seat"]
    active_sub_ids = {
        s["id"] for s in db["subscriptions"].values() if s["org_id"] == org_id
    }
    for addon in db["add_on_services"].values():
        if addon["subscription_id"] not in active_sub_ids:
            continue
        if addon["kind"] == "CLOUD_SERVICES" and addon["status"] in ("ACTIVE", "EXHAUSTED"):
            total += addon["quota_total"]
    return total


def org_over_allocated(org_id):
    over = 0
    for sub in db["subscriptions"].values():
        if sub["org_id"] != org_id:
            continue
        over += max(0, sub["seats_assigned"] - sub["seats_purchased"])
    return over


def compute_org_posture(org_id):
    over = org_over_allocated(org_id)
    under_audit = any(
        a["org_id"] == org_id and a["status"] in ("OPEN", "FINDINGS_RAISED")
        for a in db["compliance_audits"].values()
    )
    findings_raised = any(
        a["org_id"] == org_id and a["status"] == "FINDINGS_RAISED"
        for a in db["compliance_audits"].values()
    )
    if findings_raised and over > 0:
        return "FROZEN"
    if over > 0:
        return "OVER_ALLOCATED"
    if under_audit:
        return "UNDER_AUDIT"
    return "COMPLIANT"


def refresh_org(org_id):
    org = db["organizations"].get(org_id)
    if org is None:
        return None
    pool = compute_org_storage_pool(org_id)
    posture = compute_org_posture(org_id)
    changed = (org.get("storage_pool_gb") != pool) or (org.get("compliance_posture") != posture)
    org["storage_pool_gb"] = pool
    org["compliance_posture"] = posture
    if changed:
        touch(org)
    return org


def compute_user_storage_used(user_id):
    total_mb = 0
    for asset in db["assets"].values():
        if asset["owner_user_id"] == user_id and asset["status"] in ("ACTIVE", "IN_TRANSFER"):
            total_mb += asset["size_mb"]
    return math.ceil(total_mb / 1024) if total_mb > 0 else 0


def refresh_user_storage(user_id):
    user = db["end_users"].get(user_id)
    if user is None:
        return
    used = compute_user_storage_used(user_id)
    if user.get("storage_used_gb") != used:
        user["storage_used_gb"] = used
        touch(user)


def compute_monthly_charge(sub):
    plan = db["plans"][sub["plan_id"]]
    if plan["billing_model"] == "MONTHLY":
        base = plan["monthly_price_cents"]
    else:
        base = plan["annual_monthly_price_cents"]
    discount_pct = 0
    if sub.get("reseller_id"):
        reseller = db["resellers"].get(sub["reseller_id"])
        if reseller:
            discount_pct = RESELLER_DISCOUNT[reseller["tier"]]
    per_seat = (base * (100 - discount_pct)) // 100
    return per_seat * sub["seats_purchased"]


def compute_etf(sub):
    plan = db["plans"][sub["plan_id"]]
    start = parse_iso(sub["commitment_start"])
    now = now_dt()
    months_elapsed = months_elapsed_between(start, now)
    sub["months_elapsed"] = months_elapsed
    remaining_months = sub["commitment_months"] - months_elapsed
    if remaining_months < 0:
        remaining_months = 0
    remaining_value = remaining_months * sub["monthly_charge_cents"]
    return (remaining_value * plan["etf_rate_pct"]) // 100


# ---------------- entitlement cascades ----------------

def entitlements_of_subscription(subscription_id):
    seat_ids = {s["id"] for s in db["seats"].values() if s["subscription_id"] == subscription_id}
    return [e for e in db["entitlements"].values() if e["seat_id"] in seat_ids]


def entitlements_of_seat(seat_id):
    return [e for e in db["entitlements"].values() if e["seat_id"] == seat_id]


def suspend_entitlement(ent):
    if ent["status"] == "ACTIVE":
        ent["status"] = "SUSPENDED"
        touch(ent)


def resume_entitlement(ent):
    if ent["status"] == "SUSPENDED":
        ent["status"] = "ACTIVE"
        touch(ent)


def revoke_entitlement(ent):
    if ent["status"] in ("ACTIVE", "SUSPENDED", "PENDING_ACTIVATION"):
        ent["status"] = "REVOKED"
        ent["device_id"] = None
        touch(ent)


def subscription_past_due(sub):
    if sub["status"] != "ACTIVE":
        return
    sub["status"] = "PAST_DUE"
    touch(sub)
    for ent in entitlements_of_subscription(sub["id"]):
        suspend_entitlement(ent)
    refresh_org(sub["org_id"])


def subscription_settle(sub):
    sub["status"] = "ACTIVE"
    touch(sub)
    for ent in entitlements_of_subscription(sub["id"]):
        resume_entitlement(ent)
    refresh_org(sub["org_id"])


def subscription_expire(sub):
    sub["status"] = "EXPIRED"
    touch(sub)
    for seat in db["seats"].values():
        if seat["subscription_id"] != sub["id"]:
            continue
        if seat["status"] == "ASSIGNED":
            seat["status"] = "RECLAIMED"
            seat["end_user_id"] = None
            seat["assigned_at"] = None
            seat["pending_reclaim_not_before"] = None
            touch(seat)
    sub["seats_assigned"] = 0
    touch(sub)
    for ent in entitlements_of_subscription(sub["id"]):
        revoke_entitlement(ent)
    refresh_org(sub["org_id"])


def finalize_reclaim(seat):
    sub = db["subscriptions"][seat["subscription_id"]]
    seat["status"] = "RECLAIMED"
    seat["end_user_id"] = None
    seat["assigned_at"] = None
    seat["pending_reclaim_not_before"] = None
    seat.pop("_deactivation_initiated", None)
    touch(seat)
    if sub["seats_assigned"] > 0:
        sub["seats_assigned"] -= 1
        touch(sub)
    for ent in entitlements_of_seat(seat["id"]):
        revoke_entitlement(ent)
    refresh_org(sub["org_id"])


# ---------------- system sweeps ----------------

def run_sweeps():
    now = now_dt()
    # billing sweep: ACTIVE -> PAST_DUE when clock passes monthly invoice due date
    for sub in list(db["subscriptions"].values()):
        if sub["status"] != "ACTIVE":
            continue
        start = parse_iso(sub["commitment_start"])
        if sub["commitment_months"] == 1:
            # MONTHLY: monthly invoice due each month
            due = add_months(start, 1)
            if now > due:
                subscription_past_due(sub)
        else:
            plan = db["plans"].get(sub["plan_id"])
            if plan and plan["billing_model"] == "ANNUAL_MONTHLY_BILLED":
                months = months_elapsed_between(start, now)
                due = add_months(start, months + 1)
                if now > due:
                    subscription_past_due(sub)
    # commitment expiry sweep: ANNUAL_PREPAID -> EXPIRED at commitment end
    for sub in list(db["subscriptions"].values()):
        if sub["status"] != "ACTIVE":
            continue
        plan = db["plans"].get(sub["plan_id"])
        if plan and plan["billing_model"] == "ANNUAL_PREPAID":
            end = add_months(parse_iso(sub["commitment_start"]), sub["commitment_months"])
            if now >= end:
                subscription_expire(sub)
    # transfer expiry sweep
    for tr in list(db["transfer_requests"].values()):
        if tr["status"] == "PENDING_APPROVAL":
            if now >= parse_iso(tr["expires_at"]):
                tr["status"] = "EXPIRED"
                touch(tr)
                seat = db["seats"].get(tr["seat_id"])
                if seat and seat["status"] == "TRANSFERRING":
                    seat["status"] = "ASSIGNED"
                    touch(seat)
    # metering sweep: add-on EXHAUSTED
    for addon in list(db["add_on_services"].values()):
        if addon["status"] == "ACTIVE" and addon["quota_used"] >= addon["quota_total"]:
            addon["status"] = "EXHAUSTED"
            touch(addon)
    # forced-upgrade version retirement sweep
    for pv in list(db["product_versions"].values()):
        if pv["availability"] == "FORCED_UPGRADE" and pv.get("forced_upgrade_deadline"):
            if now > parse_iso(pv["forced_upgrade_deadline"]):
                active = any(
                    e["product_version_id"] == pv["id"] and e["status"] == "ACTIVE"
                    for e in db["entitlements"].values()
                )
                if not active:
                    pv["availability"] = "DEPRECATED"
                    touch(pv)

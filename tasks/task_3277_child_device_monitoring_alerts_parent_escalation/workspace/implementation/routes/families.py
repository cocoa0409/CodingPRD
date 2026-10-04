"""Family, subscription, parent-member, and family-children listing routes."""
from flask import Blueprint, request
from db import store, clock, fmt_iso, parse_iso
from errors import fail
from response import success_object, success_list, parse_pagination
from middleware import authenticate, require_role, require_parent_scope
import services as svc
import calculations as calc
from datetime import timedelta

bp = Blueprint("families", __name__)

TIERS = {"BASIC", "STANDARD", "PREMIUM"}
VARIANTS = {"LEXICAL_V1", "CONTEXTUAL_V2"}


def _get_family(family_id):
    f = store.families.get(family_id)
    if not f:
        fail("ERR_NOT_FOUND", "Family not found")
    return f


@bp.post("/api/families")
def create_family():
    role, _uid = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = request.get_json(silent=True) or {}
    family_name = body.get("family_name")
    email = body.get("primary_contact_email")
    parent_name = body.get("primary_parent_name")
    if not isinstance(family_name, str) or not family_name:
        fail("ERR_INVALID_REQUEST", "family_name is required")
    if not isinstance(email, str) or not email:
        fail("ERR_INVALID_REQUEST", "primary_contact_email is required")
    if not isinstance(parent_name, str) or not parent_name:
        fail("ERR_INVALID_REQUEST", "primary_parent_name is required")
    tier = body.get("subscription_tier", "STANDARD")
    if tier not in TIERS:
        fail("ERR_INVALID_REQUEST", "invalid subscription_tier")
    variant = body.get("analysis_variant", "LEXICAL_V1")
    if variant not in VARIANTS:
        fail("ERR_INVALID_REQUEST", "invalid analysis_variant")

    with store.lock:
        now = clock.now()
        f = svc.new_entity()
        f.update({
            "family_name": family_name,
            "primary_contact_email": email,
            "subscription_tier": tier,
            "analysis_variant": variant,
            "account_status": "ACTIVE",
            "device_limit": calc.device_limit_for(tier),
            "device_count": 0,
            "open_escalation_count": 0,
            "last_proration_charge_cents": 0,
            "billing_period_start": fmt_iso(now),
            "billing_period_end": fmt_iso(now + timedelta(days=calc.PERIOD_DAYS)),
        })
        store.families[f["id"]] = f
        p = svc.new_entity()
        p.update({
            "family_account_id": f["id"],
            "display_name": parent_name,
            "email": email,
            "is_primary": True,
            "member_status": "ACTIVE",
        })
        store.parents[p["id"]] = p
    return success_object(svc.ser_family(f), status=201)


@bp.get("/api/families/<family_id>")
def get_family(family_id):
    role, uid = authenticate()
    require_role(role, {"PlatformAdmin", "Parent"})
    f = _get_family(family_id)
    if role == "Parent":
        require_parent_scope(uid, f["id"])
    return success_object(svc.ser_family(f))


@bp.post("/api/families/<family_id>/state")
def family_state(family_id):
    role, _uid = authenticate()
    require_role(role, {"PlatformAdmin"})
    f = _get_family(family_id)
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if to_status not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_REQUEST", "to_status must be ACTIVE or SUSPENDED")
    if to_status == f["account_status"]:
        fail("ERR_INVALID_STATE", "Family already in state %s" % to_status)
    with store.lock:
        f["account_status"] = to_status
        svc.touch(f)
    return success_object(svc.ser_family(f))


@bp.post("/api/families/<family_id>/subscription/changes")
def subscription_change(family_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    f = _get_family(family_id)
    if role == "Parent":
        require_parent_scope(uid, f["id"])
    body = request.get_json(silent=True) or {}
    # OCC check (priority 5) precedes state/business checks
    expected = body.get("expected_family_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        fail("ERR_INVALID_REQUEST", "expected_family_version is required")
    if expected != f["version"]:
        fail("ERR_STALE_VERSION", "Family version mismatch")
    new_tier = body.get("new_tier")
    if new_tier not in TIERS:
        fail("ERR_INVALID_REQUEST", "invalid new_tier")
    new_limit = calc.device_limit_for(new_tier)
    if f["device_count"] > new_limit:
        fail("ERR_DEVICE_LIMIT_EXCEEDED",
             "device_count exceeds the new tier limit")
    with store.lock:
        now = clock.now()
        charge = calc.proration_charge(
            f["subscription_tier"], new_tier, now, parse_iso(f["billing_period_end"]))
        f["subscription_tier"] = new_tier
        f["device_limit"] = new_limit
        f["last_proration_charge_cents"] = charge
        svc.touch(f)
    return success_object(svc.ser_family(f))


@bp.get("/api/families/<family_id>/parents")
def list_parents(family_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    f = _get_family(family_id)
    if role == "Parent":
        require_parent_scope(uid, f["id"])
    limit, offset = parse_pagination(request.args)
    items = [p for p in store.parents.values()
             if p.get("family_account_id") == f["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_parent(p) for p in page], limit, offset, total)


@bp.get("/api/families/<family_id>/children")
def list_children(family_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    f = _get_family(family_id)
    if role == "Parent":
        require_parent_scope(uid, f["id"])
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.children.values()
             if c.get("family_account_id") == f["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_child(c) for c in page], limit, offset, total)

"""Viewer lifecycle: registration, billing posture, cancel, view grants."""
from datetime import timedelta

import clock
import util
from db import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_BLACKOUT_REGION_BLOCKED, ERR_TERRITORY_NOT_LICENSED,
    ERR_TIER_INSUFFICIENT, ERR_REPLAY_EXPIRED,
)

TIERS = {"FREE", "AD_SUPPORTED", "PREMIUM"}
GRANT_TYPES = {"LIVE", "REPLAY"}


def create_viewer(body):
    util.require_fields(body, ["email", "home_region"], allowed_extra=["subscription_tier"])
    util.req_str(body["email"], "email")
    util.req_str(body["home_region"], "home_region")
    tier = body.get("subscription_tier", "AD_SUPPORTED")
    util.req_enum(tier, "subscription_tier", TIERS)
    for v in db.viewers.values():
        if v["email"] == body["email"]:
            raise_err(ERR_INVALID_REQUEST, "email must be unique")
    now_iso = clock.now_iso()
    viewer = {
        "id": util.new_id(),
        "email": body["email"],
        "home_region": body["home_region"],
        "subscription_tier": tier,
        "subscription_status": "ACTIVE",
        "acquisition_source": None,
        "acquisition_window_id": None,
        "marquee_credit_cents": 0,
        "grace_entered_at": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.viewers[viewer["id"]] = viewer
    return viewer


def suspend_billing(viewer):
    if viewer["subscription_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "viewer not ACTIVE")
    viewer["subscription_status"] = "GRACE"
    viewer["grace_entered_at"] = clock.now()
    util.touch(viewer)
    return viewer


def reactivate(viewer):
    if viewer["subscription_status"] not in ("GRACE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "viewer not in GRACE or SUSPENDED")
    was_suspended = viewer["subscription_status"] == "SUSPENDED"
    viewer["subscription_status"] = "ACTIVE"
    viewer["grace_entered_at"] = None
    util.touch(viewer)
    if was_suspended:
        for ent in db.entitlements.values():
            if ent["viewer_id"] == viewer["id"] and not ent["active"]:
                ent["active"] = True
    return viewer


def cancel(viewer):
    if viewer["subscription_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "viewer cannot cancel from current state")
    viewer["subscription_status"] = "CANCELLED"
    viewer["grace_entered_at"] = None
    util.touch(viewer)
    for ent in db.entitlements.values():
        if ent["viewer_id"] == viewer["id"] and ent["active"]:
            ent["active"] = False
    return viewer


def issue_view_grant(win, body, actor_id):
    util.require_fields(body, ["viewer_id", "grant_type"])
    viewer = db.viewers.get(body["viewer_id"])
    if viewer is None:
        raise_err(ERR_NOT_FOUND, "viewer not found")
    util.req_enum(body["grant_type"], "grant_type", GRANT_TYPES)
    if body["viewer_id"] != actor_id:
        from errors import ERR_FORBIDDEN
        raise_err(ERR_FORBIDDEN, "viewer may only request grants for itself")

    now = clock.now()
    # 1. blackout
    for rule in db.territory_rules.values():
        if (rule["window_id"] == win["id"] and rule["rule_status"] == "ACTIVE"
                and rule["rule_kind"] == "BLACKOUT"
                and rule["region_code"] == viewer["home_region"]
                and rule["effective_start"] <= now < rule["effective_end"]):
            raise_err(ERR_BLACKOUT_REGION_BLOCKED, "active blackout covers viewer region")
    # 2. territory
    if viewer["home_region"] not in win["territory_scope"]:
        raise_err(ERR_TERRITORY_NOT_LICENSED, "viewer region not in territory_scope")
    # 3. tier
    if body["grant_type"] == "LIVE":
        if win["rights_mode"] == "EXCLUSIVE" and viewer["subscription_tier"] != "PREMIUM":
            raise_err(ERR_TIER_INSUFFICIENT, "exclusive live grant requires PREMIUM tier")
    else:
        if viewer["subscription_status"] not in ("ACTIVE", "GRACE"):
            raise_err(ERR_TIER_INSUFFICIENT, "replay grant requires ACTIVE or GRACE status")
    # 4. replay asset availability
    asset = None
    if body["grant_type"] == "REPLAY":
        for ra in db.replay_assets.values():
            if ra["window_id"] == win["id"]:
                asset = ra
                break
        if asset is None or asset["status"] != "AVAILABLE":
            raise_err(ERR_REPLAY_EXPIRED, "replay asset not AVAILABLE")

    grant = {
        "id": util.new_id(),
        "viewer_id": viewer["id"],
        "window_id": win["id"],
        "grant_type": body["grant_type"],
        "region": viewer["home_region"],
        "issued_at": now,
        "revoked": False,
        "created_at": clock.now_iso(),
    }
    db.view_grants[grant["id"]] = grant
    if asset is not None:
        asset["replay_views"] = asset.get("replay_views", 0) + 1
        util.touch(asset)
    # Marquee acquisition on first LIVE grant to marquee exclusive window
    if body["grant_type"] == "LIVE" and win["is_marquee"] and win["rights_mode"] == "EXCLUSIVE":
        if viewer.get("acquisition_window_id") is None:
            viewer["acquisition_window_id"] = win["id"]
            if viewer.get("acquisition_source") is None:
                viewer["acquisition_source"] = "ORGANIC"
            util.touch(viewer)
    return grant

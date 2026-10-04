"""Viewer accounts and subscriptions routes."""

from flask import Blueprint, request

import errors as E
from db import store
from middleware import (
    get_json_body,
    optional_bool,
    optional_enum,
    parse_pagination,
    require_positive_int,
    require_roles,
    require_str,
    to_iso_z,
)
from response import created, list_response, ok
from services.common import subscription_view, viewer_view

bp = Blueprint("viewers", __name__)

AD_CONSENTS = {"PERSONALIZED", "NON_PERSONALIZED", "OPTED_OUT"}


def get_viewer_or_404(vid):
    v = store.viewer_accounts.get(vid)
    if v is None:
        E.not_found("ViewerAccount not found")
    return v


def get_subscription_or_404(sid):
    s = store.subscriptions.get(sid)
    if s is None:
        E.not_found("Subscription not found")
    return s


@bp.post("/viewer-accounts")
def create_viewer():
    require_roles("PlatformAdmin")
    body = get_json_body()
    email = require_str(body, "email")
    ad_consent = optional_enum(body, "ad_consent", AD_CONSENTS)
    opt_out = optional_bool(body, "data_retention_opt_out")
    for v in store.viewer_accounts.values():
        if v["email"] == email:
            E.raise_err(E.ERR_DUPLICATE_EMAIL, "viewer email already exists")
    v = store.new_entity()
    v.update({
        "email": email,
        "ad_consent": ad_consent if ad_consent is not None else "NON_PERSONALIZED",
        "data_retention_opt_out": bool(opt_out) if opt_out is not None else False,
        "status": "ACTIVE",
    })
    store.viewer_accounts[v["id"]] = v
    return created(viewer_view(v))


@bp.get("/viewer-accounts/<vid>")
def get_viewer(vid):
    require_roles("PlatformAdmin", "AdOps", "Viewer")
    return ok(viewer_view(get_viewer_or_404(vid)))


@bp.patch("/viewer-accounts/<vid>/privacy")
def update_privacy(vid):
    user_id, role = require_roles("Viewer")
    v = get_viewer_or_404(vid)
    if v["id"] != user_id:
        E.forbidden("Viewer may only update own privacy controls")
    body = get_json_body()
    ad_consent = optional_enum(body, "ad_consent", AD_CONSENTS)
    opt_out = optional_bool(body, "data_retention_opt_out")
    if ad_consent is not None:
        v["ad_consent"] = ad_consent
    if opt_out is not None:
        v["data_retention_opt_out"] = opt_out
    store.touch(v)
    return ok(viewer_view(v))


@bp.get("/viewer-accounts/<vid>/subscriptions")
def viewer_subscriptions(vid):
    require_roles("PlatformAdmin", "AdOps", "Viewer")
    get_viewer_or_404(vid)
    limit, offset = parse_pagination()
    items = sorted(
        [s for s in store.subscriptions.values() if s["viewer_id"] == vid],
        key=lambda x: x["_seq"],
    )
    return list_response([subscription_view(s) for s in items], limit, offset, len(items))


@bp.get("/viewer-accounts/<vid>/device-units")
def viewer_device_units(vid):
    require_roles("PlatformAdmin", "AdOps", "Viewer")
    get_viewer_or_404(vid)
    limit, offset = parse_pagination()
    items = sorted(
        [u for u in store.device_units.values() if u.get("viewer_id") == vid],
        key=lambda x: x["_seq"],
    )
    from services.common import device_unit_view
    return list_response([device_unit_view(u) for u in items], limit, offset, len(items))


# ---- subscriptions ----

@bp.post("/subscriptions")
def create_subscription():
    user_id, role = require_roles("Viewer")
    body = get_json_body()
    channel_id = require_str(body, "channel_id")
    price = require_positive_int(body, "price_cents")
    ch = store.channels.get(channel_id)
    if ch is None:
        E.not_found("Channel not found")
    if ch["status"] != "PUBLISHED":
        E.raise_err(E.ERR_CHANNEL_NOT_PUBLISHED,
                    "Channel must be PUBLISHED to subscribe")
    s = store.new_entity()
    s.update({
        "viewer_id": user_id,
        "channel_id": channel_id,
        "price_cents": price,
        "billing_status": "ACTIVE",
        "entitlement_status": "ENTITLED",
        "period_start": to_iso_z(store.clock),
        "refunded_at": None,
    })
    store.subscriptions[s["id"]] = s
    return created(subscription_view(s))


@bp.get("/subscriptions")
def list_subscriptions():
    require_roles("PlatformAdmin", "AdOps", "Publisher", "Viewer")
    limit, offset = parse_pagination()
    viewer_id = request.args.get("viewer_id")
    channel_id = request.args.get("channel_id")
    billing_status = request.args.get("billing_status")
    items = sorted(store.subscriptions.values(), key=lambda x: x["_seq"])
    if viewer_id is not None:
        items = [s for s in items if s["viewer_id"] == viewer_id]
    if channel_id is not None:
        items = [s for s in items if s["channel_id"] == channel_id]
    if billing_status is not None:
        items = [s for s in items if s["billing_status"] == billing_status]
    return list_response([subscription_view(s) for s in items], limit, offset, len(items))


@bp.get("/subscriptions/<sid>")
def get_subscription(sid):
    require_roles("PlatformAdmin", "AdOps", "Publisher", "Viewer")
    return ok(subscription_view(get_subscription_or_404(sid)))


@bp.post("/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    user_id, role = require_roles("Viewer")
    s = get_subscription_or_404(sid)
    if s["viewer_id"] != user_id:
        E.forbidden("Viewer may only cancel own subscription")
    if s["billing_status"] != "ACTIVE":
        E.invalid_state("Subscription must be ACTIVE to cancel")
    s["billing_status"] = "CANCELLED"
    s["entitlement_status"] = "REVOKED"
    store.touch(s)
    return ok(subscription_view(s))


@bp.post("/subscriptions/<sid>/refund")
def refund_subscription(sid):
    require_roles("PlatformAdmin")
    s = get_subscription_or_404(sid)
    if s["billing_status"] != "ACTIVE":
        E.invalid_state("Subscription must be ACTIVE to refund")
    s["billing_status"] = "REFUNDED"
    s["entitlement_status"] = "REVOKED"
    s["refunded_at"] = to_iso_z(store.clock)
    store.touch(s)
    return ok(subscription_view(s))

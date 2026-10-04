"""Clock + publishers routes."""

from flask import Blueprint, request

import errors as E
from db import store
from middleware import (
    get_json_body,
    parse_pagination,
    require_datetime,
    require_enum,
    require_int,
    require_roles,
    require_str,
)
from response import created, list_response, ok
from services.common import pub_view

bp = Blueprint("core", __name__)

BILLING_MODELS = {"GROSS_SHARE", "NET_OF_FEES"}
STANDINGS = {"GOOD", "PROBATION", "SUSPENDED", "TERMINATED"}
ALL_ROLES = ("PlatformAdmin", "AdOps", "Publisher", "Viewer", "TvManufacturer")

STANDING_TRANSITIONS = {
    "GOOD": {"PROBATION", "SUSPENDED", "TERMINATED"},
    "PROBATION": {"GOOD", "SUSPENDED", "TERMINATED"},
    "SUSPENDED": {"PROBATION", "TERMINATED"},
    "TERMINATED": set(),
}


def get_publisher_or_404(pid):
    p = store.publishers.get(pid)
    if p is None:
        E.not_found("Publisher not found")
    return p


def recompute_outstanding_balance(publisher):
    """Sum of max(0, -net) over FINALIZED (not SETTLED) statements; >= 0."""
    total = 0
    for s in store.statements.values():
        if s["publisher_id"] == publisher["id"] and s["status"] == "FINALIZED":
            if s["net_payout_cents"] < 0:
                total += -s["net_payout_cents"]
    publisher["outstanding_balance_cents"] = max(0, total)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = get_json_body()
    to = body.get("to_iso8601")
    if to is None:
        E.invalid_request("to_iso8601 is required")
    from middleware import parse_iso8601
    dt = parse_iso8601(to, "to_iso8601")
    store.clock = dt
    from middleware import to_iso_z
    return ok({"current_utc": to_iso_z(store.clock)})


@bp.post("/publishers")
def create_publisher():
    require_roles("PlatformAdmin")
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    bps = require_int(body, "default_ad_share_bps")
    if bps < 0 or bps > 10000:
        E.invalid_request("default_ad_share_bps must be in 0..10000")
    billing_model = require_enum(body, "billing_model", BILLING_MODELS)
    p = store.new_entity()
    p.update({
        "legal_name": legal_name,
        "default_ad_share_bps": bps,
        "billing_model": billing_model,
        "standing": "GOOD",
        "revenue_tier": "STANDARD",
        "outstanding_balance_cents": 0,
    })
    store.publishers[p["id"]] = p
    return created(pub_view(p))


@bp.get("/publishers")
def list_publishers():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    standing = request.args.get("standing")
    items = sorted(store.publishers.values(), key=lambda x: x["_seq"])
    if standing is not None:
        items = [p for p in items if p["standing"] == standing]
    return list_response([pub_view(p) for p in items], limit, offset, len(items))


@bp.get("/publishers/<pid>")
def get_publisher(pid):
    require_roles(*ALL_ROLES)
    return ok(pub_view(get_publisher_or_404(pid)))


@bp.post("/publishers/<pid>/standing")
def publisher_standing(pid):
    require_roles("PlatformAdmin")
    pub = get_publisher_or_404(pid)
    body = get_json_body()
    to_standing = require_enum(body, "to_standing", STANDINGS)
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        E.invalid_request("reason must be a string")
    cur = pub["standing"]
    if to_standing == cur or to_standing not in STANDING_TRANSITIONS.get(cur, set()):
        E.invalid_state(f"standing transition {cur} -> {to_standing} not permitted")
    pub["standing"] = to_standing
    store.touch(pub)
    if to_standing == "TERMINATED":
        # Cascade: remove every channel not already REMOVED, each firing its
        # own removal side effects (campaigns/bookings/subscriptions).
        from services.common import channel_removal_cascade
        for ch in store.channels.values():
            if ch["publisher_id"] == pub["id"] and ch["status"] != "REMOVED":
                ch["status"] = "REMOVED"
                ch["removed_reason"] = "publisher terminated"
                store.touch(ch)
                channel_removal_cascade(ch)
    return ok(pub_view(pub))


@bp.get("/publishers/<pid>/channels")
def publisher_channels(pid):
    require_roles(*ALL_ROLES)
    get_publisher_or_404(pid)
    limit, offset = parse_pagination()
    items = sorted(
        [c for c in store.channels.values() if c["publisher_id"] == pid],
        key=lambda x: x["_seq"],
    )
    from services.common import channel_view
    return list_response([channel_view(c) for c in items], limit, offset, len(items))


@bp.get("/publishers/<pid>/campaigns")
def publisher_campaigns(pid):
    require_roles(*ALL_ROLES)
    get_publisher_or_404(pid)
    limit, offset = parse_pagination()
    items = sorted(
        [c for c in store.campaigns.values() if c["publisher_id"] == pid],
        key=lambda x: x["_seq"],
    )
    from services.common import campaign_view
    return list_response([campaign_view(c) for c in items], limit, offset, len(items))


@bp.get("/publishers/<pid>/statements")
def publisher_statements(pid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    get_publisher_or_404(pid)
    limit, offset = parse_pagination()
    items = sorted(
        [s for s in store.statements.values() if s["publisher_id"] == pid],
        key=lambda x: x["_seq"],
    )
    from services.common import statement_view
    return list_response([statement_view(s) for s in items], limit, offset, len(items))

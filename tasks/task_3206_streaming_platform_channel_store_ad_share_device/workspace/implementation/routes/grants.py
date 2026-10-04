"""Ad slot grants routes."""

from flask import Blueprint, request

import errors as E
from db import store
from middleware import (
    get_json_body,
    parse_pagination,
    require_int,
    require_period,
    require_positive_int,
    require_roles,
    require_str,
)
from response import created, list_response, ok
from services.common import floor_div, grant_view, round_half_up_cents, STANDING_PENALTY_BPS

bp = Blueprint("grants", __name__)


def get_grant_or_404(gid):
    g = store.ad_slot_grants.get(gid)
    if g is None:
        E.not_found("AdSlotGrant not found")
    return g


def _apply_split(grant, effective_bps):
    if effective_bps < 0:
        effective_bps = 0
    grant["publisher_share_bps"] = effective_bps
    grant["publisher_slots"] = floor_div(grant["total_slots"] * effective_bps, 10000)
    grant["platform_slots"] = grant["total_slots"] - grant["publisher_slots"]


@bp.post("/ad-slot-grants")
def create_grant():
    require_roles("PlatformAdmin")
    body = get_json_body()
    channel_id = require_str(body, "channel_id")
    period = require_period(body, "period")
    total_slots = require_positive_int(body, "total_slots")
    ch = store.channels.get(channel_id)
    if ch is None:
        E.not_found("Channel not found")
    for g in store.ad_slot_grants.values():
        if g["channel_id"] == channel_id and g["period"] == period and g["status"] == "OPEN":
            E.raise_err(E.ERR_GRANT_PERIOD_DUPLICATE,
                        "An OPEN grant already exists for this channel and period")
    pub = store.publishers.get(ch["publisher_id"])
    base_bps = pub["default_ad_share_bps"] if pub else 0
    g = store.new_entity()
    g.update({
        "channel_id": channel_id,
        "period": period,
        "total_slots": total_slots,
        "publisher_share_bps": base_bps,
        "publisher_slots": 0,
        "platform_slots": 0,
        "ad_gross_cents": 0,
        "publisher_payout_cents": 0,
        "status": "OPEN",
    })
    _apply_split(g, base_bps)
    store.ad_slot_grants[g["id"]] = g
    return created(grant_view(g))


@bp.get("/ad-slot-grants")
def list_grants():
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    limit, offset = parse_pagination()
    channel_id = request.args.get("channel_id")
    period = request.args.get("period")
    items = sorted(store.ad_slot_grants.values(), key=lambda x: x["_seq"])
    if channel_id is not None:
        items = [g for g in items if g["channel_id"] == channel_id]
    if period is not None:
        items = [g for g in items if g["period"] == period]
    return list_response([grant_view(g) for g in items], limit, offset, len(items))


@bp.get("/ad-slot-grants/<gid>")
def get_grant(gid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    return ok(grant_view(get_grant_or_404(gid)))


@bp.post("/ad-slot-grants/<gid>/record-revenue")
def record_revenue(gid):
    require_roles("AdOps")
    g = get_grant_or_404(gid)
    body = get_json_body()
    entries = body.get("slot_revenue_entries")
    if not isinstance(entries, list) or not entries:
        E.invalid_request("slot_revenue_entries must be a non-empty array")
    for e in entries:
        if isinstance(e, bool) or not isinstance(e, int) or e < 0:
            E.invalid_request("slot_revenue_entries entries must be non-negative integers")
    if g["status"] != "OPEN":
        E.invalid_state("Grant must be OPEN to record revenue")
    bps = g["publisher_share_bps"]
    for e in entries:
        # PINNED: round per-entry first, then sum.
        g["publisher_payout_cents"] += round_half_up_cents(e * bps, 10000)
        g["ad_gross_cents"] += e
    store.touch(g)
    return ok(grant_view(g))


@bp.post("/ad-slot-grants/<gid>/resplit")
def resplit_grant(gid):
    require_roles("PlatformAdmin")
    g = get_grant_or_404(gid)
    body = get_json_body()
    expected = body.get("expected_grant_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        E.invalid_request("expected_grant_version is required and must be an integer")
    if g["status"] != "OPEN":
        E.invalid_state("Grant must be OPEN to resplit")
    if expected != g["version"]:
        E.raise_err(E.ERR_STALE_VERSION,
                    "expected_grant_version does not match current grant version")
    ch = store.channels.get(g["channel_id"])
    pub = store.publishers.get(ch["publisher_id"]) if ch else None
    base = pub["default_ad_share_bps"] if pub else 0
    penalty = STANDING_PENALTY_BPS if (pub and pub["standing"] == "SUSPENDED") else 0
    effective = base - penalty
    _apply_split(g, effective)
    store.touch(g)
    return ok(grant_view(g))


@bp.post("/ad-slot-grants/<gid>/close")
def close_grant(gid):
    require_roles("PlatformAdmin")
    g = get_grant_or_404(gid)
    if g["status"] != "OPEN":
        E.invalid_state("Grant must be OPEN to close")
    g["status"] = "CLOSED"
    store.touch(g)
    return ok(grant_view(g))

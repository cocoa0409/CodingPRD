"""Channels, channel versions routes."""

from flask import Blueprint, request

import errors as E
from db import store
from middleware import (
    get_json_body,
    parse_pagination,
    require_bool,
    require_enum,
    require_int,
    require_roles,
    require_str,
)
from response import created, list_response, ok
from services.common import (
    channel_removal_cascade,
    channel_suspension_cascade,
    channel_version_view,
    channel_view,
)

bp = Blueprint("channels", __name__)

CATEGORIES = {"VIDEO", "AUDIO", "GAME", "NEWS", "KIDS"}
RATINGS = {"G", "PG", "R18"}
ALL_ROLES = ("PlatformAdmin", "AdOps", "Publisher", "Viewer", "TvManufacturer")


def get_channel_or_404(cid):
    c = store.channels.get(cid)
    if c is None:
        E.not_found("Channel not found")
    return c


def get_version_or_404(vid):
    v = store.channel_versions.get(vid)
    if v is None:
        E.not_found("ChannelVersion not found")
    return v


def _owning_publisher(channel):
    return store.publishers.get(channel["publisher_id"])


def _standing_gate(channel):
    pub = _owning_publisher(channel)
    if pub is not None and pub["standing"] not in ("GOOD", "PROBATION"):
        E.raise_err(E.ERR_PUBLISHER_SUSPENDED,
                    "Publisher standing must be GOOD or PROBATION")


@bp.post("/channels")
def create_channel():
    user_id, role = require_roles("Publisher")
    body = get_json_body()
    publisher_id = require_str(body, "publisher_id")
    name = require_str(body, "name")
    category = require_enum(body, "category", CATEGORIES)
    rating = require_enum(body, "content_rating", RATINGS)
    # Ownership (priority 3): Publisher caller owns the publisher being referenced
    if publisher_id != user_id:
        E.forbidden("Publisher caller may only create channels for itself")
    if publisher_id not in store.publishers:
        E.not_found("Publisher not found")
    c = store.new_entity()
    c.update({
        "publisher_id": publisher_id,
        "name": name,
        "category": category,
        "content_rating": rating,
        "status": "DRAFT",
        "active_version_id": None,
        "policy_hold": False,
        "removed_reason": None,
    })
    store.channels[c["id"]] = c
    return created(channel_view(c))


@bp.get("/channels")
def list_channels():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    pid = request.args.get("publisher_id")
    status = request.args.get("status")
    avid = request.args.get("active_version_id")
    items = sorted(store.channels.values(), key=lambda x: x["_seq"])
    if pid is not None:
        items = [c for c in items if c["publisher_id"] == pid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if avid is not None:
        items = [c for c in items if c.get("active_version_id") == avid]
    return list_response([channel_view(c) for c in items], limit, offset, len(items))


@bp.get("/channels/<cid>")
def get_channel(cid):
    require_roles(*ALL_ROLES)
    return ok(channel_view(get_channel_or_404(cid)))


@bp.post("/channels/<cid>/publish")
def publish_channel(cid):
    require_roles("PlatformAdmin")
    ch = get_channel_or_404(cid)
    if ch["status"] != "CERTIFIED":
        E.invalid_state("Channel must be CERTIFIED to publish")
    if ch.get("policy_hold"):
        E.raise_err(E.ERR_CONTENT_POLICY_BLOCK, "Channel has a content-policy hold")
    _standing_gate(ch)
    ch["status"] = "PUBLISHED"
    store.touch(ch)
    return ok(channel_view(ch))


@bp.post("/channels/<cid>/suspend")
def suspend_channel(cid):
    require_roles("PlatformAdmin")
    ch = get_channel_or_404(cid)
    body = get_json_body()
    reason = require_str(body, "reason")
    if ch["status"] != "PUBLISHED":
        E.invalid_state("Channel must be PUBLISHED to suspend")
    ch["status"] = "SUSPENDED"
    if reason == "POLICY":
        ch["policy_hold"] = True
    store.touch(ch)
    channel_suspension_cascade(ch)
    return ok(channel_view(ch))


@bp.post("/channels/<cid>/reinstate")
def reinstate_channel(cid):
    require_roles("PlatformAdmin")
    ch = get_channel_or_404(cid)
    if ch["status"] != "SUSPENDED":
        E.invalid_state("Channel must be SUSPENDED to reinstate")
    _standing_gate(ch)
    ch["status"] = "PUBLISHED"
    ch["policy_hold"] = False
    store.touch(ch)
    return ok(channel_view(ch))


@bp.post("/channels/<cid>/remove")
def remove_channel(cid):
    require_roles("PlatformAdmin")
    ch = get_channel_or_404(cid)
    body = get_json_body()
    reason = require_str(body, "reason")
    if ch["status"] not in ("PUBLISHED", "SUSPENDED"):
        E.invalid_state("Channel must be PUBLISHED or SUSPENDED to remove")
    ch["status"] = "REMOVED"
    ch["removed_reason"] = reason
    store.touch(ch)
    channel_removal_cascade(ch)
    return ok(channel_view(ch))


@bp.post("/channels/<cid>/policy-hold")
def policy_hold_channel(cid):
    require_roles("PlatformAdmin")
    ch = get_channel_or_404(cid)
    body = get_json_body()
    held = require_bool(body, "held")
    if ch["status"] != "PUBLISHED":
        E.invalid_state("policy-hold requires a PUBLISHED channel")
    ch["policy_hold"] = held
    store.touch(ch)
    return ok(channel_view(ch))


@bp.get("/channels/<cid>/versions")
def channel_versions(cid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    get_channel_or_404(cid)
    limit, offset = parse_pagination()
    items = sorted(
        [v for v in store.channel_versions.values() if v["channel_id"] == cid],
        key=lambda x: x["_seq"],
    )
    return list_response([channel_version_view(v) for v in items], limit, offset, len(items))


@bp.get("/channels/<cid>/subscriptions")
def channel_subscriptions(cid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    get_channel_or_404(cid)
    limit, offset = parse_pagination()
    items = sorted(
        [s for s in store.subscriptions.values() if s["channel_id"] == cid],
        key=lambda x: x["_seq"],
    )
    from services.common import subscription_view
    return list_response([subscription_view(s) for s in items], limit, offset, len(items))


@bp.get("/channels/<cid>/ad-slot-grants")
def channel_grants(cid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    get_channel_or_404(cid)
    limit, offset = parse_pagination()
    items = sorted(
        [g for g in store.ad_slot_grants.values() if g["channel_id"] == cid],
        key=lambda x: x["_seq"],
    )
    from services.common import grant_view
    return list_response([grant_view(g) for g in items], limit, offset, len(items))


@bp.get("/channels/<cid>/campaigns")
def channel_campaigns(cid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    get_channel_or_404(cid)
    limit, offset = parse_pagination()
    items = sorted(
        [c for c in store.campaigns.values() if c["channel_id"] == cid],
        key=lambda x: x["_seq"],
    )
    from services.common import campaign_view
    return list_response([campaign_view(c) for c in items], limit, offset, len(items))


# ---- channel versions ----

@bp.post("/channels/<cid>/versions")
def submit_version(cid):
    user_id, role = require_roles("Publisher")
    ch = get_channel_or_404(cid)
    if ch["publisher_id"] != user_id:
        E.forbidden("Publisher caller does not own this channel")
    body = get_json_body()
    version_label = require_str(body, "version_label")
    checklist = body.get("technical_checklist")
    if checklist is None or not isinstance(checklist, dict):
        E.invalid_request("technical_checklist is required and must be an object")
    expected = body.get("expected_channel_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        E.invalid_request("expected_channel_version is required and must be an integer")

    # Priority 6: channel's own state gate
    if ch["status"] in ("CERTIFIED", "PUBLISHED", "SUSPENDED", "REMOVED"):
        E.invalid_state("Channel state does not permit version submission")
    # Priority 10: standing gate
    _standing_gate(ch)
    # Priority 11: no second review while one is IN_REVIEW
    if ch["status"] == "IN_REVIEW":
        E.raise_err(E.ERR_REVIEW_IN_PROGRESS,
                    "A version of this channel is already IN_REVIEW")
    # Priority 15: OCC
    if expected != ch["version"]:
        E.raise_err(E.ERR_STALE_VERSION,
                    "expected_channel_version does not match current channel version")

    # Side effects: supersede prior SUBMITTED version, create new one.
    for v in store.channel_versions.values():
        if v["channel_id"] == ch["id"] and v["review_status"] == "SUBMITTED":
            v["review_status"] = "SUPERSEDED"
            store.touch(v)
    ch["status"] = "SUBMITTED"
    store.touch(ch)

    v = store.new_entity()
    v.update({
        "channel_id": ch["id"],
        "version_label": version_label,
        "technical_checklist": checklist,
        "review_status": "SUBMITTED",
        "failure_codes": [],
    })
    store.channel_versions[v["id"]] = v
    return created(channel_version_view(v))


@bp.get("/channel-versions/<vid>")
def get_channel_version(vid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    return ok(channel_version_view(get_version_or_404(vid)))


@bp.post("/channel-versions/<vid>/review")
def review_version(vid):
    require_roles("PlatformAdmin")
    v = get_version_or_404(vid)
    ch = store.channels.get(v["channel_id"])
    if ch is None:
        E.not_found("Channel not found")
    # Priority 6/7: version must be SUBMITTED; parent channel in SUBMITTED.
    if v["review_status"] != "SUBMITTED":
        E.invalid_state("ChannelVersion must be SUBMITTED to begin review")
    if ch["status"] != "SUBMITTED":
        E.invalid_state("Parent channel must be SUBMITTED to begin review")
    v["review_status"] = "IN_REVIEW"
    store.touch(v)
    ch["status"] = "IN_REVIEW"
    store.touch(ch)
    return ok(channel_version_view(v))


@bp.post("/channel-versions/<vid>/decide")
def decide_version(vid):
    require_roles("PlatformAdmin")
    v = get_version_or_404(vid)
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"PASS", "FAIL"})
    failure_codes = body.get("failure_codes")
    if failure_codes is not None and not (
        isinstance(failure_codes, list) and all(isinstance(x, str) for x in failure_codes)
    ):
        E.invalid_request("failure_codes must be an array of strings")
    ch = store.channels.get(v["channel_id"])
    if ch is None:
        E.not_found("Channel not found")
    if v["review_status"] != "IN_REVIEW":
        E.invalid_state("ChannelVersion must be IN_REVIEW to decide")
    if outcome == "FAIL":
        if not failure_codes:
            E.invalid_request("failure_codes must be non-empty for outcome=FAIL")
        v["review_status"] = "FAILED"
        v["failure_codes"] = list(failure_codes)
        store.touch(v)
        ch["status"] = "CHANGES_REQUESTED"
        store.touch(ch)
    else:
        v["review_status"] = "PASSED"
        v["failure_codes"] = []
        store.touch(v)
        ch["status"] = "CERTIFIED"
        ch["active_version_id"] = v["id"]
        store.touch(ch)
    return ok(channel_version_view(v))

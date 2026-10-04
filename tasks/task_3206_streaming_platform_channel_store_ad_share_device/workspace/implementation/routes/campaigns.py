"""Ad campaigns and placement bookings routes."""

from datetime import timedelta

from flask import Blueprint, request

import errors as E
from db import store
from middleware import (
    get_json_body,
    optional_str,
    parse_pagination,
    require_datetime,
    require_enum,
    require_int,
    require_nonnegative_int,
    require_positive_int,
    require_roles,
    require_str,
    to_iso_z,
)
from response import created, list_response, ok
from services.common import (
    booking_view,
    campaign_view,
    release_campaign_bookings,
    round_half_up_cents,
    CAMPAIGN_CREDIT_LIMIT_CENTS,
)

bp = Blueprint("campaigns", __name__)

TARGETING_MODES = {"CONTEXTUAL", "PERSONALIZED"}
ALL_ROLES = ("PlatformAdmin", "AdOps", "Publisher", "Viewer", "TvManufacturer")


def get_campaign_or_404(cid):
    c = store.campaigns.get(cid)
    if c is None:
        E.not_found("AdCampaign not found")
    return c


def get_booking_or_404(bid):
    b = store.placement_bookings.get(bid)
    if b is None:
        E.not_found("PlacementBooking not found")
    return b


def _channel_of(campaign):
    return store.channels.get(campaign["channel_id"])


def _require_channel_published(campaign):
    ch = _channel_of(campaign)
    if ch is None:
        E.not_found("Channel not found")
    if ch["status"] != "PUBLISHED":
        E.raise_err(E.ERR_CHANNEL_NOT_PUBLISHED,
                    "Channel must be PUBLISHED")
    return ch


def _in_flight(campaign):
    fs = None
    from middleware import parse_iso8601
    fs = parse_iso8601(campaign["flight_start"], "flight_start")
    fe = parse_iso8601(campaign["flight_end"], "flight_end")
    return fs <= store.clock < fe


@bp.post("/campaigns")
def create_campaign():
    user_id, role = require_roles("Publisher")
    body = get_json_body()
    publisher_id = require_str(body, "publisher_id")
    channel_id = require_str(body, "channel_id")
    fs = require_datetime(body, "flight_start")
    fe = require_datetime(body, "flight_end")
    budget = require_positive_int(body, "budget_cents")
    targeting = require_enum(body, "targeting_mode", TARGETING_MODES)
    if publisher_id != user_id:
        E.forbidden("Publisher caller may only create campaigns for itself")
    if publisher_id not in store.publishers:
        E.not_found("Publisher not found")
    if channel_id not in store.channels:
        E.not_found("Channel not found")
    if fe <= fs:
        E.invalid_request("flight_end must be > flight_start")
    c = store.new_entity()
    c.update({
        "publisher_id": publisher_id,
        "channel_id": channel_id,
        "flight_start": to_iso_z(fs),
        "flight_end": to_iso_z(fe),
        "budget_cents": budget,
        "targeting_mode": targeting,
        "spent_cents": 0,
        "impressions_delivered": 0,
        "status": "DRAFT",
    })
    store.campaigns[c["id"]] = c
    return created(campaign_view(c))


@bp.get("/campaigns")
def list_campaigns():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    pid = request.args.get("publisher_id")
    cid = request.args.get("channel_id")
    status = request.args.get("status")
    items = sorted(store.campaigns.values(), key=lambda x: x["_seq"])
    if pid is not None:
        items = [c for c in items if c["publisher_id"] == pid]
    if cid is not None:
        items = [c for c in items if c["channel_id"] == cid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response([campaign_view(c) for c in items], limit, offset, len(items))


@bp.get("/campaigns/<cid>")
def get_campaign(cid):
    require_roles(*ALL_ROLES)
    return ok(campaign_view(get_campaign_or_404(cid)))


@bp.post("/campaigns/<cid>/schedule")
def schedule_campaign(cid):
    user_id, role = require_roles("Publisher")
    c = get_campaign_or_404(cid)
    if c["publisher_id"] != user_id:
        E.forbidden("Publisher caller does not own this campaign")
    if c["status"] != "DRAFT":
        E.invalid_state("Campaign must be DRAFT to schedule")
    ch = _require_channel_published(c)
    if ch.get("policy_hold"):
        E.raise_err(E.ERR_CONTENT_POLICY_BLOCK, "Channel has a content-policy hold")
    pub = store.publishers.get(c["publisher_id"])
    if pub and pub["outstanding_balance_cents"] > CAMPAIGN_CREDIT_LIMIT_CENTS:
        E.raise_err(E.ERR_OUTSTANDING_BALANCE,
                    "Publisher outstanding balance exceeds the campaign credit limit")
    c["status"] = "SCHEDULED"
    store.touch(c)
    return ok(campaign_view(c))


@bp.post("/campaigns/<cid>/start")
def start_campaign(cid):
    require_roles("AdOps")
    c = get_campaign_or_404(cid)
    if c["status"] != "SCHEDULED":
        E.invalid_state("Campaign must be SCHEDULED to start")
    _require_channel_published(c)
    if not _in_flight(c):
        E.raise_err(E.ERR_CAMPAIGN_OUTSIDE_FLIGHT,
                    "Logical clock must be within [flight_start, flight_end)")
    c["status"] = "ACTIVE"
    store.touch(c)
    return ok(campaign_view(c))


@bp.post("/campaigns/<cid>/pause")
def pause_campaign_route(cid):
    require_roles("AdOps")
    c = get_campaign_or_404(cid)
    if c["status"] != "ACTIVE":
        E.invalid_state("Campaign must be ACTIVE to pause")
    c["status"] = "PAUSED"
    store.touch(c)
    release_campaign_bookings(c)
    return ok(campaign_view(c))


@bp.post("/campaigns/<cid>/resume")
def resume_campaign(cid):
    require_roles("AdOps")
    c = get_campaign_or_404(cid)
    if c["status"] != "PAUSED":
        E.invalid_state("Campaign must be PAUSED to resume")
    _require_channel_published(c)
    if not _in_flight(c):
        E.raise_err(E.ERR_CAMPAIGN_OUTSIDE_FLIGHT,
                    "Logical clock must be within [flight_start, flight_end)")
    c["status"] = "ACTIVE"
    store.touch(c)
    return ok(campaign_view(c))


@bp.post("/campaigns/<cid>/cancel")
def cancel_campaign(cid):
    user_id, role = require_roles("Publisher")
    c = get_campaign_or_404(cid)
    if c["publisher_id"] != user_id:
        E.forbidden("Publisher caller does not own this campaign")
    if c["status"] not in ("DRAFT", "SCHEDULED", "PAUSED"):
        E.invalid_state("Campaign must be DRAFT, SCHEDULED or PAUSED to cancel")
    c["status"] = "CANCELLED"
    store.touch(c)
    release_campaign_bookings(c)
    return ok(campaign_view(c))


@bp.post("/campaigns/<cid>/impressions")
def record_impressions(cid):
    require_roles("AdOps")
    c = get_campaign_or_404(cid)
    body = get_json_body()
    impression_count = body.get("impression_count")
    if impression_count is None or isinstance(impression_count, bool) or not isinstance(impression_count, int) or impression_count < 0:
        E.invalid_request("impression_count must be a non-negative integer")
    cpm = body.get("cpm_cents")
    if cpm is None or isinstance(cpm, bool) or not isinstance(cpm, int) or cpm < 0:
        E.invalid_request("cpm_cents must be a non-negative integer")
    viewer_id = optional_str(body, "viewer_id")
    viewer = None
    if viewer_id is not None:
        viewer = store.viewer_accounts.get(viewer_id)
        if viewer is None:
            E.not_found("ViewerAccount not found")
    if c["status"] != "ACTIVE":
        E.raise_err(E.ERR_CAMPAIGN_NOT_ACTIVE,
                    "Campaign must be ACTIVE for impression recording")
    cost = round_half_up_cents(impression_count * cpm, 1000)
    if c["spent_cents"] + cost > c["budget_cents"]:
        E.raise_err(E.ERR_BUDGET_EXHAUSTED,
                    "Impression cost would exceed campaign budget")
    if (viewer_id is not None and c["targeting_mode"] == "PERSONALIZED"
            and viewer["ad_consent"] != "PERSONALIZED"):
        E.raise_err(E.ERR_PRIVACY_OPTED_OUT,
                    "Viewer ad_consent must be PERSONALIZED for personalized measurement")
    c["spent_cents"] += cost
    c["impressions_delivered"] += impression_count
    if c["spent_cents"] == c["budget_cents"]:
        c["status"] = "COMPLETED"
    store.touch(c)
    return ok(campaign_view(c))


@bp.get("/campaigns/<cid>/placement-bookings")
def campaign_bookings(cid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    get_campaign_or_404(cid)
    limit, offset = parse_pagination()
    items = sorted(
        [b for b in store.placement_bookings.values() if b["campaign_id"] == cid],
        key=lambda x: x["_seq"],
    )
    return list_response([booking_view(b) for b in items], limit, offset, len(items))


# ---- placement bookings ----

def _expire_held_bookings_for_slot(slot_code):
    """HELD bookings whose window_end <= clock become EXPIRED (same slot only)."""
    from middleware import parse_iso8601
    for b in store.placement_bookings.values():
        if b["slot_code"] == slot_code and b["status"] == "HELD":
            we = parse_iso8601(b["window_end"], "window_end")
            if store.clock >= we:
                b["status"] = "EXPIRED"
                store.touch(b)


@bp.post("/placement-bookings")
def create_booking():
    user_id, role = require_roles("Publisher")
    body = get_json_body()
    campaign_id = require_str(body, "campaign_id")
    slot_code = require_str(body, "slot_code")
    ws = require_datetime(body, "window_start")
    we = require_datetime(body, "window_end")
    c = store.campaigns.get(campaign_id)
    if c is None:
        E.not_found("AdCampaign not found")
    if c["publisher_id"] != user_id:
        E.forbidden("Publisher caller does not own this campaign")
    if we <= ws:
        E.invalid_request("window_end must be > window_start (half-open)")
    if c["status"] != "ACTIVE":
        E.raise_err(E.ERR_CAMPAIGN_NOT_ACTIVE,
                    "Campaign must be ACTIVE for placement booking")
    ch = _channel_of(c)
    if ch is None:
        E.not_found("Channel not found")
    if ch.get("policy_hold") or ch["status"] == "REMOVED":
        E.raise_err(E.ERR_CONTENT_POLICY_BLOCK, "Channel has a content-policy hold")
    _expire_held_bookings_for_slot(slot_code)
    if we <= store.clock:
        E.raise_err(E.ERR_BOOKING_WINDOW_PAST,
                    "Booking window is entirely in the past")
    from middleware import parse_iso8601
    for b in store.placement_bookings.values():
        if b["slot_code"] != slot_code or b["status"] not in ("HELD", "CONFIRMED"):
            continue
        es = parse_iso8601(b["window_start"], "window_start")
        ee = parse_iso8601(b["window_end"], "window_end")
        # half-open conflict: new.start < existing.end AND new.end > existing.start
        if ws < ee and we > es:
            E.raise_err(E.ERR_SLOT_OVERLAP,
                        "Placement window overlaps an existing booking on this slot_code")
    b = store.new_entity()
    b.update({
        "campaign_id": campaign_id,
        "slot_code": slot_code,
        "window_start": to_iso_z(ws),
        "window_end": to_iso_z(we),
        "status": "HELD",
    })
    store.placement_bookings[b["id"]] = b
    return created(booking_view(b))


@bp.get("/placement-bookings")
def list_bookings():
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    slot_code = request.args.get("slot_code")
    status = request.args.get("status")
    items = sorted(store.placement_bookings.values(), key=lambda x: x["_seq"])
    if campaign_id is not None:
        items = [b for b in items if b["campaign_id"] == campaign_id]
    if slot_code is not None:
        items = [b for b in items if b["slot_code"] == slot_code]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return list_response([booking_view(b) for b in items], limit, offset, len(items))


@bp.get("/placement-bookings/<bid>")
def get_booking(bid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    return ok(booking_view(get_booking_or_404(bid)))


@bp.post("/placement-bookings/<bid>/confirm")
def confirm_booking(bid):
    require_roles("AdOps")
    b = get_booking_or_404(bid)
    if b["status"] != "HELD":
        E.invalid_state("Booking must be HELD to confirm")
    from middleware import parse_iso8601
    we = parse_iso8601(b["window_end"], "window_end")
    if not (store.clock < we):
        E.raise_err(E.ERR_BOOKING_WINDOW_PAST,
                    "Cannot confirm a booking whose window has passed")
    b["status"] = "CONFIRMED"
    store.touch(b)
    return ok(booking_view(b))


@bp.post("/placement-bookings/<bid>/release")
def release_booking(bid):
    require_roles("AdOps")
    b = get_booking_or_404(bid)
    if b["status"] not in ("HELD", "CONFIRMED"):
        E.invalid_state("Booking must be HELD or CONFIRMED to release")
    b["status"] = "RELEASED"
    store.touch(b)
    return ok(booking_view(b))

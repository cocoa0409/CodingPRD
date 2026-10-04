"""Distribution feeds, congestion preemption and uplink slot reservations."""
from flask import Blueprint, request

from core import base, config as C
from core.base import new_record, public, touch
from core.errors import ApiError, bad_request, invalid_state, not_found
from core.middleware import check_station_ownership, route
from core.response import array_response, object_response
from core.store import STORE
from services import carriage

bp = Blueprint("feeds", __name__)

FEED_CODE_RE = r"^FEED-[A-Z0-9]{4}$"
FEED_TYPES = ["SATELLITE", "DIGITAL", "HYBRID"]
FEED_STATUSES = ["PLANNED", "ONLINE", "CROWDED", "MAINTENANCE", "OFFLINE", "SUSPENDED"]
RATIO_SCALE_BPS = 10000
SUPPORTED_PREEMPTIBLE_PRIORITY_RANK_FLOOR = 2


def feed_or_404(feed_id):
    feed = STORE.feeds.get(feed_id)
    if feed is None:
        raise not_found("distribution feed")
    return feed


def slot_or_404(slot_id):
    slot = STORE.slots.get(slot_id)
    if slot is None:
        raise not_found("uplink slot")
    return slot


def feed_view(store, feed):
    data = public(feed)
    total = int(feed.get("total_capacity_units") or 1)
    reserved = int(feed.get("reserved_capacity_units") or 0)
    data["reserved_ratio_bps"] = C.floor_div(reserved * RATIO_SCALE_BPS, total)
    data["available_capacity_units"] = max(0, total - reserved)
    return data


def _threshold(feed):
    return int(feed.get("max_reserved_capacity_ratio") or RATIO_SCALE_BPS)


def _apply_congestion(store, feed, incoming_units, floor, exclude_slot_id=None):
    """One reservation's worth of congestion: flag crowded and preempt the floor.

    The feed's transition into CROWDED pins ``crowded`` true at the moment the
    congestion threshold is crossed, so the flag is not re-derived downward by
    the capacity the preemption releases in the same request.
    """
    total = int(feed.get("total_capacity_units") or 1)
    feed["reserved_capacity_units"] = int(feed.get("reserved_capacity_units") or 0) + incoming_units
    carriage.refresh_feed_flags(store, feed)
    if not feed.get("crowded"):
        if feed.get("feed_status") == "CROWDED":
            feed["feed_status"] = "ONLINE"
        return []
    if feed.get("feed_status") == "ONLINE":
        feed["feed_status"] = "CROWDED"
    preempted = []
    for slot in store.slots_of(feed["id"]):
        if slot["id"] == exclude_slot_id:
            continue
        if slot.get("slot_status") not in ("RESERVED", "SCHEDULED"):
            continue
        if int(slot.get("priority_rank") or 0) <= int(floor):
            continue
        slot["slot_status"] = "PREEMPTED"
        if slot.get("_reserved_units_recorded"):
            feed["reserved_capacity_units"] = max(
                0, int(feed.get("reserved_capacity_units") or 0)
                - int(slot.get("_units") or 1)
            )
            slot["_reserved_units_recorded"] = False
        touch(slot)
        window = store.windows.get(slot.get("window_id"))
        if window is not None and window.get("clearance_status") == "SCHEDULED":
            window["clearance_status"] = "CLEARED"
            carriage.refresh_window_flags(store, window)
            touch(window)
            carriage.refresh_agreement_from_windows(store, window.get("parent_agreement_id"))
        preempted.append(slot)
    feed["_reserved_ratio_bps"] = C.floor_div(
        int(feed.get("reserved_capacity_units") or 0) * RATIO_SCALE_BPS, total
    )
    feed["crowded"] = True
    return preempted


def _reserve_one(store, feed, body, role, ident):
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    if station_id not in store.member_stations:
        raise not_found("member station")
    check_station_ownership(role, ident, station_id)
    window_id = body.get("window_id")
    if window_id is None:
        raise bad_request("window_id is required")
    window = store.windows.get(window_id)
    if window is None:
        raise not_found("broadcast window")
    if window.get("station_id") != station_id:
        raise ApiError("ERR_SLOT_STATION_MISMATCH")
    start = base.as_instant(body.get("slot_start"), "slot_start")
    end = base.as_instant(body.get("slot_end"), "slot_end")
    if C.parse_dt(end) <= C.parse_dt(start):
        raise bad_request("slot_end must be after slot_start")
    priority = base.as_int(body.get("priority_rank"), "priority_rank", low=1, high=5)
    units = base.as_int(body.get("capacity_units"), "capacity_units", low=1, required=False)
    units = 1 if units is None else units
    for sibling in store.slots_of(feed["id"]):
        if sibling.get("slot_status") in ("CANCELLED", "RELEASED"):
            continue
        s_start = C.parse_dt(sibling.get("slot_start"))
        s_end = C.parse_dt(sibling.get("slot_end"))
        if s_start is None or s_end is None:
            continue
        if C.parse_dt(start) < s_end and s_start < C.parse_dt(end):
            raise ApiError("ERR_UPLINK_CAPACITY_CONFLICT")
    total = int(feed.get("total_capacity_units") or 1)
    reserved = int(feed.get("reserved_capacity_units") or 0)
    if reserved + units > total:
        raise ApiError("ERR_UPLINK_CAPACITY_EXHAUSTED")
    slot = new_record(
        "UplinkSlot",
        parent_feed_id=feed["id"],
        station_id=station_id,
        window_id=window_id,
        slot_start=start,
        slot_end=end,
        slot_status="RESERVED",
        priority_rank=priority,
        _units=units,
        _reserved_units_recorded=True,
    )
    store.put("slots", slot)
    floor = body.get("preemptible_priority_rank_floor")
    floor = SUPPORTED_PREEMPTIBLE_PRIORITY_RANK_FLOOR if floor is None else int(floor)
    _apply_congestion(store, feed, units, floor, exclude_slot_id=slot["id"])
    touch(feed)
    return slot


@bp.route("/network/distribution-feeds", methods=["POST"])
@route("/network/distribution-feeds", "POST")
def create_feed():
    body = base.get_body(request.get_json(silent=True))
    code = base.as_text(body.get("feed_code"), "feed_code", pattern=FEED_CODE_RE)
    for existing in STORE.feeds.values():
        if existing.get("feed_code") == code:
            raise ApiError("ERR_FEED_CODE_TAKEN")
    feed_type = base.as_enum(body.get("feed_type"), FEED_TYPES, "feed_type")
    total = base.as_int(body.get("total_capacity_units"), "total_capacity_units", low=1)
    ratio = base.as_int(
        body.get("max_reserved_capacity_ratio"), "max_reserved_capacity_ratio",
        low=1, high=RATIO_SCALE_BPS, required=False,
    )
    ratio = RATIO_SCALE_BPS if ratio is None else ratio
    feed = new_record(
        "DistributionFeed",
        feed_code=code,
        feed_type=feed_type,
        total_capacity_units=total,
        max_reserved_capacity_ratio=ratio,
        reserved_capacity_units=0,
        crowded=False,
        feed_status="PLANNED",
        maintenance_start=None,
        maintenance_end=None,
    )
    STORE.put("feeds", feed)
    carriage.refresh_feed_flags(STORE, feed)
    return object_response(feed_view(STORE, feed), 201)


@bp.route("/network/distribution-feeds", methods=["GET"])
@route("/network/distribution-feeds", "GET")
def list_feeds():
    args = request.args
    recs = STORE.all("feeds")
    for field in ("feed_type", "feed_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([feed_view(STORE, r) for r in page], meta)


@bp.route("/network/distribution-feeds/<fid>", methods=["GET"])
@route("/network/distribution-feeds/<fid>", "GET")
def read_feed(fid):
    feed = feed_or_404(fid)
    return object_response(feed_view(STORE, feed))


@bp.route("/network/distribution-feeds/<fid>/uplink-slots", methods=["GET"])
@route("/network/distribution-feeds/<fid>/uplink-slots", "GET")
def feed_slots(fid):
    feed_or_404(fid)
    args = request.args
    recs = STORE.slots_of(fid)
    status = base.scalar_arg(args, "slot_status")
    if status is not None:
        recs = [r for r in recs if r.get("slot_status") == status]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/distribution-feeds/<fid>/bring-online", methods=["POST"])
@route("/network/distribution-feeds/<fid>/bring-online", "POST")
def bring_online(fid):
    feed = feed_or_404(fid)
    if feed.get("feed_status") != "PLANNED":
        raise invalid_state("the feed is not planned")
    if int(feed.get("total_capacity_units") or 0) < 1:
        raise invalid_state("the feed has no capacity")
    feed["feed_status"] = "ONLINE"
    carriage.refresh_feed_flags(STORE, feed)
    if feed.get("crowded"):
        feed["feed_status"] = "CROWDED"
    touch(feed)
    return object_response(feed_view(STORE, feed))


@bp.route("/network/distribution-feeds/<fid>/maintenance", methods=["POST"])
@route("/network/distribution-feeds/<fid>/maintenance", "POST")
def feed_maintenance(fid):
    feed = feed_or_404(fid)
    status = feed.get("feed_status")
    if status not in ("ONLINE", "CROWDED"):
        raise invalid_state("the feed cannot enter maintenance from its current state")
    body = base.get_body(request.get_json(silent=True))
    start = base.as_instant(body.get("maintenance_start"), "maintenance_start")
    end = base.as_instant(body.get("maintenance_end"), "maintenance_end")
    if C.parse_dt(end) <= C.parse_dt(start):
        raise bad_request("maintenance_end must be after maintenance_start")
    if C.now() < C.parse_dt(start):
        raise invalid_state("the maintenance window has not opened")
    if status == "ONLINE" and C.now() >= C.parse_dt(end):
        raise invalid_state("the maintenance window has already closed")
    feed["feed_status"] = "MAINTENANCE"
    feed["maintenance_start"] = start
    feed["maintenance_end"] = end
    for slot in STORE.slots_of(fid):
        if slot.get("slot_status") in ("RESERVED", "SCHEDULED"):
            slot["slot_status"] = "CANCELLED"
            if slot.get("_reserved_units_recorded"):
                feed["reserved_capacity_units"] = max(
                    0, int(feed.get("reserved_capacity_units") or 0)
                    - int(slot.get("_units") or 1)
                )
                slot["_reserved_units_recorded"] = False
            touch(slot)
            window = STORE.windows.get(slot.get("window_id"))
            if window is not None and window.get("clearance_status") == "SCHEDULED":
                window["clearance_status"] = "CLEARED"
                carriage.refresh_window_flags(STORE, window)
                touch(window)
    carriage.refresh_feed_flags(STORE, feed)
    touch(feed)
    return object_response(feed_view(STORE, feed))


@bp.route("/network/distribution-feeds/<fid>/restore", methods=["POST"])
@route("/network/distribution-feeds/<fid>/restore", "POST")
def restore_feed(fid):
    feed = feed_or_404(fid)
    if feed.get("feed_status") != "MAINTENANCE":
        raise invalid_state("the feed is not in maintenance")
    end = C.parse_dt(feed.get("maintenance_end"))
    if end is None or C.now() < end:
        raise invalid_state("the maintenance window has not closed")
    feed["feed_status"] = "ONLINE"
    carriage.refresh_feed_flags(STORE, feed)
    if feed.get("crowded"):
        feed["feed_status"] = "CROWDED"
    touch(feed)
    return object_response(feed_view(STORE, feed))


@bp.route("/network/distribution-feeds/<fid>/take-offline", methods=["POST"])
@route("/network/distribution-feeds/<fid>/take-offline", "POST")
def take_offline(fid):
    feed = feed_or_404(fid)
    if feed.get("feed_status") not in ("ONLINE", "CROWDED"):
        raise invalid_state("the feed cannot be taken offline from its current state")
    if int(feed.get("reserved_capacity_units") or 0) != 0:
        raise invalid_state("the feed still holds reservations")
    feed["feed_status"] = "OFFLINE"
    touch(feed)
    return object_response(feed_view(STORE, feed))


@bp.route("/network/distribution-feeds/<fid>/replan", methods=["POST"])
@route("/network/distribution-feeds/<fid>/replan", "POST")
def replan_feed(fid):
    feed = feed_or_404(fid)
    if feed.get("feed_status") != "OFFLINE":
        raise invalid_state("the feed is not offline")
    feed["feed_status"] = "PLANNED"
    feed["reserved_capacity_units"] = 0
    carriage.refresh_feed_flags(STORE, feed)
    touch(feed)
    return object_response(feed_view(STORE, feed))


@bp.route("/network/distribution-feeds/<fid>/suspend", methods=["POST"])
@route("/network/distribution-feeds/<fid>/suspend", "POST")
def suspend_feed(fid):
    feed = feed_or_404(fid)
    if feed.get("feed_status") != "ONLINE":
        raise invalid_state("the feed is not online")
    body = base.get_body(request.get_json(silent=True))
    reason = base.as_text(body.get("suspension_reason"), "suspension_reason")
    feed["feed_status"] = "SUSPENDED"
    feed["_suspension_reason"] = reason
    for slot in STORE.slots_of(fid):
        if slot.get("slot_status") in ("RESERVED", "SCHEDULED"):
            slot["slot_status"] = "CANCELLED"
            if slot.get("_reserved_units_recorded"):
                feed["reserved_capacity_units"] = max(
                    0, int(feed.get("reserved_capacity_units") or 0)
                    - int(slot.get("_units") or 1)
                )
                slot["_reserved_units_recorded"] = False
            touch(slot)
    carriage.refresh_feed_flags(STORE, feed)
    touch(feed)
    return object_response(feed_view(STORE, feed))


# --- uplink slots ------------------------------------------------------------
@bp.route("/network/uplink-slots", methods=["POST"])
@route("/network/uplink-slots", "POST")
def create_slot():
    body = base.get_body(request.get_json(silent=True))
    feed_id = body.get("parent_feed_id")
    if feed_id is None:
        raise bad_request("parent_feed_id is required")
    feed = feed_or_404(feed_id)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    slot = _reserve_one(STORE, feed, body, role, ident)
    return object_response(public(slot), 201)


@bp.route("/network/uplink-slots/block", methods=["POST"])
@route("/network/uplink-slots/block", "POST")
def create_slot_block():
    body = base.get_body(request.get_json(silent=True))
    reservations = body.get("reservations")
    if not isinstance(reservations, list):
        raise bad_request("reservations must be a list")
    if len(reservations) > 3:
        raise ApiError(
            "ERR_SLOT_REQUEST_LIMIT_EXCEEDED",
            "a block request may carry at most three reservations",
        )
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    staged = []
    for entry in reservations:
        if not isinstance(entry, dict):
            raise bad_request("each reservation must be an object")
        feed_id = entry.get("parent_feed_id")
        if feed_id is None:
            raise bad_request("parent_feed_id is required on every reservation")
        feed = feed_or_404(feed_id)
        stored = list(STORE.slots.items())
        snapshot_feed = dict(feed)
        snapshot_windows = {k: dict(v) for k, v in STORE.windows.items()}
        try:
            slot = _reserve_one(STORE, feed, entry, role, ident)
        except ApiError:
            STORE.slots = dict(stored)
            STORE.feeds[feed["id"]] = snapshot_feed
            STORE.windows = {k: v for k, v in snapshot_windows.items()}
            continue
        staged.append(slot)
    return object_response([public(s) for s in staged])


@bp.route("/network/uplink-slots", methods=["GET"])
@route("/network/uplink-slots", "GET")
def list_slots():
    args = request.args
    recs = STORE.all("slots")
    for field in ("parent_feed_id", "station_id", "window_id", "slot_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/uplink-slots/<sid>", methods=["GET"])
@route("/network/uplink-slots/<sid>", "GET")
def read_slot(sid):
    return object_response(public(slot_or_404(sid)))


@bp.route("/network/uplink-slots/<sid>/air", methods=["POST"])
@route("/network/uplink-slots/<sid>/air", "POST")
def air_slot(sid):
    slot = slot_or_404(sid)
    feed = feed_or_404(slot.get("parent_feed_id"))
    if slot.get("slot_status") != "SCHEDULED":
        raise invalid_state("the slot is not scheduled")
    start = C.parse_dt(slot.get("slot_start"))
    end = C.parse_dt(slot.get("slot_end"))
    if start is None or C.now() < start:
        raise invalid_state("the slot's start instant has not arrived")
    if end is None or C.now() >= end:
        raise invalid_state("the slot's end instant has passed")
    window = STORE.windows.get(slot.get("window_id"))
    if window is None:
        raise not_found("broadcast window")
    if window.get("clearance_status") != "SCHEDULED":
        raise invalid_state("the slot's window is not scheduled")
    if feed.get("feed_status") != "ONLINE":
        raise invalid_state("the reserving feed is not online")
    slot["slot_status"] = "AIRED"
    window["clearance_status"] = "BROADCAST"
    carriage.refresh_window_flags(STORE, window)
    touch(window)
    carriage.refresh_agreement_from_windows(STORE, window.get("parent_agreement_id"))
    touch(slot)
    return object_response(public(slot))


@bp.route("/network/uplink-slots/<sid>/release", methods=["POST"])
@route("/network/uplink-slots/<sid>/release", "POST")
def release_slot(sid):
    slot = slot_or_404(sid)
    feed = feed_or_404(slot.get("parent_feed_id"))
    if slot.get("slot_status") not in ("RESERVED", "PREEMPTED"):
        raise invalid_state("the slot cannot be released from its current state")
    slot["slot_status"] = "RELEASED"
    carriage.release_slot(STORE, slot)
    carriage.refresh_feed_flags(STORE, feed)
    if feed.get("feed_status") == "CROWDED" and not feed.get("crowded"):
        feed["feed_status"] = "ONLINE"
    touch(slot)
    touch(feed)
    return object_response(public(slot))


@bp.route("/network/uplink-slots/<sid>/preemption-review", methods=["POST"])
@route("/network/uplink-slots/<sid>/preemption-review", "POST")
def preemption_review(sid):
    slot = slot_or_404(sid)
    feed = feed_or_404(slot.get("parent_feed_id"))
    if slot.get("slot_status") != "PREEMPTED":
        raise invalid_state("the slot is not preempted")
    if feed.get("feed_status") != "ONLINE":
        raise invalid_state("the feed is not online")
    units = int(slot.get("_units") or 1)
    reserved = int(feed.get("reserved_capacity_units") or 0)
    total = int(feed.get("total_capacity_units") or 1)
    if reserved + units > total:
        raise ApiError("ERR_UPLINK_CAPACITY_EXHAUSTED")
    slot["slot_status"] = "RESERVED"
    feed["reserved_capacity_units"] = reserved + units
    slot["_reserved_units_recorded"] = True
    carriage.refresh_feed_flags(STORE, feed)
    touch(slot)
    touch(feed)
    return object_response(public(slot))
"""Channels, connectivity health and freeze windows (PRD 3.3)."""

from flask import Blueprint

import calc
import cascade
import guards
import refs
import serialize
import shape
import store
from envelope import created, ok
from errors import fail
from guards import must, page
from refs import put, rows, where

bp = Blueprint("channel", __name__)

INTERNAL = shape.INTERNAL_ROLES
CHANNEL_KINDS = ("OTA_PUBLIC", "OTA_OPAQUE", "GDS", "DIRECT_BRAND", "WHOLESALER")
PROTOCOLS = ("XML_PUSH", "JSON_PUSH", "ARI_PULL")
CONNECTION_STATES = ("PENDING", "HEALTHY", "DEGRADED", "SUSPENDED", "RETIRED")
FAILURE_CODES = ("TIMEOUT", "AUTH_REJECTED", "SCHEMA_ERROR", "MAPPING_REJECTED",
                 "UNKNOWN")
FREEZE_REASONS = ("MAINTENANCE", "CERTIFICATION", "INCIDENT")


@bp.post("/distribution/properties/<pid>/channels")
def create_channel(pid):
    shape.auth("PlatformAdmin")
    prop = must("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    body = shape.body_obj()
    code = shape.v_string(body, "code", required=True, minlen=2, maxlen=16,
                          pattern=r"^[A-Z0-9-]+$")
    kind = shape.v_enum(body, "channel_kind", CHANNEL_KINDS, required=True)
    commission = shape.v_int(body, "commission_bp", required=True, lo=0, hi=5000)
    adjustment = shape.v_int(body, "sell_adjustment_bp", default=0, lo=-3000, hi=3000)
    member = shape.v_bool(body, "allows_member_rate", default=False)
    opaque = shape.v_bool(body, "allows_opaque_rate", default=False)
    markets = shape.v_str_array(body, "geo_market_codes", default=[], minlen=2,
                                maxlen=8, pattern=r"^[A-Z0-9-]+$")
    parity = shape.v_bool(body, "requires_content_parity", default=True)
    for existing in where("channels", property_id=prop["id"]):
        if existing["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE",
                 "Channel code %s already exists on this property." % code)
    rec = store.base_record()
    rec.update({
        "property_id": prop["id"],
        "code": code,
        "channel_kind": kind,
        "commission_bp": commission,
        "sell_adjustment_bp": adjustment,
        "allows_member_rate": member,
        "allows_opaque_rate": opaque,
        "geo_market_codes": markets,
        "requires_content_parity": parity,
        "gross_revenue_cents": 0,
        "commission_accrued_cents": 0,
        "net_revenue_cents": 0,
        "room_nights_sold": 0,
        "bookings_count": 0,
        "cancellations_count": 0,
        "mismatch_alert_count": 0,
    })
    put("channels", rec)
    return created(serialize.channel_out(rec))


@bp.get("/distribution/channels")
def list_channels():
    shape.auth(*INTERNAL)
    property_id = shape.q_id("property_id")
    kind = shape.q_enum("channel_kind", CHANNEL_KINDS)
    records = rows("channels")
    if property_id is not None:
        records = [r for r in records if r["property_id"] == property_id]
    if kind is not None:
        records = [r for r in records if r["channel_kind"] == kind]
    return page(serialize.channel_out, records)


@bp.get("/distribution/channels/<cid>")
def read_channel(cid):
    shape.auth(*INTERNAL)
    channel = must("channels", cid, "ERR_CHANNEL_NOT_FOUND")
    return ok(serialize.channel_out(channel))


@bp.post("/distribution/channels/<cid>/connections")
def create_connection(cid):
    shape.auth("ChannelOpsEngineer")
    channel = must("channels", cid, "ERR_CHANNEL_NOT_FOUND")
    body = shape.body_obj()
    protocol = shape.v_enum(body, "protocol", PROTOCOLS, required=True)
    url = shape.v_string(body, "endpoint_url", required=True, minlen=8, maxlen=200,
                         pattern=r"^https://")
    interval = shape.v_int(body, "heartbeat_interval_minutes", default=15, lo=5, hi=1440)
    for existing in where("connections", channel_id=channel["id"]):
        if existing["connection_state"] != "RETIRED":
            fail("ERR_DUPLICATE_RESOURCE",
                 "This channel already holds a live connection.")
    rec = store.base_record()
    rec.update({
        "channel_id": channel["id"],
        "protocol": protocol,
        "endpoint_url": url,
        "heartbeat_interval_minutes": interval,
        "connection_state": "PENDING",
        "consecutive_failures": 0,
        "last_heartbeat_at": None,
        "last_failure_code": None,
        "suspended_at": None,
    })
    put("connections", rec)
    return created(serialize.connection_out(rec))


@bp.post("/distribution/channel-connections/<cid>/activate")
def activate_connection(cid):
    shape.auth("ChannelOpsEngineer")
    connection = must("connections", cid, "ERR_CONNECTION_NOT_FOUND")
    if connection["connection_state"] != "PENDING":
        fail("ERR_CONNECTION_STATE_INVALID")
    connection["connection_state"] = "HEALTHY"
    connection["consecutive_failures"] = 0
    connection["last_failure_code"] = None
    store.bump(connection)
    return ok(serialize.connection_out(connection))


@bp.post("/distribution/channel-connections/<cid>/heartbeats")
def record_heartbeat(cid):
    shape.auth("ChannelOpsEngineer")
    connection = must("connections", cid, "ERR_CONNECTION_NOT_FOUND")
    body = shape.body_obj()
    status = shape.v_enum(body, "status", ("OK", "ERROR"), required=True)
    failure_code = shape.v_enum(body, "failure_code", FAILURE_CODES)
    if connection["connection_state"] == "RETIRED":
        fail("ERR_CONNECTION_STATE_INVALID")
    connection["last_heartbeat_at"] = store.now_iso()
    if status == "OK":
        connection["consecutive_failures"] = 0
        connection["last_failure_code"] = None
        if connection["connection_state"] == "DEGRADED":
            connection["connection_state"] = "HEALTHY"
        store.bump(connection)
    else:
        cascade.record_failure(connection, failure_code or "UNKNOWN")
    return ok(serialize.connection_out(connection))


@bp.post("/distribution/channel-connections/<cid>/revalidate")
def revalidate_connection(cid):
    shape.auth("ChannelOpsEngineer")
    connection = must("connections", cid, "ERR_CONNECTION_NOT_FOUND")
    if connection["connection_state"] != "SUSPENDED":
        fail("ERR_CONNECTION_STATE_INVALID")
    connection["connection_state"] = "DEGRADED"
    connection["consecutive_failures"] = 2
    store.bump(connection)
    return ok(serialize.connection_out(connection))


@bp.post("/distribution/channel-connections/<cid>/retire")
def retire_connection(cid):
    shape.auth("PlatformAdmin")
    connection = must("connections", cid, "ERR_CONNECTION_NOT_FOUND")
    if connection["connection_state"] not in ("PENDING", "HEALTHY", "DEGRADED",
                                              "SUSPENDED"):
        fail("ERR_CONNECTION_STATE_INVALID")
    cascade.retire(connection)
    return ok(serialize.connection_out(connection))


@bp.post("/distribution/channel-connections/<cid>/freeze-windows")
def create_freeze_window(cid):
    shape.auth("ChannelOpsEngineer")
    connection = must("connections", cid, "ERR_CONNECTION_NOT_FOUND")
    prop = refs.prop_of_channel(refs.get("channels", connection["channel_id"]))
    body = shape.body_obj()
    starts_at = shape.v_instant(body, "starts_at", required=True)
    ends_at = shape.v_instant(body, "ends_at", required=True)
    reason = shape.v_enum(body, "reason", FREEZE_REASONS, default="MAINTENANCE")
    if ends_at <= starts_at:
        fail("ERR_INVALID_REQUEST", "Field 'ends_at' must be after 'starts_at'.")
    if starts_at < store.now():
        fail("ERR_WINDOW_OUTSIDE_HORIZON")
    low, high = guards.horizon_bounds(prop)
    if store.fmt_instant(ends_at)[0:10] > high:
        fail("ERR_WINDOW_OUTSIDE_HORIZON")
    effective = cascade.buffered_start(starts_at)
    effective_s = store.fmt_instant(effective)
    ends_s = store.fmt_instant(ends_at)
    for existing in where("freeze_windows", connection_id=connection["id"]):
        if effective_s < existing["ends_at"] and existing["effective_starts_at"] < ends_s:
            fail("ERR_FREEZE_WINDOW_OVERLAP")
    rec = store.base_record(with_version=False)
    rec.update({
        "connection_id": connection["id"],
        "starts_at": store.fmt_instant(starts_at),
        "ends_at": ends_s,
        "reason": reason,
        "effective_starts_at": effective_s,
    })
    put("freeze_windows", rec)
    return created(serialize.freeze_window_out(rec))


@bp.get("/distribution/channel-connections")
def list_connections():
    shape.auth(*INTERNAL)
    channel_id = shape.q_id("channel_id")
    state = shape.q_enum("connection_state", CONNECTION_STATES)
    records = rows("connections")
    if channel_id is not None:
        records = [r for r in records if r["channel_id"] == channel_id]
    if state is not None:
        records = [r for r in records if r["connection_state"] == state]
    return page(serialize.connection_out, records)


@bp.get("/distribution/channel-connections/<cid>")
def read_connection(cid):
    shape.auth(*INTERNAL)
    connection = must("connections", cid, "ERR_CONNECTION_NOT_FOUND")
    return ok(serialize.connection_out(connection))


@bp.get("/distribution/channel-connections/<cid>/freeze-windows")
def list_freeze_windows(cid):
    shape.auth(*INTERNAL)
    connection = must("connections", cid, "ERR_CONNECTION_NOT_FOUND")
    return page(serialize.freeze_window_out,
                where("freeze_windows", connection_id=connection["id"]))

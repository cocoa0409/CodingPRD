"""Channel mappings, parity, surveillance and the quoted rate (PRD 3.4, 3.6)."""

from flask import Blueprint

import calc
import cascade
import refs
import serialize
import shape
import store
from envelope import created, ok
from errors import fail
from guards import must, page
from refs import get, put, rows, where

bp = Blueprint("mapping", __name__)

INTERNAL = shape.INTERNAL_ROLES
MAPPING_STATES = ("DRAFT", "VERIFIED", "ERRORED", "DISABLED")
MISMATCH_STATES = ("UNKNOWN", "IN_SYNC", "MISMATCHED")


def rate_eligibility(plan, channel, dates, member_flag, geo_market_code,
                     negotiated_account_code):
    """Check 18 of PRD 2.7, in the declared order."""
    if plan["rate_class"] == "OPAQUE" and not channel["allows_opaque_rate"]:
        fail("ERR_OPAQUE_RATE_NOT_ALLOWED")
    member_claimed = calc.approved_member_promo_in_play(plan, dates)
    if plan["member_only"] or member_claimed:
        if not member_flag or not channel["allows_member_rate"]:
            fail("ERR_MEMBER_RATE_NOT_ELIGIBLE")
    if plan["rate_class"] == "NEGOTIATED":
        if negotiated_account_code != plan["negotiated_account_code"]:
            fail("ERR_NEGOTIATED_ACCOUNT_MISMATCH")
    markets = channel["geo_market_codes"] or []
    if markets and geo_market_code not in markets:
        fail("ERR_GEO_MARKET_NOT_SERVED")


@bp.post("/distribution/channel-mappings")
def create_mapping():
    shape.auth("ChannelOpsEngineer")
    body = shape.body_obj()
    rate_plan_id = shape.v_string(body, "rate_plan_id", required=True)
    channel_id = shape.v_string(body, "channel_id", required=True)
    room_type_id = shape.v_string(body, "room_type_id", required=True)
    external_code = shape.v_string(body, "external_rate_code", required=True, minlen=2,
                                   maxlen=24, pattern=r"^[A-Z0-9_-]+$")
    content_hash = shape.v_string(body, "content_description_hash", minlen=4, maxlen=64,
                                  pattern=r"^[a-z0-9]+$")
    content_images = shape.v_int(body, "content_image_count", lo=0, hi=40)
    plan = get("rate_plans", rate_plan_id)
    if plan is None:
        fail("ERR_RATE_PLAN_NOT_FOUND")
    channel = get("channels", channel_id)
    if channel is None:
        fail("ERR_CHANNEL_NOT_FOUND")
    room_type = get("room_types", room_type_id)
    if room_type is None:
        fail("ERR_ROOM_TYPE_NOT_FOUND")
    if not (plan["property_id"] == channel["property_id"] == room_type["property_id"]):
        fail("ERR_PROPERTY_SCOPE_MISMATCH")
    if refs.connection_of_channel(channel["id"]) is None:
        fail("ERR_CHANNEL_CONNECTION_MISSING")
    for existing in rows("mappings"):
        if existing["rate_plan_id"] == plan["id"] and \
                existing["channel_id"] == channel["id"] and \
                existing["room_type_id"] == room_type["id"]:
            fail("ERR_DUPLICATE_RESOURCE",
                 "This rate plan, channel and room type are already mapped.")
    rec = store.base_record()
    rec.update({
        "rate_plan_id": plan["id"],
        "channel_id": channel["id"],
        "room_type_id": room_type["id"],
        "external_rate_code": external_code,
        "mapping_state": "DRAFT",
        "content_description_hash": content_hash,
        "content_image_count": content_images,
        "parity_state": "UNKNOWN",
        "last_push_at": None,
        "last_pushed_rate_cents": None,
        "observed_rate_cents": None,
        "observed_stay_date": None,
        "mismatch_state": "UNKNOWN",
        "mismatch_delta_cents": None,
    })
    cascade.refresh_parity(rec)
    put("mappings", rec)
    return created(serialize.mapping_out(rec))


@bp.post("/distribution/channel-mappings/<mid>/verify")
def verify_mapping(mid):
    shape.auth("ChannelOpsEngineer")
    mapping = must("mappings", mid, "ERR_CHANNEL_MAPPING_NOT_FOUND")
    if mapping["mapping_state"] not in ("DRAFT", "ERRORED"):
        fail("ERR_MAPPING_STATE_INVALID")
    plan = get("rate_plans", mapping["rate_plan_id"])
    if plan["plan_state"] != "ACTIVE":
        fail("ERR_RATE_PLAN_STATE_INVALID")
    connection = refs.connection_of_channel(mapping["channel_id"])
    if connection is None or connection["connection_state"] not in ("HEALTHY", "DEGRADED"):
        fail("ERR_CONNECTION_NOT_SELLABLE")
    mapping["mapping_state"] = "VERIFIED"
    cascade.refresh_parity(mapping)
    store.bump(mapping)
    return ok(serialize.mapping_out(mapping))


@bp.post("/distribution/channel-mappings/<mid>/disable")
def disable_mapping_route(mid):
    shape.auth("ChannelOpsEngineer")
    mapping = must("mappings", mid, "ERR_CHANNEL_MAPPING_NOT_FOUND")
    if mapping["mapping_state"] not in ("DRAFT", "VERIFIED", "ERRORED"):
        fail("ERR_MAPPING_STATE_INVALID")
    cascade.disable_mapping(mapping)
    return ok(serialize.mapping_out(mapping))


@bp.patch("/distribution/channel-mappings/<mid>/content")
def update_mapping_content(mid):
    shape.auth("ChannelOpsEngineer")
    mapping = must("mappings", mid, "ERR_CHANNEL_MAPPING_NOT_FOUND")
    body = shape.body_obj()
    content_hash = shape.v_string(body, "content_description_hash", minlen=4, maxlen=64,
                                  pattern=r"^[a-z0-9]+$")
    content_images = shape.v_int(body, "content_image_count", lo=0, hi=40)
    if "content_description_hash" in body:
        mapping["content_description_hash"] = content_hash
    if "content_image_count" in body:
        mapping["content_image_count"] = content_images
    cascade.refresh_parity(mapping)
    store.bump(mapping)
    return ok(serialize.mapping_out(mapping))


@bp.post("/distribution/channel-mappings/<mid>/observed-rates")
def record_observed_rate(mid):
    shape.auth("ChannelOpsEngineer")
    mapping = must("mappings", mid, "ERR_CHANNEL_MAPPING_NOT_FOUND")
    body = shape.body_obj()
    observed = shape.v_int(body, "observed_rate_cents", required=True, lo=0)
    observed_date = shape.v_date(body, "observed_stay_date", required=True)
    mapping["observed_rate_cents"] = observed
    mapping["observed_stay_date"] = observed_date
    cascade.refresh_mismatch(mapping)
    store.bump(mapping)
    cascade.refresh_alert_count(get("channels", mapping["channel_id"]))
    return ok(serialize.mapping_out(mapping))


@bp.get("/distribution/channel-mappings")
def list_mappings():
    shape.auth(*INTERNAL)
    rate_plan_id = shape.q_id("rate_plan_id")
    channel_id = shape.q_id("channel_id")
    room_type_id = shape.q_id("room_type_id")
    mapping_state = shape.q_enum("mapping_state", MAPPING_STATES)
    mismatch_state = shape.q_enum("mismatch_state", MISMATCH_STATES)
    records = rows("mappings")
    if rate_plan_id is not None:
        records = [r for r in records if r["rate_plan_id"] == rate_plan_id]
    if channel_id is not None:
        records = [r for r in records if r["channel_id"] == channel_id]
    if room_type_id is not None:
        records = [r for r in records if r["room_type_id"] == room_type_id]
    if mapping_state is not None:
        records = [r for r in records if r["mapping_state"] == mapping_state]
    if mismatch_state is not None:
        records = [r for r in records if r["mismatch_state"] == mismatch_state]
    return page(serialize.mapping_out, records)


@bp.get("/distribution/channel-mappings/<mid>")
def read_mapping(mid):
    shape.auth(*INTERNAL)
    mapping = must("mappings", mid, "ERR_CHANNEL_MAPPING_NOT_FOUND")
    return ok(serialize.mapping_out(mapping))


@bp.get("/distribution/channel-mappings/<mid>/quoted-rate")
def quoted_rate(mid):
    shape.auth("RevenueManager", "RevenueDirector", "ChannelOpsEngineer")
    mapping = must("mappings", mid, "ERR_CHANNEL_MAPPING_NOT_FOUND")
    stay_date = shape.q_date("stay_date", required=True)
    member_flag = shape.q_bool("member_flag", default=False)
    geo_market_code = shape.q_str("geo_market_code", minlen=2, maxlen=8,
                                  pattern=r"^[A-Z0-9-]+$")
    account_code = shape.q_str("negotiated_account_code", minlen=2, maxlen=16,
                               pattern=r"^[A-Z0-9-]+$")
    plan = get("rate_plans", mapping["rate_plan_id"])
    channel = get("channels", mapping["channel_id"])
    rate_eligibility(plan, channel, [stay_date], member_flag, geo_market_code,
                     account_code)
    quote = calc.resolve_sell_rate(plan, channel, stay_date, member_flag,
                                   geo_market_code)
    data = {"channel_mapping_id": mapping["id"], "stay_date": stay_date}
    data.update(quote)
    return ok(data)

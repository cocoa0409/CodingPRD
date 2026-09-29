"""Assigned cable channels (PRD 3.4)."""

from flask import Blueprint

import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, bad_request

bp = Blueprint("channels", __name__)

READ_ROLES = (C.ROLE_CENTER_ADMIN, C.ROLE_SCHEDULING_COORDINATOR, C.ROLE_PRODUCER)


@bp.post("/channels")
def create_channel():
    middleware.authorize(C.ROLE_CENTER_ADMIN)
    body = validation.body()
    call_sign = validation.req_string(body, "call_sign")
    tier = validation.req_enum(body, "tier", C.CHANNEL_TIERS)
    start_minute = validation.req_int(body, "daily_window_start_minute", minimum=0, maximum=1439)
    end_minute = validation.req_int(body, "daily_window_end_minute", minimum=0, maximum=1440)
    buffer_seconds = validation.req_int(body, "inter_program_buffer_seconds", minimum=0)
    preemption_enabled = validation.opt_bool(body, "preemption_enabled", default=True)
    if end_minute <= start_minute:
        raise bad_request("daily_window_end_minute must be strictly greater than the start minute")
    for row in db.all_rows("channels"):
        if row["call_sign"] == call_sign:
            raise ApiError("ERR_DUPLICATE_NATURAL_KEY", "This call_sign is already assigned")
    row = db.new_row(
        "channels",
        {
            "call_sign": call_sign,
            "tier": tier,
            "daily_window_start_minute": start_minute,
            "daily_window_end_minute": end_minute,
            "inter_program_buffer_seconds": buffer_seconds,
            "preemption_enabled": preemption_enabled,
            "slot_sequence_high": 0,
        },
    )
    return support.created("channels", row)


@bp.get("/channels/<channel_id>")
def read_channel(channel_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("channels", channel_id)
    return support.single("channels", row)


@bp.get("/channels")
def list_channels():
    middleware.authorize(*READ_ROLES)
    tier = validation.query_enum("tier", C.CHANNEL_TIERS)
    validation.pagination()
    rows = support.filter_rows("channels", [("tier", tier)])
    return support.collection_response("channels", rows)

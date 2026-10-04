"""Shared request helpers: query parsing, pagination and left-to-right lookups."""

from flask import request

import db
from errors import raise_error
from response import ok_array

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit not in (None, "") else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(raw_offset) if raw_offset not in (None, "") else DEFAULT_OFFSET
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    offset = max(0, offset)
    return limit, offset


def paginated(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_array(page, limit, offset, total)


def sort_by_created_at(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))


def get_channel(channel_id):
    channel = db.get("channels", channel_id)
    if channel is None:
        raise_error("ERR_CHANNEL_NOT_FOUND")
    return channel


def get_content_item(item_id, channel=None):
    item = db.get("content_items", item_id)
    if item is None:
        raise_error("ERR_CONTENT_ITEM_NOT_FOUND")
    if channel is not None and item["channel_id"] != channel["id"]:
        raise_error("ERR_CONTENT_ITEM_NOT_FOUND")
    return item


def resolve_channel_item(channel_id, item_id):
    """Left-to-right existence resolution for a channel-scoped content item."""
    channel = get_channel(channel_id)
    item = get_content_item(item_id, channel)
    return channel, item


def get_claim(claim_id):
    claim = db.get("claims", claim_id)
    if claim is None:
        raise_error("ERR_CLAIM_NOT_FOUND")
    return claim


def get_reference_file(reference_file_id):
    reference = db.get("reference_files", reference_file_id)
    if reference is None:
        raise_error("ERR_REFERENCE_FILE_NOT_FOUND")
    return reference


def get_payout_batch(channel_id, batch_id):
    batch = db.get("payout_batches", batch_id)
    if batch is None or batch["channel_id"] != channel_id:
        raise_error("ERR_PAYOUT_BATCH_NOT_FOUND")
    return batch


def get_appeal(claim, appeal_id):
    from services import claims as claim_svc

    for appeal in claim_svc.appeals_of(claim["id"]):
        if appeal["id"] == appeal_id:
            return appeal
    raise_error("ERR_APPEAL_NOT_FOUND")


def body():
    return request.get_json(silent=True) or {}


def body_field(payload, name, default=None):
    value = payload.get(name)
    return default if value is None else value


def channel_id_of_item(item):
    return item["channel_id"] if item else None


def body_channel_of_item(item_id):
    item = db.get("content_items", item_id)
    return item["channel_id"] if item else None


def require_stream_type(stream_type):
    from services.money import STREAM_TYPES

    if stream_type not in STREAM_TYPES:
        raise_error("ERR_UNSUPPORTED_STREAM_TYPE")
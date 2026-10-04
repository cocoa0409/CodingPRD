"""Shared route helpers: id minting, common fields, pagination, OCC."""
import uuid
from datetime import datetime, timezone

from flask import request

from clock import now_dt
from errors import err_invalid_request, ApiError
from response import success_list


def new_id():
    return str(uuid.uuid4())


_seq = [0]


def _next_seq():
    _seq[0] += 1
    return _seq[0]


def stamp_new(entity):
    now = now_dt()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = _next_seq()
    return entity


def touch(entity):
    entity["updated_at"] = now_dt()
    entity["version"] = int(entity.get("version", 1)) + 1
    entity["_seq"] = _next_seq()


def serialize(entity):
    out = {k: _deep_serialize(v) for k, v in entity.items() if not k.startswith("_")}
    return out


def _deep_serialize(value, key=None):
    if isinstance(value, datetime):
        return _fmt_dt(key or "", value)
    if isinstance(value, dict):
        return {k: _deep_serialize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_serialize(v, key) for v in value]
    return value


def _fmt_dt(field, dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    d = dt.astimezone(timezone.utc)
    if field in ("created_at", "updated_at"):
        return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def paginate(items, sort_key=None):
    """Apply limit/offset pagination; sort by created_at ASC by default."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise err_invalid_request("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    if sort_key is not None:
        items = sorted(items, key=sort_key)
    else:
        items = sorted(items, key=lambda e: (e.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), e.get("_seq", 0)))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(i) for i in page], limit, offset, total)


def check_occ(campaign, data):
    """OCC: expected_campaign_version must match campaign.version (412)."""
    expected = data.get("expected_campaign_version")
    if expected is None:
        raise err_invalid_request("expected_campaign_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_campaign_version must be an integer")
    if expected != int(campaign["version"]):
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION", 412,
                       "expected_campaign_version does not match current campaign version")

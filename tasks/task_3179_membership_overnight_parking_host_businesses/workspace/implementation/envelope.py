"""Response envelope helpers (PRD section 2.2, SCAFFOLD response_envelope)."""

import random
import string
from datetime import datetime, timezone

from errors import ApiError

_ALPHABET = string.ascii_uppercase + string.digits


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", "An ISO 8601 timestamp was expected.")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "An ISO 8601 timestamp was expected.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok_object(data):
    return {"meta": _meta(), "response_type": "object", "data": data}, 200


def created_object(data):
    return {"meta": _meta(), "response_type": "object", "data": data}, 201


def ok_array(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return {"meta": _meta(pagination), "response_type": "array", "data": items}, 200


def error_body(error):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }, error.http_status
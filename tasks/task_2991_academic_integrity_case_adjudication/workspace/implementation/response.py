"""Standard response envelope (PRD section 2.2) and pagination (PRD section 2.3)."""

import json
import random
import re
import string
import uuid
from decimal import Decimal

from flask import request

from db import S
from errors import ApiError
from util import fmt_dt

# PRD 2.7: every percentage and index value carries exactly two decimal places.
# json.dumps would render Decimal("60.00") through float and emit 60.0, so a
# Decimal is encoded as a nonce-tagged string and unquoted again afterwards,
# which puts the exact two-decimal literal into the JSON body as a number.
_DEC_NONCE = uuid.uuid4().hex
_DEC_OPEN = "@@%s:" % _DEC_NONCE
_DEC_RE = re.compile(r'"@@%s:(-?\d+(?:\.\d+)?)@@"' % _DEC_NONCE)


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return "%s%s@@" % (_DEC_OPEN, o)
        return json.JSONEncoder.default(self, o)

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": fmt_dt(S.clock),
    }
    if extra:
        meta.update(extra)
    return meta


def _dump(payload, status):
    body = json.dumps(payload, allow_nan=False, cls=_Encoder)
    if _DEC_OPEN in body:
        body = _DEC_RE.sub(r"\1", body)
    return body, status, {"Content-Type": "application/json"}


def ok(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _dump(payload, status)


def created(data):
    return ok(data, 201)


def ok_list(rows, serializer, limit, offset):
    total_count = len(rows)
    page = rows[offset:offset + limit]
    payload = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(page) < total_count,
        }),
        "response_type": "array",
        "data": [serializer(row) for row in page],
    }
    return _dump(payload, 200)


def error_body(error_id, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return payload


_INT_RE = re.compile(r"^[+-]?\d+$")


def _as_int(raw):
    if raw is None:
        return None
    if not _INT_RE.match(raw.strip()):
        return None
    return int(raw.strip())


def pagination():
    """limit/offset with PRD 2.3 defaults and bounds -> ERR_INVALID_PAGINATION."""
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        limit = _as_int(args.get("limit"))
        if limit is None or limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer from 1 to 100.")
    if "offset" in args:
        offset = _as_int(args.get("offset"))
        if offset is None or offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be a non-negative integer.")
    return limit, offset

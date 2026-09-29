"""Response envelope helpers (PRD section 2.2)."""

import json
import re
from decimal import Decimal

from flask import Response

import db

_DEC_OPEN = "__DEC__"
_DEC_CLOSE = "__ENDDEC__"
_DEC_RE = re.compile(r'"__DEC__(-?[0-9]+(?:\.[0-9]+)?)__ENDDEC__"')


def _tokenise(value):
    if isinstance(value, Decimal):
        return _DEC_OPEN + _plain(value) + _DEC_CLOSE
    if isinstance(value, dict):
        return {k: _tokenise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_tokenise(v) for v in value]
    return value


def _plain(value):
    text = format(value, "f")
    if text in ("-0", "-0.0"):
        text = text[1:]
    return text


def dump(payload):
    body = json.dumps(_tokenise(payload), ensure_ascii=False)
    return _DEC_RE.sub(r"\1", body)


def _meta(extra=None):
    meta = {
        "api_request_id": db.request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def make(payload, status):
    return Response(dump(payload), status=status, mimetype="application/json")


def object_response(data, status=200):
    return make({"meta": _meta(), "response_type": "object", "data": data}, status)


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return make({"meta": meta, "response_type": "array", "data": items}, status)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return make(payload, status)
